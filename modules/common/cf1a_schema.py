"""CF1-A closed wire shapes; the exported API schema is generated from these."""
import copy

I53 = (1 << 53) - 1
VERSION = 'cf1a/1.0'
CAPABILITIES = ('fixed_read', 'typed_json_v1', 'strong_integrity', 'catalog_cas')
SHAPES = {
    'Field': {'field_id': 'positive', 'name': 'id', 'type': ('int8', 'text', 'bool'),
              'nullable': 'bool', 'role': ('value', 'logical_id', 'record_version')},
    'ResourceDescriptor': {'tenant_id': 'id', 'namespace_id': 'id', 'dataset_id': 'id',
                           'display_name': 'text', 'schema_id': 'id', 'schema_version': 'positive',
                           'schema_sha256': 'hash', 'fields': ['Field', 1, 64]},
    'Integrity': {'mode': ('whole_sha256', 'block_sha256'), 'block_size': 'n',
                  'block_sha256': ['hash', 0, 4096], 'proof_ref': 'text'},
    'ObjectRef': {'backend_id': 'id', 'bucket': 'opaque', 'key': 'text', 'version': 'opaque',
                  'size_bytes': 'positive', 'sha256': 'hash', 'integrity': 'Integrity'},
    'FieldMapping': {'source_field_id': 'n', 'resource_field_id': 'positive',
                     'type': ('int8', 'text', 'bool'), 'source_type': ('int8', 'text', 'bool', 'none'),
                     'transform': ('identity', 'key_v1', 'revision_version')},
    'SourceVersion': {'source_id': 'id', 'source_version_id': 'id', 'format': ('manifest', 'iceberg'),
                      'format_version': ('1', '2'), 'snapshot_id': 'id',
                      'source_schema_sha256': 'hash', 'resource_schema_sha256': 'hash',
                      'metadata': 'ObjectRef', 'field_mapping': ['FieldMapping', 1, 64],
                      'protected_until_unix_ms': 'positive', 'protection_ref': 'id'},
    'DataRevision': {'data_revision_id': 'id', 'dataset_id': 'id', 'schema_id': 'id',
                     'schema_version': 'positive', 'parent_revision_ids': ['id', 0, 32],
                     'sources': ['SourceVersion', 1, 32], 'objects': ['ObjectRef', 1, 128],
                     'content_sha256': 'hash'},
    'Usage': {'object_requests': 'n', 'object_bytes': 'n', 'memory_bytes': 'n',
              'output_bytes': 'n', 'elapsed_ms': 'n'},
    'Budget': {'memory_bytes': 'positive', 'object_requests': 'positive', 'object_bytes': 'positive',
               'candidates': 'positive', 'top_k': 'positive', 'graph_edges': 'positive',
               'output_bytes': 'positive', 'concurrency': 'positive', 'temp_bytes': 'positive'},
    'IndexArtifact': {'artifact_id': 'id', 'build_id': 'id', 'data_revision_id': 'id',
                      'schema_sha256': 'hash', 'kind': ('bm25', 'exact_vector'),
                      'model_id': 'id', 'model_version': 'id', 'dimension': 'positive',
                      'format_id': 'id', 'format_version': 'positive', 'configuration_sha256': 'hash', 'processing_version': 'id',
                      'metric': ('squared_l2', 'bm25'), 'analyzer': 'id',
                      'source_version_ids': ['id', 1, 32], 'logical_mapping_sha256': 'hash',
                      'deletion_mode': ('none',), 'deletion_watermark': 'n',
                      'shard_count': 'positive', 'shards': ['ObjectRef', 1, 128],
                      'build_usage': 'Usage', 'reader_capabilities': ['id', 1, 8]},
    'IndexRequirement': {'artifact_id': 'id', 'model_id': 'id', 'model_version': 'id',
                         'dimension': 'positive', 'metric': ('squared_l2', 'bm25'), 'analyzer': 'id',
                         'format_id': 'id', 'format_version': 'positive', 'configuration_sha256': 'hash', 'processing_version': 'id'},
    'ReadView': {'read_view_id': 'id', 'data_revision_id': 'id', 'publication_generation': 'positive',
                 'publication_sequence': 'positive', 'required_artifact_ids': ['id', 0, 128],
                 'index_requirements': ['IndexRequirement', 0, 128], 'descriptor_sha256': 'hash'},
    'AuthContext': {'tenant_id': 'id', 'subject_id': 'id', 'dataset_id': 'id',
                    'actions': [('read',), 1, 1], 'policy_epoch': 'positive',
                    'expires_unix_ms': 'positive', 'delegation_ref': 'id'},
    'Pin': {'pin_id': 'id', 'lease_id': 'id', 'data_revision_id': 'id',
            'read_view_id': 'id', 'expires_unix_ms': 'positive'},
    'QueryContext': {'request_id': 'id', 'query_id': 'id', 'tenant_id': 'id', 'dataset_id': 'id',
                     'schema_id': 'id', 'schema_version': 'positive', 'data_revision_id': 'id',
                     'read_view_id': 'id', 'source_version_ids': ['id', 1, 32],
                     'artifact_ids': ['id', 0, 128], 'auth': 'AuthContext', 'pin': 'Pin',
                     'bound_at_unix_ms': 'positive', 'deadline_unix_ms': 'positive',
                     'remaining_ttl_ms': 'positive', 'budget': 'Budget', 'cancellation_id': 'id',
                     'trace_id': 'id', 'span_id': 'id'},
    'ReadDescriptors': {'resource': 'ResourceDescriptor', 'revision': 'DataRevision', 'view': 'ReadView',
                        'indexes': ['IndexArtifact', 0, 128]},
    'ReadBinding': {'resource': 'ResourceDescriptor', 'revision': 'DataRevision', 'view': 'ReadView',
                    'indexes': ['IndexArtifact', 0, 128], 'context': 'QueryContext'},
    'BindRequest': {'tenant_id': 'id', 'subject_id': 'id', 'dataset_id': 'id', 'delegation_ref': 'id',
                    'request_id': 'id', 'query_id': 'id', 'view_mode': ('published', 'explicit'),
                    'read_view_id': 'text', 'timeout_ms': 'positive', 'budget': 'Budget',
                    'cancellation_id': 'id', 'trace_id': 'id', 'span_id': 'id'},
    'RowLocator': {'source_version_id': 'id', 'object': 'ObjectRef', 'row_group': 'n', 'row_offset': 'n'},
    'Candidate': {'record_id': 'id', 'record_version': 'id', 'score_f64_hex': 'score', 'locator': 'RowLocator'},
    'IndexQuery': {'context_sha256': 'hash', 'artifact_id': 'id', 'kind': ('bm25', 'exact_vector'),
                   'model_id': 'id', 'model_version': 'id', 'dimension': 'positive',
                   'metric': ('squared_l2', 'bm25'), 'analyzer': 'id',
                   'configuration_sha256': 'hash', 'processing_version': 'id',
                   'top_k': 'positive', 'candidate_limit': 'positive', 'query_text': 'text',
                   'query_vector_f64_hex': ['score', 0, 4096], 'filter_mode': ('all', 'ids'),
                   'allowed_record_ids': ['id', 0, 1024]},
    'CandidateBatch': {'context_sha256': 'hash', 'index_query_sha256': 'hash', 'artifact_id': 'id',
                       'metric': ('squared_l2', 'bm25'), 'score_order': ('ascending', 'descending'),
                       'complete': 'bool', 'rows': ['Candidate', 0, 1024], 'usage': 'Usage'},
    'Record': {'record_id': 'id', 'record_version': 'id', 'cells': ['cell', 1, 64]},
    'ReadBatch': {'context_sha256': 'hash', 'schema_id': 'id', 'schema_version': 'positive',
                  'fields': ['Field', 1, 64], 'batch_ordinal': 'n', 'last': 'bool',
                  'truncated': 'bool', 'ordering': ('unspecified', 'logical_id_asc'),
                  'rows': ['Record', 0, 1024], 'usage': 'Usage', 'content_sha256': 'hash'},
    'MutationAuth': {'tenant_id': 'id', 'subject_id': 'id', 'dataset_id': 'id',
                     'actions': [('register', 'publish', 'reconcile'), 1, 3], 'policy_epoch': 'positive',
                     'expires_unix_ms': 'positive', 'delegation_ref': 'id'},
    'RegisterIntent': {'operation_id': 'id', 'tenant_id': 'id', 'dataset_id': 'id',
                       'expected_generation': 'n', 'owner_epoch': 'positive',
                       'revision_sha256': 'hash', 'target_revision_id': 'id', 'target_descriptors_sha256': 'hash'},
    'PublishIntent': {'operation_id': 'id', 'tenant_id': 'id', 'dataset_id': 'id',
                      'expected_generation': 'n', 'owner_epoch': 'positive',
                      'expected_view_id': 'text', 'target_view_id': 'id',
                      'target_revision_id': 'id', 'target_descriptors_sha256': 'hash', 'target_revision_sha256': 'hash', 'target_view_sha256': 'hash',
                      'publication_sequence': 'positive',
                      'artifact_ids': ['id', 0, 128]},
    'MutationReceipt': {'operation_id': 'id', 'request_sha256': 'hash',
                        'state': ('applied', 'rejected', 'outcome_unknown'),
                        'generation': 'n', 'result_id': 'text', 'reconcile_ref': 'id',
                        'error_code': ('none', 'conflict', 'stale_generation', 'outcome_unknown', 'idempotency_conflict')},
    'ReaderConfig': {'max_envelope_bytes': 'positive', 'max_batch_rows': 'positive',
                     'max_ttl_ms': 'positive', 'capabilities': ['id', 1, 8]},
    'ContractError': {'code': ('invalid_contract', 'unsupported_version', 'unsupported_capability',
                             'unauthorized', 'revoked', 'expired_context', 'conflict',
                             'stale_generation', 'outcome_unknown', 'cancelled', 'deadline',
                             'resource_limit', 'corrupt_object', 'missing_object', 'backend_unavailable'),
                      'diagnostic_id': 'id', 'retryable': 'bool', 'reconcile_ref': 'text'},
}
KINDS = {'read_binding': 'ReadBinding', 'read_batch': 'ReadBatch', 'register_intent': 'RegisterIntent',
         'publish_intent': 'PublishIntent', 'mutation_receipt': 'MutationReceipt',
         'reader_config': 'ReaderConfig', 'contract_error': 'ContractError',
         'bind_request': 'BindRequest', 'candidate_batch': 'CandidateBatch', 'mutation_auth': 'MutationAuth', 'index_query': 'IndexQuery', 'read_descriptors': 'ReadDescriptors'}


