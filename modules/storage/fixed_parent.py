"""Private pre-bind parent and explicit network authority, without catalog imports."""
from contextlib import contextmanager
import math
import threading
import time

from modules.common.cf1a_primitives import ContractFailure, require, validate_shape


def finite(value):
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0,
            'invalid parent monotonic value')
    return value


class ReadParent:
    """One T0, one attachment, one cumulative object/output/memory ledger."""
    def __init__(self, timeout_ms, budget, cancelled=lambda: False, *,
                 monotonic=time.monotonic, wall_ms=lambda: time.time_ns() // 1_000_000):
        require(type(timeout_ms) is int and timeout_ms > 0, 'invalid parent timeout')
        validate_shape(budget, 'Budget')
        require(budget['top_k'] <= budget['candidates'], 'top_k exceeds candidates')
        require(callable(cancelled) and callable(monotonic) and callable(wall_ms), 'invalid parent callbacks')
        self._linux = None
        self.cancelled, self.monotonic, self.wall_ms = cancelled, monotonic, wall_ms
        self.started = finite(monotonic())
        self.deadline = self.started + timeout_ms / 1000
        self._budget, self._scope, self._catalog = dict(budget), None, None
        self._attached, self._admission = False, 'not_attempted'
        self._lock = threading.Lock()

    @classmethod
    def from_linux_anchor(cls, anchor, budget, cancelled):
        from modules.storage.fixed_anchor import LinuxDeadline, TrustedLinuxAnchor, seconds_floor
        require(cls is ReadParent and type(anchor) is TrustedLinuxAnchor,
                'expected trusted Linux anchor token')
        # Consume before budget/admission validation: a failure cannot re-import.
        origin, now = anchor.consume(cancelled)
        validate_shape(budget, 'Budget')
        require(budget['top_k'] <= budget['candidates'], 'top_k exceeds candidates')
        parent = cls.__new__(cls)
        parent._linux = LinuxDeadline(origin, now)
        parent.cancelled, parent.monotonic = cancelled, parent._linux.monotonic
        parent.wall_ms = lambda: time.time_ns() // 1_000_000
        parent.started = seconds_floor(origin.original_t0_ns)
        parent.deadline = seconds_floor(origin.absolute_cutoff_ns)
        parent._budget, parent._scope, parent._catalog = dict(budget), None, None
        parent._attached, parent._admission = False, 'not_attempted'
        parent._lock = threading.Lock()
        parent.checkpoint()
        return parent

    @property
    def linux_origin(self):
        return None if self._linux is None else self._linux.origin

    def effective_deadline(self):
        return self.checkpoint()

    @contextmanager
    def active_operation(self, sequence, pg_sequence, absolute_cutoff_ns):
        require(self._linux is not None, 'operation anchor requires Linux parent')
        self.checkpoint()
        with self._linux.operation(sequence, pg_sequence, absolute_cutoff_ns) as active:
            self.checkpoint()
            yield active

    @contextmanager
    def fd_operation(self, kind, sequence, pg_sequence, absolute_cutoff_ns):
        require(self._linux is not None, 'FD operation requires Linux parent')
        self.checkpoint()
        with self._linux.fd_operation(kind, sequence, pg_sequence, absolute_cutoff_ns) as active:
            self.checkpoint()
            yield active

    def checkpoint(self, *, slack=0):
        try:
            stopped = self.cancelled()
        except Exception:
            raise ContractFailure('cancelled', 'parent cancellation unavailable') from None
        require(type(stopped) is bool and not stopped, 'parent cancelled', 'cancelled')
        if self._linux is not None:
            return self._linux.checkpoint(slack)
        require(finite(self.monotonic()) < self.deadline, 'parent deadline reached', 'deadline')
        return self.deadline

    def attach(self, scope, binding):
        with self._lock:
            require(not self._attached, 'parent binding attachment already consumed', 'expired_context')
            # Consumption is distinct from a ready ledger. Failure keeps PG
            # observations readable and must never expose a partial ReadScope.
            self._attached, self._admission = True, 'pending'
            try:
                self.checkpoint()
                context = binding.value['context']
                remaining = min(context['remaining_ttl_ms'],
                                context['deadline_unix_ms'] - self.wall_ms())
                if self._linux is None:
                    self.deadline = min(self.deadline, finite(self.monotonic()) + max(0, remaining / 1000))
                else:
                    self.deadline = self._linux.tighten_binding(remaining)
                issued = context['budget']
                validate_shape(self._budget, 'Budget')
                require(self._budget['top_k'] <= self._budget['candidates'], 'top_k exceeds candidates')
                require(set(issued) == set(self._budget), 'host budget fields differ from binding')
                budget = {key: min(issued[key], self._budget[key]) for key in issued}
                require(budget['top_k'] <= budget['candidates'], 'effective top_k exceeds candidates')
                self.checkpoint()
                return budget
            except BaseException:
                self._admission = 'rejected_before_object_execution'
                raise

    def ready(self, scope):
        require(self._attached and self._admission == 'pending' and self._scope is None,
                'parent scope admission is not pending')
        self._scope, self._admission = scope, 'ready'

    def catalog(self, control):
        require(self._catalog is None, 'catalog ledger already attached')
        require(hasattr(control, 'invoice'), 'expected catalog observation ledger')
        self._catalog = control

    @property
    def invoice(self):
        return {'admission': self._admission,
                'execution': None if self._scope is None else self._scope.usage(),
                'catalog': None if self._catalog is None else self._catalog.invoice,
                'elapsed_ms': (self._linux.elapsed_ms() if self._linux is not None else
                               max(0, int((self.monotonic() - self.started) * 1000))),
                'pg_native_memory_bytes': None}


class ControlledAuthority:
    """Explicit network slot; old callback slot remains memory-only."""
    def __init__(self, parent, reauthorize):
        require(type(parent) is ReadParent and callable(reauthorize) and
                getattr(reauthorize, '__self__', None) is not None,
                'controlled authority requires parent and bound reauthorization method')
        self.parent, self._reauthorize = parent, reauthorize

    def authorize(self, scope):
        require(scope.parent is self.parent, 'authority parent differs from scope', 'unauthorized')
        scope.check()
        epoch = self._reauthorize(scope.binding, operation_deadline=scope.effective_deadline())
        # Callback may block or advance both clocks. Never use its earlier time.
        scope.check()
        return epoch
