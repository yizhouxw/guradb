"""Offline capability claims: schema, public allowlists and behavioral negatives.

References name verification entrypoints; their existence is not coverage proof.
The full harness still runs existing functional, cost and fault suites.
"""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from jsonschema import Draft202012Validator

from modules.cluster.transport import endpoint
from modules.common.contracts import Budget, Failure, MAX_FILES, MAX_ROWS
from modules.connectors.training import samples_for
from modules.gateway.m1 import Handler
from modules.index.bm25 import FORMAT, build as build_bm25
from modules.index.retrieval import ANALYZER, build, features, search

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = json.loads((ROOT/'api/capabilities/v1.json').read_text())
SCHEMA = json.loads((ROOT/'api/capabilities/v1.schema.json').read_text())
API = json.loads((ROOT/'api/http/m1-openapi.json').read_text())


def validate_request(name, request):
    return Draft202012Validator(dict(API, **{'$ref': '#/components/schemas/'+name})).is_valid(request)


def bundle():
    return {
        'version': 1, 'revision': 'new-revision', 'context': {'read_view_id': 'fixed-view'},
        'model': {'model': 'test-model', 'dimension': 2}, 'retention_mode': 'managed-copy',
        'manifest': {'dataset_id': 'dataset', 'schema': [
            {'name': 'id', 'data_type': 'int8'}, {'name': 'title', 'data_type': 'text'},
            {'name': 'active', 'data_type': 'bool'}]},
        'rows': [
            {'logical_key': 'b', 'record_version': 'new-revision', 'vector': [1., 0.],
             'values': {'id': 9223372036854775807, 'title': None, 'active': False}, 'media': []},
            {'logical_key': 'a', 'record_version': 'old-revision', 'vector': [0., 0.],
             'values': {'id': -9223372036854775808, 'title': 'ALPHA beta', 'active': True}, 'media': []}
        ]
    }


