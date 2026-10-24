"""One P03 query scope with private source batch observation and child limits.

The trusted composition root creates this scope before constructing FixedObjects;
the source does not clone a binding, budget, counter, or monotonic query anchor.
"""
from contextlib import contextmanager
import threading

from modules.common.cf1a_primitives import require
from modules.storage.fixed_scope import ReadScope, Reservation


class SourceScope(ReadScope):
    def __init__(self, binding, cancelled=lambda: False, **clocks):
        super().__init__(binding, cancelled, **clocks)
        self._batch_lock = threading.Lock()
        self._batch_thread = None
        self._page_deadline = self._cohort_deadline = None
        self.batch_started = None
        self._batch_peak = 0
        self.producer_credit = None
        self.producer_closed = False
        self.last_usage_point = None

    def check(self, *, slack=0):
        require(not self.producer_closed, 'producer scope closed', 'expired_context')
        super().check(slack=slack)
        # P03's 5ms I/O monitor dispatches here, including its 200ms cleanup
        # slack. The parent's query deadline is never assigned a child deadline.
        now = self.monotonic()
        for deadline in (self._cohort_deadline, self._page_deadline):
            if deadline is not None:
                require(now + slack < deadline, 'fixed source deadline reached', 'deadline')

    def effective_deadline(self):
        self.check()
        parent_deadline = (self.parent.effective_deadline()
                           if self.parent is not None and self.parent.linux_origin is not None else None)
        return min(value for value in (self.deadline, parent_deadline, self._cohort_deadline,
                                       self._page_deadline) if value is not None)

    def _observe(self):
        if self._batch_thread is not None:
            require(self._batch_thread == threading.get_ident(),
                    'source scope is in another batch', 'resource_limit')
            self._batch_peak = max(self._batch_peak, self.memory_current)

    def reserve(self, size):
        return SourceReservation(self, size)

    @contextmanager
    def operation(self):
        # Only P03 acquires its operation lock. The source batch has a different
        # lock, and every P03 read is still a complete, independently owned I/O.
        require(self._batch_thread in (None, threading.get_ident()),
                'source scope is in another batch', 'resource_limit')
        with super().operation():
            # The batch may have started after the first ownership check and
            # before this thread acquired P03's operation lock.
            require(self._batch_thread in (None, threading.get_ident()),
                    'source scope is in another batch', 'resource_limit')
            yield

    @contextmanager
    def batch(self):
        require(self._batch_lock.acquire(blocking=False),
                'concurrent source batches rejected', 'resource_limit')
        try:
            # Admission rejects a preexisting P03 operation or active asyncio
            # caller. Release its lock before any object read, avoiding nesting.
            with super().operation():
                self._batch_thread = threading.get_ident()
                started = self.monotonic()
                self.batch_started = started
                if self._cohort_deadline is None:
                    self._cohort_deadline = min(self.deadline, started + 5)
                self._page_deadline = min(self.deadline, self._cohort_deadline, started + 1)
                self._batch_peak = self.memory_current
            self.check()
            yield
        finally:
            self._page_deadline = None
            self.batch_started = None
            self._batch_thread = None
            self._batch_lock.release()

    def batch_usage(self, before):
        require(self._batch_thread == threading.get_ident(), 'no current source batch')
        after = self.usage()
        if self.producer_credit is not None:
            from modules.connectors.fixed_producer_observation import Snapshot
            self.last_usage_point = Snapshot.from_usage(after, self.memory_current)
        result = {key: after[key] - before[key]
                  for key in ('object_requests', 'object_bytes', 'output_bytes', 'elapsed_ms')}
        result['memory_bytes'] = self._batch_peak
        return result


class SourceReservation(Reservation):
    def __enter__(self):
        # Check ownership before touching the parent ledger. A failed reserve
        # leaves memory_current and the original query budget unchanged.
        self.scope._observe()
        require(self.size <= (8 << 20) - self.scope.memory_current,
                'fixed source live working set exceeds 8MiB', 'resource_limit')
        self._producer_lease = None
        if self.scope.producer_credit is not None:
            self._producer_lease = self.scope.producer_credit.reserve(self.size)
        try:
            super().__enter__()
        except BaseException:
            if self._producer_lease is not None:
                self._producer_lease.release()
            raise
        self.scope._observe()
        return self

    def __exit__(self, kind, value, traceback):
        super().__exit__(kind, value, traceback)
        if self._producer_lease is not None:
            retained = self.retained if kind is None else 0
            if retained:
                self._producer_lease.shrink(retained)
            else:
                self._producer_lease.release()
