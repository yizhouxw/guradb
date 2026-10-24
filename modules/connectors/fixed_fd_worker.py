"""Private real-C1/producer FD adapter, not a launcher or acceptance driver.

Trusted composition must acquire fd0/bootstrap/config, create actual C1 and a
Linux ReadParent, and charge all credits in the original Rust owner first.
This seam never creates a SQL/PG client, decodes arbitrary endpoint config,
rebinds, releases a pin, claims native cost=0, or refunds the parent grant.
"""
import hashlib
import math
import threading

from modules.catalog.cf1a_controlled import ControlledReads
from modules.common.cf1a_primitives import ContractFailure, require
from modules.common.cf1a_read import validate_access
from modules.common.cf1a_wire import Contract
from modules.connectors.fixed_fd_protocol import (Credit, Transport, TYPES, KINDS, PHASES,
                                                 SAFE, encode, decode)
from modules.connectors.fixed_fd_protocol import scan_request
from modules.connectors.fixed_producer import FixedProducer
from modules.connectors.fixed_producer_credits import PreparedPermit, ProducerGrant
from modules.connectors.fixed_source_reader import FixedSourceReader
from modules.connectors.fixed_source_scope import SourceScope
from modules.storage.fixed_objects import FixedObjects
from modules.storage.fixed_parent import ControlledAuthority

ERRORS = dict(unsupported=1, invalid_contract=2, resource_limit=3, cancelled=4,
              deadline=5, revoked=6, expired_context=7, missing_object=8,
              backend_unavailable=9, corrupt_object=10, outcome_unknown=11, unauthorized=12)
ZERO_HASH = b'\0' * 32
ZERO_HANDLE = b'\0' * 16


def bounded(value):
    require(type(value) is int and 0 <= value <= SAFE, 'FD counter outside safe integer')
    return value