class CapabilityContract(unittest.TestCase):
    def test_manifest_schema_and_closed_version(self):
        Draft202012Validator.check_schema(SCHEMA)
        validator = Draft202012Validator(SCHEMA)
        validator.validate(MANIFEST)
        changes = [lambda m: m.update(schema_version=2), lambda m: m.update(unrecognized=True),
                   lambda m: m['domains'][0].update(status='production'),
                   lambda m: m['domains'][0].update(id='F02'),
                   lambda m: m['boundaries']['writer'].update(public_api=True),
                   lambda m: m['boundaries']['training'].update(query_fields=['seed', 'filter']),
                   lambda m: m['boundaries']['lance'].update(external_connector=True),
                   lambda m: m['boundaries']['workers'].update(cross_machine=True),
                   lambda m: m['boundaries']['refresh'].update(indexes='incremental')]
        for change in changes:
            invalid = deepcopy(MANIFEST)
            change(invalid)
            self.assertFalse(validator.is_valid(invalid))

    def test_twelve_domains_have_resolvable_verification_entrypoints(self):
        self.assertEqual([d['id'] for d in MANIFEST['domains']], [f'F{n:02}' for n in range(1, 13)])
        for domain in MANIFEST['domains']:
            self.assertFalse(set(domain['supports']) & set(domain['rejects']))
            for value in domain['source_paths'] + domain['verification_paths']:
                path = (ROOT/value).resolve()
                self.assertTrue(path.is_relative_to(ROOT) and path.is_file(), value)

    def test_services_remain_separate_and_operations_match_openapi(self):
        for name, service in MANIFEST['services'].items():
            spec = json.loads((ROOT/service['openapi']).read_text())
            reference = spec['x-guradb-capability-manifest']
            self.assertEqual(reference['schema_version'], MANIFEST['schema_version'])
            self.assertEqual(reference['scope'], 'source-tree')
            self.assertEqual((ROOT/service['openapi']).parent.joinpath(reference['path']).resolve(),
                             ROOT/'api/capabilities/v1.json')
            operations = {op['operationId'] for route in spec['paths'].values()
                          for op in route.values() if isinstance(op, dict) and 'operationId' in op}
            self.assertEqual(set(service['operations']), operations, name)
        self.assertEqual(MANIFEST['services']['m0-sql']['execution'], 'rust-arrow-datafusion')
        self.assertEqual(MANIFEST['services']['m1-m2-jobs']['execution'], 'python-pyarrow')
        self.assertFalse(MANIFEST['boundaries']['unified_sql_jobs'])
        self.assertFalse(MANIFEST['discovery']['reports_global_capabilities'])

    def test_scan_and_training_schemas_do_not_advertise_selection(self):
        self.assertEqual(set(API['components']['schemas']['Scan']['properties']), {'limit'})
        declared = MANIFEST['boundaries']['training']['query_fields']
        self.assertEqual(set(API['components']['schemas']['Export']['properties']), set(declared))
        self.assertTrue(validate_request('Scan', {'limit': 1000}))
        self.assertTrue(validate_request('Export', {'seed': 'a0', 'train_basis_points': 0}))
        for name in ('Scan', 'Export'):
            for invalid in ({'filter': {'field': 'active', 'equals': True}},
                            {'projection': ['id']}, {'sql': 'SELECT id FROM documents'}, {'unknown': 1}):
                self.assertFalse(validate_request(name, invalid), (name, invalid))

    def test_training_all_records_versions_values_and_split_extremes(self):
        data = bundle()
        expected_values = [
            {'id': '-9223372036854775808', 'title': 'ALPHA beta', 'active': True},
            {'id': '9223372036854775807', 'title': None, 'active': False}
        ]
        for threshold, split in ((0, 'validation'), (10000, 'train')):
            samples = samples_for(data, {'seed': 'a0', 'train_basis_points': threshold}, Budget())
            self.assertEqual([s['logical_key'] for s in samples], ['a', 'b'])
            self.assertEqual([s['record_version'] for s in samples], ['old-revision', 'new-revision'])
            self.assertEqual([json.loads(s['values_json']) for s in samples], expected_values)
            self.assertEqual([s['split'] for s in samples], [split, split])
        for invalid in ({'filter': {'field': 'active', 'equals': True}}, {'projection': ['id']},
                        {'sql': 'SELECT id FROM documents'}, {'train_basis_points': 10001}):
            with self.assertRaises(Failure):
                samples_for(data, invalid, Budget())

    def test_both_bm25_paths_and_unimplemented_query_forms(self):
        boundaries = MANIFEST['boundaries']['bm25']
        self.assertEqual(boundaries['bundle_v2'], FORMAT)
        self.assertEqual(boundaries['analyzer'], ANALYZER)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = bundle()
            data['index_path'] = str(root/'text')
            build(root/'text', data['rows'], 'title', Budget())
            for version in (1, 2):
                if version == 2:
                    data['version'] = 2
                    data['bm25'] = build_bm25(root/'bm25', data['rows'], 'title', Budget())
                result = search(data, {'text': 'alpha'}, Budget())
                self.assertEqual([r['logical_key'] for r in result['hits']], ['a'])
                self.assertEqual(result['read_context'], {'read_view_id': 'fixed-view'})
                for text in ('中文', '"alpha beta"', 'alpha*'):
                    with self.assertRaises(Failure):
                        search(data, {'text': text}, Budget())

    def test_dimensions_and_candidates_stay_within_existing_limits(self):
        limits = MANIFEST['boundaries']['limits']
        self.assertEqual((limits['m1_m2_rows'], limits['source_files']), (MAX_ROWS, MAX_FILES))
        self.assertEqual(limits['vector_dimensions'], API['components']['schemas']['Search']['properties']['vector']['maxItems'])
        self.assertEqual(limits['search_candidates'], API['components']['schemas']['Search']['properties']['candidate_limit']['maximum'])
        data = bundle()
        with self.assertRaises(Failure):
            search(data, {'vector': [0., 0.], 'model': 'test-model', 'candidate_limit': 1001}, Budget())
        for dimension, supported in ((256, True), (257, False)):
            row = {'logical_key': 'a', 'values': {'title': 'alpha'}}
            feature = {'model': 'test', 'dimension': dimension, 'metric': 'squared_l2',
                       'preprocessing': 'identity-v1', 'records': [
                           {'logical_key': 'a', 'vector': [0.]*dimension, 'media': []}]}
            if supported:
                self.assertEqual(features([row], feature, 'title')['dimension'], dimension)
            else:
                with self.assertRaises(Failure):
                    features([row], feature, 'title')

    def test_no_public_write_route_and_no_remote_worker(self):
        service = SimpleNamespace(check_lease=lambda: None, control=SimpleNamespace(principal=lambda _: 'reader'))
        for route in ('/v1/append', '/v1/refresh', '/v1/publish', '/v1/queries'):
            request = SimpleNamespace(server=SimpleNamespace(service=service), path=route,
                                      command='POST', headers={'Authorization': 'Bearer test'})
            with self.assertRaises(Failure) as caught:
                Handler.dispatch(request)
            self.assertEqual(caught.exception.code, 'not_found')
        self.assertEqual(endpoint('http://127.0.0.1:8082'), ('127.0.0.1', 8082))
        for url in ('http://192.0.2.1:8082', 'https://127.0.0.1:8082', 'http://localhost:8082'):
            with self.assertRaises(Failure) as caught:
                endpoint(url)
            self.assertEqual(caught.exception.code, 'unsupported_transport')


if __name__ == '__main__':
    unittest.main()
