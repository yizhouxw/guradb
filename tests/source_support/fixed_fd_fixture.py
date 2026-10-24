"""SQL-compatible fixture target; preserves already-uploaded Parquet identities.

This test-only factory publishes metadata, never a binding/context or a reader.
Actual PG register/publish and query binding are separate existing C1 operations.
"""
from copy import deepcopy
import os
from pathlib import Path
import uuid

from modules.catalog.cf1a_codec import contract
from modules.common.cf1a_primitives import canonical, digest, require, validate_shape
from modules.common.cf1a_read import without
from tests.source_support.fixed_evidence import error_record
from tests.source_support.fixed_fixture import FIELDS, encoded, sha

SQL_FIELDS = [
    {'field_id': 1, 'name': 'id', 'type': 'text', 'nullable': False, 'role': 'logical_id'},
    {'field_id': 2, 'name': 'version', 'type': 'text', 'nullable': False, 'role': 'record_version'},
    {'field_id': 3, 'name': 'number', 'type': 'int8', 'nullable': True, 'role': 'value'},
    {'field_id': 4, 'name': 'active', 'type': 'bool', 'nullable': True, 'role': 'value'},
    {'field_id': 6, 'name': 'tokens_text', 'type': 'text', 'nullable': True, 'role': 'value'},
    {'field_id': 17, 'name': 'title', 'type': 'text', 'nullable': True, 'role': 'value'},
]
PHYSICAL_OFFSETS = (1, 2, 5, 4, 6, 3)
ROW_KEYS = ('record_id', 'record_version', 'priority', 'active', 'tokens_text', 'title')


def save(path, raw):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def expected_cells(rows):
    result = []
    for row in sorted(rows, key=lambda value: value['record_id']):
        cells = []
        for field, key in zip(SQL_FIELDS, ROW_KEYS):
            value = row[key]
            cells.append({'type': 'null' if value is None else field['type'],
                          'value': str(value) if value is not None and field['type'] == 'int8' else value})
        result.append({'record_id': row['record_id'], 'record_version': row['record_version'], 'cells': cells})
    return result


