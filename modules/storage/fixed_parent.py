"""Private pre-bind parent and explicit network authority, without catalog imports."""
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
        self.cancelled, self.monotonic, self.wall_ms = cancelled, monotonic, wall_ms
        self.started = finite(monotonic())
        self.deadline = self.started + timeout_ms / 1000
        self._budget, self._scope, self._catalog = dict(budget), None, None
        self._attached, self._admission = False, 'not_attempted'
        self._lock = threading.Lock()

    def checkpoint(self):
        try:
            stopped = self.cancelled()
        except Exception:
            raise ContractFailure('cancelled', 'parent cancellation unavailable') from None
        require(type(stopped) is bool and not stopped, 'parent cancelled', 'cancelled')
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
                                context['deadline_unix_ms'] - self.wall_ms()) / 1000
                self.deadline = min(self.deadline, finite(self.monotonic()) + max(0, remaining))
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
                'elapsed_ms': max(0, int((self.monotonic() - self.started) * 1000)),
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
