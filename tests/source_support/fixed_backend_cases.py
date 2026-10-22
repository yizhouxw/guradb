"""Real fixed-version S3 pairing; expected identities never come from P04."""
from copy import deepcopy
import hashlib
from importlib import import_module
from importlib.metadata import version as package_version
import json
from pathlib import Path
import re
import struct
import time

from modules.common.cf1a_primitives import ContractFailure
from modules.storage.fixed_cache import VerifiedCache
from tests.source_support.fixed_acceptance import (batch_rows, enumerate_all, expected_rows,
    instance, measured, save_case_input, upload, upload_multisource)
from tests.source_support.fixed_fixture import envelope, facts
from tests.source_support.fixed_evidence import observation
from tests.source_support.fixed_located_acceptance import located_cases
from tests.storage_support.recording_proxy import RecordingProxy


SDK_VERSIONS = {'boto3': '1.40.56', 'botocore': '1.40.76', 'urllib3': '2.8.0'}


def sdk_identity():
    versions, hashes = {}, {}
    for name, expected in SDK_VERSIONS.items():
        module = import_module(name)
        actual = package_version(name)
        assert actual == expected and module.__version__ == expected
        versions[name] = actual
        hashes[name] = hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
    return {'sdk_versions': versions, 'sdk_init_sha256': hashes}


def certify_fixture(lab, requested_image):
    cert = lab.s3_certification
    assert type(cert) is dict and set(cert) == {
        'requested_image', 'image_id', 'container_image_id', 'os', 'architecture', 'repo_digests'}
    assert cert['requested_image'] == requested_image and cert['os'] == 'linux'
    assert type(cert['image_id']) is str and re.fullmatch(r'sha256:[0-9a-f]{64}', cert['image_id'])
    assert cert['container_image_id'] == cert['image_id']
    assert type(cert['architecture']) is str and re.fullmatch(r'[a-z0-9_]{1,32}', cert['architecture'])
    digests = cert['repo_digests']
    assert type(digests) is list and 0 < len(digests) <= 16
    assert all(type(item) is str and re.fullmatch(
        r'(?:docker.io/)?chrislusf/seaweedfs(?::3\.97)?@sha256:[0-9a-f]{64}', item) for item in digests)
    canonical = 'chrislusf/seaweedfs@' + requested_image.split('@')[1]
    assert any(item.removeprefix('docker.io/') in (requested_image, canonical) for item in digests)
    assert type(lab.client.meta.config.proxies) is dict and lab.client.meta.config.proxies == {}
    # Docker's reported ID is an observation, not a config/child-manifest attestation.
    return {**deepcopy(cert), **sdk_identity(), 'profile': 'p04-seaweed397-direct',
            'proxy_policy': 'Config.proxies={}', 'proxy_enabled': False,
            'image_identity_scope': 'requested index and actual Docker-reported ID/platform only'}


def start_fixture(lab, directory):
    from scripts.m0lib.kit import S3
    lab.s3(direct=True)
    certification = certify_fixture(lab, S3)
    (directory/'fixture-certification.json').write_text(
        json.dumps(certification, indent=2, allow_nan=False) + '\n')
    return lab.client, certification


def many_rows():
    base = facts()
    return [{**deepcopy(base[index % 11]), 'record_id': f'r-{index:04d}'} for index in range(130)]


def typed_transform(fixture):
    expected, locations = [], {}
    for row in expected_rows(fixture):
        original = row['record_id']
        raw = original.encode('utf-8')
        identifier = (b'\x01' + struct.pack('>I', 1) + b'\x01' + struct.pack('>I', len(raw)) + raw).hex()
        row.update(record_id=identifier, record_version='p04-revision-v2')
        row['values'][0], row['values'][1] = identifier, 'p04-revision-v2'
        locations[identifier] = fixture['locations'][original]
        expected.append(row)
    value = fixture['binding'].value
    mappings = value['revision']['sources'][0]['field_mapping']
    mappings[0]['transform'] = 'key_v1'
    mappings[1].update(transform='revision_version', source_field_id=0, source_type='none')
    fixture['binding'] = envelope(value)
    fixture['expected_rows'] = sorted(expected, key=lambda row: row['record_id'])
    fixture['locations'] = locations
    return fixture


