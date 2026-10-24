"""Private GFD2 wire seam. Credits are precharged subgrants, never native proof.

The trusted Rust launcher owns the parent ledger. This module only constrains
its prepaid Python mirror; it does not mint parent credit or authenticate a
malicious peer sharing the interpreter. No configuration/PG client lives here.
"""
from dataclasses import dataclass
import hashlib
import os
import select
import struct
import threading
import time

from modules.common.cf1a_primitives import require

SAFE = (1 << 53) - 1
WIRE_CAP = 8 << 20
CONTROL_CAP = 1024
DATA_CAP = 768 << 10
TYPES = dict(CALL=1, OFFER=2, PERMIT=3, DATA=4, OP_FINISH=5,
             DECLARATION=6, ACK=7, ERROR=8, RECONCILE=9, CANCEL=10, HELLO=11)
KINDS = dict(BIND=1, AUTH=2, OPEN=3, READ=4, CLOSE_PREPARE=5, AUTH_RETIRE=6)
PHASES = ('connect_attempt', 'connect_success', 'connect_failure', 'wait',
          'sql_attempt', 'sql_success', 'sql_failure', 'commit_attempt',
          'commit_success', 'commit_failure', 'closed')
HEADER = struct.Struct('>4sHH16sQQQ32s')
# Exact body layouts from the joint wire-profile, including zero padding.
FORMATS = {
    'call': '>HHIQQQ16s32sQQ',
    'caps': '>6Q',
    'offer': '>HHIQQQ32s8s',
    'prefix': '>19Q32sQQ',
    'permit': '>HHHHQQQ32sQQQQ',
    'ack': '>HHHHQQ32s8s',
    'finish': '>HHIH6s' + 'Q' * 31 + '8s',
    'declaration': '>32sQ16s5Q',
    'reconcile': '>HHHHQQ32s8s',
    'error': '>HHIQQ',
    'hello': '>32s32s16sQQ',
    'bootstrap': '>H6s18Q32s32s32s8s',
}
SIZES = dict(call=96, caps=48, offer=72, prefix=200, permit=96, ack=64,
             finish=272, declaration=96, reconcile=64, error=24, hello=96,
             bootstrap=256)


