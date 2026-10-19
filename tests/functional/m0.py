"""HTTP/S3/PG18 differential acceptance against a live GuraDB binary."""
from copy import deepcopy
import json
from urllib.parse import quote

from jsonschema import Draft202012Validator
import pyarrow.parquet as pq

from m0lib.pgwire import publish_auth
from m0lib.kit import DATASET, ROOT, laboratory, truth, write

API = json.loads((ROOT / 'api/http/openapi.json').read_text())


def validate(name, value):
    Draft202012Validator(dict(API, **{'$ref': '#/components/schemas/' + name})).validate(value)


def run(directory):
    checks = 0
    with laboratory(directory) as lab:
        # Independent Parquet reader confirms the physical fixture, without the server.
        physical = [r for f in lab.manifest['files'] for r in pq.read_table(lab.directory / 'objects' / f['key']).to_pylist()]
        assert physical == lab.rows
        manifest_schema = json.loads((ROOT/'api/manifest/v1.schema.json').read_text())
        Draft202012Validator(manifest_schema).validate(lab.manifest)
        lab.reject_manifest(lab.manifest, bad_pin=True)
        for mutate in [lambda m:m.update(schema_version=2), lambda m:m.update(delete_vectors=[]),
                       lambda m:m['schema'].append(m['schema'][0]),
                       lambda m:m['files'][0].update(key='../escape.parquet'),
                       lambda m:m['files'][0].update(version_id='local-version'),
                       lambda m:m['files'][0].update(version_id=None),
                       lambda m:m['schema'][0].update(data_type='float8')]:
            bad = deepcopy(lab.manifest)
            mutate(bad)
            lab.reject_manifest(bad)
            checks += 1
        lab.postgres()
        lab.start()
        queries = [
            'SELECT * FROM documents ORDER BY id',
            'SELECT id, title FROM documents WHERE id >= 3 AND id < 12 ORDER BY id DESC LIMIT 4',
            'SELECT id, active FROM documents WHERE active IS NULL ORDER BY id',
            'SELECT id FROM documents WHERE NOT active ORDER BY id',
            'SELECT id, title FROM documents WHERE title IS NOT NULL ORDER BY title ASC NULLS LAST, id DESC',
            'SELECT id, title FROM documents ORDER BY title DESC NULLS FIRST, id LIMIT 8',
            'SELECT id AS document_id FROM documents WHERE id < 0 ORDER BY id',
            'SELECT "id", title FROM "documents" WHERE id = 9223372036854775807 ORDER BY id',
            'SELECT id FROM documents WHERE active = true OR title IS NULL ORDER BY id',
            'SELECT id FROM documents WHERE id = NULL ORDER BY id',
            'SELECT id FROM documents WHERE NULL ORDER BY id',
            'SELECT id FROM documents WHERE NOT NULL ORDER BY id',
            'SELECT id FROM documents WHERE active OR NULL ORDER BY id',
            'SELECT id FROM documents WHERE id > -9223372036854775808 ORDER BY id',
            'SELECT id FROM documents ORDER BY id LIMIT 0',
        ]
        for sql in queries:
            handle, page = lab.query(sql)
            assert page['rows'] == lab.oracle(sql), (sql, page)
            validate('QueryHandle', handle)
            validate('ResultPage', page)
            assert page['read_context'] == handle['read_context']
            checks += 1
        for sql, params, oracle in [
            ('SELECT id FROM documents WHERE id > $1 AND title = $2 ORDER BY id', [2, "agent's data"],
             "SELECT id FROM documents WHERE id > 2 AND title = 'agent''s data' ORDER BY id"),
            ('SELECT id FROM documents WHERE id = $1', [{'type': 'int8', 'value': '9223372036854775807'}],
             'SELECT id FROM documents WHERE id = 9223372036854775807'),
            ('SELECT id FROM documents WHERE active = $1 ORDER BY id', [False], 'SELECT id FROM documents WHERE active = false ORDER BY id'),
            ('SELECT id FROM documents WHERE title = $1 ORDER BY id', [None], 'SELECT id FROM documents WHERE title = NULL ORDER BY id'),
            ('SELECT id FROM documents WHERE title = $1 ORDER BY id', ["' OR true; DROP TABLE documents; --"],
             "SELECT id FROM documents WHERE id < 0 ORDER BY id"),
        ]:
            _, page = lab.query(sql, parameters=params)
            assert page['rows'] == lab.oracle(oracle)
            checks += 1
        rejected = [
            'SELECT 1', 'SELECT * FROM documents; SELECT * FROM documents',
            'SELECT * FROM documents FOR UPDATE', 'DELETE FROM documents', 'DROP TABLE documents',
            'COPY documents TO \'/tmp/leak\'', 'BEGIN', 'INSERT INTO documents VALUES (1,\'x\',true)',
            'WITH x AS (DELETE FROM documents RETURNING *) SELECT * FROM x',
            'WITH x AS (SELECT * FROM documents) SELECT * FROM x',
            'SELECT pg_read_file(\'/etc/passwd\') FROM documents',
            'SELECT * FROM read_parquet(\'/etc/passwd\')', 'SELECT * FROM documents d',
            'SELECT * FROM documents JOIN documents b ON true', 'SELECT COUNT(*) FROM documents',
            'SELECT DISTINCT id FROM documents', 'SELECT id FROM documents UNION SELECT id FROM documents',
            'SELECT (SELECT id FROM documents LIMIT 1) FROM documents',
            'SELECT * FROM documents OFFSET 1', 'SELECT * INTO hacked FROM documents',
            'SELECT title COLLATE "C" FROM documents', 'SELECT id + 1 FROM documents',
            'SELECT * FROM documents WHERE id = \'1\'', 'SELECT * FROM documents WHERE id AND active',
            'SELECT * FROM documents WHERE title LIKE \'a%\'', 'SELECT * FROM documents ORDER BY random()',
            'SELECT * FROM documents TABLESAMPLE BERNOULLI (10)', 'SELECT id, id FROM documents',
            'SELECT * FROM missing', 'SELECT * FROM documents WHERE id = $0',
        ]
        for sql in rejected:
            code, body = lab.http('POST', '/v1/queries', {'sql': sql})
            assert code in (400, 404), (sql, code, body)
            validate('ErrorEnvelope', body)
            checks += 1
        for extra in [ {'parameters': [1]}, {'parameters': [9007199254740992], 'sql': 'SELECT id FROM documents WHERE id = $1'},
                       {'parameters': [{'type': 'int8', 'value': '01'}], 'sql': 'SELECT id FROM documents WHERE id = $1'},
                       {'parameters': [1.5], 'sql': 'SELECT id FROM documents WHERE id = $1'},
                       {'parameters': [], 'sql': 'SELECT id FROM documents WHERE id = $1'},
                       {'parameters': [[1]], 'sql': 'SELECT id FROM documents WHERE id = $1'},
                       {'tenant_id': 'tenant-b'}, {'max_rows': None}, {'timeout_ms': None}, {'read_view_id': None}, {'mode': 'read_write'}, {'read_consistency': 'data_committed'},
                       {'read_view_id': 'wrong-view'}, {'timeout_ms': 10001}, {'max_rows': 1001}, {'max_rows': 0} ]:
            code, _ = lab.http('POST', '/v1/queries', {'sql': 'SELECT * FROM documents', **extra})
            assert code in (400, 429), (extra, code)
            checks += 1
        assert lab.http('POST', '/v1/queries', {'sql': 'SELECT * FROM documents'}, auth=False)[0] == 401
        assert lab.http('POST', '/v1/queries', {'sql': 'SELECT * FROM documents'}, token='wrong')[0] == 401
        handle, page = lab.query(max_rows=7)
        assert page['rows'] == truth(lab.rows[:7]) and page['truncated'] is True
        path = '/v1/queries/' + handle['query_id']
        for method, suffix in [('GET', ''), ('GET', '/results'), ('DELETE', '')]:
            assert lab.http(method, path + suffix, token=lab.other_token)[0] == 404
        # Repeatable bounded pages retain the same context and do not rescan data.
        _, first = lab.http('GET', path + '/results?page_size=3')
        cursor = first['next_cursor']
        _, second = lab.http('GET', path + '/results?page_size=3&cursor=' + quote(cursor))
        assert second == lab.http('GET', path + '/results?page_size=3&cursor=' + quote(cursor))[1]
        assert first['rows'] + second['rows'] == truth(lab.rows[:6])
        assert first['read_context'] == second['read_context'] == handle['read_context']
        assert lab.http('GET', path + '/results?cursor=' + quote(cursor + 'x'))[0] == 400
        another = lab.terminal(lab.submit())
        assert lab.http('GET', '/v1/queries/' + another['query_id'] + '/results?cursor=' + quote(cursor))[0] == 400
        assert lab.http('DELETE', path)[1]['status'] == 'succeeded'
        lab.principals[0]['datasets'] = []
        publish_auth(lab)
        assert lab.http('GET', path + '/results')[0] == 404
        assert lab.http('POST', '/v1/queries', {'sql': 'SELECT * FROM documents'})[0] == 404
        lab.principals[0]['datasets'] = [DATASET]
        publish_auth(lab)
        lab.auth.write_text('{invalid')
        assert lab.http('GET', path)[0] == 503
        publish_auth(lab)
        checks += 16
        # Real application budgets fail without publishing partial rows.
        for limits in [{'scan_bytes': 1}, {'decoded_bytes': 1}, {'result_bytes': 1}]:
            lab.start(limits)
            outcome = lab.terminal(lab.submit())
            assert outcome['status'] == 'failed' and outcome['error']['code'] == 'resource_limit', outcome
            assert lab.http('GET', '/v1/queries/' + outcome['query_id'] + '/results')[0] == 409
            checks += 1
        # Local backend rejects symlink traversal and corrupt/schema-mismatched objects.
        lab.start()
        first_path = lab.directory/'objects'/lab.manifest['files'][0]['key']
        payload = first_path.read_bytes()
        target = lab.directory/'outside.parquet'
        target.write_bytes(payload)
        first_path.unlink()
        first_path.symlink_to(target)
        bad = lab.terminal(lab.submit())
        assert bad['status'] == 'failed' and bad['error']['code'] == 'source_invalid', bad
        first_path.unlink()
        first_path.write_bytes(payload)
        original = deepcopy(lab.manifest)
        first_path.write_bytes(b'not a Parquet file')
        import hashlib
        lab.manifest['files'][0].update(size_bytes=first_path.stat().st_size, sha256=hashlib.sha256(first_path.read_bytes()).hexdigest())
        lab.start()
        bad = lab.terminal(lab.submit())
        assert bad['status'] == 'failed' and bad['error']['code'] == 'source_invalid', bad
        first_path.write_bytes(payload)
        lab.manifest = deepcopy(original)
        lab.manifest['schema'][0]['data_type'] = 'text'
        lab.start()
        bad = lab.terminal(lab.submit())
        assert bad['status'] == 'failed' and bad['error']['code'] == 'source_invalid', bad
        lab.manifest = original
        checks += 4
        # Exact S3 reads, immutable version selection and historical overwrite.
        lab.s3()
        lab.client.put_bucket_versioning(Bucket='m0-data', VersioningConfiguration={'Status': 'Enabled'})
        for fragment in lab.manifest['files']:
            payload = (lab.directory / 'objects' / fragment['key']).read_bytes()
            response = lab.client.put_object(Bucket='m0-data', Key=fragment['key'], Body=payload)
            assert response.get('VersionId'), response
            fragment['version_id'] = response['VersionId']
        lab.start()
        handle, page = lab.query()
        assert page['rows'] == truth(lab.rows)
        assert handle['stats']['source_reads'] == 2
        assert handle['stats']['source_bytes'] == sum(f['size_bytes'] for f in lab.manifest['files'])
        lab.client.put_object(Bucket='m0-data', Key=lab.manifest['files'][0]['key'], Body=b'overwritten')
        assert lab.query()[1]['rows'] == truth(lab.rows)
        # An explicitly non-existent version never falls back to current data.
        original = deepcopy(lab.manifest)
        lab.manifest['files'][0]['version_id'] = 'nonexistent-version'
        lab.start()
        outcome = lab.terminal(lab.submit())
        assert outcome['status'] == 'failed' and outcome['error']['code'] in ['source_unavailable', 'source_invalid'], outcome
        lab.manifest = original
        checks += 4
        lab.event('functional_passed', assertions=checks)
    return {'suite': 'functional', 'passed': True, 'assertions': checks, 'oracle': 'PostgreSQL 18 C collation + PyArrow 22', 's3': 'SeaweedFS 3.97 versioned GET'}
