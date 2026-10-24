"""Immutable producer observations; no transport or future-tail completeness claim."""
from dataclasses import dataclass

from modules.common.cf1a_primitives import require


@dataclass(frozen=True)
class Snapshot:
    object_requests: int
    object_bytes: int
    output_bytes: int
    elapsed_ms: int
    memory_current: int
    memory_peak: int

    @classmethod
    def from_usage(cls, usage, current):
        return cls(*(usage[key] for key in ('object_requests', 'object_bytes', 'output_bytes',
                                           'elapsed_ms')), current, usage['memory_bytes'])

    @classmethod
    def capture(cls, scope):
        return cls.from_usage(scope.usage(), scope.memory_current)

    def delta(self, base):
        result = tuple(getattr(self, key) - getattr(base, key) for key in
                       ('object_requests', 'object_bytes', 'output_bytes', 'elapsed_ms'))
        require(all(value >= 0 for value in result), 'producer cumulative observation regressed')
        return result


@dataclass(frozen=True)
class PrefixRecord:
    base: Snapshot
    usage_point: Snapshot
    at_a: Snapshot
    final: Snapshot
    batch_peak: int
    a_bytes: int
    a_sha256: str
    usage: tuple

    def validate(self, contract):
        value = contract.value['usage']
        expected = dict(zip(('object_requests', 'object_bytes', 'output_bytes', 'elapsed_ms'),
                            self.usage_point.delta(self.base)))
        expected['output_bytes'] += self.a_bytes
        expected['memory_bytes'] = self.batch_peak
        require(self.a_bytes == len(contract.encoded) and self.a_sha256 == contract.sha256
                and value == expected and self.usage == tuple(sorted(value.items())),
                'immutable A prefix witness mismatch')
        self.at_a.delta(self.usage_point)
        self.final.delta(self.at_a)
        return self


@dataclass(frozen=True)
class ProducerOpen:
    handle: str
    binding_sha256: str
    grant_id: str
    total_rows: int
    page_count: int
    fields: int
    frame_cap: int


@dataclass(frozen=True)
class ExecutionObservation:
    snapshot: Snapshot
    logical_live_bytes: int
    logical_peak_bytes: int
    state: str
    producer_observation_complete: bool
    # No IPC/PG/native completeness is asserted by this local lifecycle slice.
    pg_observation: object = None
    native_memory_bytes: object = None
    server_cost: object = None
