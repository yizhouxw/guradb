"""Trusted fixture digest import; no PG/I1 authentication claim."""
import unittest

from modules.catalog.cf1a_auth import FixedInputAuthority
from modules.common.cf1a_primitives import ContractFailure, digest
from tests.catalog_support.fixed_fixture import target


class FixtureDigestTests(unittest.TestCase):
    def setUp(self):
        self.authority = FixedInputAuthority()
        self.target = target(1000)

    def test_whole_contract_digest_is_required_and_withdrawn(self):
        self.authority.allow_fixture_target_sha256(digest(self.target.value), 5000)
        with self.assertRaises(ContractFailure) as failure:
            self.authority.verify(self.target, 1000, 2000)
        self.assertEqual(failure.exception.code, 'revoked')
        self.authority.allow_fixture_target_sha256(self.target.sha256, 5000)
        self.authority.verify(self.target, 1000, 2000)
        self.authority.withdraw(self.target)
        with self.assertRaises(ContractFailure):
            self.authority.verify(self.target, 1000, 2000)

    def test_import_expiry_and_original_source_protection_both_apply(self):
        self.authority.allow_fixture_target_sha256(self.target.sha256, 500000)
        with self.assertRaises(ContractFailure) as failure:
            self.authority.verify(self.target, 1000, 400000)
        self.assertEqual(failure.exception.code, 'expired_context')
        other = FixedInputAuthority()
        other.allow_fixture_target_sha256(self.target.sha256, 1500)
        with self.assertRaises(ContractFailure) as failure:
            other.verify(self.target, 1000, 1501)
        self.assertEqual(failure.exception.code, 'expired_context')

    def test_duplicate_cannot_extend_or_replace_deadline(self):
        self.authority.allow_fixture_target_sha256(self.target.sha256, 5000)
        self.authority.allow_fixture_target_sha256(self.target.sha256, 5000)
        for expiry in (4999, 5001):
            with self.subTest(expiry=expiry), self.assertRaises(ContractFailure):
                self.authority.allow_fixture_target_sha256(self.target.sha256, expiry)
        self.authority.verify(self.target, 1000, 5000)

    def test_closed_hash_and_safe_credit_domains(self):
        for value in ('0' * 64, 'A' * 64, 'f' * 63, b'f' * 64, None):
            with self.subTest(value=value), self.assertRaises(ContractFailure):
                self.authority.allow_fixture_target_sha256(value, 5000)
        for expiry in (0, True, 1 << 53, (1 << 64) - 1):
            with self.subTest(expiry=expiry), self.assertRaises(ContractFailure):
                self.authority.allow_fixture_target_sha256(self.target.sha256, expiry)

    def test_shared_capacity_and_existing_allow_behavior(self):
        self.authority.allow(self.target)
        for index in range(255):
            self.authority.allow_fixture_target_sha256('%064x' % (index + 1), 5000)
        self.authority.allow(self.target)
        self.authority.verify(self.target, 1000, 2000)
        with self.assertRaises(ContractFailure) as failure:
            self.authority.allow_fixture_target_sha256('e' * 64, 5000)
        self.assertEqual(failure.exception.code, 'resource_limit')
        self.authority.withdraw(self.target)
        self.authority.allow_fixture_target_sha256('e' * 64, 5000)


if __name__ == '__main__':
    unittest.main()
