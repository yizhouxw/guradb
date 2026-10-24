"""Executable module fault traces; no source/catalog mutations or false success."""
from copy import deepcopy
import json
from unittest.mock import patch
import pyarrow.parquet as pq
from modules.common.cf1a_primitives import ContractFailure, canonical, digest, require
from modules.index.fixed_artifacts import seal, validate_source_batches
from modules.index.fixed_layout import envelope
from tests.index_support.fixed_fixture import (build_pair, prepare, query_for, reader_for,
    reference, rehash_binding, source_batches)


def run_faults(output):
    fixture = prepare(output / 'physical')
    binding, indexes = build_pair(fixture)
    trace = []
    def refusal(name, expected, callback):
        try:
            callback()
        except ContractFailure as error:
            require(error.code == expected, f'{name} unexpected failure {error.code}')
            trace.append({'scenario': name, 'state': 'rejected', 'code': error.code,
                          'complete_output_emitted': False})
        else:
            raise AssertionError(name + ' returned success')
    artifact = indexes[0]
    reader, scope = reader_for(binding, fixture['objects'])
    path = fixture['root'] / 'bm25.index'
    original = path.read_bytes()
    path.write_bytes(original[:-1])
    refusal('short-physical-object', 'corrupt_object',
            lambda: reader.candidates(binding, query_for(binding, artifact)))
    path.unlink()
    refusal('missing-fixed-version', 'missing_object', lambda: reader.read_artifact(binding, artifact['artifact_id']))
    path.write_bytes(original)
    body = json.loads(original)
    for name, mutate in (
        ('global-statistics', lambda b: b['statistics'].update(document_count=10)),
        ('physical-locator', lambda b: b['ledger'][0]['locator'].update(row_offset=99)),
        ('build-header', lambda b: b['header'].update(build_id='old-build')),
        ('coverage-ledger', lambda b: b['ledger'].pop()),
    ):
        changed_body = deepcopy(body); mutate(changed_body)
        path.write_bytes(canonical(changed_body))
        # A deliberately forged trusted registry/descriptor exercises semantic checks
        # even when the physical checksum alone would pass. No catalog accepts it.
        ref = reference(path)
        changed = binding.value
        changed['indexes'][0]['shards'] = [ref]
        changed_binding = rehash_binding(changed)
        fixture['objects'].register(ref, path)
        changed_reader, _ = reader_for(changed_binding, fixture['objects'])
        refusal(name, 'corrupt_object', lambda: changed_reader.read_artifact(changed_binding, artifact['artifact_id']))
    path.write_bytes(original)
    fixture['objects'].register(artifact['shards'][0], path)
    state = {'epoch': 1, 'cancelled': False}
    guarded, parent = reader_for(binding, fixture['objects'], reauthorize=lambda _: state['epoch'],
                                 cancelled=lambda: state['cancelled'])
    guarded.candidates(binding, query_for(binding, artifact))
    state['epoch'] = 2
    refusal('revoked-old-reader', 'revoked', lambda: guarded.candidates(binding, query_for(binding, artifact)))
    state.update(epoch=1, cancelled=True)
    refusal('cancelled-old-reader', 'cancelled', lambda: guarded.candidates(binding, query_for(binding, artifact)))
    limited_value = binding.value
    limited_value['context']['budget']['object_requests'] = 1
    limited = rehash_binding(limited_value)
    limited_reader, limited_scope = reader_for(limited, fixture['objects'])
    refusal('second-object-budget', 'resource_limit',
            lambda: limited_reader.candidates(limited, query_for(limited, artifact)))
    refusal('existing-sealed-destination', 'conflict', lambda: seal(original, path))
    failed_path = fixture['root'] / 'failed-fsync'
    with patch('modules.index.fixed_artifacts.os.fsync', side_effect=OSError('injected fsync')):
        refusal('fsync-failure', 'backend_unavailable', lambda: seal(b'partial-staging', failed_path))
    assert failed_path.exists()
    batches = source_batches(fixture['binding'], fixture['objects'], fixture['source_ref'])
    missing = deepcopy(fixture['manifest']); missing['rows'].pop()
    refusal('missing-processing-entry', 'invalid_contract',
            lambda: validate_source_batches(fixture['binding'], batches, missing))
    source_path = fixture['root'] / 'source.parquet'
    original_source = source_path.read_bytes()
    table = pq.read_table(source_path)
    pq.write_table(table, source_path, row_group_size=3)
    rewritten = reference(source_path)
    assert rewritten['sha256'] != fixture['source_ref']['sha256']
    refusal('rewritten-source-under-old-fixed-ref', 'corrupt_object',
            lambda: fixture['objects'].read(fixture['binding'], fixture['source_ref'], 0,
                                           fixture['source_ref']['size_bytes']))
    source_path.write_bytes(original_source)
    return {'status': 'pass', 'mode': 'fault', 'fault_trace': trace,
            'retained_staging': str(failed_path), 'scope_usage': scope.snapshot(),
            'guarded_scope_usage': parent.snapshot(), 'limited_scope_usage': limited_scope.snapshot(),
            'scope': 'module-only fixed-file faults, not publication/ingest crash recovery'}