def rejections(reader, proxy):
    before, charged = proxy.requests, reader.scope.output_bytes
    reader.objects.reauthorize = lambda _: 2
    try:
        reader.port.read_batch(reader.scope.binding, 0)
    except ContractFailure as error:
        assert error.code == 'revoked'
    else:
        raise AssertionError('revoked fixed source returned a page')
    assert proxy.requests == before and reader.scope.output_bytes == charged
    assert reader._state is None and reader._failed
    reader.objects.reauthorize = lambda _: 1
    try:
        reader.port.read_batch(reader.scope.binding, 0)
    except ContractFailure as error:
        assert error.code == 'expired_context'
    else:
        raise AssertionError('poisoned source resumed')
    return {'case': 'cached-source-revoked', 'new_gets': proxy.requests - before,
            'new_output_bytes': reader.scope.output_bytes - charged,
            'state_cleared': reader._state is None, 'resume_rejected': True}


def real_backend(lab, directory, mode):
    client, certification = start_fixture(lab, directory)
    client.put_bucket_versioning(Bucket='m0-data', VersioningConfiguration={'Status': 'Enabled'})
    assert client.get_bucket_versioning(Bucket='m0-data').get('Status') == 'Enabled'
    fixed = upload(client, directory/'p01-input')
    rows = many_rows()
    multiple = upload(client, directory/'multi-input', rows=rows, split=[rows[:65], rows[65:]],
                      writer_options={'row_group_size': 16})
    empty = upload(client, directory/'empty-input', rows=[]) if mode == 'functional' else None
    dual = upload_multisource(client, directory/'two-source-input')
    dual_rows = [{**row, 'source_id': 'source-main' if i < 65 else 'source-mirror'}
                 for i, row in enumerate(deepcopy(rows))]
    dual_many = upload_multisource(client, directory/'two-source-many-input', source_rows=[
        ('source-main', 'p04-main-v2', dual_rows[:65]),
        ('source-mirror', 'p04-mirror-v2', dual_rows[65:])], writer_options={'row_group_size': 16})
    samples, negative = [], []
    with RecordingProxy(client.meta.endpoint_url) as proxy:
        cache = VerifiedCache(256 << 10)
        cases = [('p01-cold', fixed), ('p01-warm', fixed), ('multi-cold', multiple), ('multi-warm', multiple)]
        if empty is not None:
            cases += [('empty-cold', empty), ('typed-key-revision', typed_transform(deepcopy(fixed)))]
        cases += [('two-source-cold', dual), ('two-source-warm', dual)]
        cases += [('two-source-many-cold', dual_many), ('two-source-many-warm', dual_many)]
        query_ids = set()
        for case, fixture in cases:
            reader, primary = None, None
            before, completed = proxy.requests, False
            try:
                reader = instance(fixture, proxy.endpoint, cache=cache)
                save_case_input(reader, fixture, directory/'cases'/case)
                query_id = reader.scope.context['query_id']
                assert query_id not in query_ids
                query_ids.add(query_id)
                before = proxy.requests
                cohort_start = time.monotonic()
                pages = enumerate_all(reader, fixture)
                replay, repeated = measured(reader, 0)
                assert batch_rows(replay) == pages[0]['rows']
                assert repeated['usage']['object_requests'] == repeated['usage']['object_bytes'] == 0
                assert repeated['usage']['memory_bytes'] > 0
                assert proxy.wait_idle() and proxy.active == 0
                count = proxy.requests - before
                assert count == reader.scope.object_requests
                metadata = fixture.get('source_metadata', [fixture['metadata']])
                assert count == (0 if 'warm' in case or case == 'typed-key-revision' else
                                 len(metadata) + sum(len(item['files']) for item in metadata))
                assert all(page['context_sha256'] == reader.scope.binding.sha256 for page in pages)
                assert repeated['context_sha256'] == reader.scope.binding.sha256
                cohort_ms = (time.monotonic() - cohort_start) * 1000
                assert cohort_ms < 5000
                sample = {'case': case, 'query_id': query_id, 'actual_gets': count,
                    'cache_capacity_bytes': cache.capacity, 'application_cache': 'warm' if count == 0 else 'cold',
                    'os_cache': 'uncontrolled/warm development host', 'cohort_elapsed_ms': cohort_ms,
                    'input_rows': len(fixture['rows']), 'expected_rows': expected_rows(fixture),
                    'physical_locations': fixture['locations'], 'versions': fixture['versions'],
                    'pages': pages, 'replay': repeated, 'scope_trace': reader.scope.trace,
                    'independent_source_schema': fixture['metadata']['source_schema'],
                    'independent_row_groups': [entry['row_group_rows'] for entry in fixture['metadata']['files']]}
                if 'source_metadata' in fixture:
                    origins = fixture['source_origins']
                    assert len(origins) == len(fixture['rows'])
                    many = 'many' in case
                    assert sum(row['source_id'] == 'source-main' for row in origins.values()) == (65 if many else 10)
                    assert sum(row['source_id'] == 'source-mirror' for row in origins.values()) == (65 if many else 1)
                    if many:
                        assert len(origins) == 130
                        assert [len(page['rows']) for page in pages] == [64, 64, 2]
                        assert [page['ordinal'] for page in pages] == [0, 1, 2]
                        assert [page['last'] for page in pages] == [False, False, True]
                    else:
                        assert len(origins) == 11
                        assert origins['r-a1'] == {'record_version': '2', 'source_id': 'source-main',
                                                   'source_version_id': 'p04-main-v2'}
                        assert origins['r-a1-copy'] == {'record_version': '1', 'source_id': 'source-mirror',
                                                        'source_version_id': 'p04-mirror-v2'}
                    observed = [entry['sample']['context_sha256'] for entry in reader.acceptance_journal
                                if entry['sample'] is not None]
                    query_ids_seen = [entry['query_id'] for entry in reader.acceptance_journal]
                    assert observed and set(observed) == {reader.scope.binding.sha256}
                    assert set(query_ids_seen) == {query_id}
                    sample.update(independent_source_metadata=fixture['source_metadata'],
                        independent_source_origins=origins, binding_sha256=reader.scope.binding.sha256,
                        source_version_ids=reader.scope.context['source_version_ids'],
                        observed_binding_sha256=observed, observed_query_ids=query_ids_seen,
                        observed_binding_changes=sum(a != b for a, b in zip(observed, observed[1:])),
                        independent_source_schema=[{'source_version_id': item['source_version_id'],
                            'fields': item['source_schema']} for item in metadata],
                        independent_row_groups=[{'source_version_id': item['source_version_id'],
                            'groups': [entry['row_group_rows'] for entry in item['files']]} for item in metadata],
                        mirror_rows_returned=sum(origins[row['record_id']]['source_id'] == 'source-mirror'
                                                 for page in pages for row in page['rows']))
                    assert sample['mirror_rows_returned'] == (65 if many else 1)
                samples.append(sample)
                if mode == 'functional' and case == 'p01-cold':
                    negative.append(rejections(reader, proxy))
                completed = True
            except BaseException as error:
                primary = error
                raise
            finally:
                observation(directory/('case-' + case + '-observation.json'), reader=reader,
                    server=proxy, primary=primary, case=case, completed=completed,
                    requests_before=before, actual_gets=proxy.requests - before,
                    query_id=reader.scope.context['query_id'] if reader else None,
                    binding_sha256=reader.scope.binding.sha256 if reader else None,
                    completed_calls=reader.acceptance_journal if reader else [])
        located = located_cases(proxy, directory, dual, dual_many)
        assert proxy.wait_idle()
        backend = proxy.snapshot()
        assert backend['active_connections'] == 0
    return {'passed': True, 'mode': mode, 'samples': samples, 'negative': negative,
            'located_samples': located,
            'fixture_certification': certification,
            'backend': backend, 'scope': 'P04 narrow source paired with real P03/Seaweed immutable versions',
            'authorization': 'bounded in-memory test callback, no PG pairing',
            'missing': ['PG query lifecycle', 'B-L', 'Iceberg/delete/schema evolution',
                        'production scale', 'TLS/real cloud/multihost', 'I1']}
