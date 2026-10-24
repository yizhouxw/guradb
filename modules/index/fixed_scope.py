"""Injected, cumulative execution accounting; no authorization or catalog cache."""
import time
from modules.common.cf1a_primitives import require, validate_shape
from modules.common.cf1a_read import validate_access


class ExecutionScope:
    """Caller owns one parent scope across attempts; trusted callbacks stay injected.

    reauthorize must perform current authority validation and return its epoch.
    Memory accounting is a conservative reservation peak, never a reset per batch.
    """
    def __init__(self, binding, reauthorize, cancelled, now_unix_ms, monotonic=time.monotonic):
        require(binding.kind == 'read_binding', 'expected scope binding')
        self.binding = binding
        self.reauthorize = reauthorize
        self.cancelled = cancelled
        self.now_unix_ms = now_unix_ms
        self.monotonic = monotonic
        self.started = monotonic()
        now = now_unix_ms()
        validate_shape(now, 'n')
        context = binding.value['context']
        ttl = min(context['remaining_ttl_ms'], context['deadline_unix_ms'] - now)
        self.deadline = self.started + ttl / 1000
        self.usage = dict.fromkeys(('object_requests', 'object_bytes', 'memory_bytes', 'output_bytes'), 0)
        self.metrics = dict.fromkeys(('checks', 'scanned_rows', 'checksum_bytes', 'decoded_bytes', 'sealed_bytes'), 0)
        self.checkpoint()

    def checkpoint(self):
        require(self.monotonic() < self.deadline, 'execution monotonic deadline reached', 'deadline')
        cancelled = self.cancelled()
        require(type(cancelled) is bool, 'invalid cancellation state')
        require(not cancelled, 'execution cancelled', 'cancelled')
        epoch = self.reauthorize(self.binding)
        cancelled = self.cancelled()
        require(type(cancelled) is bool, 'invalid cancellation state')
        require(not cancelled, 'execution cancelled after authorization', 'cancelled')
        # Both callbacks can consume the scope. Read clocks only after they return.
        now, monotonic_now = self.now_unix_ms(), self.monotonic()
        validate_access(self.binding.value, now, epoch)
        wall_remaining = (self.binding.value['context']['deadline_unix_ms'] - now) / 1000
        self.deadline = min(self.deadline, monotonic_now + wall_remaining)
        require(monotonic_now < self.deadline, 'execution monotonic deadline reached', 'deadline')
        self.metrics['checks'] += 1

    def matches(self, binding):
        require(binding.sha256 == self.binding.sha256, 'scope belongs to another binding')
        self.checkpoint()

    def charge(self, name, amount):
        require(name in self.usage, 'unknown budget counter')
        validate_shape(amount, 'n')
        value = max(self.usage[name], amount) if name == 'memory_bytes' else self.usage[name] + amount
        require(value <= self.binding.value['context']['budget'][name], 'execution budget exceeded', 'resource_limit')
        self.usage[name] = value

    def read(self, port, ref):
        self.checkpoint()
        self.charge('object_requests', 1)
        self.charge('object_bytes', ref['size_bytes'])
        # Reserve before allocation/decoding. The closed layout is additionally bounded to 1MiB.
        self.charge('memory_bytes', ref['size_bytes'] * 64)
        return port.read(self.binding, ref, 0, ref['size_bytes'])

    def scan(self):
        self.checkpoint()
        self.metrics['scanned_rows'] += 1

    def snapshot(self):
        elapsed = max(0, int((self.monotonic() - self.started) * 1000))
        validate_shape(elapsed, 'n')
        return {**self.usage, 'elapsed_ms': elapsed}


def delta_usage(before, after):
    return {name: (after[name] if name == 'memory_bytes' else after[name] - before[name])
            for name in after}
