"""Independent real Parquet consumer and whole-call B2 observations.

Only the LocatedBatch and fixed fixture are consumed; producer state is never
read to infer a locator, expected value, page boundary or source membership.
"""
from copy import deepcopy
import json
import time

import pyarrow as pa
import pyarrow.parquet as pq

from modules.connectors.fixed_source_located import validate_located_for
from modules.storage.fixed_cache import VerifiedCache
from tests.source_support.fixed_acceptance import batch_rows, expected_rows, instance, save_case_input
from tests.source_support.fixed_evidence import error_record, observation, write
from tests.source_support.fixed_fixture import encoded, sha
from tests.storage_support.acceptance import rss_bytes, scope_snapshot


def consume_located(binding, located, fixture):
    """Read each exact fixed object/RG/offset with PyArrow, not a producer lookup."""
    sidecar = validate_located_for(binding, located)
    value = binding.value
    sources = {source['source_version_id']: source for source in value['revision']['sources']}
    metadata = {item['source_version_id']: item for item in fixture['source_metadata']}
    evidence = []
    for row, position in zip(located.batch.value['rows'], sidecar['rows']):
        locator = position['locator']
        source, current = sources[locator['source_version_id']], metadata[locator['source_version_id']]
        entry = next(item for item in current['files'] if item['object'] == locator['object'])
        raw = fixture['objects'][encoded(locator['object'])]
        assert sha(raw) == locator['object']['sha256'] and len(raw) == locator['object']['size_bytes']
        reader = pq.ParquetFile(pa.BufferReader(raw))
        assert locator['row_group'] < reader.num_row_groups
        actual = reader.read_row_group(locator['row_group']).to_pylist()
        assert locator['row_offset'] < len(actual)
        physical = actual[locator['row_offset']]
        by_id = {field['source_field_id']: field for field in current['source_schema']}
        mappings = {item['resource_field_id']: item for item in source['field_mapping']}
        cells = []
        for field in value['resource']['fields']:
            mapping = mappings[field['field_id']]
            assert mapping['transform'] == 'identity', 'this independent real-case oracle certifies identity fixtures'
            item = physical[by_id[mapping['source_field_id']]['name']]
            cells.append({'type': 'null' if item is None else field['type'],
                          'value': str(item) if item is not None and field['type'] == 'int8' else item})
        assert cells == row['cells']
        assert physical['record_id'] == row['record_id'] and physical['record_version'] == row['record_version']
        assert entry['row_group_rows'][locator['row_group']] == len(actual)
        evidence.append({'record_id': row['record_id'], 'record_version': row['record_version'],
                         'source_id': source['source_id'], 'locator': locator, 'cells_sha256': sha(encoded(cells))})
    return sidecar, evidence


def measured_located(reader, fixture, ordinal):
    scope = reader.scope
    before, started = scope.usage(), time.monotonic()
    if reader.acceptance_cohort_started is None:
        reader.acceptance_cohort_started = started
    result = sample = returned = primary = None
    try:
        result = reader.read_located_batch(scope.binding, ordinal)
        returned = time.monotonic()
        after, observed, value = scope.usage(), deepcopy(reader.last_observation), result.batch.value
        usage = value['usage']
        sample = {'ordinal': ordinal, 'context_sha256': scope.binding.sha256,
            'batch_sha256': result.batch.sha256, 'provenance_sha256': sha(result.provenance_encoded),
            'a_bytes': len(result.batch.encoded), 'provenance_bytes': len(result.provenance_encoded),
            'joint_bytes': result.wire_bytes, 'rows': batch_rows(result.batch), 'last': value['last'],
            'usage': usage, 'before': before, 'after': after, 'page_elapsed_ms': (returned-started)*1000,
            'cohort_elapsed_ms': (returned-reader.acceptance_cohort_started)*1000,
            'finalization_tail_ms': (returned-observed['observed_monotonic_s'])*1000,
            'source_last_observation': observed, 'rss_peak_bytes': rss_bytes()}
        # Record actual returned bytes/observations before independent assertions.
        for key in ('object_requests', 'object_bytes', 'output_bytes'):
            assert usage[key] == after[key] - before[key]
        prefix = after['output_bytes'] - before['output_bytes'] - result.wire_bytes
        assert prefix >= 0 and usage['output_bytes'] == prefix + result.wire_bytes
        assert 0 < usage['memory_bytes'] <= 8 << 20 and result.wire_bytes <= 768 << 10
        assert len(value['rows']) <= 64 and not value['truncated']
        assert 0 <= usage['elapsed_ms'] <= (returned-started)*1000 + 1
        assert returned-started < 1 and returned-reader.acceptance_cohort_started < 5
        assert observed['observed_monotonic_s'] <= observed['precommit_monotonic_s'] <= returned
        assert scope.wire_bytes == scope.header_bytes + scope.object_bytes and rss_bytes() <= 512 << 20
        sidecar, witnesses = consume_located(scope.binding, result, fixture)
        sample.update(output_prefix_bytes=prefix, provenance=sidecar, independent_rows=witnesses,
                      scope_io=scope_snapshot(scope, returned))
        return result, sample
    except BaseException as error:
        primary = error
        raise
    finally:
        directory, number = reader.acceptance_directory, len(reader.acceptance_journal)
        entry = {'ordinal': ordinal, 'query_id': scope.context['query_id'],
                 'context_sha256': scope.binding.sha256, 'returned_located': result is not None,
                 'started_monotonic_s': started, 'returned_monotonic_s': returned, 'sample': sample,
                 'after': scope.usage(), 'primary_error': error_record(primary) if primary else None}
        reader.acceptance_journal.append(entry)
        if directory is not None:
            if result is not None:
                (directory/f'located-{number}-batch.json').write_bytes(result.batch.encoded)
                (directory/f'located-{number}-provenance.json').write_bytes(result.provenance_encoded)
            write(directory/'located-journal.json', reader.acceptance_journal)


