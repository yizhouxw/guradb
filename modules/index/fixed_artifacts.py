"""Create-once P06 artifacts and exact descriptor/layout validation."""
from copy import deepcopy
import hashlib
import os
from pathlib import Path
from modules.common.cf1a_primitives import ContractFailure, canonical, digest, require, validate_shape
from modules.common.cf1a_read import validate_batch_for
from modules.common.cf1a_wire import Contract
from modules.index import fixed_bm25, fixed_vectors
from modules.index.fixed_layout import (MAX_FILE_BYTES, closed, mapping, object_ref, strict_json,
                                        tokens, validate_manifest, verified_bytes)

ALGORITHMS = {'bm25': fixed_bm25, 'exact_vector': fixed_vectors}
FORMATS = {'bm25': 'p06-bm25-flat', 'exact_vector': 'p06-exact-vector-flat'}
MODEL_FIELDS = ('model_id', 'model_version', 'dimension', 'metric', 'analyzer', 'processing_version')


def read_manifest(raw, ref, binding):
    verified_bytes(raw, ref)
    value = validate_manifest(strict_json(raw), binding, ref)
    for kind, algorithm in ALGORITHMS.items():
        algorithm.validate_configuration(value['configurations'][kind])
    return value


def validate_source_batches(binding, batches, manifest):
    require(type(batches) is list and 0 < len(batches) <= 100, 'missing complete source batches')
    actual = {}
    text_id = manifest['configurations']['bm25']['text_field_id']
    fields = binding.value['resource']['fields']
    selected = [i for i, field in enumerate(fields) if field['field_id'] == text_id and
                field['type'] == 'text' and field['role'] == 'value']
    require(len(selected) == 1, 'BM25 field is not a source text value')
    for ordinal, batch in enumerate(batches):
        validate_batch_for(binding, batch)
        value = batch.value
        require(value['batch_ordinal'] == ordinal and not value['truncated'] and
                value['last'] == (ordinal == len(batches) - 1), 'incomplete source batch stream')
        for row in value['rows']:
            require(row['record_id'] not in actual and len(actual) < 100, 'duplicate/excess source identity')
            actual[row['record_id']] = row
    require(set(actual) == {row['record_id'] for row in manifest['rows']}, 'processing mask/coverage gap')
    for row in manifest['rows']:
        source = actual[row['record_id']]
        require(source['record_version'] == row['record_version'] and
                digest(source['cells']) == row['source_cells_sha256'], 'source cell/version mismatch')
        cell = source['cells'][selected[0]]
        source_tokens = [] if cell['type'] == 'null' else tokens(cell['value'])
        state = 'null' if cell['type'] == 'null' else ('present' if source_tokens else 'empty')
        require(row['text_state'] == state and row['tokens'] == source_tokens, 'processing tokens differ from source')


def body_for(kind, artifact_id, build_id, manifest, manifest_ref):
    require(type(kind) is str and kind in ALGORITHMS, 'unsupported private artifact kind')
    for item in (artifact_id, build_id):
        validate_shape(item, 'id')
    configuration = manifest['configurations'][kind]
    rows, statistics = ALGORITHMS[kind].materialize(manifest['rows'])
    return {'format_id': FORMATS[kind], 'format_version': 1,
            'header': {'artifact_id': artifact_id, 'build_id': build_id,
                       'dataset_id': manifest['dataset_id'], 'data_revision_id': manifest['data_revision_id'],
                       'schema_sha256': manifest['schema_sha256'], 'source_version_id': manifest['source_version_id'],
                       'processing_manifest': manifest_ref},
            'configuration': configuration, 'configuration_sha256': digest(configuration),
            'logical_mapping_sha256': digest(mapping(manifest['rows'])),
            'coverage_sha256': digest(manifest['rows']), 'ledger': manifest['rows'],
            'rows': rows, 'statistics': statistics}


