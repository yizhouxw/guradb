"""P0 schedule/trace negatives use an independent fake clock, never real sleep."""
import copy
import math
import unittest
from concurrent.futures import ThreadPoolExecutor
import threading
import time

from scripts.p0lib.schedule import plan, stop_on_exit, validate_capacity, validate_trace, wait_for_update


class Clock:
    def __init__(self, now=100.):
        self.now = now

    def __call__(self):
        return self.now


class Stop:
    def __init__(self, clock, *, cancel=False, oversleep=0.):
        self.clock, self.cancel, self.oversleep = clock, cancel, oversleep
        self.stopped, self.waits = False, []

    def is_set(self):
        return self.stopped

    def wait(self, seconds):
        self.waits.append(seconds)
        if self.cancel:
            self.stopped = True
        else:
            self.clock.now += seconds + self.oversleep
        return self.stopped


def valid_trace(duration=60):
    # Expected offsets are calculated from a hand-written rational schedule,
    # without calling plan, so plan and trace validation cannot agree by accident.
    offsets = [duration * numerator / 140 for numerator in (7, 24, 41, 58, 75, 92, 109, 126)]
    updates = [{'scheduled_seconds': offset, 'started_seconds': offset + .02,
                'published_seconds': offset + .2} for offset in offsets]
    requests = [{'started_seconds': second, 'completed_seconds': second + .5}
                for second in (1., 16., 31., 46.)]
    return updates, requests


