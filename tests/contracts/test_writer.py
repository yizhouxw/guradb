"""Managed append input contract: explicit schema and deterministic input identity."""
import unittest

from modules.common.contracts import Failure
from modules.connectors.writer import validate


class WriterContract(unittest.TestCase):
    def test_stable_identity(self):
        rows = [{'id': 1, 'title': '数据库', 'active': None}]
        self.assertEqual(validate(rows), validate(rows))

    def test_rejects_schema_change_delete_and_nonfinite_keys(self):
        for rows in ([], [{'id': True, 'title': 'a', 'active': True}],
                     [{'id': 1, 'title': 'a', 'active': True, 'delete': True}],
                     [{'id': 1, 'title': 3, 'active': True}],
                     [{'id': 1, 'title': 'a', 'active': 'true'}],
                     [{'id': 1, 'title': 'a', 'active': True}]*2):
            with self.subTest(rows=rows), self.assertRaises(Failure):
                validate(rows)
