"""Private cooperative parent control and bounded PG observations, not A wire.

The trusted host creates its parent before bind. Callbacks only inspect that
same in-memory parent; they cannot perform I/O or create another time budget.
PG/native memory is outside this observation profile, never reported as zero.
"""
from dataclasses import dataclass, field
import math
import time

from modules.common.cf1a_primitives import ContractFailure, require


def finite(value):
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0,
            'invalid parent monotonic value')
    return value


@dataclass(frozen=True)
class CatalogReadControl:
    checkpoint: object
    monotonic: object
    _counts: dict = field(default_factory=dict, init=False, repr=False, compare=False)
    _seconds: dict = field(default_factory=dict, init=False, repr=False, compare=False)
    _events: list = field(default_factory=list, init=False, repr=False, compare=False)

    def __post_init__(self):
        require(callable(self.checkpoint) and callable(self.monotonic),
                'expected trusted bounded parent callbacks')

    def now(self):
        try:
            return finite(self.monotonic())
        except ContractFailure:
            raise
        except Exception:
            raise ContractFailure('cancelled', 'parent monotonic clock unavailable') from None

    def _parent(self):
        try:
            return finite(self.checkpoint())
        except ContractFailure:
            raise
        except Exception:
            raise ContractFailure('cancelled', 'parent control unavailable') from None

    def remaining(self, operation_deadline):
        # Take fresh time AFTER the parent's cancellation/checkpoint callback.
        parent = self._parent()
        value = min(finite(operation_deadline), parent) - self.now()
        require(value > 0, 'catalog parent deadline reached', 'deadline')
        return value

    def limit(self, seconds):
        require(finite(seconds) > 0, 'invalid catalog operation limit')
        parent = self._parent()
        now = self.now()
        require(parent > now, 'catalog parent deadline reached', 'deadline')
        return min(parent, now + seconds)

    def mark(self, phase, started=None):
        require(phase in ('connect_attempt', 'connect_success', 'connect_failure',
                         'wait', 'sql_attempt', 'sql_success', 'sql_failure',
                         'commit_attempt', 'commit_success', 'commit_failure', 'closed'),
                'invalid private catalog observation')
        self._counts[phase] = self._counts.get(phase, 0) + 1
        elapsed = 0.0 if started is None else max(0.0, time.monotonic() - started)
        if started is not None:
            self._seconds[phase] = self._seconds.get(phase, 0.0) + elapsed
        if len(self._events) < 128:
            self._events.append((phase, elapsed))

    @property
    def invoice(self):
        return {'counts': dict(self._counts), 'seconds': dict(self._seconds),
                'events': tuple(self._events),
                'events_dropped': sum(self._counts.values()) - len(self._events),
                'timing': 'nested observations; parent elapsed is not their sum',
                'pg_native_memory_bytes': None, 'object_requests': None}


def transaction(store, deadline, control):
    # Do not add a keyword to legacy injected stores or change their API.
    return store.transaction(deadline) if control is None else store.transaction(deadline, control)