def scan_request(raw):
    """Bound the fixed BindRequest profile before any JSON tree is created.

    57 nodes (including keys)/1628 decoded codepoints are the joint closed
    request shape. This lexical bound does not replace Contract validation,
    duplicate detection or canonical equality. It never grows a token list.
    """
    require(len(raw) <= 65536, 'request raw cap', 'resource_limit')
    nodes = text = position = depth = 0
    stack = [0] * 64
    while position < len(raw):
        byte = raw[position]
        if byte in b' \r\n\t,:':
            position += 1
            continue
        if byte in (ord('{'), ord('[')):
            require(depth < 64, 'request depth cap', 'resource_limit')
            stack[depth] = byte
            depth += 1
            nodes += 1
            position += 1
        elif byte in (ord('}'), ord(']')):
            require(depth > 0 and stack[depth - 1] == (ord('{') if byte == ord('}') else ord('[')),
                    'request container mismatch')
            depth -= 1
            position += 1
        elif byte == ord('"'):
            nodes += 1
            position += 1
            closed = False
            while position < len(raw):
                byte = raw[position]
                position += 1
                if byte == ord('"'):
                    closed = True
                    break
                require(byte >= 32, 'request control byte')
                if byte == ord('\\'):
                    require(position < len(raw), 'request short escape')
                    escape = raw[position]
                    position += 1
                    if escape == ord('u'):
                        require(position + 4 <= len(raw), 'request short Unicode escape')
                        token = bytes(raw[position:position + 4])
                        require(all(x in b'0123456789abcdefABCDEF' for x in token), 'request Unicode escape')
                        scalar = int(token, 16)
                        position += 4
                        if 0xD800 <= scalar <= 0xDBFF:
                            require(raw[position:position + 2] == b'\\u' and position + 6 <= len(raw),
                                    'request unmatched surrogate')
                            token = bytes(raw[position + 2:position + 6])
                            require(all(x in b'0123456789abcdefABCDEF' for x in token), 'request surrogate escape')
                            require(0xDC00 <= int(token, 16) <= 0xDFFF, 'request low surrogate')
                            position += 6
                        else:
                            require(not 0xDC00 <= scalar <= 0xDFFF, 'request lone surrogate')
                    else:
                        require(escape in b'"\\/bfnrt', 'request unknown escape')
                elif byte >= 128:
                    width = 2 if 0xC2 <= byte <= 0xDF else 3 if 0xE0 <= byte <= 0xEF else 4 if 0xF0 <= byte <= 0xF4 else 0
                    require(width and position + width - 1 <= len(raw), 'request UTF8 lead')
                    scalar = byte & (0x7F >> width)
                    for _ in range(width - 1):
                        part = raw[position]
                        require(0x80 <= part <= 0xBF, 'request UTF8 continuation')
                        scalar = (scalar << 6) | (part & 63)
                        position += 1
                    require(scalar >= (0x80 if width == 2 else 0x800 if width == 3 else 0x10000)
                            and scalar <= 0x10FFFF and not 0xD800 <= scalar <= 0xDFFF, 'request UTF8 scalar')
                text += 1
                require(text <= 1628, 'request text profile cap', 'resource_limit')
            require(closed, 'request unterminated string')
        else:
            start = position
            while position < len(raw) and raw[position] not in b' \r\n\t,:{}[]':
                position += 1
                require(position - start <= 17, 'request number/token cap', 'resource_limit')
            token = bytes(raw[start:position])
            if token not in (b'true', b'false', b'null'):
                require(token and (token.isdigit() or token[:1] == b'-' and token[1:].isdigit())
                        and token != b'-0' and abs(int(token)) <= SAFE, 'request integer token')
            nodes += 1
        require(nodes <= 57, 'request node profile cap', 'resource_limit')
    require(depth == 0, 'request unclosed container')
    return nodes, text


def encode(name, *values):
    require(name in FORMATS, 'unknown FD body')
    try:
        raw = struct.pack(FORMATS[name], *values)
    except (struct.error, TypeError, OverflowError):
        require(False, 'invalid FD body values')
    require(len(raw) == SIZES[name], 'FD body layout differs')
    return raw


def decode(name, raw):
    require(name in FORMATS and len(raw) == SIZES[name], 'FD body length differs')
    return struct.unpack(FORMATS[name], raw)


@dataclass(frozen=True)
class Header:
    message_type: int
    session: bytes
    sequence: int
    ordinal: int
    length: int
    sha256: bytes

    def encoded(self):
        self.validate()
        return HEADER.pack(b'GFD2', 2, self.message_type, self.session,
                           self.sequence, self.ordinal, self.length, self.sha256)

    def validate(self):
        require(type(self.message_type) is int and self.message_type in TYPES.values(), 'unknown FD type')
        require(type(self.session) is bytes and len(self.session) == 16 and any(self.session), 'invalid FD session')
        require(type(self.sequence) is int and 0 <= self.sequence <= SAFE
                and type(self.ordinal) is int and 0 <= self.ordinal <= SAFE, 'invalid FD sequence')
        require(self.sequence > 0 or (self.message_type in (10, 11) and self.ordinal == 0), 'zero FD sequence')
        cap = DATA_CAP if self.message_type == TYPES['DATA'] else CONTROL_CAP
        require(type(self.length) is int and 0 <= self.length <= cap, 'FD payload cap', 'resource_limit')
        require(type(self.sha256) is bytes and len(self.sha256) == 32, 'invalid FD digest')

    @classmethod
    def parse(cls, raw, session):
        require(len(raw) == 80, 'FD header length')
        magic, version, kind, actual, sequence, ordinal, length, fingerprint = HEADER.unpack(raw)
        require(magic == b'GFD2' and version == 2 and actual == session, 'FD header identity')
        header = cls(kind, actual, sequence, ordinal, length, fingerprint)
        header.validate()
        return header


