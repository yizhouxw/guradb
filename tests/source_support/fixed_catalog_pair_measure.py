"""C3 observer retaining P04 assertions with the actual pre-bind T0 deadline."""
from copy import deepcopy
import time

from tests.source_support.fixed_acceptance import batch_rows
from tests.source_support.fixed_evidence import error_record, write
from tests.storage_support.acceptance import rss_bytes, scope_snapshot


def measured(reader, ordinal):
    scope = reader.scope
    before = scope.usage()
    start = time.monotonic()
    if reader.acceptance_cohort_started is None:
        reader.acceptance_cohort_started = start
    batch, sample, primary = None, None, None
    returned = None
    try:
        batch = reader.port.read_batch(scope.binding, ordinal)
        returned = time.monotonic()
        after, observed = scope.usage(), deepcopy(reader.last_observation)
        value, usage = batch.value, batch.value['usage']
        # Materialize observations before any acceptance assertion can fail.
        sample = {'ordinal': ordinal, 'context_sha256': scope.binding.sha256,
            'batch_sha256': batch.sha256, 'wire_bytes': len(batch.encoded), 'rows': batch_rows(batch),
            'last': value['last'], 'truncated': value['truncated'], 'usage': usage,
            'before': before, 'after': after, 'external_started_monotonic_s': start,
            'external_returned_monotonic_s': returned, 'page_elapsed_ms': (returned - start) * 1000,
            'cohort_elapsed_ms': (returned - reader.acceptance_cohort_started) * 1000,
            'finalization_tail_ms': (returned - observed['observed_monotonic_s']) * 1000,
            'post_precommit_tail_ms': (returned - observed['precommit_monotonic_s']) * 1000,
            'source_last_observation': observed, 'rss_peak_bytes': rss_bytes()}
        for key in ('object_requests', 'object_bytes', 'output_bytes'):
            assert usage[key] == after[key] - before[key], key
        assert 0 <= usage['elapsed_ms'] <= (returned - start) * 1000 + 1
        assert 0 < usage['memory_bytes'] <= 8 << 20
        assert len(value['rows']) <= 64 and len(batch.encoded) <= 768 << 10
        assert observed['observed_monotonic_s'] <= observed['precommit_monotonic_s'] <= returned
        assert (returned - start) < 1 and returned - reader.acceptance_cohort_started < 5
        assert scope.wire_bytes == scope.header_bytes + scope.object_bytes
        parent = reader.acceptance_parent
        admission = reader.acceptance_admission
        assert scope.started == parent.started == admission['t0']
        assert scope.deadline <= parent.deadline <= admission['initial_deadline']
        assert admission['initial_deadline'] == parent.started + reader.acceptance_timeout_ms / 1000
        wall_upper = admission['monotonic'] + (
            admission['issued_deadline_wall_ms'] - admission['wall_ms']) / 1000
        # Wall timestamps use integral milliseconds. This observation allowance
        # cannot extend the actual parent/query deadline enforced above.
        assert scope.deadline <= wall_upper + .001
        sample['admission'] = admission
        sample['binding_wall_mapping_upper_s'] = wall_upper + .001
        assert rss_bytes() <= 512 << 20
        sample['scope_io'] = scope_snapshot(scope, returned)
        return batch, sample
    except BaseException as error:
        primary = error
        raise
    finally:
        entry = {'ordinal': ordinal, 'context_sha256': scope.binding.sha256,
            'query_id': scope.context['query_id'], 'returned_envelope': batch is not None,
            'external_started_monotonic_s': start, 'external_returned_monotonic_s': returned,
            'after': scope.usage(), 'last_observation': deepcopy(reader.last_observation),
            'sample': sample, 'primary_error': error_record(primary) if primary is not None else None}
        reader.acceptance_journal.append(entry)
        if reader.acceptance_directory is not None:
            if batch is not None:
                (reader.acceptance_directory/f'call-{len(reader.acceptance_journal)-1}.json').write_bytes(batch.encoded)
            write(reader.acceptance_directory/'pages-journal.json', reader.acceptance_journal)
