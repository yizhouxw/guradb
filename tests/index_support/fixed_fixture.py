"""Trusted module-only processing/locator input backed by real Parquet bytes.

Not a P04 source adapter, P03 implementation, catalog or public B-L contract.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time
import pyarrow as pa
import pyarrow.parquet as pq
from modules.common.cf1a_ports import ObjectReadPort
from modules.common.cf1a_primitives import ContractFailure, canonical, digest, require
from modules.common.cf1a_read import validate_range, without
from modules.index import fixed_bm25, fixed_vectors
from modules.index.fixed_artifacts import build_artifact
from modules.index.fixed_candidates import FixedArtifactReader
from modules.index.fixed_layout import envelope, f64_hex
from modules.index.fixed_scope import ExecutionScope
from tests.outline_oracles.truth import OutlineOracle

ROOT = Path(__file__).resolve().parents[2]
FIELDS = [{'field_id': i, 'name': name, 'type': kind, 'nullable': nullable, 'role': role}
          for i, (name, kind, nullable, role) in enumerate((
              ('record_id', 'text', False, 'logical_id'), ('record_version', 'text', False, 'record_version'),
              ('title', 'text', True, 'value'), ('active', 'bool', True, 'value'),
              ('priority', 'int8', True, 'value'), ('tokens_text', 'text', True, 'value')), 1)]
SOURCE_FIELDS = [
    {'source_field_id': 101, 'name': 'record_id', 'type': 'text', 'nullable': False},
    {'source_field_id': 102, 'name': 'record_version', 'type': 'text', 'nullable': False},
    {'source_field_id': 103, 'name': 'title', 'type': 'text', 'nullable': True},
    {'source_field_id': 104, 'name': 'active', 'type': 'bool', 'nullable': True},
    {'source_field_id': 105, 'name': 'priority', 'type': 'int8', 'nullable': True},
    {'source_field_id': 106, 'name': 'tokens_text', 'type': 'text', 'nullable': True}]
# A separately declared complete processing decision, not inferred from missing features.
PROCESSING_MASK = {('r-a1', '2'): 'present', ('r-a1-copy', '1'): 'present', ('r-a2', '1'): 'present',
                   ('r-a3', '1'): 'present', ('r-b1', '1'): 'present', ('r-b2', '1'): 'present',
                   ('r-b3', '1'): 'present', ('r-c1', '1'): 'present', ('r-c2', '1'): 'present',
                   ('r-c3', '1'): 'present', ('r-null', '1'): 'null'}


def typed_cells(row):
    return [{'type': 'null', 'value': None} if row[field['name']] is None else
            {'type': field['type'], 'value': str(row[field['name']]) if field['type'] == 'int8'
             else row[field['name']]} for field in FIELDS]


def reference(path, key=None):
    path = Path(path)
    raw = path.read_bytes()
    return {'backend_id': 'p06_fixture', 'bucket': 'synthetic.local', 'key': key or path.name,
            'version': 'sealed-v1', 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'integrity': {'mode': 'whole_sha256', 'block_size': 0, 'block_sha256': [], 'proof_ref': ''}}


class LocalObjects:
    """An actual bounded file-reading ObjectReadPort with an explicit trusted registry."""
    def __init__(self):
        self.registry = {}
        self.requests = []

    def register(self, ref, path):
        self.registry[(ref['backend_id'], ref['bucket'], ref['key'], ref['version'])] = (deepcopy(ref), Path(path))

    def verify(self, ref):
        validate_range(ref, 0, ref['size_bytes'])

    def read(self, binding, ref, offset, length):
        validate_range(ref, offset, length)
        key = (ref['backend_id'], ref['bucket'], ref['key'], ref['version'])
        require(key in self.registry, 'fixture object missing', 'missing_object')
        expected, path = self.registry[key]
        require(expected == ref, 'registry immutable version mismatch', 'corrupt_object')
        attempt = {'key': ref['key'], 'requested_bytes': length, 'actual_bytes': 0, 'checksum_bytes': 0}
        self.requests.append(attempt)
        try:
            with path.open('rb') as stream:
                raw = stream.read(length + 1)
        except FileNotFoundError as error:
            raise ContractFailure('missing_object', 'sealed fixture object missing') from error
        except OSError as error:
            raise ContractFailure('backend_unavailable', 'fixture object read failed') from error
        attempt.update(actual_bytes=len(raw), checksum_bytes=len(raw))
        require(len(raw) == length and hashlib.sha256(raw).hexdigest() == ref['sha256'],
                'fixture file size/hash mismatch', 'corrupt_object')
        return raw

    def port(self):
        return ObjectReadPort(verify_proof=self.verify, read=self.read)


def new_scope(binding, **overrides):
    arguments = {'reauthorize': lambda _: 1, 'cancelled': lambda: False,
                 'now_unix_ms': lambda: 1001}
    arguments.update(overrides)
    return ExecutionScope(binding, **arguments)


def rehash_binding(value):
    value = deepcopy(value)
    value['revision']['content_sha256'] = digest(without(value['revision'], 'content_sha256'))
    value['view']['descriptor_sha256'] = digest(without(value['view'], 'descriptor_sha256'))
    return envelope('read_binding', value)


def binding_for(source_ref, metadata_ref, processing_ref, source_schema, indexes=()):
    value = json.loads((ROOT / 'api/cf1a/golden.json').read_text())[0]['payload']['read_binding']
    resource = value['resource']
    resource.update(dataset_id='p06-fixture', schema_id='p06-schema', fields=deepcopy(FIELDS),
                    schema_sha256=digest(FIELDS))
    revision = value['revision']
    revision.update(dataset_id=resource['dataset_id'], schema_id=resource['schema_id'],
                    data_revision_id='p06-revision-v2', parent_revision_ids=[],
                    objects=[source_ref, metadata_ref, processing_ref])
    source = revision['sources'][0]
    physical = {field['name']: field for field in source_schema}
    source.update(source_id='p06-source', source_version_id='p06-source-v2', snapshot_id='p06-snapshot-v2',
                  source_schema_sha256=digest(source_schema), resource_schema_sha256=resource['schema_sha256'],
                  metadata=metadata_ref, field_mapping=[{'source_field_id': physical[field['name']]['source_field_id'],
                      'resource_field_id': field['field_id'], 'type': field['type'], 'source_type': field['type'],
                      'transform': 'identity'} for field in FIELDS])
    value['indexes'] = list(indexes)
    value['view'].update(read_view_id='p06-index-view' if indexes else 'p06-scan-view',
                         data_revision_id=revision['data_revision_id'],
                         required_artifact_ids=[item['artifact_id'] for item in indexes],
                         index_requirements=[{name: item[name] for name in (
                             'artifact_id', 'model_id', 'model_version', 'dimension', 'metric', 'analyzer',
                             'format_id', 'format_version', 'configuration_sha256', 'processing_version')}
                             for item in indexes])
    context = value['context']
    context.update(dataset_id=resource['dataset_id'], schema_id=resource['schema_id'],
                   data_revision_id=revision['data_revision_id'], read_view_id=value['view']['read_view_id'],
                   source_version_ids=[source['source_version_id']], artifact_ids=value['view']['required_artifact_ids'])
    context['pin'].update(data_revision_id=revision['data_revision_id'], read_view_id=value['view']['read_view_id'])
    context['auth']['dataset_id'] = resource['dataset_id']
    context['budget'].update(memory_bytes=512 << 20, object_requests=100, object_bytes=16 << 20,
                             candidates=100, top_k=100, output_bytes=16 << 20)
    return rehash_binding(value)


def source_schema(file):
    """Read field IDs from the actual footer (the writer omits ARROW:schema metadata)."""
    require(b'ARROW:schema' not in (file.metadata.metadata or {}), 'fixture must use physical footer schema')
    kinds = {'string': 'text', 'int64': 'int8', 'bool': 'bool'}
    result = []
    for index, field in enumerate(file.schema_arrow):
        encoded_id = (field.metadata or {}).get(b'PARQUET:field_id', b'')
        require(encoded_id.isdigit() and str(int(encoded_id)).encode() == encoded_id,
                'missing/noncanonical physical field ID')
        require(str(field.type) in kinds and file.schema.column(index).max_repetition_level == 0 and
                file.schema.column(index).max_definition_level == int(field.nullable), 'unexpected physical scalar type')
        result.append({'source_field_id': int(encoded_id), 'name': field.name,
                       'type': kinds[str(field.type)], 'nullable': field.nullable})
    return result


def enumerate_parquet(raw, source_ref):
    """Physical group/offset is obtained from actual Parquet enumeration, never a batch ordinal."""
    file = pq.ParquetFile(pa.BufferReader(raw))
    result = {}
    for group in range(file.num_row_groups):
        for offset, row in enumerate(file.read_row_group(group).to_pylist()):
            key = (row['record_id'], row['record_version'])
            require(key not in result, 'duplicate physical fixture identity')
            result[key] = {'row': row, 'locator': {'source_version_id': 'p06-source-v2',
                           'object': source_ref, 'row_group': group, 'row_offset': offset}}
    return result


def source_batches(binding, objects, source_ref):
    raw = objects.port().read(binding, source_ref, 0, source_ref['size_bytes'])
    physical = enumerate_parquet(raw, source_ref)
    # Deliberately use ID ordering, unrelated to physical row groups and offsets.
    records = [{'record_id': key[0], 'record_version': key[1], 'cells': typed_cells(value['row'])}
               for key, value in sorted(physical.items())]
    batches = []
    for ordinal, start in enumerate(range(0, len(records), 3)):
        value = {'context_sha256': binding.sha256, 'schema_id': 'p06-schema', 'schema_version': 1,
                 'fields': FIELDS, 'batch_ordinal': ordinal, 'last': start + 3 >= len(records),
                 'truncated': False, 'ordering': 'logical_id_asc', 'rows': records[start:start + 3],
                 'usage': {'object_requests': int(ordinal == 0), 'object_bytes': len(raw) if ordinal == 0 else 0,
                           'memory_bytes': len(raw) * 64, 'output_bytes': 0, 'elapsed_ms': 0}, 'content_sha256': ''}
        value['content_sha256'] = digest(without(value, 'content_sha256'))
        batches.append(envelope('read_batch', value))
    return batches


def prepare(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    oracle = OutlineOracle()
    require(set(PROCESSING_MASK) == set(oracle.rows), 'incomplete independent processing mask')
    rows = [{**row, 'tokens_text': ' '.join(row['tokens']) if row['title'] is not None else None}
            for _, row in sorted(oracle.rows.items(), reverse=True)]
    schema = pa.schema([pa.field(f['name'], {'text': pa.string(), 'int8': pa.int64(), 'bool': pa.bool_()}[f['type']],
                                nullable=f['nullable'],
                                metadata={b'PARQUET:field_id': str(f['source_field_id']).encode()})
                        for f in SOURCE_FIELDS])
    table = pa.Table.from_pylist([{f['name']: row[f['name']] for f in FIELDS} for row in rows], schema=schema)
    source_path = root / 'source.parquet'
    pq.write_table(table, source_path, row_group_size=4, store_schema=False)
    physical_schema = source_schema(pq.ParquetFile(source_path))
    require(physical_schema == SOURCE_FIELDS, 'written source schema differs from declaration')
    source_ref = reference(source_path)
    metadata_path = root / 'source-metadata.json'
    metadata_path.write_bytes(canonical({'source': source_ref, 'source_schema': physical_schema,
        'source_schema_sha256': digest(physical_schema), 'resource_schema_sha256': digest(FIELDS),
        'snapshot': 'p06-snapshot-v2'}))
    metadata_ref = reference(metadata_path)
    physical = enumerate_parquet(source_path.read_bytes(), source_ref)
    processing_rows = []
    for key, item in sorted(physical.items()):
        facts = oracle.rows[key]
        feature = oracle.features.get(key)
        state = PROCESSING_MASK[key]
        require((state == 'present') == (feature is not None), 'processing mask/value disagreement')
        feature_input = None
        if feature is not None:
            require(feature['parent'] == {'record_id': key[0], 'record_version': key[1]} and
                    (feature['space_id'], feature['model_version'], feature['dimension'], feature['metric']) ==
                    ('outline-synthetic-zh-image3', '1', 3, 'squared_l2'), 'wrong processing feature input')
            feature_input = {name: feature[name] for name in ('feature_id', 'feature_version', 'model_version',
                                                              'dimension', 'metric')}
            feature_input.update(record_id=key[0], record_version=key[1], model_id=feature['space_id'],
                                 normalization='none', processing_version='zh-CN-hand-segmented-v1')
        processing_rows.append({'record_id': key[0], 'record_version': key[1], 'locator': item['locator'],
            'source_cells_sha256': digest(typed_cells(item['row'])),
            'text_state': 'null' if facts['title'] is None else ('present' if facts['tokens'] else 'empty'),
            'tokens': facts['tokens'], 'vector_state': state,
            'vector_reason': '' if state == 'present' else 'fixture-explicit-missing-modality',
            'vector_f64_hex': [f64_hex(value) for value in feature['vector']] if feature else [],
            'feature_input': feature_input})
    manifest = {'manifest_version': 'p06-processing/1', 'dataset_id': 'p06-fixture',
                'data_revision_id': 'p06-revision-v2', 'schema_sha256': digest(FIELDS),
                'source_version_id': 'p06-source-v2', 'source_objects': [source_ref],
                'configurations': {'bm25': fixed_bm25.configuration(6), 'exact_vector': fixed_vectors.configuration()},
                'rows': processing_rows}
    processing_path = root / 'processing.json'
    processing_path.write_bytes(canonical(manifest))
    processing_ref = reference(processing_path)
    objects = LocalObjects()
    for ref, path in ((source_ref, source_path), (metadata_ref, metadata_path), (processing_ref, processing_path)):
        objects.register(ref, path)
    binding = binding_for(source_ref, metadata_ref, processing_ref, physical_schema)
    return {'root': root, 'oracle': oracle, 'objects': objects, 'binding': binding, 'source_ref': source_ref,
            'metadata_ref': metadata_ref, 'processing_ref': processing_ref, 'manifest': manifest,
            'processing_path': processing_path, 'physical': physical, 'source_schema': physical_schema}


def build_pair(fixture):
    indexes = []
    fixture['build_metrics'] = []
    for kind in ('bm25', 'exact_vector'):
        started = time.perf_counter()
        binding, objects = fixture['binding'], fixture['objects']
        request_start = len(objects.requests)
        batches = source_batches(binding, objects, fixture['source_ref'])
        raw = objects.port().read(binding, fixture['processing_ref'], 0, fixture['processing_ref']['size_bytes'])
        path = fixture['root'] / (kind + '.index')
        scope = new_scope(binding)
        artifact = build_artifact(binding, batches, raw, fixture['processing_ref'], kind,
            'p06-' + kind, 'p06-build-' + kind, path,
            {'backend_id': 'p06_fixture', 'bucket': 'synthetic.local', 'key': path.name, 'version': 'sealed-v1'},
            scope)
        fixture['build_metrics'].append({'kind': kind, 'pipeline_ms': (time.perf_counter() - started) * 1000,
                                        'usage': scope.snapshot(), 'metrics': deepcopy(scope.metrics),
                                        'actual_io': deepcopy(objects.requests[request_start:])})
        indexes.append(artifact)
        objects.register(artifact['shards'][0], path)
    bound = binding_for(fixture['source_ref'], fixture['metadata_ref'], fixture['processing_ref'],
                        fixture['source_schema'], indexes)
    return bound, indexes


def query_for(binding, artifact, text='权限 缓存', vector=(0, 0, 0), ids=None, top_k=100):
    return envelope('index_query', {'context_sha256': binding.sha256, 'artifact_id': artifact['artifact_id'],
        **{name: artifact[name] for name in ('kind', 'model_id', 'model_version', 'dimension', 'metric',
                                            'analyzer', 'configuration_sha256', 'processing_version')},
        'top_k': top_k, 'candidate_limit': 100, 'query_text': text if artifact['kind'] == 'bm25' else '',
        'query_vector_f64_hex': [] if artifact['kind'] == 'bm25' else [f64_hex(x) for x in vector],
        'filter_mode': 'all' if ids is None else 'ids', 'allowed_record_ids': [] if ids is None else ids})


def reader_for(binding, objects, **callbacks):
    scope = new_scope(binding, **callbacks)
    return FixedArtifactReader(objects.port(), scope), scope