def schema():
    """Return a standalone JSON Schema 2020-12 with closed, required fields."""
    scalars = {'id': {'type': 'string', 'pattern': '^(?!latest$)[A-Za-z0-9_-]{1,128}$'},
               'text': {'type': 'string', 'maxLength': 4096},
               'opaque': {'type': 'string', 'minLength': 1, 'maxLength': 1024, 'pattern': '^[^\x00-\x20\x7f]+$'},
               'score': {'type': 'string', 'pattern': '^[0-9a-f]{16}$'},
               'hash': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'},
               'bool': {'type': 'boolean'}, 'n': {'type': 'integer', 'minimum': 0, 'maximum': I53},
               'positive': {'type': 'integer', 'minimum': 1, 'maximum': I53}}
    def shape(spec):
        if isinstance(spec, list):
            return {'type': 'array', 'items': shape(spec[0]), 'minItems': spec[1], 'maxItems': spec[2]}
        if isinstance(spec, tuple):
            return {'type': 'string', 'enum': list(spec)}
        if spec == 'cell':
            return {'oneOf': [obj({'type': {'const': name}, 'value': value}) for name, value in (
                ('null', {'type': 'null'}), ('text', scalars['text']), ('bool', scalars['bool']),
                ('int8', {'type': 'string', 'pattern': '^(0|-[1-9][0-9]*|[1-9][0-9]*)$',
                          'maxLength': 20}))]}
        return copy.deepcopy(scalars[spec]) if spec in scalars else {'$ref': '#/$defs/'+spec}
    def obj(properties):
        return {'type': 'object', 'properties': properties, 'required': list(properties),
                'additionalProperties': False}
    definitions = {name: obj({key: shape(spec) for key, spec in fields.items()})
                   for name, fields in SHAPES.items()}
    definitions['FixedId'] = shape('id')
    return {'$schema': 'https://json-schema.org/draft/2020-12/schema', '$defs': definitions,
            **obj({'contract_version': {'const': VERSION},
                   'required_capabilities': {'type': 'array', 'items': {'enum': list(CAPABILITIES)},
                                             'minItems': 1, 'uniqueItems': True},
                   'payload': {'oneOf': [obj({kind: shape(value)}) for kind, value in KINDS.items()]}})}
