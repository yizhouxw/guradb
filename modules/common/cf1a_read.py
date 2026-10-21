"""CF1-A binding, integrity and bounded typed-batch invariants."""
import struct
from modules.common.cf1a_schema import CAPABILITIES
from modules.common.cf1a_primitives import digest, require, unique, validate_shape


def without(value, key):
    return {name: item for name, item in value.items() if name != key}


def validate_object(ref):
    integrity = ref['integrity']
    require(bool(ref['key']), 'empty object key')
    if integrity['mode'] == 'whole_sha256':
        require(integrity['block_size'] == 0 and not integrity['block_sha256'] and not integrity['proof_ref'],
                'whole digest cannot claim block verification')
    else:
        width = integrity['block_size']
        require(width > 0 and bool(integrity['proof_ref']), 'missing trusted block proof')
        require(len(integrity['block_sha256']) == (ref['size_bytes'] + width - 1) // width,
                'incomplete block digest table')


def validate_range(ref, offset, length):
    """Structural range check; storage must additionally verify the trusted proof."""
    validate_shape(ref, 'ObjectRef')
    validate_object(ref)
    require(type(offset) is int and type(length) is int and 0 <= offset < ref['size_bytes']
            and 0 < length <= ref['size_bytes'] - offset, 'invalid object range')
    integrity = ref['integrity']
    if integrity['mode'] == 'whole_sha256':
        require(offset == 0 and length == ref['size_bytes'], 'whole hash does not verify a partial range')
    else:
        require(offset % integrity['block_size'] == 0 and
                ((offset + length) % integrity['block_size'] == 0 or offset + length == ref['size_bytes']),
                'strong range must cover complete blocks')


def field_invariants(fields):
    require(unique([field['field_id'] for field in fields]) and unique([field['name'] for field in fields]),
            'duplicate field identity')
    for role in ('logical_id', 'record_version'):
        chosen = [field for field in fields if field['role'] == role]
        require(len(chosen) == 1 and chosen[0]['type'] == 'text' and not chosen[0]['nullable'],
                'missing stable identity/version field')


