"""Private trusted Linux origin import; no FD, transport or shared credit ledger."""
from contextlib import contextmanager
from dataclasses import dataclass
import math
import struct
import sys
import threading
import time
import uuid

from modules.common.cf1a_primitives import require

_U64 = (1 << 64) - 1
_SAFE = (1 << 53) - 1


def integer(value, maximum=_U64):
    require(type(value) is int and 0 <= value <= maximum, 'invalid anchor integer')
    return value


def seconds_floor(ns):
    """Project to the existing seconds interface, never beyond exact ns/1e9."""
    integer(ns)
    value = ns / 1_000_000_000
    numerator, denominator = value.as_integer_ratio()
    if numerator * 1_000_000_000 > ns * denominator:
        value = math.nextafter(value, -math.inf)
    return value


def slack_ns(seconds):
    require(type(seconds) in (int, float) and math.isfinite(seconds) and seconds >= 0,
            'invalid deadline slack')
    numerator, denominator = seconds.as_integer_ratio()
    return (numerator * 1_000_000_000 + denominator - 1) // denominator


def current_boot():
    require(sys.platform == 'linux' and struct.calcsize('P') == 8,
            'Linux64 anchor required', 'unsupported_capability')
    with open('/proc/sys/kernel/random/boot_id', 'rb') as source:
        raw = source.read(38)
    require(len(raw) == 37 and raw[-1:] == b'\n', 'invalid Linux boot identity')
    try:
        parsed = uuid.UUID(raw[:36].decode('ascii'))
    except (ValueError, UnicodeError):
        require(False, 'invalid Linux boot identity')
    require(str(parsed).encode() == raw[:36] and parsed.int != 0, 'invalid Linux boot identity')
    return parsed.bytes


def current_ns():
    return integer(time.clock_gettime_ns(time.CLOCK_MONOTONIC))


def check_cancel(cancelled):
    from modules.common.cf1a_primitives import ContractFailure
    try:
        stopped = cancelled()
    except Exception:
        raise ContractFailure('cancelled', 'anchor cancellation unavailable') from None
    require(type(stopped) is bool and not stopped, 'anchor cancelled', 'cancelled')


@dataclass(frozen=True)
class LinuxOrigin:
    boot: bytes
    session: bytes
    nonce: bytes
    generation: int
    original_t0_ns: int
    absolute_cutoff_ns: int


class TrustedLinuxAnchor:
    """Only the trusted composition root supplies inherited-config identity.

    This is a local ownership token, not authentication against malicious code
    in the same interpreter. Actual trusted FD acquisition remains a later slice.
    """
    def __init__(self, raw, *, session, nonce, generation):
        require(type(raw) is bytes and len(raw) == 80, 'expected exact prepaid 80B anchor')
        require(type(session) is bytes and len(session) == 16 and any(session), 'invalid launch session')
        require(type(nonce) is bytes and len(nonce) == 16 and any(nonce), 'invalid launch nonce')
        require(integer(generation, _SAFE) > 0, 'invalid launch generation')
        self._raw, self._identity = raw, (session, nonce, generation)
        self._consumed, self._lock = False, threading.Lock()

    def consume(self, cancelled):
        with self._lock:
            require(not self._consumed, 'anchor import already consumed', 'expired_context')
            self._consumed = True
            require(callable(cancelled), 'invalid anchor cancellation')
            raw = self._raw
            require(raw[:8] == b'GLNA\x00\x02\x01\x02', 'unsupported Linux anchor layout')
            boot, session, nonce = raw[8:24], raw[24:40], raw[40:56]
            generation, started, cutoff = struct.unpack('>QQQ', raw[56:])
            require((session, nonce, generation) == self._identity, 'anchor launch identity differs')
            require(cutoff > started, 'invalid anchor cutoff')
            require(boot == current_boot(), 'anchor boot differs')
            check_cancel(cancelled)
            now = current_ns()
            require(now >= started, 'anchor T0 is in the future')
            require(now < cutoff, 'anchor deadline reached', 'deadline')
            return LinuxOrigin(boot, session, nonce, generation, started, cutoff), now


@dataclass(frozen=True)
class ActiveOperation:
    sequence: int
    pg_sequence: int
    absolute_cutoff_ns: int