class Credit:
    """Trusted composition hands in credit already charged in the Rust owner.

    Reserved bytes remain until explicit release of known destroyed local
    objects; a failed/partial transmission is never an automatic refund.
    """
    def __init__(self, amount, session, generation):
        require(type(amount) is int and 0 < amount <= SAFE, 'invalid prepaid credit')
        require(type(session) is bytes and len(session) == 16 and any(session)
                and type(generation) is int and 0 < generation <= SAFE, 'invalid credit identity')
        self.amount, self.session, self.generation = amount, session, generation
        self.live = self.peak = 0

    def reserve(self, amount):
        require(type(amount) is int and amount >= 0 and amount <= self.amount - self.live,
                'FD credit exhausted', 'resource_limit')
        self.live += amount
        self.peak = max(self.peak, self.live)
        return amount

    def release(self, amount):
        require(type(amount) is int and 0 <= amount <= self.live, 'invalid FD credit release')
        self.live -= amount


class Cancellation:
    """Inherited fd2 cancellation shared by PG checkpoints and FD waits."""
    def __init__(self, fd=2):
        require(type(fd) is int and fd == 2, 'expected inherited cancel fd2')
        self.fd, self.stopped, self.observed_bytes = fd, False, 0
        self._lock = threading.Lock()
        os.set_blocking(fd, False)

    def cancelled(self):
        with self._lock:
            if not self.stopped:
                ready, _, _ = select.select([self.fd], [], [], 0)
                if ready:
                    raw = os.read(self.fd, 16)
                    self.observed_bytes += len(raw)
                    self.stopped = True
            return self.stopped


