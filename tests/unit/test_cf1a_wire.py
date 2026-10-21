"""CF1-A primitive encoding, rejection corpus and immutable values."""
from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import unittest
from modules.common.cf1a_schema import CAPABILITIES
from modules.common.cf1a_wire import Contract, ContractFailure, canonical, decode, digest, validate_shape
from modules.common.cf1a_read import without

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = json.loads((ROOT/'api/cf1a/golden.json').read_text())


def contract(index, change=None, rehash=True):
    document = deepcopy(GOLDEN[index])
    value = next(iter(document['payload'].values()))
    if change:
        change(value)
    if rehash:
        if index in (0,11):
            value['revision']['content_sha256'] = digest(without(value['revision'], 'content_sha256'))
            value['view']['descriptor_sha256'] = digest(without(value['view'], 'descriptor_sha256'))
        elif index == 1:
            value['content_sha256'] = digest(without(value, 'content_sha256'))
    return decode(canonical(document))


class Cf1aWireTests(unittest.TestCase):
    def test_values_are_canonical_and_immutable(self):
        value = contract(0)
        self.assertEqual(value.kind, 'read_binding')
        self.assertEqual(value.document, GOLDEN[0])
        self.assertEqual(len(value.sha256), 64)
        value.value['resource']['dataset_id'] = 'different'
        self.assertEqual(value.value['resource']['dataset_id'], 'dataset-1')
        with self.assertRaises(FrozenInstanceError):
            value.encoded = b'{}'
        with self.assertRaises(ContractFailure):
            Contract(b'{}')

    def test_shared_rejection_corpus(self):
        for case in json.loads((ROOT/'api/cf1a/rejections.json').read_text()):
            with self.subTest(case=case['name']), self.assertRaises(ContractFailure):
                decode(case['raw'])

    def test_primitive_type_rejections(self):
        cases = [(False, 'n'), (-1, 'n'), (1 << 53, 'n'), (0, 'positive'), (1.0, 'n'),
                 ('false', 'bool'), (None, 'text'), ('x'*4097, 'text'), ('latest', 'id'),
                 ('bad/id', 'id'), ('A'*64, 'hash'), ({}, 'ReadBinding'), ([], ['id', 1, 2]),
                 (['a']*3, ['id', 1, 2]), ('unknown', ('read',)), ('x', 'unknown'),
                 ({'type':'other','value':0}, 'cell'), ({'type':'null','value':0}, 'cell'),
                 ({'type':'text','value':0}, 'cell'), ({'type':'bool','value':0}, 'cell'),
                 ({'type':'int8','value':None}, 'cell'), ({'type':'null'}, 'cell')]
        for value, spec in cases:
            with self.subTest(value=value, spec=spec), self.assertRaises(ContractFailure):
                validate_shape(value, spec)
        for item in ('+1', '01', '-0', '', '9223372036854775808', '-9223372036854775809', '1.0', True, 1):
            with self.subTest(int8=item), self.assertRaises(ContractFailure):
                validate_shape({'type':'int8','value':item}, 'cell')

    def test_invalid_json_and_capability_negotiation(self):
        for raw in ('{', '[', 'null', 'NaN', 'Infinity', b'\xff', '"\\ud800"', '['*2000, ' '*((1<<20)+1)):
            with self.subTest(raw=str(raw)[:20]), self.assertRaises(ContractFailure):
                decode(raw)
        for field, value in [('contract_version','cf1a/2.0'), ('required_capabilities',[]),
                             ('required_capabilities',['new_required']), ('required_capabilities',[True]),
                             ('required_capabilities',list(CAPABILITIES)*2), ('payload',{}),
                             ('payload',{'other':{}}), ('payload',{'read_batch':{},'reader_config':{}})]:
            document = deepcopy(GOLDEN[0]); document[field] = value
            with self.subTest(field=field,value=value), self.assertRaises(ContractFailure):
                decode(canonical(document))
        document = deepcopy(GOLDEN[0]); document['payload']['read_binding']['resource']['display_name'] = '\ud800'
        with self.assertRaises(ContractFailure):
            decode(json.dumps(document))
        validate_shape({'type':'text','value':'中文'}, 'cell')
        validate_shape({'type':'bool','value':False}, 'cell')

    def test_utf8_limits_count_input_bytes_and_counter_negative_zero(self):
        document=deepcopy(GOLDEN[0])
        document['payload']['read_binding']['resource']['display_name']='中'*4096
        raw=json.dumps(document,ensure_ascii=False)
        # JSON whitespace counts toward input budget independently of canonical size.
        excess=' '*((1<<20)-len(raw.encode())+1)+raw
        for value in (excess,excess.encode()):
            with self.assertRaises(ContractFailure):decode(value)
        self.assertEqual(decode(raw).value['resource']['display_name'],'中'*4096)
        for raw_encoding in (b'\xef\xbb\xbf'+canonical(GOLDEN[0]), json.dumps(GOLDEN[0]).encode('utf-16'), json.dumps(GOLDEN[0]).encode('utf-32')):
            with self.assertRaises(ContractFailure):decode(raw_encoding)
        nested = '0'
        for _ in range(65):nested = '['+nested+']'
        with self.assertRaises(ContractFailure):decode(nested)
        raw=canonical(GOLDEN[2]).decode().replace('"expected_generation":0','"expected_generation":-0')
        with self.assertRaises(ContractFailure):decode(raw)
