"""Local controlled producer lifecycle; actual IPC and worker reaping are later slices."""
import threading
import uuid
from dataclasses import dataclass

from modules.common.cf1a_primitives import digest, require
from modules.connectors.fixed_producer_credits import ProducerGrant
from modules.connectors.fixed_producer_observation import ExecutionObservation, ProducerOpen, Snapshot
from modules.connectors.fixed_source_reader import FixedSourceReader, MAX_ENVELOPE


class ProducerPage:
    """One charged payload shared with the registry until its exact ACK.

    The trusted consumer must destroy borrowed Contract/bytes references before
    release. ACK alone never refunds its still-live output lease.
    """
    def __init__(self, contract, prefix, lease):
        self._contract, self.prefix, self._lease = contract, prefix, lease
        self.producer_released = False
        self.sha256, self.bytes = contract.sha256, len(contract.encoded)

    @property
    def contract(self):
        require(self._contract is not None, 'consumer payload released', 'expired_context')
        return self._contract

    def release(self):
        require(self.producer_released, 'producer still owns payload', 'resource_limit')
        self._contract = None
        return self._lease.release()


@dataclass(frozen=True)
class Completion:
    sequence: int
    request_digest: str
    response_digest: str
    response: object


class FixedProducer:
    def __init__(self, reader):
        require(type(reader) is FixedSourceReader, 'producer requires actual fixed reader')
        self.reader = reader
        self.binding = reader.scope.binding
        self.handle = uuid.uuid4().hex
        self.state = 'new'
        self._token = object()
        self._grant = None
        self._control = None
        self._reader_attempted = False
        self._lock = threading.Lock()
        self._completed = None
        self._last_sequence = 0
        self._last_ack = None
        self._ordinal = 0
        self._summary = None
        self._observation_complete = True

    def _enter(self):
        require(self._lock.acquire(blocking=False), 'producer operation in flight', 'resource_limit')

    def _begin(self, sequence, request):
        require(type(sequence) is int and 0 < sequence < 1 << 53, 'invalid producer sequence')
        fingerprint = digest(request)
        if self._completed is not None:
            require(sequence == self._completed.sequence
                    and fingerprint == self._completed.request_digest,
                    'producer registry full or conflicting replay', 'resource_limit')
            return fingerprint, self._completed.response
        require(sequence == self._last_sequence + 1, 'old or skipped producer sequence')
        self._last_sequence = sequence
        return fingerprint, None

    def _finish(self, sequence, fingerprint, response, response_digest):
        self._completed = Completion(sequence, fingerprint, response_digest, response)
        return response

    def open(self, grant, sequence=1):
        self._enter()
        try:
            require(type(grant) is ProducerGrant, 'trusted prepared producer grant required')
            fingerprint, cached = self._begin(sequence, {'op': 'open', 'grant': grant.identifier})
            if cached is not None:
                return cached
            require(self.state == 'new', 'producer open already consumed', 'expired_context')
            self.state, self._grant = 'opening', grant
            try:
                grant.claim(self.binding.sha256, self.reader.scope.budget['memory_bytes'], owner=self._token)
                require(self.reader.scope.memory_current == 0
                        and self.reader.scope.producer_credit is None,
                        'producer needs unused scope', 'expired_context')
                self.reader.scope.producer_credit = grant
                self._control = grant.reserve(4096, kind='control')
                self._reader_attempted = True
                rows, pages, fields = self.reader.producer_open(self._token)
                require(pages <= 32, 'producer exceeds joint page profile', 'resource_limit')
                self._summary = ProducerOpen(self.handle, self.binding.sha256, grant.identifier,
                                             rows, pages, fields, MAX_ENVELOPE)
                self.state = 'open'
                return self._finish(sequence, fingerprint, self._summary,
                                    digest(self._summary.__dict__))
            except BaseException:
                if not grant.owned_by(self._token):
                    self._grant = None
                self.state, self._observation_complete = 'failed', False
                raise
        finally:
            self._lock.release()

    def read(self, handle, ordinal, sequence):
        self._enter()
        try:
            require(handle == self.handle, 'foreign producer handle', 'unauthorized')
            fingerprint, cached = self._begin(sequence, {'op': 'read', 'handle': handle, 'ordinal': ordinal})
            if cached is not None:
                return cached
            require(self.state == 'open' and type(ordinal) is int and ordinal == self._ordinal
                    and ordinal < self._summary.page_count, 'producer ordinal or state mismatch')
            try:
                result = self.reader.producer_read(self._token, self.binding, ordinal)
                page = ProducerPage(result, self.reader.last_prefix, self.reader.last_output_lease)
                self._ordinal += 1
                return self._finish(sequence, fingerprint, page, page.sha256)
            except BaseException:
                self.state, self._observation_complete = 'failed', False
                raise
        finally:
            self._lock.release()

    def acknowledge(self, sequence, response_digest):
        self._enter()
        try:
            if self._completed is None:
                require(self._last_ack == (sequence, response_digest), 'unknown producer ACK')
                return False
            item = self._completed
            require(sequence == item.sequence and response_digest == item.response_digest,
                    'foreign producer ACK', 'unauthorized')
            self._completed = None
            self._last_ack = sequence, response_digest
            if type(item.response) is ProducerPage:
                item.response.producer_released = True
            return True
        finally:
            self._lock.release()

    @property
    def completion(self):
        item = self._completed
        return None if item is None else (item.sequence, item.response_digest)

    def observe(self):
        raw = Snapshot.capture(self.reader.scope)
        credit = {'live_bytes': 0, 'peak_bytes': 0} if self._grant is None else self._grant.snapshot()
        return ExecutionObservation(raw, credit['live_bytes'], credit['peak_bytes'], self.state,
                                    self._observation_complete)

    def prepare_close(self, handle):
        """FD stop-only seam: destroy payloads, keep the prepaid grant/pin.

        Neither this acknowledgement nor Python logical object destruction is
        evidence of worker exit/reap or native memory release. The old local
        close path remains separate and retains its existing release behavior.
        """
        self._enter()
        try:
            require(handle == self.handle, 'foreign producer close', 'unauthorized')
            require(self.state != 'closed', 'local producer already closed', 'expired_context')
            if self.state != 'prepared':
                if self._reader_attempted:
                    self.reader.producer_close(self._token)
                if self._completed is not None and type(self._completed.response) is ProducerPage:
                    self._completed.response.producer_released = True
                self._completed = None
                self.state = 'prepared'
            return self.observe()
        finally:
            self._lock.release()

    def close(self, handle):
        self._enter()
        try:
            require(handle == self.handle, 'foreign producer close', 'unauthorized')
            if self.state == 'closed':
                return self.observe()
            # Destroy producer references before returning resident logical credit.
            if self._reader_attempted:
                self.reader.producer_close(self._token)
            if self._completed is not None and type(self._completed.response) is ProducerPage:
                self._completed.response.producer_released = True
            self._completed = None
            if self._grant is not None:
                self._grant.close_resident()
            self.state = 'closed'
            return self.observe()
        finally:
            self._lock.release()