class P0Schedule(unittest.TestCase):
    def test_main_failure_stops_waiting_writer_before_executor_shutdown(self):
        waiting, stop = threading.Event(), threading.Event()
        writes = []

        def writer():
            waiting.set()
            if wait_for_update(time.monotonic(), 10, stop):
                writes.append('unexpected append after main failure')

        with self.assertRaisesRegex(RuntimeError, 'resource assertion'):
            with ThreadPoolExecutor(1) as pool, stop_on_exit(stop):
                future = pool.submit(writer)
                self.assertTrue(waiting.wait(1))
                raise RuntimeError('resource assertion')
        self.assertTrue(future.done())
        self.assertTrue(stop.is_set())
        self.assertEqual(writes, [])

    def test_fixed_eight_updates_span_all_quarters(self):
        expected = [3, 72/7, 123/7, 174/7, 225/7, 276/7, 327/7, 54]
        for requested in (1, 2, 8):
            schedule = plan(60, requested)
            self.assertEqual(schedule.effective_count, 8)
            for actual, offset in zip(schedule.scheduled_offsets, expected):
                self.assertAlmostEqual(actual, offset)
            self.assertEqual(validate_capacity(schedule.effective_count),
                             {'writer_batches': 9, 'writer_rows': 384, 'catalog_runs': 10})

    def test_untimed_preserves_count_and_never_claims_sustained_load(self):
        self.assertEqual(plan(0, 2).scheduled_offsets, (0., 0.))
        trace = [{'scheduled_seconds': 0, 'started_seconds': 0, 'published_seconds': 1},
                 {'scheduled_seconds': 0, 'started_seconds': 1, 'published_seconds': 2}]
        result = validate_trace(0, trace, [{'started_seconds': 0, 'completed_seconds': 2}])
        self.assertFalse(result['continuous_writes_proven'])
        self.assertIn('no continuous-write evidence', result['claim'])

    def test_rejects_invalid_plan_parameters(self):
        for duration in (-1, 86401, math.nan, math.inf, -math.inf, True, '60', None):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                plan(duration, 2)
        for updates in (-1, 0, 9, 32, 1.0, True, None):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                plan(60, updates)
        self.assertEqual(plan(86400, 8).effective_count, 8)

    def test_capacity_boundaries_are_not_raised_for_timed_runs(self):
        self.assertEqual(validate_capacity(8, source_batches=24, source_rows=9872, catalog_runs=120),
                         {'writer_batches': 32, 'writer_rows': 10000, 'catalog_runs': 128})
        for kwargs in ({'source_batches': 25}, {'source_rows': 9873}, {'catalog_runs': 121},
                       {'source_batches': -1}, {'source_rows': True}, {'catalog_runs': 2.0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                validate_capacity(8, **kwargs)

    def test_wait_uses_absolute_time_and_can_stop(self):
        clock = Clock()
        stop = Stop(clock)
        self.assertTrue(wait_for_update(100, 3, stop, interval=7, clock=clock))
        self.assertEqual(stop.waits, [3])
        clock.now += 1  # Simulated build time does not shift the next deadline.
        self.assertTrue(wait_for_update(100, 10, stop, interval=7, clock=clock))
        self.assertEqual(stop.waits, [3, 6])
        cancelled = Stop(clock, cancel=True)
        self.assertFalse(wait_for_update(100, 20, cancelled, interval=7, clock=clock))
        self.assertEqual(clock.now, 110)
        self.assertFalse(wait_for_update(100, 20, cancelled, interval=7, clock=clock))
        self.assertEqual(cancelled.waits, [10])

    def test_late_start_and_oversleep_fail_before_append(self):
        for clock, oversleep in ((Clock(120), 0), (Clock(100), 8)):
            with self.subTest(clock=clock.now), self.assertRaisesRegex(ValueError, 'later'):
                wait_for_update(100, 3, Stop(clock, oversleep=oversleep), interval=7, clock=clock)
        for kwargs in ({'interval': 0}, {'interval': math.nan}, {'offset': -1}, {'start': -1}):
            arguments = {'start': 100, 'offset': 3, 'interval': 7, **kwargs}
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                wait_for_update(stop=Stop(Clock()), clock=Clock(), **arguments)

    def test_real_window_trace_and_tail_request_accounting(self):
        trace, requests = valid_trace()
        requests += [{'started_seconds': 59.9, 'completed_seconds': 60.2},
                     {'started_seconds': 61, 'completed_seconds': 62}]
        result = validate_trace(60, trace, requests)
        self.assertTrue(result['continuous_writes_proven'])
        self.assertEqual(result['append_starts_per_quartile'], [2, 2, 2, 2])
        self.assertEqual(result['publications_per_quartile'], [2, 2, 2, 2])
        self.assertEqual(result['reads_per_quartile'], [1, 1, 1, 1])
        self.assertEqual(result['out_of_window_requests'], 2)

    def test_two_front_loaded_updates_do_not_prove_sustained_load(self):
        trace, requests = valid_trace()
        with self.assertRaisesRegex(ValueError, 'count'):
            validate_trace(60, trace[:2], requests)
        for update in trace:
            update.update(started_seconds=1, published_seconds=2)
        with self.assertRaises(ValueError):
            validate_trace(60, trace, requests)

    def test_slow_build_late_slot_and_outside_window_fail(self):
        trace, requests = valid_trace()
        mutations = [
            (0, 'published_seconds', 61),
            (7, 'started_seconds', 61),
            (0, 'started_seconds', trace[1]['scheduled_seconds'] + 1),
            (0, 'scheduled_seconds', 0),
            (0, 'published_seconds', -1),
            (0, 'started_seconds', math.nan),
        ]
        for index, field, value in mutations:
            broken = copy.deepcopy(trace)
            broken[index][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                validate_trace(60, broken, requests)
        overlapping = copy.deepcopy(trace)
        overlapping[0]['published_seconds'] = 11
        with self.assertRaisesRegex(ValueError, 'overlap'):
            validate_trace(60, overlapping, requests)
        late = copy.deepcopy(trace)
        late[0]['started_seconds'] = 11
        late[0]['published_seconds'] = 11.1
        with self.assertRaisesRegex(ValueError, 'later'):
            validate_trace(60, late, requests)

    def test_missing_quarter_cannot_use_planned_times_or_tail_reads(self):
        trace, requests = valid_trace()
        # A slow first build pushes both early publications out of quarter one.
        trace[0]['published_seconds'] = 15.1
        trace[1]['started_seconds'] = 15.1
        trace[1]['published_seconds'] = 15.2
        with self.assertRaisesRegex(ValueError, 'quartile'):
            validate_trace(60, trace, requests)
        trace, requests = valid_trace()
        requests[-1]['completed_seconds'] = 60.1
        with self.assertRaisesRegex(ValueError, 'quartile'):
            validate_trace(60, trace, requests)

    def test_missing_nonfinite_and_inverted_evidence_is_rejected(self):
        trace, requests = valid_trace()
        for broken in ([], [{}], [{'started_seconds': -1, 'completed_seconds': 2}],
                       [{'started_seconds': 2, 'completed_seconds': 1}],
                       [{'started_seconds': 1, 'completed_seconds': math.inf}]):
            with self.subTest(requests=broken), self.assertRaises(ValueError):
                validate_trace(60, trace, broken)
        broken = copy.deepcopy(trace)
        del broken[0]['published_seconds']
        with self.assertRaises(ValueError):
            validate_trace(60, broken, requests)


if __name__ == '__main__':
    unittest.main()
