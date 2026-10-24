"""Private bootstrap parsing and composition unit definitions, not FD runtime proof."""
from contextlib import ExitStack
import hashlib
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from modules.common.cf1a_primitives import ContractFailure
from modules.connectors import fixed_fd_entry as entry
from modules.connectors.fixed_fd_protocol import encode
from modules.connectors.fixed_fd_protocol import decode


def config_raw(**changes):
    values = dict(zip(entry.TEXT_NAMES, ('tenant-1', 'subject-1', 'delegation-1', 'fixture', 'fixture',
                      "private' password", 'p04_fixture', 'access', 'secret', '')))
    values.update(changes)
    texts = [values[name].encode('utf-8') for name in entry.TEXT_NAMES]
    total = 96 + sum(map(len, texts))
    return (struct.pack('>4sHHIHH10HQQ12s32s', b'PCF2', 2, 0, total, 5432, 8333,
                        *map(len, texts), 0, 300000, b'\0' * 12, b't' * 32) + b''.join(texts))


def bootstrap_raw(**changes):
    numbers = [256 << 20, 1000, 64 << 20, 1000, 1000, 1000, 32 << 20, 1, 32 << 20,
               65536, 8192, 16 << 20, 8 << 20, 8 << 20, 65536, 65536, 768 << 10, 256]
    for index, value in changes.items():
        numbers[int(index)] = value
    return encode('bootstrap', 2, b'\0' * 6, *numbers, b'c' * 32, b's' * 32, b'q' * 32, b'\0' * 8)