class LinuxDeadline:
    """Actual ns remains authoritative; seconds values are compatibility views."""
    def __init__(self, origin, now):
        self.origin = origin
        self._cutoff, self._last = origin.absolute_cutoff_ns, now
        self._active, self._last_sequence, self._last_pg_sequence = None, 0, 0
        self._sequence_profile = None
        self._lock = threading.RLock()

    def _now(self):
        require(current_boot() == self.origin.boot, 'anchor boot changed')
        now = current_ns()
        require(now >= self._last, 'Linux monotonic clock moved backwards')
        self._last = now
        return now

    def monotonic(self):
        with self._lock:
            return seconds_floor(self._now())

    @property
    def cutoff_ns(self):
        with self._lock:
            return self._cutoff

    def effective_ns(self):
        with self._lock:
            return min(self._cutoff, self._active.absolute_cutoff_ns) if self._active else self._cutoff

    def checkpoint(self, slack=0):
        with self._lock:
            require(self._now() + slack_ns(slack) < self.effective_ns(),
                    'anchor execution deadline reached', 'deadline')
            return seconds_floor(self.effective_ns())

    def elapsed_ms(self):
        with self._lock:
            return (self._now() - self.origin.original_t0_ns) // 1_000_000

    def tighten_binding(self, remaining_ms):
        with self._lock:
            now = self._now()
            require(type(remaining_ms) is int, 'invalid binding remaining time')
            remaining_ns = integer(max(0, remaining_ms)) * 1_000_000
            require(now + remaining_ns <= _U64, 'binding deadline overflows ns')
            self._cutoff = min(self._cutoff, now + remaining_ns)
            return seconds_floor(self._cutoff)

    @contextmanager
    def operation(self, sequence, pg_sequence, absolute_cutoff_ns):
        integer(sequence, _SAFE)
        integer(pg_sequence, _SAFE)
        integer(absolute_cutoff_ns)
        with self._lock:
            require(self._sequence_profile in (None, 'legacy'), 'mixed anchor sequence profile')
            self._sequence_profile = 'legacy'
            require(sequence > self._last_sequence and pg_sequence > self._last_pg_sequence,
                    'invalid or repeated operation sequence')
            require(self._active is None, 'anchor operation already active', 'resource_limit')
            self._last_sequence, self._last_pg_sequence = sequence, pg_sequence
            active = ActiveOperation(sequence, pg_sequence, min(self._cutoff, absolute_cutoff_ns))
            self._active = active
        try:
            self.checkpoint()
            yield active
        finally:
            with self._lock:
                require(self._active is active, 'anchor operation ownership differs')
                self._active = None

    @contextmanager
    def fd_operation(self, kind, sequence, pg_sequence, absolute_cutoff_ns):
        """Joint GFD2 domains; no surrogate sequence or reference PG ticket.

        BIND/AUTH/RETIRE use header=PG sequence; OPEN/READ advance both actual
        source and outer PG counters; CLOSE advances source only with PG zero.
        A replay belongs to the FD registry and never re-enters this API.
        """
        require(type(kind) is int and kind in (1, 2, 3, 4, 5, 6), 'invalid FD operation kind')
        require(integer(sequence, _SAFE) > 0, 'invalid FD header sequence')
        integer(pg_sequence, _SAFE)
        integer(absolute_cutoff_ns)
        with self._lock:
            require(self._sequence_profile in (None, 'fd'), 'mixed anchor sequence profile')
            self._sequence_profile = 'fd'
            require(self._active is None, 'anchor operation already active', 'resource_limit')
            if kind in (1, 2, 6):
                require(sequence == pg_sequence and pg_sequence > self._last_pg_sequence,
                        'FD PG sequence differs or repeated')
            else:
                require(sequence > self._last_sequence, 'FD source sequence repeated')
                if kind == 5:
                    require(pg_sequence == 0, 'close reference cannot mint PG ticket')
                else:
                    require(pg_sequence > self._last_pg_sequence, 'FD outer PG sequence repeated')
                self._last_sequence = sequence
            if pg_sequence:
                self._last_pg_sequence = pg_sequence
            active = ActiveOperation(sequence, pg_sequence, min(self._cutoff, absolute_cutoff_ns))
            self._active = active
        try:
            self.checkpoint()
            yield active
        finally:
            with self._lock:
                require(self._active is active, 'anchor operation ownership differs')
                self._active = None