def validate_descriptors(value):
    resource, revision, view = (value[name] for name in ('resource', 'revision', 'view'))
    fields = resource['fields']
    field_invariants(fields)
    require(resource['schema_sha256'] == digest(fields), 'schema digest mismatch')
    require(revision['content_sha256'] == digest(without(revision, 'content_sha256')), 'revision digest mismatch')
    require(view['descriptor_sha256'] == digest(without(view, 'descriptor_sha256')), 'view digest mismatch')
    for name in ('dataset_id', 'schema_id', 'schema_version'):
        require(resource[name] == revision[name], 'resource/schema binding mismatch')
    require(revision['data_revision_id'] == view['data_revision_id'], 'revision mismatch')
    require(unique(revision['parent_revision_ids']) and revision['data_revision_id'] not in revision['parent_revision_ids'],
            'invalid revision parents')
    sources = revision['sources']
    source_ids = [source['source_version_id'] for source in sources]
    require(unique(source_ids) and unique([source['source_id'] for source in sources]), 'duplicate source identity')
    field_types = {field['field_id']: field['type'] for field in fields}
    identity_strategies = {}
    for source in sources:
        require((source['format'], source['format_version']) in (('manifest', '1'), ('iceberg', '2')),
                'unsupported source format version')
        require(source['resource_schema_sha256'] == resource['schema_sha256'], 'source schema mismatch')
        mappings = source['field_mapping']
        require(unique([item['resource_field_id'] for item in mappings]) and
                {item['resource_field_id']: item['type'] for item in mappings} == field_types,
                'incomplete source field mapping')
        source_types = {}
        for item in mappings:
            role = next(field['role'] for field in fields if field['field_id'] == item['resource_field_id'])
            transform = item['transform']
            require((transform == 'identity' and item['source_field_id'] > 0 and item['source_type'] == item['type'])
                    or (transform == 'key_v1' and item['source_field_id'] > 0 and item['source_type'] in ('int8', 'text')
                        and item['type'] == 'text' and role == 'logical_id')
                    or (transform == 'revision_version' and item['source_field_id'] == 0 and item['source_type'] == 'none'
                        and item['type'] == 'text' and role == 'record_version'), 'unsupported identity transform')
            if role in ('logical_id', 'record_version'):
                strategy = (transform, item['source_type'])
                require(identity_strategies.get(role, strategy) == strategy, 'mixed source identity strategies')
                identity_strategies[role] = strategy
            if item['source_field_id'] > 0:
                require(source_types.get(item['source_field_id'], item['source_type']) == item['source_type'],
                        'conflicting physical source field type')
                source_types[item['source_field_id']] = item['source_type']
        validate_object(source['metadata'])
    object_ids = []
    for ref in revision['objects']:
        validate_object(ref)
        object_ids.append((ref['backend_id'], ref['bucket'], ref['key'], ref['version']))
    require(unique(object_ids), 'duplicate immutable object')
    requirements = {item['artifact_id']: item for item in view['index_requirements']}
    require(len(requirements) == len(view['index_requirements']) and
            set(requirements) == set(view['required_artifact_ids']), 'index requirement mismatch')
    artifact_ids = []
    for artifact in value['indexes']:
        artifact_ids.append(artifact['artifact_id'])
        require(artifact['data_revision_id'] == revision['data_revision_id'] and
                artifact['schema_sha256'] == resource['schema_sha256'], 'index version mismatch')
        require(unique(artifact['source_version_ids']) and set(artifact['source_version_ids']) == set(source_ids),
                'index coverage gap')
        require(artifact['artifact_id'] in requirements and all(artifact[name] == required for name, required
                in requirements[artifact['artifact_id']].items()), 'index model requirement mismatch')
        require(artifact['deletion_watermark'] == 0, 'deletes not certified')
        require(artifact['shard_count'] == len(artifact['shards']), 'missing index shard')
        require(artifact['reader_capabilities'] == ['fixed_read'], 'unsupported index reader capability')
        require((artifact['kind'] == 'bm25' and artifact['metric'] == 'bm25' and artifact['dimension'] == 1)
                or (artifact['kind'] == 'exact_vector' and artifact['metric'] == 'squared_l2'
                    and artifact['analyzer'] == 'none'), 'incompatible model/metric/analyzer')
        require(unique([(shard['backend_id'], shard['bucket'], shard['key'], shard['version'])
                        for shard in artifact['shards']]), 'duplicate index shard')
        for shard in artifact['shards']:
            validate_object(shard)
    require(unique(artifact_ids) and unique(view['required_artifact_ids'])
            and set(artifact_ids) == set(view['required_artifact_ids']),
            'index binding mismatch')
    immutable = {}
    for ref in [source['metadata'] for source in sources] + revision['objects'] + [shard for artifact in value['indexes'] for shard in artifact['shards']]:
        locator = (ref['backend_id'], ref['bucket'], ref['key'], ref['version'])
        require(locator not in immutable or immutable[locator] == ref, 'contradictory immutable object descriptors')
        immutable[locator] = ref



def validate_binding(value):
    validate_descriptors(value)
    resource, revision, view, context = (value[name] for name in ('resource', 'revision', 'view', 'context'))
    require(all(context[name] == resource[name] for name in ('dataset_id', 'schema_id', 'schema_version')), 'context resource/schema mismatch')
    require(context['tenant_id'] == resource['tenant_id'] == context['auth']['tenant_id'], 'tenant mismatch')
    require(context['auth']['dataset_id'] == resource['dataset_id'], 'authorization scope mismatch')
    require(revision['data_revision_id'] == context['data_revision_id'] == context['pin']['data_revision_id'], 'context revision mismatch')
    require(view['read_view_id'] == context['read_view_id'] == context['pin']['read_view_id'], 'context view mismatch')
    source_ids = [source['source_version_id'] for source in revision['sources']]
    require(unique(context['source_version_ids']) and set(source_ids) == set(context['source_version_ids']), 'source binding mismatch')
    require(unique(context['artifact_ids']) and set(context['artifact_ids']) == set(view['required_artifact_ids']), 'context index mismatch')
    deadline = context['deadline_unix_ms']
    require(0 < context['remaining_ttl_ms'] <= 30000 and deadline - context['bound_at_unix_ms'] == context['remaining_ttl_ms'], 'invalid remaining deadline')
    require(context['pin']['expires_unix_ms'] >= deadline and context['auth']['expires_unix_ms'] >= deadline, 'pin/auth expires before execution', 'expired_context')
    require(all(source['protected_until_unix_ms'] >= context['pin']['expires_unix_ms'] for source in revision['sources']), 'source retention cannot protect pin', 'expired_context')
    require(context['budget']['top_k'] <= context['budget']['candidates'], 'top-k exceeds candidate budget')


