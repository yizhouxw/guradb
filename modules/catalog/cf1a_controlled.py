"""Private one-bind read facade and exact original-request cleanup.

Absent is not a durable closed request. C2 must add that separate persistence
contract before an absent observation can exclude a delayed bind.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import threading

from modules.catalog.cf1a_access import principal_for
from modules.catalog.cf1a_auth import TrustedPrincipal
from modules.catalog.cf1a_control import CatalogReadControl
from modules.catalog.cf1a_store import CommitUnknown
from modules.common.cf1a_primitives import ContractFailure, require
from modules.common.cf1a_wire import Contract


@dataclass(frozen=True)
class BindCloseResult:
    request_sha256: str
    state: str
    binding_sha256: str | None = None


class ControlledReads:
    def __init__(self, bindings, principal, control):
        require(type(principal) is TrustedPrincipal, 'expected authenticated host principal', 'unauthorized')
        require(type(control) is CatalogReadControl, 'expected private parent control')
        self._bindings, self._principal, self.control = bindings, principal, control
        self._request = self._binding = None
        self._attempted = self._failed = self._unknown = False
        self._lock = threading.Lock()

    @contextmanager
    def _operation(self):
        require(self._lock.acquire(blocking=False), 'concurrent controlled catalog call', 'resource_limit')
        try:
            yield
        finally:
            self._lock.release()

    def bind(self, request):
        with self._operation():
            require(not self._attempted, 'controlled bind already consumed',
                    'outcome_unknown' if self._unknown else 'expired_context')
            self._attempted = True
            require(type(request) is Contract and request.kind == 'bind_request', 'expected original BindRequest')
            self._request = request
            try:
                binding = self._bindings.bind(self._principal, request, control=self.control)
                self._binding = binding
                return binding
            except BaseException as error:
                self._failed = True
                self._unknown = isinstance(error, ContractFailure) and error.code == 'outcome_unknown'
                raise

    def reauthorize(self, binding, *, operation_deadline=None):
        with self._operation():
            require(not self._failed and self._binding is not None and
                    type(binding) is Contract and binding.encoded == self._binding.encoded,
                    'controlled read has no usable issued binding', 'unauthorized')
            try:
                return self._bindings.reauthorize(self._principal, binding, control=self.control,
                                                  operation_deadline=operation_deadline)
            except BaseException:
                self._failed = True
                raise

    def _cleanup(self, control):
        require(type(control) is CatalogReadControl and control is not self.control,
                'cleanup requires its own explicit bounded control')
        self._failed = True
        return control.limit(5)

    def release_pin(self, binding, cleanup_control):
        with self._operation():
            deadline = self._cleanup(cleanup_control)
            require(self._binding is not None and type(binding) is Contract and
                    binding.encoded == self._binding.encoded, 'cleanup must match issued binding', 'unauthorized')
            return self._bindings.release(self._principal, binding, control=cleanup_control, deadline=deadline)

    def close_bind_request(self, request, cleanup_control):
        with self._operation():
            deadline = self._cleanup(cleanup_control)
            self._attempted = True
            require(type(request) is Contract and request.kind == 'bind_request', 'expected original BindRequest')
            require(self._request is None or self._request.encoded == request.encoded,
                    'cleanup differs from original complete request', 'conflict')
            self._request = request
            value, principal, store = request.value, self._principal, self._bindings.store
            principal_for(principal, value['tenant_id'])
            require(principal.cleanup or (value['subject_id'] == principal.subject_id and
                    value['delegation_ref'] == principal.delegation_ref), 'not original request owner', 'unauthorized')
            found = None
            try:
                with store.transaction(deadline, cleanup_control) as conn:
                    row = store.dataset(conn, value['tenant_id'], value['dataset_id'])
                    exists = conn.execute('SELECT query_id FROM gura_cf1a.queries WHERE dataset=%s AND query_id=%s',
                        (row['dataset'], value['query_id'])).fetchone()
                    if exists is None:
                        result = BindCloseResult(request.sha256, 'cleanup_unconfirmed')
                    else:
                        query, original, binding = self._bindings.stored(conn, row['dataset'], value['query_id'])
                        require(original.encoded == request.encoded and original.sha256 == request.sha256,
                                'cleanup request fingerprint conflict', 'conflict')
                        found = binding.sha256
                        if not query['released']:
                            conn.execute('UPDATE gura_cf1a.queries SET released=true WHERE dataset=%s AND query_id=%s',
                                         (row['dataset'], value['query_id']))
                        result = BindCloseResult(request.sha256, 'released', found)
                return result
            except CommitUnknown:
                return BindCloseResult(request.sha256, 'outcome_unknown', found)
