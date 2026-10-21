"""Independent schema/golden checks; never compile Rust inside the 60s suite."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from jsonschema import Draft202012Validator
from modules.common.cf1a_schema import schema
from modules.common.cf1a_wire import canonical, decode

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = json.loads((ROOT/'api/cf1a/golden.json').read_text())


class Cf1aContractTests(unittest.TestCase):
    def test_schema_is_exported_and_all_golden_are_valid(self):
        machine = json.loads((ROOT/'api/cf1a/schema.json').read_text())
        self.assertEqual(machine, schema())
        Draft202012Validator.check_schema(machine)
        validator = Draft202012Validator(machine)
        for value in GOLDEN:
            with self.subTest(kind=next(iter(value['payload']))):
                validator.validate(value)
                self.assertEqual(decode(canonical(value)).document, value)

    def test_closed_structures_do_not_silently_ignore_fields(self):
        validator = Draft202012Validator(schema())
        for mutate in (lambda x: x.update(extra=True),
                       lambda x: x['payload']['read_binding']['resource'].update(extra=True),
                       lambda x: x['payload']['read_binding']['context'].pop('budget'),
                       lambda x: x['payload']['read_binding']['context'].update(schema_version=True)):
            value = deepcopy(GOLDEN[0])
            mutate(value)
            self.assertFalse(validator.is_valid(value))

    def test_full_int8_null_and_utf8_have_explicit_wire_values(self):
        rows = GOLDEN[1]['payload']['read_batch']['rows']
        self.assertEqual([row['cells'][2] for row in rows], [
            {'type': 'int8', 'value': '-9223372036854775808'},
            {'type': 'int8', 'value': '9223372036854775807'}, {'type': 'null', 'value': None}])
        self.assertIn('图文\n知识库', GOLDEN[0]['payload']['read_binding']['resource']['display_name'])