def validate_batch(value):
    fields = value['fields']
    field_invariants(fields)
    require(value['content_sha256'] == digest(without(value, 'content_sha256')), 'batch digest mismatch')
    identities = []
    for row in value['rows']:
        identities.append(row['record_id'])
        require(len(row['cells']) == len(fields), 'row width mismatch')
        for field, cell in zip(fields, row['cells']):
            require(cell['type'] == field['type'] or (field['nullable'] and cell['type'] == 'null'),
                    'cell type mismatch')
            if field['role'] in ('logical_id', 'record_version'):
                name = 'record_id' if field['role'] == 'logical_id' else 'record_version'
                require(cell['value'] == row[name], 'record identity/version mapping mismatch')
    require(unique(identities), 'duplicate logical record')
    if value['ordering'] == 'logical_id_asc':
        require(identities == sorted(identities), 'incorrect declared order')
    require(not value['truncated'] or value['last'], 'truncation must end batch stream')


def validate_read(kind, value):
    if kind == 'read_binding':
        validate_binding(value)
    elif kind == 'read_descriptors':
        validate_descriptors(value)
    elif kind == 'read_batch':
        validate_batch(value)
    elif kind == 'bind_request':
        require(value['timeout_ms'] <= 30000 and value['budget']['top_k'] <= value['budget']['candidates'], 'invalid bind budget/deadline')
        require((value['view_mode'] == 'published') == (value['read_view_id'] == ''), 'invalid bind view selector')
        if value['view_mode'] == 'explicit':
            validate_shape(value['read_view_id'], 'id')
    elif kind == 'index_query':
        require(value['top_k'] <= value['candidate_limit'] <= 1024, 'invalid index query limit')
        require(unique(value['allowed_record_ids']) and (value['filter_mode'] == 'ids' or not value['allowed_record_ids']), 'invalid index query filter')
        require((value['kind'] == 'bm25' and value['metric'] == 'bm25' and value['dimension'] == 1 and
                 bool(value['query_text']) and not value['query_vector_f64_hex']) or
                (value['kind'] == 'exact_vector' and value['metric'] == 'squared_l2' and value['analyzer'] == 'none' and
                 not value['query_text'] and len(value['query_vector_f64_hex']) == value['dimension']), 'incompatible index query')
        require(all(abs(struct.unpack('>d', bytes.fromhex(item))[0]) <= 1e150 for item in value['query_vector_f64_hex']), 'query vector outside finite distance bounds')
    elif kind == 'candidate_batch':
        require(value['complete'], 'partial candidate coverage is not certified')
        require((value['metric'] == 'squared_l2') == (value['score_order'] == 'ascending'), 'wrong candidate score order')
        require(unique([row['record_id'] for row in value['rows']]), 'duplicate candidate ID')
        for row in value['rows']:
            validate_object(row['locator']['object'])
        ordered = [(struct.unpack('>d', bytes.fromhex(row['score_f64_hex']))[0], row['record_id']) for row in value['rows']]
        expected = sorted(ordered, key=lambda item: (item[0] if value['score_order'] == 'ascending' else -item[0], item[1]))
        require(value['metric'] != 'squared_l2' or all(score >= 0 for score, _ in ordered), 'negative squared distance')
        require(ordered == expected, 'candidate rows violate score/tie order')
    elif kind == 'reader_config':
        require(value['max_envelope_bytes'] <= 1 << 20 and value['max_batch_rows'] <= 1024 and
                value['max_ttl_ms'] <= 30000, 'config exceeds certified bounds')
        require(unique(value['capabilities']) and set(value['capabilities']) == set(CAPABILITIES),
                'config cannot weaken capability contract', 'unsupported_capability')


