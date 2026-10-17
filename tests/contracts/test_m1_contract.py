"""M1 public schema validation; real behavior is covered by the M1 live driver."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator
from openapi_spec_validator import validate
from modules.common.contracts import Failure, key

ROOT=Path(__file__).resolve().parents[2]
API=json.loads((ROOT/'api/http/m1-openapi.json').read_text())


def validator(name):
    return Draft202012Validator(dict(API,**{'$ref':'#/components/schemas/'+name}))


class M1ContractTests(unittest.TestCase):
    def test_identity_vectors_match_the_frozen_rust_contract(self):
        self.assertEqual(key('ab','string'),'010000000101000000026162')
        self.assertEqual(key(1,'long'),'010000000102000000080000000000000001')
        self.assertEqual(key(-1,'long'),'01000000010200000008ffffffffffffffff')
        self.assertNotEqual(key('1','string'),key(1,'long'))
        self.assertNotEqual(key('é','string'),key('e\u0301','string'))
        for invalid in (None,True,1<<63):
            with self.assertRaises(Failure):key(invalid,'long')

    def test_standard(self):
        validate(API)

    def test_query_subset_and_negative_bounds(self):
        valid={'dataset_id':'89b349e2-cc73-4c22-871d-c80a159d7789','query':{'text':'alpha'}}
        validator('SearchRequest').validate(valid)
        for query in ({},{'text':'*'},{'vector':[0,1]},{'text':'alpha','candidate_limit':1001},
                      {'text':'alpha','top_k':0},{'text':'alpha','unknown':1}):
            self.assertFalse(validator('SearchRequest').is_valid(dict(valid,query=query)))
        self.assertFalse(validator('SearchRequest').is_valid(dict(valid,tenant_id='other')))
        self.assertFalse(validator('SearchRequest').is_valid(dict(valid,read_view_id=None)))
