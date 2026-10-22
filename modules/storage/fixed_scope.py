"""One bounded CF1-A execution scope, shared by every fixed-object read."""
from contextlib import contextmanager
import asyncio
import threading
import time

from modules.common.cf1a_primitives import ContractFailure, require


class ReadScope:
    """Trusted caller owns this scope for the complete binding, never an attempt.

    Returned bytes are conservatively retained until the scope is discarded.
    Logical reserved memory is distinct from process RSS in the acceptance report.
    Callbacks must be bounded in-memory operations, without blocking I/O.
    """
    def __init__(self, binding, cancelled=lambda: False, *, monotonic=time.monotonic,
                 wall_ms=lambda: time.time_ns() // 1_000_000, parent=None):
        require(binding.kind == 'read_binding', 'expected fixed read binding')
        self.binding = binding
        self.context = binding.value['context']
        self.budget = self.context['budget']
        self.parent = parent
        if parent is not None:
            from modules.storage.fixed_parent import ReadParent
            require(type(parent) is ReadParent, 'expected trusted read parent')
            self.budget = parent.attach(self, binding)
            cancelled, monotonic, wall_ms = parent.cancelled, parent.monotonic, parent.wall_ms
        self.cancelled, self.monotonic, self.wall_ms = cancelled, monotonic, wall_ms
        self.started = monotonic()
        remaining = min(self.context['remaining_ttl_ms'],
                        self.context['deadline_unix_ms'] - wall_ms()) / 1000
        self.deadline = self.started + max(0, remaining)
        if parent is not None:
            self.started, self.deadline = parent.started, min(self.deadline, parent.deadline)
        self.object_requests = self.object_bytes = self.output_bytes = 0
        self.header_bytes = self.wire_bytes = self.verified_bytes = 0
        self.last_header_positive_receive_elapsed_us = None
        self.last_body_positive_receive_elapsed_us = None
        self.last_socket_close_elapsed_us = None
        self.memory_current = self.memory_peak = 0
        self.trace = []
        self.trace_dropped = 0
        self._lock = threading.Lock()
        if parent is not None:
            parent.ready(self)

    def event(self, name):
        # No URI, headers, exceptions, credentials or caller text enters traces.
        elapsed_us = max(0, int((self.monotonic() - self.started) * 1_000_000))
        if name == 'socket_closed':
            self.last_socket_close_elapsed_us = elapsed_us
        if len(self.trace) < 128:
            self.trace.append({'event': name, 'elapsed_us': elapsed_us})
        else:
            self.trace_dropped += 1

    def effective_deadline(self):
        self.check()
        return self.deadline

    def check(self, *, slack=0):
        if self.parent is not None:
            self.parent.checkpoint()
        try:
            cancelled = self.cancelled()
        except Exception:
            raise ContractFailure('cancelled', 'cancellation status unavailable') from None
        require(type(cancelled) is bool and not cancelled, 'fixed read cancelled', 'cancelled')
        now_ms = self.wall_ms()
        require(now_ms >= self.context['bound_at_unix_ms'], 'clock precedes binding', 'expired_context')
        remaining = (self.context['deadline_unix_ms'] - now_ms) / 1000
        self.deadline = min(self.deadline, self.monotonic() + max(0, remaining))
        require(self.monotonic() + slack < self.deadline, 'fixed read deadline reached', 'deadline')

    @contextmanager
    def operation(self):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            require(False, 'synchronous fixed read requires a thread without an event loop',
                    'unsupported_capability')
        require(self._lock.acquire(blocking=False), 'concurrent reads of one scope rejected', 'resource_limit')
        try:
            self.check(slack=0.250)
            yield
        finally:
            self._lock.release()

    def request(self, expected_bytes):
        self.check(slack=0.250)
        require(self.object_requests < self.budget['object_requests'], 'request budget exhausted', 'resource_limit')
        require(expected_bytes + 1 <= self.budget['object_bytes'] - self.object_bytes,
                'body and EOF allowance exceed byte budget', 'resource_limit')
        self.object_requests += 1
        self.event('attempt_started')

    def received(self, count, *, header=False):
        if count > 0:
            elapsed_us = max(0, int((self.monotonic() - self.started) * 1_000_000))
            if header:
                self.last_header_positive_receive_elapsed_us = elapsed_us
            else:
                self.last_body_positive_receive_elapsed_us = elapsed_us
        self.wire_bytes += count
        if header:
            self.header_bytes += count
        else:
            require(count <= self.budget['object_bytes'] - self.object_bytes,
                    'received body exceeds byte budget', 'resource_limit')
            self.object_bytes += count

    def output(self, count):
        require(count <= self.budget['output_bytes'] - self.output_bytes,
                'output budget exhausted', 'resource_limit')

    def delivered(self, count):
        self.output(count)
        self.check()
        self.output_bytes += count
        self.event('output_delivered')

    def reserve(self, size):
        return Reservation(self, size)

    def usage(self):
        return {'object_requests': self.object_requests, 'object_bytes': self.object_bytes,
                'memory_bytes': self.memory_peak, 'output_bytes': self.output_bytes,
                'elapsed_ms': max(0, int((self.monotonic() - self.started) * 1000))}


class Reservation:
    def __init__(self, scope, size):
        require(type(size) is int and size >= 0, 'invalid memory reservation')
        self.scope, self.size, self.retained = scope, size, 0

    def __enter__(self):
        scope = self.scope
        require(self.size <= scope.budget['memory_bytes'] - scope.memory_current,
                'memory budget exhausted', 'resource_limit')
        scope.memory_current += self.size
        scope.memory_peak = max(scope.memory_peak, scope.memory_current)
        return self

    def keep(self, count):
        require(type(count) is int and 0 <= count <= self.size, 'invalid retained memory')
        self.retained = count

    def __exit__(self, kind, value, traceback):
        self.scope.memory_current -= self.size - (self.retained if kind is None else 0)