class PrivateEntryTests(unittest.TestCase):
    def test_config_closed_layout_and_secret_repr(self):
        config = entry.decode_config(config_raw())
        self.assertEqual((config.pg_port, config.s3_port), (5432, 8333))
        self.assertEqual(config.target_sha256, (b't' * 32).hex())
        self.assertNotIn('password', repr(config))
        self.assertNotIn('secret', repr(config))
        # Password is conninfo-escaped by compose, never concatenated as a DSN.
        self.assertEqual(config.values['pg_password'], "private' password")

    def test_config_rejects_flags_reserved_trailing_and_credit_overflow(self):
        for offset, replacement in ((7, b'\x04'), (52, b'x'), (44, struct.pack('>Q', 1 << 53)),
                                     (36, struct.pack('>Q', (1 << 64) - 1))):
            raw = bytearray(config_raw())
            raw[offset:offset + len(replacement)] = replacement
            with self.subTest(offset=offset), self.assertRaises(ContractFailure):
                entry.decode_config(raw)
        with self.assertRaises(ContractFailure):
            entry.decode_config(config_raw() + b'x')
        with self.assertRaises(ContractFailure):
            entry.decode_config(config_raw(tenant_id='bad\0id'))

    def test_config_invalid_utf8_and_credential_expiry_is_not_protection_expiry(self):
        raw = bytearray(config_raw())
        raw[96] = 255
        with self.assertRaises(ContractFailure):
            entry.decode_config(raw)
        raw = bytearray(config_raw())
        raw[6:8], raw[36:44] = struct.pack('>H', 2), struct.pack('>Q', 15000)
        self.assertEqual(entry.decode_config(raw).expiry_ms, 15000)

    def test_bootstrap_rejects_every_credit_outside_safeint(self):
        self.assertEqual(entry.parse_bootstrap(bootstrap_raw())['producer'], 8 << 20)
        for index in range(18):
            for number in (0, 1 << 53, (1 << 64) - 1):
                with self.subTest(index=index, number=number), self.assertRaises(ContractFailure):
                    entry.parse_bootstrap(bootstrap_raw(**{str(index): number}))
        with self.assertRaises(ContractFailure):
            entry.parse_bootstrap(bootstrap_raw(**{'13': 16 << 20}))

    def test_preload_cancel_short_unready_and_original_cutoff(self):
        cancel = SimpleNamespace(cancelled=lambda: False)
        with patch.object(entry.select, 'select', return_value=([], [], [])):
            with self.assertRaises(ContractFailure) as caught:
                entry.read_preloaded(0, 80, cancel)
            self.assertEqual(caught.exception.code, 'outcome_unknown')
        with patch.object(entry.select, 'select', return_value=([0], [], [])), \
                patch.object(entry.os, 'readv', return_value=0):
            with self.assertRaises(ContractFailure):
                entry.read_preloaded(0, 80, cancel)
        with patch.object(entry.time, 'clock_gettime_ns', return_value=100):
            with self.assertRaises(ContractFailure) as caught:
                entry.read_preloaded(0, 80, cancel, cutoff_ns=100)
            self.assertEqual(caught.exception.code, 'deadline')
        with self.assertRaises(ContractFailure) as caught:
            entry.read_preloaded(0, 80, SimpleNamespace(cancelled=lambda: True))
        self.assertEqual(caught.exception.code, 'cancelled')

    def test_fixed_source_profile_verifies_actual_leaf_and_asset_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = ('leaf.py', 'schema.json')
            for name in files:
                (root / name).write_bytes(name.encode())
            body = struct.pack('>4sHH', b'GFSP', 1, 2) + b''.join(
                hashlib.sha256((root / name).read_bytes()).digest() for name in files)
            profile = root / 'profile'
            profile.write_bytes(body)
            profile.chmod(0o600)
            with patch.object(entry, 'ROOT', root), patch.object(entry, 'PROFILE', profile), \
                    patch.object(entry, 'SOURCE_FILES', files):
                entry.verify_source_profile(hashlib.sha256(body).digest(), lambda: None)
                (root / files[1]).write_bytes(b'changed schema')
                with self.assertRaises(ContractFailure):
                    entry.verify_source_profile(hashlib.sha256(body).digest(), lambda: None)

    def test_runtime_digest_uses_actual_observation_and_lock_bytes(self):
        lock_hash = b'l' * 32
        value = {'domain': 'guradb-fd-runtime-v1', 'python': '3.12.12', 'system': 'Linux',
                 'machine': 'aarch64', 'packages': entry.PINS,
                 'locks': {name: lock_hash.hex() for name in entry.LOCKS}}
        with ExitStack() as stack:
            version = stack.enter_context(patch.object(entry.importlib.metadata, 'version',
                                          side_effect=lambda name: entry.PINS[name]))
            stack.enter_context(patch.object(entry.sys, 'version_info', (3, 12, 12)))
            stack.enter_context(patch.object(entry.platform, 'system', return_value='Linux'))
            stack.enter_context(patch.object(entry.platform, 'machine', return_value='aarch64'))
            digest = stack.enter_context(patch.object(entry, 'fixed_file_digest', return_value=lock_hash))
            self.assertEqual(entry.observe_runtime(lambda: None), hashlib.sha256(entry.canonical(value)).digest())
            self.assertEqual(version.call_count, 11)
            self.assertEqual(digest.call_count, 3)
            version.side_effect = lambda name: 'unexpected'
            with self.assertRaises(ContractFailure):
                entry.observe_runtime(lambda: None)

    def test_inherited_anchor_is_imported_once_without_safeint_ns_truncation(self):
        from modules.storage.fixed_parent import ReadParent
        raw = config_raw()
        cutoff = (1 << 54) + 1000000000
        anchor = b'GLNA\0\2\1\2' + b'b' * 16 + b's' * 16 + b'n' * 16 + struct.pack(
            '>QQQ', 1, cutoff - 2000000000, cutoff)
        bootstrap = bytearray(bootstrap_raw())
        # Bootstrap configuration length is the eighteenth u64, followed by SHA.
        bootstrap[144:152] = struct.pack('>Q', len(raw))
        bootstrap[152:184] = hashlib.sha256(raw).digest()
        parent = SimpleNamespace(checkpoint=lambda: 10.0, wall_ms=lambda: 1000,
                                 linux_origin=SimpleNamespace(session=b's' * 16, generation=1))
        cancel = SimpleNamespace(cancelled=lambda: False)
        with ExitStack() as stack:
            stack.enter_context(patch('modules.connectors.fixed_fd_protocol.Cancellation', return_value=cancel))
            transport = stack.enter_context(patch('modules.connectors.fixed_fd_protocol.Transport'))
            imported = stack.enter_context(patch.object(ReadParent, 'from_linux_anchor', return_value=parent))
            preload = stack.enter_context(patch.object(entry, 'read_preloaded', side_effect=[anchor, bootstrap, raw]))
            stack.enter_context(patch.object(entry.os, 'set_blocking'))
            stack.enter_context(patch.object(entry.os, 'read', return_value=b''))
            stack.enter_context(patch.object(entry.select, 'select', return_value=([0], [], [])))
            stack.enter_context(patch.object(entry.time, 'clock_gettime_ns', return_value=cutoff - 1000000000))
            stack.enter_context(patch.object(entry, 'verify_source_profile'))
            observed = entry.load_inherited()
        imported.assert_called_once()
        token, _, cancelled = imported.call_args.args
        self.assertEqual(token._raw, anchor)
        self.assertIs(cancelled, cancel.cancelled)
        self.assertIs(observed[0], parent)
        self.assertEqual(preload.call_args_list[2].kwargs['cutoff_ns'], cutoff)
        self.assertEqual(transport.call_args.kwargs['bootstrap_wire_bytes'], 336 + len(raw))

    def test_compose_uses_nonadmin_principal_same_control_and_no_pg_probe(self):
        parent = SimpleNamespace(checkpoint=lambda: 10.0, monotonic=lambda: 1.0,
                                 linux_origin=SimpleNamespace(session=b's' * 16, generation=1))
        config = entry.decode_config(config_raw())
        with patch('modules.catalog.cf1a_catalog.FixedCatalog.initialize') as initialize, \
                patch('modules.catalog.cf1a_catalog.FixedCatalog.provision') as provision, \
                patch('modules.connectors.fixed_fd_worker.FixedFdWorker') as worker:
            result = entry.compose(parent, object(), entry.parse_bootstrap(bootstrap_raw()), config)
            reads = worker.call_args.args[1]
            principal, control = reads._principal, reads.control
            self.assertFalse(principal.administrator or principal.cleanup)
            self.assertIs(control.checkpoint, parent.checkpoint)
            initialize.assert_not_called()
            provision.assert_not_called()
            self.assertIs(result, worker.return_value)
            dsn, authority = reads._bindings.store.dsn, reads._bindings.store.protection
            from psycopg.conninfo import conninfo_to_dict
            self.assertEqual(conninfo_to_dict(dsn)['password'], config.values['pg_password'])
            self.assertEqual(conninfo_to_dict(dsn)['hostaddr'], '127.0.0.1')
            self.assertEqual(authority._fixture_sha256, {config.target_sha256: config.protection_ms})

    def test_main_emits_one_measured_hello_and_returns_only_actual_serve_result(self):
        from unittest.mock import Mock
        parent, transport, worker = Mock(), Mock(), Mock()
        worker.serve.return_value = 0
        loaded = (parent, transport, {}, object(), b'a' * 32, object())
        with patch.object(entry.sys, 'argv', ['worker']), \
                patch.object(entry, 'load_inherited', return_value=loaded), \
                patch.object(entry, 'observe_runtime', return_value=b'r' * 32), \
                patch.object(entry, 'compose', return_value=worker), \
                patch('modules.storage.fixed_anchor.current_boot', return_value=b'b' * 16), \
                patch('modules.storage.fixed_anchor.current_ns', return_value=(1 << 54)), \
                patch.object(entry.os, 'getpid', return_value=123):
            self.assertEqual(entry.main(), 0)
        transport.send.assert_called_once()
        message, sequence, ordinal, body, wire, extra = transport.send.call_args.args
        self.assertEqual((message, sequence, ordinal, wire, extra), (11, 0, 0, 176, 176))
        self.assertEqual(decode('hello', body), (b'a' * 32, b'r' * 32, b'b' * 16, 123, 1 << 54))
        worker.serve.assert_called_once_with()
        with patch.object(entry.sys, 'argv', ['worker', '--role=admin']), \
                patch.object(entry, 'load_inherited') as load:
            with self.assertRaises(ContractFailure):
                entry.main()
            load.assert_not_called()


if __name__ == '__main__':
    unittest.main()