def validate_body(value, artifact, manifest, manifest_ref):
    closed(value, ('format_id', 'format_version', 'header', 'configuration', 'configuration_sha256',
                   'logical_mapping_sha256', 'coverage_sha256', 'ledger', 'rows', 'statistics'))
    kind = artifact['kind']
    require(kind in ALGORITHMS and artifact['format_id'] == FORMATS[kind] and
            artifact['format_version'] == 1, 'unsupported private format', 'unsupported_version')
    expected = body_for(kind, artifact['artifact_id'], artifact['build_id'], manifest, manifest_ref)
    require(canonical(value) == canonical(expected), 'physical layout/coverage/values mismatch', 'corrupt_object')
    config = value['configuration']
    require(all(artifact[name] == config[name] for name in MODEL_FIELDS) and
            artifact['configuration_sha256'] == value['configuration_sha256'] and
            artifact['logical_mapping_sha256'] == value['logical_mapping_sha256'] and
            artifact['data_revision_id'] == manifest['data_revision_id'] and
            artifact['schema_sha256'] == manifest['schema_sha256'] and
            artifact['source_version_ids'] == [manifest['source_version_id']] and
            artifact['shard_count'] == 1 and len(artifact['shards']) == 1 and
            artifact['reader_capabilities'] == ['fixed_read'] and artifact['deletion_mode'] == 'none' and
            artifact['deletion_watermark'] == 0, 'descriptor does not describe physical artifact', 'corrupt_object')


def seal(raw, destination):
    """Trusted new local staging destination; failure is retained, never published."""
    require(len(raw) <= MAX_FILE_BYTES, 'artifact exceeds private bound', 'resource_limit')
    target = Path(destination)
    require(target.parent.is_dir() and not target.parent.is_symlink() and not target.is_symlink(),
            'invalid trusted staging destination')
    try:
        with target.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        directory = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except FileExistsError as error:
        raise ContractFailure('conflict', 'artifact destination already exists') from error
    except OSError as error:
        raise ContractFailure('backend_unavailable', 'artifact sealing failed; staging retained') from error


def build_artifact(binding, batches, manifest_raw, manifest_ref, kind, artifact_id, build_id,
                   destination, object_identity, scope):
    """Build from published, protected source batches and explicit trusted processing.

    object_identity supplies backend/bucket/key/version allocated by the trusted
    staging registry. No inferred row position, directory mutation or publication.
    """
    scope.matches(binding)
    before = scope.snapshot()
    require(type(manifest_raw) is bytes and len(manifest_raw) <= MAX_FILE_BYTES, 'processing input exceeds bound')
    require(type(batches) is list and 0 < len(batches) <= 100 and
            all(isinstance(batch, Contract) and batch.kind == 'read_batch' for batch in batches),
            'expected bounded typed source batches')
    input_bytes = len(manifest_raw) + sum(len(batch.encoded) for batch in batches)
    scope.charge('memory_bytes', input_bytes * 64)
    for batch in batches:
        for name in ('object_requests', 'object_bytes', 'memory_bytes'):
            scope.charge(name, batch.value['usage'][name])
    scope.charge('object_requests', 1)
    scope.charge('object_bytes', len(manifest_raw))
    manifest = read_manifest(manifest_raw, manifest_ref, binding)
    validate_source_batches(binding, batches, manifest)
    body = body_for(kind, artifact_id, build_id, manifest, manifest_ref)
    raw = canonical(body)
    scope.charge('memory_bytes', (len(raw) + input_bytes) * 64)
    scope.metrics['decoded_bytes'] += len(manifest_raw)
    scope.metrics['checksum_bytes'] += len(manifest_raw) + len(raw)
    scope.metrics['scanned_rows'] += len(manifest['rows'])
    scope.checkpoint()
    closed(object_identity, ('backend_id', 'bucket', 'key', 'version'))
    ref = {**object_identity, 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
           'integrity': {'mode': 'whole_sha256', 'block_size': 0, 'block_sha256': [], 'proof_ref': ''}}
    object_ref(ref)
    seal(raw, destination)
    scope.metrics['sealed_bytes'] += len(raw)
    scope.checkpoint()
    usage = scope.snapshot()
    usage = {name: (usage[name] if name == 'memory_bytes' else usage[name] - before[name]) for name in usage}
    config = manifest['configurations'][kind]
    artifact = {'artifact_id': artifact_id, 'build_id': build_id,
                'data_revision_id': manifest['data_revision_id'], 'schema_sha256': manifest['schema_sha256'],
                'kind': kind, **{name: config[name] for name in MODEL_FIELDS}, 'format_id': FORMATS[kind],
                'format_version': 1, 'configuration_sha256': digest(config),
                'source_version_ids': [manifest['source_version_id']],
                'logical_mapping_sha256': body['logical_mapping_sha256'], 'deletion_mode': 'none',
                'deletion_watermark': 0, 'shard_count': 1, 'shards': [ref],
                'build_usage': usage, 'reader_capabilities': ['fixed_read']}
    validate_shape(artifact, 'IndexArtifact')
    return deepcopy(artifact)