def validate_access(binding, now_unix_ms, current_policy_epoch):
    """Call only with epoch from a successful, current catalog reauthorization."""
    validate_shape(binding, 'ReadBinding')
    context = binding['context']
    validate_shape(now_unix_ms, 'n')
    validate_shape(current_policy_epoch, 'positive')
    require(type(now_unix_ms) is int and now_unix_ms >= context['bound_at_unix_ms'], 'invalid current time')
    require(type(current_policy_epoch) is int and current_policy_epoch > 0, 'invalid policy epoch')
    require(current_policy_epoch == context['auth']['policy_epoch'], 'authorization revoked', 'revoked')
    require(now_unix_ms < context['deadline_unix_ms'], 'query deadline reached', 'deadline')


def validate_batch_for(binding_contract, batch_contract):
    binding, batch = binding_contract.value, batch_contract.value
    require(binding_contract.kind == 'read_binding' and batch_contract.kind == 'read_batch', 'wrong contract kinds')
    require(batch['context_sha256'] == binding_contract.sha256 and
            batch['schema_id'] == binding['resource']['schema_id'] and
            batch['schema_version'] == binding['resource']['schema_version'] and
            batch['fields'] == binding['resource']['fields'], 'batch context/schema mismatch')
    budget, usage = binding['context']['budget'], batch['usage']
    derived = any(item['transform'] == 'revision_version' for source in binding['revision']['sources'] for item in source['field_mapping'])
    require(not derived or all(row['record_version'] == binding['revision']['data_revision_id'] for row in batch['rows']), 'derived record version mismatch')
    require(all(usage[name] <= budget[name] for name in ('object_requests', 'object_bytes', 'memory_bytes', 'output_bytes')),
            'batch exceeds request budget', 'resource_limit')


def validate_candidates_for(binding_contract, query_contract, batch_contract):
    require(binding_contract.kind == 'read_binding' and query_contract.kind == 'index_query' and batch_contract.kind == 'candidate_batch', 'wrong candidate contract kinds')
    binding, batch = binding_contract.value, batch_contract.value
    query = query_contract.value
    artifact = next((item for item in binding['indexes'] if item['artifact_id'] == batch['artifact_id']), None)
    require(artifact is not None and batch['metric'] == artifact['metric'] and
            batch['context_sha256'] == binding_contract.sha256 and query['context_sha256'] == binding_contract.sha256 and
            query['artifact_id'] == batch['artifact_id'] and batch['index_query_sha256'] == query_contract.sha256 and
            all(query[name] == artifact[name] for name in ('kind', 'model_id', 'model_version', 'dimension', 'metric', 'analyzer', 'configuration_sha256', 'processing_version')),
            'candidate binding/artifact mismatch')
    require(len(batch['rows']) <= query['top_k'] <= binding['context']['budget']['top_k'] and
            query['candidate_limit'] <= binding['context']['budget']['candidates'], 'candidate budget exceeded', 'resource_limit')
    for row in batch['rows']:
        require(query['filter_mode'] == 'all' or row['record_id'] in query['allowed_record_ids'], 'candidate violates requested filter')
        require(row['locator']['source_version_id'] in artifact['source_version_ids'] and
                row['locator']['object'] in binding['revision']['objects'], 'candidate locator outside fixed input')
    require(all(batch['usage'][name] <= binding['context']['budget'][name]
                for name in ('object_requests', 'object_bytes', 'memory_bytes', 'output_bytes')), 'candidate usage exceeds budget', 'resource_limit')