def located_cases(proxy, directory, dual, dual_many):
    samples, query_ids = [], set()
    for name, fixture in [('full11', dual), ('dual130', dual_many)]:
        cache = VerifiedCache(256 << 10)
        for temperature in ('cold', 'warm'):
            case = 'located-' + name + '-' + temperature
            reader, primary, completed = None, None, False
            try:
                reader = instance(fixture, proxy.endpoint, cache=cache)
                query_id = reader.scope.context['query_id']
                assert query_id not in query_ids
                query_ids.add(query_id)
                save_case_input(reader, fixture, directory/'cases'/case)
                before_gets, pages, ordinal = proxy.requests, [], 0
                while True:
                    _, page = measured_located(reader, fixture, ordinal)
                    pages.append(page)
                    if page['last']:
                        break
                    ordinal += 1
                    assert ordinal < 3
                assert [row for page in pages for row in page['rows']] == expected_rows(fixture)
                assert [len(page['rows']) for page in pages] == ([11] if name == 'full11' else [64, 64, 2])
                assert [page['ordinal'] for page in pages] == list(range(len(pages)))
                _, replay = measured_located(reader, fixture, 0)
                assert replay['rows'] == pages[0]['rows']
                assert replay['provenance']['rows'] == pages[0]['provenance']['rows']
                assert replay['usage']['object_requests'] == replay['usage']['object_bytes'] == 0
                assert replay['output_prefix_bytes'] == 0
                assert {entry['context_sha256'] for entry in reader.acceptance_journal} == {reader.scope.binding.sha256}
                assert {entry['query_id'] for entry in reader.acceptance_journal} == {query_id}
                inputs = sum(len(raw) for raw in fixture['objects'].values())
                assert pages[0]['output_prefix_bytes'] == inputs
                assert all(page['output_prefix_bytes'] == 0 for page in pages[1:])
                gets = proxy.requests-before_gets
                assert gets == reader.scope.object_requests == (4 if temperature == 'cold' else 0)
                assert proxy.wait_idle() and proxy.active == 0
                members = [row for page in pages for row in page['independent_rows']]
                assert sum(row['source_id'] == 'source-mirror' for row in members) == (1 if name == 'full11' else 65)
                samples.append({'case': case, 'query_id': reader.scope.context['query_id'],
                    'binding_sha256': reader.scope.binding.sha256, 'pages': pages, 'replay': replay,
                    'actual_gets': gets, 'versions': fixture['versions'], 'input_rows': len(members),
                    'same_parent_output_bytes': reader.scope.output_bytes,
                    'authorization': 'bounded in-memory callback, not PG', 'os_cache': 'uncontrolled'})
                completed = True
            except BaseException as error:
                primary = error
                raise
            finally:
                observation(directory/('case-'+case+'-observation.json'), reader=reader,
                    server=proxy, primary=primary, case=case, completed=completed,
                    completed_calls=reader.acceptance_journal if reader else [])
    return samples