def sql_target_from_uploaded(fixture, client, directory, dataset, schema_id, *, protected_until_unix_ms):
    """Add exactly two fresh fixed metadata objects, never remap/rewrite Parquet.

    Original versions here mean the same run's actual upload_multisource refs;
    they do not assert reuse of a deleted historical namespace's VersionIds.
    """
    validate_shape(dataset, 'id')
    validate_shape(schema_id, 'id')
    validate_shape(protected_until_unix_ms, 'positive')
    require(type(protected_until_unix_ms) is int and 0 < protected_until_unix_ms < 1 << 53,
            'invalid fixture protection')
    original = fixture['binding'].value
    require(dataset != original['resource']['dataset_id'] and schema_id != original['resource']['schema_id'],
            'new SQL target requires fresh dataset/schema')
    require(len(fixture['rows']) in (11, 130) and len(original['revision']['sources']) == 2
            and len(fixture['source_metadata']) == 2 and original['indexes'] == [], 'fixed target profile differs')
    # Complete preflight before the first PUT, including both physical schemas.
    inputs = []
    for number, (source, metadata) in enumerate(zip(original['revision']['sources'], fixture['source_metadata'])):
        require(source['source_id'] == ('source-main' if number == 0 else 'source-mirror')
                and metadata['source_id'] == source['source_id']
                and metadata['source_version_id'] == source['source_version_id']
                and metadata['snapshot_id'] == source['snapshot_id'], 'old source identity differs')
        shift = 100 * (number + 1)
        expected = [{'source_field_id': shift + field['field_id'],
                     **{key: field[key] for key in ('name', 'type', 'nullable')}} for field in FIELDS]
        require(metadata['source_schema'] == expected and source['source_schema_sha256'] == digest(expected),
                'original physical schema differs')
        require(len(metadata['files']) == 1, 'exactly one original Parquet per source')
        ref = metadata['files'][0]['object']
        raw = fixture['objects'][encoded(ref)]
        split = (10, 1) if len(fixture['rows']) == 11 else (65, 65)
        require(sum(metadata['files'][0]['row_group_rows']) == split[number], 'fixed source row split differs')
        require(ref['version'] not in ('', 'null', 'sealed-v1') and ref['size_bytes'] == len(raw)
                and ref['sha256'] == sha(raw), 'expected actual uploaded Parquet identity')
        inputs.append((deepcopy(source), deepcopy(metadata), deepcopy(ref), raw))
    require(len({row['record_id'] for row in fixture['rows']}) == len(fixture['rows']),
            'fixed target duplicate record identity')
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    token = uuid.uuid4().hex
    value = {key: deepcopy(original[key]) for key in ('resource', 'revision', 'view', 'indexes')}
    resource, revision, view = (value[key] for key in ('resource', 'revision', 'view'))
    resource.update(dataset_id=dataset, schema_id=schema_id, schema_version=1,
                    fields=deepcopy(SQL_FIELDS), schema_sha256=digest(SQL_FIELDS))
    revision.update(dataset_id=dataset, schema_id=schema_id, schema_version=1,
                    data_revision_id='fd-revision-' + token, parent_revision_ids=[])
    view.update(read_view_id='fd-view-' + token, data_revision_id=revision['data_revision_id'],
                publication_generation=2, publication_sequence=1, required_artifact_ids=[], index_requirements=[])
    objects, sources, metadata_list, versions, progress = {}, [], [], [], []
    primary = None
    try:
        for number, (source, metadata, parquet, raw) in enumerate(inputs):
            fresh_version = 'fd-source-' + token + '-' + str(number)
            fresh_snapshot = 'fd-snapshot-' + token + '-' + str(number)
            require(fresh_version != source['source_version_id'] and fresh_snapshot != source['snapshot_id'],
                    'new immutable source identity collided')
            source.update(source_version_id=fresh_version,
                          snapshot_id=fresh_snapshot,
                          protected_until_unix_ms=protected_until_unix_ms,
                          resource_schema_sha256=resource['schema_sha256'])
            source['field_mapping'] = [
                {'source_field_id': 100 * (number + 1) + offset,
                 'resource_field_id': field['field_id'], 'source_type': field['type'],
                 'type': field['type'], 'transform': 'identity'}
                for field, offset in zip(SQL_FIELDS, PHYSICAL_OFFSETS)]
            metadata.update(source_version_id=source['source_version_id'], snapshot_id=source['snapshot_id'])
            body = canonical(metadata)
            require(len(body) <= 65536, 'new metadata exceeds existing cap', 'resource_limit')
            key = 'fd-' + token + '/' + str(number) + '/metadata.json'
            progress.append({'source_id': source['source_id'], 'stage': 'metadata-put-started'})
            first = client.put_object(Bucket='m0-data', Key=key, Body=body).get('VersionId')
            progress[-1]['first_version_received'] = type(first) is str and first not in ('', 'null')
            later = client.put_object(Bucket='m0-data', Key=key, Body=b'later-unbound-version').get('VersionId')
            require(type(first) is str and type(later) is str and first not in ('', 'null')
                    and later not in ('', 'null') and first != later, 'metadata fixed versions unavailable')
            ref = {**deepcopy(source['metadata']), 'key': key, 'version': first,
                   'size_bytes': len(body), 'sha256': sha(body)}
            # Metadata proof remains whole-SHA; never copy a stale block proof.
            ref['integrity'] = {'mode': 'whole_sha256', 'block_size': 0, 'block_sha256': [], 'proof_ref': ''}
            source['metadata'] = ref
            objects[encoded(ref)], objects[encoded(parquet)] = body, raw
            sources.append(source)
            metadata_list.append(metadata)
            versions.append({'object': ref, 'unbound_later_version': later})
            progress[-1]['stage'] = 'two-fixed-versions-received'
            save(directory / ('metadata-%d.json' % number), body)
        revision.update(sources=sources, objects=[ref for source, metadata in zip(sources, metadata_list)
                                                 for ref in [source['metadata'], metadata['files'][0]['object']]])
        revision['content_sha256'] = digest(without(revision, 'content_sha256'))
        view['descriptor_sha256'] = digest(without(view, 'descriptor_sha256'))
        descriptor = contract('read_descriptors', value)
        save(directory / 'target-before-prepare.json', descriptor.encoded)
        truth = expected_cells(fixture['rows'])
        save(directory / 'truth.json', canonical(truth))
        return {'target': descriptor, 'objects': objects, 'source_metadata': metadata_list,
                'truth': truth, 'versions': versions, 'parquet_refs': [entry[2] for entry in inputs],
                'rows': deepcopy(fixture['rows']), 'directory': directory,
                'original_binding_sha256': fixture['binding'].sha256,
                'scope': 'target only; final prepare_target SHA and actual PG binding still required'}
    except BaseException as error:
        primary = error
        progress.append({'stage': 'failed', 'error': error_record(error)})
        raise
    finally:
        try:
            save(directory / 'new-metadata-progress.json', canonical(progress))
        except BaseException:
            if primary is None:
                raise  # Evidence failure cannot turn a successful build green.
            # Keep the original SDK/contract failure; launcher records missing journal.
