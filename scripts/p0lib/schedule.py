"""Absolute P0 update times and fail-closed validation of measured window traces.

Timed runs use eight updates, preserving the 256-row initial input and 16-row
append size. Requested updates remain a minimum; the accepted CLI range is 1..8.
This module schedules evidence collection, not production writes or admission.
"""
import math
from contextlib import contextmanager
from numbers import Real
import time
from typing import NamedTuple


class UpdatePlan(NamedTuple):
    scheduled_offsets: tuple[float, ...]
    effective_count: int


@contextmanager
def stop_on_exit(stop):
    """Enter after the executor so cancellation precedes shutdown(wait=True)."""
    try:
        yield
    finally:
        stop.set()


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise ValueError(f'{label} must be a finite number')
    return float(value)


def _count(value, label, minimum=0):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f'{label} must be an integer >= {minimum}')
    return value


def validate_capacity(update_count, *, source_batches=1, source_rows=256, catalog_runs=2):
    """Check existing capacity plus planned writes against unchanged hard limits.

    The defaults include the initial document append and both document/graph
    catalog runs. Retrying the same operation does not allocate another batch.
    """
    _count(update_count, 'update_count', 1)
    usage = {'writer_batches': _count(source_batches, 'source_batches') + update_count,
             'writer_rows': _count(source_rows, 'source_rows') + 16 * update_count,
             'catalog_runs': _count(catalog_runs, 'catalog_runs') + update_count}
    for name, limit in (('writer_batches', 32), ('writer_rows', 10000), ('catalog_runs', 128)):
        if usage[name] > limit:
            raise ValueError(f'{name} exceeds existing limit {limit}: {usage[name]}')
    return usage


def plan(duration, updates):
    """Return fixed absolute offsets; a zero duration makes no sustained claim."""
    duration = _number(duration, 'duration')
    if not 0 <= duration <= 86400:
        raise ValueError('duration must be in 0..86400 seconds')
    if not 1 <= _count(updates, 'updates', 1) <= 8:
        raise ValueError('updates must be in 1..8')
    count = 8 if duration else updates
    validate_capacity(count)
    offsets = tuple(duration * (0.05 + 0.85 * i / 7) for i in range(count)) if duration else (0.,) * count
    return UpdatePlan(offsets, count)


def wait_for_update(start, offset, stop, *, interval=None, clock=time.monotonic):
    """Wait for one absolute deadline, returning False on cancellation.

    Passing the planned interval rejects a missed slot before its append starts;
    callers must not catch that failure and perform a burst of catch-up writes.
    The injected clock and Event-compatible stop make this testable without sleep.
    """
    start, offset = _number(start, 'start'), _number(offset, 'offset')
    if start < 0 or offset < 0:
        raise ValueError('start and offset must be nonnegative')
    if interval is not None and _number(interval, 'interval') <= 0:
        raise ValueError('interval must be positive')
    while not stop.is_set():
        now = _number(clock(), 'clock')
        remaining = start + offset - now
        if remaining <= 0:
            if interval is not None and now - start - offset > interval:
                raise ValueError('update start is later than one scheduled interval')
            return True
        if stop.wait(remaining):
            return False
    return False


def _times(item, names):
    try:
        values = [_number(item[name], name) for name in names]
    except (KeyError, TypeError) as exc:
        raise ValueError(f'trace requires {", ".join(names)}') from exc
    if values[0] < 0 or any(left > right for left, right in zip(values, values[1:])):
        raise ValueError('trace times must be nonnegative and ordered')
    return values


def _quartile(seconds, duration):
    return min(3, int(4 * seconds / duration))


def validate_trace(duration, trace, observations):
    """Validate recorded times relative to the same monotonic window origin.

    Updates require scheduled_seconds, started_seconds and published_seconds.
    Requests require started_seconds and completed_seconds. Tail requests remain
    in raw evidence but count only if their entire execution is in the window.
    Append starts, publication completions, and complete reads must each cover
    all four quarters. Zero-duration runs never prove continuous writes.
    """
    duration = _number(duration, 'duration')
    expected = plan(duration, 1)
    if not isinstance(trace, (list, tuple)) or not isinstance(observations, (list, tuple)):
        raise ValueError('trace and observations must be sequences')
    if not trace or not observations:
        raise ValueError('update and request evidence must not be empty')
    if (duration and len(trace) != expected.effective_count) or (not duration and len(trace) > 8):
        raise ValueError('update evidence count does not match the bounded schedule')
    validate_capacity(len(trace))
    starts, publications, reads = [0] * 4, [0] * 4, [0] * 4
    delays, excluded, previous_publish = [], 0, 0.
    interval = expected.scheduled_offsets[1] - expected.scheduled_offsets[0] if duration else None
    for number, entry in enumerate(trace):
        scheduled, started, published = _times(
            entry, ('scheduled_seconds', 'started_seconds', 'published_seconds'))
        if started < previous_publish:
            raise ValueError('serial updates overlap or are out of order')
        previous_publish = published
        if not duration:
            if scheduled != 0:
                raise ValueError('untimed updates must use zero scheduled offsets')
            continue
        if not math.isclose(scheduled, expected.scheduled_offsets[number], rel_tol=0, abs_tol=1e-9):
            raise ValueError('recorded schedule differs from the frozen absolute offsets')
        if published > duration:
            raise ValueError('append and publication must finish inside the measurement window')
        delay = started - scheduled
        if delay > interval:
            raise ValueError('update start is later than one scheduled interval')
        delays.append(delay)
        starts[_quartile(started, duration)] += 1
        publications[_quartile(published, duration)] += 1
    for observation in observations:
        started, completed = _times(observation, ('started_seconds', 'completed_seconds'))
        if duration:
            if completed <= duration:
                reads[_quartile(started, duration)] += 1
            else:
                excluded += 1
    if duration and (not all(starts) or not all(publications) or not all(reads)):
        raise ValueError('each window quartile requires actual append, publication and complete read evidence')
    return {'continuous_writes_proven': bool(duration),
            'window_seconds': duration,
            'update_count': len(trace),
            'append_starts_per_quartile': starts,
            'publications_per_quartile': publications,
            'reads_per_quartile': reads,
            'out_of_window_requests': excluded,
            'maximum_start_delay_seconds': max(delays, default=0.),
            'claim': 'synthetic component window only; not production soak' if duration else
                     'untimed component integration; no continuous-write evidence'}
