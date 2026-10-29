#!/usr/bin/env python3
"""Real controlled Parquet -> Rust HTTP -> DataFusion core acceptance (fixture)."""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
import uuid

import pyarrow as pa
import pyarrow.parquet as pq
from jsonschema import Draft202012Validator
from harnesslib.policy import load
from harnesslib.runner import checkout_digest

ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'guradb-rust:1.90.0'
DATASET = '89b349e2-cc73-4c22-871d-c80a159d7789'


def write(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def command(*args, check=True):
    return subprocess.run(args, cwd=ROOT, text=True, capture_output=True, check=check, timeout=120)


def mapped(path):
    return '/workspace/' + str(path.relative_to(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    args = parser.parse_args()
    directory = args.run_dir.resolve()
    if not directory.is_relative_to(ROOT / 'artifacts'):
        parser.error('run-dir must be a new directory under workspace artifacts')
    directory.mkdir(parents=True, exist_ok=False)
    name = 'gura-fixed-core-' + uuid.uuid4().hex[:12]
    trace = []
    active = False
    result = {'passed': False, 'stage': 'core-limited', 'business_data': False}
    try:
        commit = command('git', 'rev-parse', 'HEAD').stdout.strip()
        digest = checkout_digest(ROOT, load(ROOT)[0])
        with (directory / 'build.log').open('x') as log:
            subprocess.run([sys.executable, 'scripts/cargo.py', 'build', '--locked', '--package', 'guradb-gateway'],
                           cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=900)
        schema = pa.schema([pa.field('record_id', pa.string(), False), pa.field('value', pa.int64(), False),
                            pa.field('title', pa.string()), pa.field('active', pa.bool_())])
        # Literal independent input; physical order is intentionally not key order.
        rows = [{'record_id': 'z', 'value': 9, 'title': None, 'active': False},
                {'record_id': 'a', 'value': 9223372036854775807, 'title': '数据库', 'active': True},
                {'record_id': 'm', 'value': -8, 'title': 'beta', 'active': True},
                {'record_id': 'b', 'value': 7, 'title': None, 'active': True}]
        objects = directory / 'objects'
        objects.mkdir()
        source = objects / 'part.parquet'
        pq.write_table(pa.Table.from_pylist(rows, schema=schema), source, compression='snappy')
        original = source.read_bytes()
        assert pq.read_table(source).to_pylist() == rows
        manifest = {'schema_version': 1, 'dataset_id': DATASET, 'table_name': 'records',
                    'schema': [{'name': field.name, 'data_type': kind, 'nullable': field.nullable}
                               for field, kind in zip(schema, ['text', 'int8', 'text', 'bool'])],
                    'backend': {'kind': 'local', 'root': mapped(objects)}, 'retention_mode': 'best-effort',
                    'files': [{'fragment_id': 'part', 'key': 'part.parquet', 'size_bytes': len(original),
                               'sha256': hashlib.sha256(original).hexdigest()}]}
        # Same source with a duplicated logical key, selected with LIMIT 0 below.
        duplicate = objects / 'duplicate.parquet'
        pq.write_table(pa.Table.from_pylist([rows[0], rows[0]], schema=schema), duplicate)
        duplicate_manifest = deepcopy(manifest)
        duplicate_manifest.update(dataset_id='d563a8ab-f599-4c9b-8db7-48d5cfa936a2', table_name='duplicates')
        duplicate_manifest['files'] = [{'fragment_id': 'duplicate', 'key': duplicate.name,
                                       'size_bytes': duplicate.stat().st_size,
                                       'sha256': hashlib.sha256(duplicate.read_bytes()).hexdigest()}]
        references = []
        for filename, value in [('manifest.json', manifest), ('duplicate-manifest.json', duplicate_manifest)]:
            path = directory / filename
            write(path, value)
            references.append({'path': mapped(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
        revision, view = 'rev_' + references[0]['sha256'], 'view_' + references[0]['sha256']
        token, other = secrets.token_hex(24), secrets.token_hex(24)
        auth = {'principals': [{'token_sha256': hashlib.sha256(value.encode()).hexdigest(),
                               'tenant_id': tenant, 'principal_id': 'reader',
                               'datasets': [DATASET, duplicate_manifest['dataset_id']]}
                              for value, tenant in [(token, 'tenant-a'), (other, 'tenant-b')]]}
        write(directory / 'auth.json', auth)
        write(directory / 'server.json', {'listen': '0.0.0.0:8080', 'auth_file': mapped(directory / 'auth.json'),
                                         'manifests': references, 'limits': {'concurrent_queries': 1, 'handles': 1,
                                                                          'retention_seconds': 1}})
        command('docker', 'run', '-d', '--name', name, '--network', 'bridge',
                '-p', '127.0.0.1::8080', '-v', f'{ROOT}:/workspace:ro', IMAGE,
                '/workspace/target/debug/guradb', '--config', mapped(directory / 'server.json'))
        active = True
        port = command('docker', 'port', name, '8080').stdout.strip().rsplit(':', 1)[1]
        url = 'http://127.0.0.1:' + port
        deadline = time.monotonic() + 15
        while True:
            try:
                urllib.request.urlopen(url + '/healthz', timeout=1).close()
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(.05)
        api = json.loads((ROOT / 'api/http/openapi.json').read_text())
        example = api['paths']['/v1/fixed-queries']['post']['requestBody']['content']['application/json']['example']
        Draft202012Validator(dict(api, **{'$ref': '#/components/schemas/FixedQueryRequest'})).validate(example)

        def request(method, path, body=None, key=token):
            req = urllib.request.Request(url + path, method=method,
                                         headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'},
                                         data=None if body is None else json.dumps(body).encode())
            try:
                with urllib.request.urlopen(req, timeout=12) as response:
                    status, value = response.status, json.load(response)
            except urllib.error.HTTPError as error:
                with error:
                    status, value = error.code, json.load(error)
            trace.append({'method': method, 'path': path, 'status': status, 'response': value})
            write(directory / 'trace.json', trace)
            return status, value

        def terminal(handle):
            end = time.monotonic() + 12
            while time.monotonic() < end:
                status, value = request('GET', '/v1/queries/' + handle['query_id'])
                assert status == 200, value
                if value['status'] in ['succeeded', 'failed', 'cancelled']:
                    return value
                time.sleep(.01)
            raise AssertionError('query did not terminate')

        def submitted(body, path='/v1/fixed-queries'):
            status, handle = request('POST', path, body)
            assert status == 202, handle
            return terminal(handle)

        def result_page(handle):
            status, value = request('GET', '/v1/queries/' + handle['query_id'] + '/results')
            assert status == 200, value
            Draft202012Validator(dict(api, **{'$ref': '#/components/schemas/ResultPage'})).validate(value)
            return value

        def publish_bytes(path, raw):
            # Administrative update is committed only when the service sees it.
            temporary = path.with_name(path.name + '.publishing')
            temporary.write_bytes(raw)
            os.replace(temporary, path)
            expected = hashlib.sha256(raw).hexdigest()
            end = time.monotonic() + 2
            while time.monotonic() < end:
                observed = command('docker', 'exec', name, 'sha256sum', mapped(path)).stdout.split()[0]
                if observed == expected:
                    return
                time.sleep(.02)
            raise AssertionError('administrative file publication not visible in service')

        body = {'dataset_id': DATASET, 'data_revision_id': revision, 'read_view_id': view,
                'sql': 'SELECT title, value FROM records WHERE active ORDER BY value DESC LIMIT 2'}
        for mutate, error in [(lambda b: b.update(data_revision_id='latest'), 'view_unavailable'),
                              (lambda b: b.update(read_view_id='latest'), 'view_unavailable'),
                              (lambda b: b.pop('dataset_id'), 'invalid_request'),
                              (lambda b: b.update(tenant_id='admin'), 'invalid_request'),
                              (lambda b: b.update(sql='SELECT count(*) FROM records'), 'unsupported'),
                              (lambda b: b.update(max_rows=1001), 'resource_limit')]:
            invalid = deepcopy(body)
            mutate(invalid)
            status, value = request('POST', '/v1/fixed-queries', invalid)
            assert status == (429 if error == 'resource_limit' else 400) and value['error']['code'] == error, value
        assert request('POST', '/v1/fixed-queries', body, key='invalid')[0] == 401
        handle = submitted(body)
        assert handle['status'] == 'succeeded', handle
        page = result_page(handle)
        assert page['rows'] == [['数据库', '9223372036854775807'], [None, '7']], page
        binding = {'tenant_id': 'tenant-a', 'principal_id': 'reader', 'dataset_id': DATASET,
                   'data_revision_id': revision, 'read_view_id': view}
        assert page['binding'] == handle['binding'] == binding
        assert page['lineage'] == [{'entity_kind': 'record', 'record_id': key, 'record_version': revision}
                                   for key in ['a', 'b']]
        assert page['truncated'] is False and page['read_context']['data_revision_id'] == revision
        assert handle['stats']['source_reads'] == 1 and handle['stats']['source_bytes'] == len(original)
        assert request('GET', '/v1/queries/' + handle['query_id'] + '/results', key=other)[0] == 404
        auth['principals'][0]['datasets'] = []
        publish_bytes(directory / 'auth.json', json.dumps(auth).encode())
        assert request('GET', '/v1/queries/' + handle['query_id'] + '/results')[0] == 404
        auth['principals'][0]['datasets'] = [DATASET, duplicate_manifest['dataset_id']]
        publish_bytes(directory / 'auth.json', json.dumps(auth).encode())
        time.sleep(1.1)
        assert request('GET', '/v1/queries/' + handle['query_id'])[0] == 410
        # Failed integrity attempt must release the source handle and semaphore.
        publish_bytes(source, b'X' * len(original))
        failed = submitted(body)
        assert failed['status'] == 'failed' and failed['error']['code'] == 'source_invalid', failed
        assert request('GET', '/v1/queries/' + failed['query_id'] + '/results')[0] == 409
        descriptors = command('docker', 'exec', name, 'sh', '-c',
                              'for fd in /proc/1/fd/*; do readlink "$fd" || true; done').stdout.splitlines()
        assert not any('part.parquet' in fd for fd in descriptors), descriptors
        publish_bytes(source, original)
        time.sleep(1.1)
        recovered = submitted(body)
        assert recovered['status'] == 'succeeded' and result_page(recovered)['rows'] == page['rows']
        time.sleep(1.1)
        dup = dict(body, dataset_id=duplicate_manifest['dataset_id'],
                   data_revision_id='rev_' + references[1]['sha256'], read_view_id='view_' + references[1]['sha256'],
                   sql='SELECT value FROM duplicates LIMIT 0')
        rejected = submitted(dup)
        assert rejected['status'] == 'failed' and rejected['error']['code'] == 'source_invalid', rejected
        time.sleep(1.1)
        legacy = submitted({'sql': 'SELECT record_id FROM records ORDER BY record_id LIMIT 1'}, '/v1/queries')
        assert legacy['status'] == 'succeeded'
        legacy_page = result_page(legacy)
        assert legacy_page['rows'] == [['a']] and 'binding' not in legacy_page and 'lineage' not in legacy_page
        assert commit == command('git', 'rev-parse', 'HEAD').stdout.strip()
        assert digest == checkout_digest(ROOT, load(ROOT)[0]), 'source changed during acceptance'
        result.update(passed=True, git_commit=commit, checkout_digest=digest, input_rows=len(rows),
                      input_bytes=len(original), manifest_sha256=references[0]['sha256'],
                      resource_terminal='integrity failure: no source fd, no result; subsequent query acquired sole permit',
                      pin_lease='not used: controlled local best-effort operator retention',
                      untested=['full cancellation/timeout IO shutdown', 'performance', 'scale', 'release'])
    except Exception:
        result['failure'] = traceback.format_exc()
        print(result['failure'], file=sys.stderr)
    finally:
        if active:
            logs = command('docker', 'logs', name, check=False)
            (directory / 'service.log').write_text(logs.stdout + logs.stderr)
            removed = command('docker', 'rm', '-f', name, check=False)
            absent = command('docker', 'inspect', name, check=False).returncode != 0
            result['service_removed'] = absent and removed.returncode == 0
            result['passed'] = result['passed'] and result['service_removed']
        result['trace_sha256'] = hashlib.sha256((directory / 'trace.json').read_bytes()).hexdigest() if trace else None
        write(directory / 'result.json', result)
    print(json.dumps({'passed': result['passed'], 'evidence': str(directory / 'result.json')}))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
