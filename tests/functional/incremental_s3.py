"""Real SeaweedFS GET identity/HEAD append verification and old-file refusal."""
from pathlib import Path
from unittest.mock import patch

import pyarrow as pa

from m0lib.kit import DATASET, laboratory
from m1lib.fixtures import feature_file, iceberg, pg, target
from modules.common.contracts import Budget, Failure
from modules.index.retrieval import load_bundle
from modules.query.incremental import refresh
from modules.query.snapshot import construct, publish
from modules.storage.objects import Objects


def run(directory):
    directory = Path(directory).resolve()
    with laboratory(directory) as lab:
        control, _, _ = pg(lab)
        lab.s3()
        properties = {'s3.endpoint': 'http://127.0.0.1:'+lab.port(lab.store, 8333),
                      's3.access-key-id': 'm0-test-key', 's3.secret-access-key': 'm0-test-secret',
                      's3.region': 'us-east-1', 's3.force-virtual-addressing': 'false'}
        lake = directory/'lake'
        table, _, rows = iceberg(lake, 64, properties=properties, location='s3://m0-data/lake/table')
        selected = target(table, feature_file(lake, rows, lab.client), s3=lab.client)
        control.register(DATASET, 'tenant', 'documents',
                         {'root': 's3://m0-data/lake', 'key_field': 'id', 'text_field': 'title'})
        first = construct(control, DATASET, 'base-s3', selected, directory/'builds', lab.client)
        publish(control, first['id'], 0)
        base = load_bundle(first['artifact'], Budget())
        old_files = {d['uri']: d for d in base['source']['dependencies'] if d['uri'].endswith('.parquet')}
        assert len(old_files) == 2
        for uri, dependency in old_files.items():
            identity = dependency['identity']
            assert identity['kind'] == 's3-head-v1' and identity['etag']
            head = lab.client.head_object(Bucket='m0-data', Key=uri.removeprefix('s3://m0-data/'))
            assert identity['etag'] == head['ETag'] and identity['size'] == head['ContentLength']
        schema = pa.schema([pa.field('id', pa.int64(), nullable=False),
                            pa.field('title', pa.string()), pa.field('active', pa.bool_())])
        appended = [{'id': i, 'title': 'new alpha '+str(i), 'active': i % 2 == 0} for i in range(64, 80)]
        table.append(pa.Table.from_pylist(appended, schema=schema))
        selected = target(table, feature_file(lake, rows+appended, lab.client), s3=lab.client)
        oracle = sorted(table.scan().to_arrow().to_pylist(), key=lambda row: row['id'])
        reads, heads = [], []
        def head_event(**kwargs):
            heads.append(True)
        lab.client.meta.events.register('before-call.s3.HeadObject', head_event)
        original = Objects.read
        def read(objects, uri, *args, **kwargs):
            assert uri not in old_files, 'refresh fetched old source Parquet'
            reads.append(uri)
            return original(objects, uri, *args, **kwargs)
        with patch.object(Objects, 'read', read):
            candidate = refresh(control, DATASET, 'append-s3', selected, directory/'builds', lab.client)
        assert len(heads) >= 2*len(old_files), 'validation and ready must both perform real HEAD'
        actual = load_bundle(candidate['artifact'], Budget())
        assert sorted([r['values'] for r in actual['rows']], key=lambda row: row['id']) == oracle
        versions = {r['logical_key']: r['record_version'] for r in base['rows']}
        assert all(r['record_version'] == versions[r['logical_key']] for r in actual['rows'] if r['logical_key'] in versions)
        assert len([uri for uri in reads if uri.endswith('.parquet')]) == 1
        assert publish(control, candidate['id'], 1) == 2
        assert refresh(control, DATASET, 'append-s3', selected, directory/'builds', lab.client)['id'] == candidate['id']
        tail = [{'id': 80, 'title': 'later alpha', 'active': True}]
        table.append(pa.Table.from_pylist(tail, schema=schema))
        later = target(table, feature_file(lake, rows+appended+tail, lab.client), s3=lab.client)
        uri = sorted(old_files)[0]
        source_key = uri.removeprefix('s3://m0-data/')
        raw = lab.client.get_object(Bucket='m0-data', Key=source_key)['Body'].read()
        lab.client.put_object(Bucket='m0-data', Key=source_key, Body=b'replaced source bytes')
        for operation, expected in (('changed-s3', 'source_invalid'), ('missing-s3', 'source_unavailable')):
            if operation == 'missing-s3':
                lab.client.put_object(Bucket='m0-data', Key=source_key, Body=raw)
                lab.client.delete_object(Bucket='m0-data', Key=source_key)
            try:
                refresh(control, DATASET, operation, later, directory/'builds', lab.client)
            except Failure as error:
                assert error.code == expected, (error.code, expected)
                assert 'http' not in error.message and 'm0-test' not in error.message
            else:
                raise AssertionError('changed/missing old S3 source was accepted')
            failed = refresh(control, DATASET, operation, later, directory/'builds', lab.client)
            assert failed['status'] == 'failed' and failed['artifact'] is None and failed['error'] == expected
            assert control.dataset(DATASET)['published'] == candidate['id']
        # Serving remains independent of the deleted external source.
        assert len(load_bundle(candidate['artifact'], Budget())['rows']) == 80
        lab.event('incremental_s3_verified', base_rows=64, appended_rows=16, old_data_gets=0,
                  added_data_gets=1, real_head_requests=len(heads))
        return {'passed': True, 'source': 'real SeaweedFS S3 and PostgreSQL', 'base_rows': 64,
                'appended_rows': 16, 'old_data_gets': 0, 'added_data_gets': 1,
                'real_head_requests': len(heads), 'negative': ['old source ETag changed', 'old source deleted'],
                'oracle': 'independent PyIceberg S3 scan and inherited record versions'}