class Transport:
    """One inherited control socket and cancellation read FD, no listener.

    All sends/receives use nonblocking FDs and the original absolute cutoff.
    The aggregate counts each locally observed physical byte once, both ways;
    Rust reconciles this mirror, it must not add two endpoint observations.
    """
    def __init__(self, fd, cancel_fd, parent, control_credit, *, bootstrap_wire_bytes):
        origin = parent.linux_origin
        require(origin is not None and type(fd) is int and type(cancel_fd) is int
                and fd == 1 and cancel_fd == 2, 'expected inherited fd1/fd2')
        cancellation = getattr(parent.cancelled, '__self__', None)
        require(type(cancellation) is Cancellation and cancellation.fd == cancel_fd,
                'FD and PG checkpoints must share inherited cancellation')
        require(type(control_credit) is Credit and control_credit.session == origin.session
                and control_credit.generation == origin.generation and control_credit.amount >= 2208,
                'FD control credit identity/cap differs')
        self.fd, self.cancel_fd, self.parent = fd, cancel_fd, parent
        self.cancellation, self._cancel_bytes = cancellation, 0
        self.session, self.control = origin.session, control_credit
        require(type(bootstrap_wire_bytes) is int and 336 <= bootstrap_wire_bytes <= 4432,
                'missing exact inherited bootstrap byte observation')
        self.wire_bytes = self.received_bytes = bootstrap_wire_bytes
        self.sent_bytes = 0
        self.messages = 0
        self.partial = False
        self.failed = False
        self._stopped = False
        self._cutoff = origin.absolute_cutoff_ns
        os.set_blocking(fd, False)
        os.set_blocking(cancel_fd, False)

    def begin(self, absolute_cutoff_ns):
        require(not self.failed, 'FD transport poisoned', 'expired_context')
        self.messages = 0
        self._cutoff = min(self.parent.linux_origin.absolute_cutoff_ns, absolute_cutoff_ns)
        self.checkpoint()

    def tighten(self, absolute_cutoff_ns):
        require(type(absolute_cutoff_ns) is int and 0 < absolute_cutoff_ns < 1 << 64,
                'invalid FD operation cutoff')
        self._cutoff = min(self._cutoff, absolute_cutoff_ns)
        self.checkpoint()

    def checkpoint(self):
        self._stopped = self.cancellation.cancelled()
        observed = self.cancellation.observed_bytes
        self._account(observed - self._cancel_bytes, False)
        self._cancel_bytes = observed
        require(not self._stopped, 'FD cancelled', 'cancelled')
        self.parent.checkpoint()
        remaining = (self._cutoff - time.clock_gettime_ns(time.CLOCK_MONOTONIC)) / 1e9
        require(remaining > 0, 'FD operation expired', 'deadline')
        return remaining

    def _account(self, count, sent):
        require(type(count) is int and count >= 0, 'invalid observed FD byte count')
        self.wire_bytes += count
        if sent:
            self.sent_bytes += count
        else:
            self.received_bytes += count
        require(self.wire_bytes <= WIRE_CAP, 'FD total wire exhausted', 'resource_limit')

    def _transfer(self, buffer, sending):
        view = memoryview(buffer)
        while view:
            require(len(view) <= WIRE_CAP - self.wire_bytes, 'FD physical wire admission', 'resource_limit')
            wait = min(.05, self.checkpoint())
            readable, writable, _ = select.select([self.cancel_fd] + ([] if sending else [self.fd]),
                                                 [self.fd] if sending else [], [], wait)
            if self.cancel_fd in readable:
                self.checkpoint()
            if (self.fd in writable) if sending else (self.fd in readable):
                try:
                    count = os.write(self.fd, view) if sending else os.readv(self.fd, [view])
                except BlockingIOError:
                    continue
                require(count > 0, 'FD short/EOF', 'outcome_unknown')
                self._account(count, sending)
                self.partial = True
                view = view[count:]
        self.checkpoint()

    def _message(self, length, *, header_received=False):
        require(self.messages < 32, 'FD operation message cap', 'resource_limit')
        require((0 if header_received else 80) + length <= WIRE_CAP - self.wire_bytes,
                'FD wire admission', 'resource_limit')
        self.messages += 1

    def send(self, message_type, sequence, ordinal, body, wire_credit, extra_credit):
        self._message(len(body))
        require(type(wire_credit) is int and 80 + len(body) <= wire_credit <= SAFE
                and type(extra_credit) is int and extra_credit <= SAFE and extra_credit >=
                (80 if message_type == TYPES['DATA'] else 80 + len(body)),
                'missing send wire/extra grant', 'resource_limit')
        header = Header(message_type, self.session, sequence, ordinal, len(body), hashlib.sha256(body).digest())
        charged = self.control.reserve(80)
        try:
            self._transfer(header.encoded(), True)
            self._transfer(body, True)
            self.partial = False
        except BaseException:
            self.failed = True
            raise
        finally:
            self.control.release(charged)

    def receive(self, expected_type, sequence, ordinal, *, data=None, digest=None, with_header=False):
        """DATA requires an already allocated prepaid buffer; no post-read grant."""
        charge = self.control.reserve(80 + (0 if data is not None else CONTROL_CAP))
        try:
            header_raw = bytearray(80)
            self._transfer(header_raw, False)
            header = Header.parse(header_raw, self.session)
            allowed = expected_type if type(expected_type) is tuple else (expected_type,)
            require(header.message_type in allowed
                    and (sequence is None or header.sequence == sequence)
                    and (ordinal is None or header.ordinal == ordinal), 'FD message key differs')
            self._message(header.length, header_received=True)
            if data is not None:
                require(header.message_type == TYPES['DATA'] and len(data) == header.length
                        and header.sha256 == digest, 'DATA differs from permitted offer')
                body = data
            else:
                require(header.message_type != TYPES['DATA'] and header.length <= CONTROL_CAP,
                        'DATA needs prepaid receive buffer', 'resource_limit')
                body = bytearray(header.length)
            self._transfer(body, False)
            require(hashlib.sha256(body).digest() == header.sha256, 'FD body hash differs', 'corrupt_object')
            self.partial = False
            return (header, body) if with_header else body
        except BaseException:
            self.failed = True
            raise
        finally:
            self.control.release(charge)