class FixedFdWorker:
    """One in-flight operation, one completed payload until its exact ACK.

    arena/raw/decode credit is a prepaid logical envelope, not a demonstrated
    Python/native upper bound. Its complete Root256/W proof remains pending.
    Real ControlledReads and FixedObjects type checks forbid a fake authority
    being presented as the production composition seam.
    """
    def __init__(self, transport, reads, backends, arena, *, request_decode_credit,
                 producer_credit):
        require(type(transport) is Transport and type(reads) is ControlledReads,
                'actual FD transport and C1 required')
        self.io, self.parent, self.reads = transport, transport.parent, reads
        require(getattr(reads.control.checkpoint, '__self__', None) is self.parent
                and reads.control.monotonic == self.parent.monotonic,
                'C1 does not use original parent')
        origin = self.parent.linux_origin
        require(type(arena) is Credit and (arena.session, arena.generation)
                == (origin.session, origin.generation), 'worker arena identity differs')
        require(type(request_decode_credit) is int and request_decode_credit <= SAFE and request_decode_credit >=
                2 * (256 * 57 + 4 * 1628 + 65536)
                and request_decode_credit + 65536 <= arena.amount,
                'missing precharged request raw/decode arena', 'resource_limit')
        require(type(producer_credit) is int and 0 < producer_credit <= 8 << 20,
                'invalid prepaid producer subpool', 'resource_limit')
        self.parent.catalog(reads.control)
        self.backends, self.arena = backends, arena
        self.decode_credit, self.producer_credit = request_decode_credit, producer_credit
        self.request = self.binding = self.producer = None
        self.state = 'new'
        self.first_error = None
        self._busy = False
        self._operation_lock = threading.Lock()
        self._finish_raw = self._data = self._page = None
        self._declaration = None
        self._call = None
        self._header = None
        self._epoch = self._lease_epoch = 0
        self._response_wire = self._response_extra = 0
        self._data_wire = self._data_extra = 0
        self._replayed = False

    def _send(self, kind, body):
        cost = len(body) + 80
        require(cost <= self._response_wire and cost <= self._response_extra,
                'response control subgrant exhausted', 'resource_limit')
        self._response_wire -= cost
        self._response_extra -= cost
        self.io.send(kind, self._header.sequence, self._header.ordinal, body, cost, cost)

    def _receive(self, message_type):
        return self.io.receive(message_type, self._header.sequence, self._header.ordinal)

    def _identity(self, handle, binding_hash):
        require(self.binding is not None and binding_hash == bytes.fromhex(self.binding.sha256),
                'FD binding differs', 'unauthorized')
        expected = ZERO_HANDLE if self.producer is None else bytes.fromhex(self.producer.handle)
        require(handle == expected, 'FD handle differs', 'unauthorized')

    def _parse_call(self, header, raw):
        require(len(raw) in (96, 144), 'CALL body length')
        call = decode('call', raw[:96])
        kind, flags, reserved, pgseq, cutoff, grant, handle, binding_hash, wire, extra = call
        require(kind in KINDS.values() and flags == reserved == 0, 'CALL closed fields')
        require(len(raw) == (144 if kind == KINDS['OPEN'] else 96), 'CALL caps shape')
        bounded(wire)
        bounded(extra)
        require(type(grant) is int and 0 < grant <= SAFE and wire > 0 and extra > 0,
                'CALL missing prepaid grants')
        require(cutoff > self.parent.linux_origin.original_t0_ns, 'CALL cutoff precedes T0')
        if kind in (1, 2, 6):
            require(header.ordinal == 0, 'PG operation ordinal must be zero')
        elif kind != 4:
            require(header.ordinal == 0, 'nonread source ordinal')
        self._header, self._call = header, call
        self._response_wire, self._response_extra = wire, extra
        self._replayed = False
        return kind, pgseq, cutoff

    def _bind(self):
        require(self.state == 'new' and self.binding is None, 'FD bind already consumed', 'expired_context')
        require(self._call[6] == ZERO_HANDLE and self._call[7] == ZERO_HASH, 'prebind CALL identity')
        self.state = 'binding'  # Failure consumes the sole bind attempt.
        offer = decode('offer', self._receive(TYPES['OFFER']))
        kind, role, flags, lease, grant, length, fingerprint, reserved = offer
        require((kind, role, flags, grant, reserved) == (1, 1, 0, self._call[5], b'\0' * 8)
                and 0 < lease <= SAFE and 0 < length <= 65536, 'BIND request OFFER differs')
        charge = self.arena.reserve(length + self.decode_credit)
        try:
            raw = bytearray(length)  # Pre-reserved before PERMIT and before reading any DATA.
            permit = encode('permit', 1, 1, 0, 0, lease, grant, length, fingerprint,
                            length, self.decode_credit, 80 + length, 80 + length)
            self._send(TYPES['PERMIT'], permit)
            self.io.receive(TYPES['DATA'], self._header.sequence, 0, data=raw, digest=fingerprint)
            scan_request(raw)
            self.request = Contract(bytes(raw))
            require(self.request.kind == 'bind_request' and self.request.encoded == raw,
                    'BIND request must be canonical')
            self._send(TYPES['ACK'], encode('ack', 1, 1, 1, 0, lease, length, fingerprint, b'\0' * 8))
            self.binding = self.reads.bind(self.request)  # The actual PG C1, exactly once.
            require(len(self.binding.encoded) <= 65536, 'binding response cap', 'resource_limit')
            self._epoch = self.binding.value['context']['auth']['policy_epoch']
            self.state = 'bound'
            self._offer_data(self.binding.encoded, 2)
        finally:
            # Retain the arena subgrant, request and issued binding until worker
            # exit/reap. No acknowledgement proves W physically free.
            self._request_charge = charge

    def _authorize(self, retiring=False):
        require(self.state == ('prepared' if retiring else 'bound')
                or (not retiring and self.state == 'open'), 'FD authority state')
        self._identity(self._call[6], self._call[7])
        self._epoch = self.reads.reauthorize(self.binding, operation_deadline=self.parent.effective_deadline())
        validate_access(self.binding.value, self.parent.wall_ms(), self._epoch)
        self.io.checkpoint()  # Fresh clocks after the blocking callback.
        if retiring:
            self.state = 'retiring'

    def _open(self, raw):
        require(self.state == 'bound', 'FD source already opened', 'expired_context')
        self._identity(self._call[6], self._call[7])
        resident, frame, frame_rows, fields, rows, pages = decode('caps', raw[96:])
        require(0 < resident <= self.producer_credit and 0 < frame <= 768 << 10
                and 0 < frame_rows <= 64 and 0 < fields <= 32
                and 0 < rows <= 1000 and 0 < pages <= 32, 'OPEN caps exceed P04 limits', 'resource_limit')
        scope = SourceScope(self.binding, parent=self.parent)
        objects = FixedObjects(scope, self.backends,
                               controlled=ControlledAuthority(self.parent, self.reads.reauthorize))
        self.producer = FixedProducer(FixedSourceReader(objects))
        origin = self.parent.linux_origin
        grant = ProducerGrant(PreparedPermit(origin.session.hex(), self.binding.sha256, origin.generation), resident)
        summary = self.producer.open(grant, self._header.sequence)
        require(summary.total_rows <= rows and summary.page_count <= pages and summary.fields <= fields,
                'actual producer declaration exceeds caps', 'resource_limit')
        self._frame_cap, self._frame_rows = frame, frame_rows
        self._producer_grant_id = self._call[5]
        self._declaration = encode('declaration', bytes.fromhex(summary.binding_sha256), self._call[5],
                                   bytes.fromhex(summary.handle), summary.total_rows,
                                   summary.page_count, summary.fields, frame, frame_rows)
        self.state = 'open'
        self._send(TYPES['DECLARATION'], self._declaration)

    def _read(self):
        require(self.state == 'open', 'FD read state')
        self._identity(self._call[6], self._call[7])
        require(self._call[5] == self._producer_grant_id, 'source grant differs', 'unauthorized')
        self._page = self.producer.read(self.producer.handle, self._header.ordinal, self._header.sequence)
        require(self._page.bytes <= self._frame_cap
                and len(self._page.contract.value['rows']) <= self._frame_rows,
                'actual page exceeds OPEN caps', 'resource_limit')
        prefix = self._page.prefix.validate(self._page.contract)
        counters = lambda snap: (snap.object_requests, snap.object_bytes, snap.output_bytes, snap.elapsed_ms)
        usage = self._page.contract.value['usage']
        proof = encode('prefix', *counters(prefix.base), *counters(prefix.usage_point),
                       *counters(prefix.at_a), usage['object_requests'], usage['object_bytes'],
                       usage['memory_bytes'], usage['output_bytes'], usage['elapsed_ms'],
                       prefix.batch_peak, prefix.a_bytes, bytes.fromhex(prefix.a_sha256),
                       self._header.ordinal, self._header.sequence)
        self._offer_data(self._page.contract.encoded, 3, proof)

    def _offer_data(self, raw, role, prefix=b''):
        self._lease_epoch += 1
        self._data, self._role = raw, role
        fingerprint = hashlib.sha256(raw).digest()
        offer = encode('offer', self._call[0], role, 0, self._lease_epoch,
                       self._call[5], len(raw), fingerprint, b'\0' * 8)
        self._send(TYPES['OFFER'], offer + prefix)
        permit = decode('permit', self._receive(TYPES['PERMIT']))
        kind, got_role, status, reserved, lease, grant, length, digest, raw_credit, decode_credit, wire, extra = permit
        require((kind, got_role, status, reserved, lease, grant, length, digest)
                == (self._call[0], role, 0, 0, self._lease_epoch, self._call[5], len(raw), fingerprint),
                'DATA PERMIT identity differs', 'unauthorized')
        for credit in (raw_credit, decode_credit, wire, extra):
            bounded(credit)
        require(raw_credit >= len(raw) and decode_credit > 0 and wire >= 80 + len(raw)
                and extra >= (80 + len(raw) if role == 2 else 80), 'DATA PERMIT lacks credit', 'resource_limit')
        self._data_wire, self._data_extra = wire, extra
        self._send_data(False)

    def _send_data(self, replay):
        cost = 80 + len(self._data)
        extra = cost if replay or self._role == 2 else 80
        require(cost <= self._data_wire and extra <= self._data_extra, 'DATA subgrant exhausted', 'resource_limit')
        self._data_wire -= cost
        self._data_extra -= extra
        self.io.send(TYPES['DATA'], self._header.sequence, self._header.ordinal,
                     self._data, cost, extra)

    def _finish(self, error=None):
        complete = error is None
        kind, pgseq = self._call[0], self._call[3]
        observation = None if self.producer is None or kind in (1, 2, 6) else self.producer.observe()
        counters = (0,) * 6 if observation is None else (
            observation.snapshot.object_requests, observation.snapshot.object_bytes,
            observation.snapshot.output_bytes, observation.snapshot.elapsed_ms,
            observation.logical_live_bytes, max(observation.snapshot.memory_peak, observation.logical_peak_bytes))
        invoice = self.reads.control.invoice
        counts = tuple(bounded(invoice['counts'].get(phase, 0)) for phase in PHASES)
        times = []
        for phase in PHASES:
            seconds = invoice['seconds'].get(phase, 0.0)
            require(type(seconds) in (int, float) and math.isfinite(seconds) and seconds >= 0, 'invalid PG phase time')
            times.append(bounded(math.ceil(seconds * 1_000_000)))
        code = 0 if complete else ERRORS.get(getattr(error, 'code', None), ERRORS['outcome_unknown'])
        status = 0 if complete else 2 if code == ERRORS['outcome_unknown'] else 1
        # Stop-only close is not a claim that every resident descriptor/lease
        # or native allocation is freed. The Rust resident/W grant stays live.
        flags = 1 if complete else 0
        pgflags = 7 if kind == 5 else (3 if complete else 1)
        self._finish_raw = encode('finish', kind, status, flags, code, b'\0' * 6,
                                  self._epoch, *(bounded(x) for x in counters), pgseq,
                                  pgflags, *counts, *times, b'\0' * 8)
        self._send(TYPES['OP_FINISH'], self._finish_raw)

    def _ack(self):
        while True:
            header, raw = self.io.receive((TYPES['ACK'], TYPES['RECONCILE']),
                                         self._header.sequence, self._header.ordinal, with_header=True)
            kind, role, mode, reserved, lease, length, fingerprint, tail = decode(
                'ack' if header.message_type == TYPES['ACK'] else 'reconcile', raw)
            target = (self._data if self._data is not None else self._declaration
                      if self._call[0] == 3 else self._finish_raw)
            expected_role = (self._role if self._data is not None else
                             5 if self._call[0] == 3 else 4 if self._call[0] == 5 else 0)
            expected_lease = self._lease_epoch if self._data is not None else 0
            require((kind, role, reserved, lease, length, fingerprint, tail)
                    == (self._call[0], expected_role, 0, expected_lease, len(target),
                        hashlib.sha256(target).digest(), b'\0' * 8), 'FD ACK/reconcile key differs')
            if header.message_type == TYPES['ACK']:
                require(mode in (1, 2), 'unknown ACK disposition')
                break
            require(not self._replayed and mode in (1, 2), 'FD replay budget exhausted', 'resource_limit')
            self._replayed = True
            if mode == 1:
                require(self._data is not None, 'no DATA to reconcile')
                self._send_data(True)  # Same permit, same bytes, no PG/read/second buffer.
            self._send(TYPES['OP_FINISH'], self._finish_raw)
        # The validation alias is itself an A owner. Drop it before either the
        # cache/worker references or the page's last Contract are relinquished.
        target = None
        if self.producer is not None and self.producer.completion is not None:
            sequence, fingerprint = self.producer.completion
            self.producer.acknowledge(sequence, fingerprint)
        self._data = self._declaration = None
        if self._page is not None:
            page, self._page = self._page, None
            page.release()  # Producer no longer owns it; consumer Rust retains its own lease.

    def serve_operation(self):
        require(self._operation_lock.acquire(blocking=False), 'FD operation in flight', 'resource_limit')
        self._call = self._header = self._finish_raw = None
        try:
            require(self.state not in ('failed', 'retired'), 'FD worker unavailable', 'expired_context')
            self._busy = True
            # Admit the next CALL against the original query cutoff. Its header
            # is part of this operation's32 messages and is never erased by begin.
            self.io.begin(self.parent.linux_origin.absolute_cutoff_ns)
            header, raw = self.io.receive(TYPES['CALL'], None, None, with_header=True)
            kind, pgseq, cutoff = self._parse_call(header, raw)
            self.io.tighten(cutoff)
            with self.parent.fd_operation(kind, header.sequence, pgseq, cutoff):
                if kind == 1:
                    self._bind()
                elif kind in (2, 6):
                    self._authorize(kind == 6)
                elif kind == 3:
                    self._open(raw)
                elif kind == 4:
                    self._read()
                else:
                    require(self.state == 'open', 'CLOSE_PREPARE requires opened producer')
                    self._identity(self._call[6], self._call[7])
                    require(self._call[5] == self._producer_grant_id, 'source grant differs', 'unauthorized')
                    self.producer.prepare_close(self.producer.handle)
                    self.state = 'prepared'
                self.io.checkpoint()
                self._finish()
                self._ack()
                if kind == 6:
                    self.state = 'retired'
                return self.state
        except BaseException as error:
            if self.first_error is None:
                self.first_error = error
            self.state = 'failed'
            # Only attempt a bounded lower-bound finish while transport remains
            # usable. Failure here never replaces the original execution error.
            if self._call is not None and not self.io.failed:
                try:
                    self._finish(error)
                except BaseException:
                    pass
            raise
        finally:
            self._busy = False
            self._operation_lock.release()

    def serve(self):
        while self.state != 'retired':
            self.serve_operation()
        # The launcher owns actual exit/status/FD shutdown. No grant release or
        # PG cleanup here; Rust must require exact normal exit/reap then cleanup.
        return 0
