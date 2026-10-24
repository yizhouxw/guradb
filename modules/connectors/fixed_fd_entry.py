"""Private inherited-FD worker entry. No public CLI, endpoint or role arguments.

Rust must prepay startup and prefill fd0 before spawn, then shutdown its write
side. fd1 is the protocol socket; fd2 is read-only cancellation. Never print or
emit a traceback on these descriptors. Root/Rust alone proves exit/reap and
the actual query binary identity. This is not a W/native memory certificate.
"""
from dataclasses import dataclass, field
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import select
import stat
import struct
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
PROFILE = Path('/run/gura-worker-profile/sha256.bin')
PINS = {'pyarrow': '22.0.0', 'boto3': '1.40.56', 'botocore': '1.40.76',
        'jmespath': '1.1.0', 's3transfer': '0.14.0', 'python-dateutil': '2.9.0.post0',
        'urllib3': '2.8.0', 'six': '1.17.0', 'psycopg': '3.2.10',
        'psycopg-binary': '3.2.10', 'typing-extensions': '4.16.0'}
LOCKS = ('requirements-dev.lock', 'requirements-m0.lock', 'requirements-m1.lock')
# Binary source profile: GFSP,u16 version1,u16 count, then32-byte SHA values
# in this exact order. Paths are not supplied by a caller; manifest never hashes
# itself. Includes the static local import closure, footer/compact/HTTP and
# catalog schema assets. Locked third-party/runtime identity is separate.
# The entry code's digest is an ordinary leaf, not recursive self-hash.
SOURCE_FILES = (
    'modules/connectors/fixed_fd_entry.py', 'modules/connectors/fixed_fd_protocol.py',
    'modules/connectors/fixed_fd_worker.py', 'modules/connectors/fixed_producer.py',
    'modules/connectors/fixed_producer_credits.py', 'modules/connectors/fixed_producer_observation.py',
    'modules/connectors/fixed_source_reader.py', 'modules/connectors/fixed_source_scope.py',
    'modules/connectors/fixed_source_inputs.py', 'modules/connectors/fixed_source_manifest.py',
    'modules/connectors/fixed_source_located.py', 'modules/connectors/fixed_parquet_pages.py',
    'modules/connectors/fixed_parquet_plan.py', 'modules/storage/fixed_parent.py',
    'modules/storage/fixed_anchor.py', 'modules/storage/fixed_scope.py',
    'modules/storage/fixed_objects.py', 'modules/storage/fixed_signing.py',
    'modules/storage/fixed_transport.py', 'modules/storage/fixed_cache.py',
    'modules/storage/fixed_proofs.py', 'modules/catalog/cf1a_auth.py',
    'modules/catalog/cf1a_catalog.py', 'modules/catalog/cf1a_binding.py',
    'modules/catalog/cf1a_controlled.py', 'modules/catalog/cf1a_control.py',
    'modules/catalog/cf1a_pg.py', 'modules/catalog/cf1a_store.py',
    'modules/catalog/cf1a_access.py', 'modules/catalog/cf1a_codec.py',
    'modules/common/cf1a_primitives.py', 'modules/common/cf1a_schema.py',
    'modules/common/cf1a_wire.py', 'modules/common/cf1a_read.py',
    'modules/common/cf1a_publication.py', 'modules/common/cf1a_ports.py',
    'modules/common/contracts.py', 'modules/connectors/fixed_compact.py',
    'modules/storage/fixed_http.py', 'modules/catalog/cf1a_admin.py',
    'modules/catalog/cf1a_mutation.py', 'modules/catalog/cf1a_schema.sql',
    'api/cf1a/schema.json',
)
TEXT_NAMES = ('tenant_id', 'subject_id', 'delegation_ref', 'pg_dbname', 'pg_user',
              'pg_password', 'backend_id', 's3_access_key', 's3_secret_key', 's3_session_token')
TEXT_CAPS = (128, 128, 128, 128, 128, 1024, 128, 1024, 1024, 4096)
BUDGET_NAMES = ('memory_bytes', 'object_requests', 'object_bytes', 'candidates', 'top_k',
                'graph_edges', 'output_bytes', 'concurrency', 'temp_bytes')
SAFE = (1 << 53) - 1


def check(value, reason, code='invalid_contract'):
    # Imports happen inside the guarded entry path; no sensitive config repr.
    from modules.common.cf1a_primitives import require
    require(value, reason, code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


@dataclass(frozen=True)
class PrivateConfig:
    values: dict = field(repr=False)
    pg_port: int
    s3_port: int
    expiry_ms: int
    protection_ms: int
    target_sha256: str


def decode_config(raw):
    check(96 <= len(raw) <= 4096, 'config byte cap', 'resource_limit')
    magic, version, flags, total, pg, s3 = struct.unpack('>4sHHIHH', raw[:16])
    lengths = struct.unpack('>10H', raw[16:36])
    expiry, protection = struct.unpack('>QQ', raw[36:52])
    check((magic, version) == (b'PCF2', 2) and flags & ~3 == 0 and raw[52:64] == b'\0' * 12,
          'config layout/flags/reserved')
    check(total == len(raw) == 96 + sum(lengths) and 0 < pg < 65536 and 0 < s3 < 65536,
          'config lengths or ports')
    check(0 < protection <= SAFE and 0 <= expiry <= SAFE and bool(flags & 2) == (expiry != 0),
          'config protection/expiry')
    check(any(raw[64:96]), 'config missing approved target digest')
    values, offset = {}, 96
    for name, length, cap in zip(TEXT_NAMES, lengths, TEXT_CAPS):
        check(length <= cap, 'config text byte cap', 'resource_limit')
        try:
            text = raw[offset:offset + length].decode('utf-8')
        except UnicodeError:
            check(False, 'config UTF8')
        check('\0' not in text, 'config NUL')
        values[name] = text
        offset += length
    from modules.common.cf1a_primitives import validate_shape
    for name in TEXT_NAMES[:3]:
        validate_shape(values[name], 'id')
    for name in ('pg_dbname', 'pg_user'):
        check(values[name] and all(32 <= ord(char) < 127 for char in values[name]), 'config PG identifier')
    check(values['backend_id'] and all(char.isascii() and (char.isalnum() or char in '_-')
                                      for char in values['backend_id']), 'config backend ID')
    check(bool(flags & 1) == bool(values['s3_session_token']), 'config token flag')
    from modules.storage.fixed_signing import CredentialSnapshot
    CredentialSnapshot(values['s3_access_key'], values['s3_secret_key'],
                       values['s3_session_token'] or None, expiry or None).frozen(0)
    return PrivateConfig(values, pg, s3, expiry, protection, bytes(raw[64:96]).hex())


def parse_bootstrap(raw):
    from modules.connectors.fixed_fd_protocol import decode
    values = decode('bootstrap', raw)
    check(values[0] == 2 and values[1] == b'\0' * 6 and values[23] == b'\0' * 8, 'bootstrap version/reserved')
    check(all(type(x) is int and 0 < x <= SAFE for x in values[2:20]), 'bootstrap credit/budget domain')
    check(values[15:19] == (8 << 20, 65536, 65536, 768 << 10), 'bootstrap finite wire profile')
    check(values[14] <= 8 << 20 and values[12] >= 2208 and values[19] <= 4096,
          'bootstrap source/control/config cap', 'resource_limit')
    check(all(any(x) for x in values[20:23]), 'bootstrap required hashes')
    return {'budget': dict(zip(BUDGET_NAMES, values[2:11])), 'metadata': values[11],
            'control': values[12], 'arena': values[13], 'producer': values[14],
            'config_length': values[19], 'config_sha': values[20], 'source_sha': values[21],
            'query_binary_sha': values[22]}


def read_preloaded(fd, size, cancellation, *, cutoff_ns=None):
    check(fd == 0 and type(size) is int and 0 < size <= 4096, 'fixed inherited config read')
    buffer = bytearray(size)
    view = memoryview(buffer)
    while view:
        check(not cancellation.cancelled(), 'startup cancelled', 'cancelled')
        if cutoff_ns is not None:
            check(time.clock_gettime_ns(time.CLOCK_MONOTONIC) < cutoff_ns, 'startup deadline', 'deadline')
        readable, _, _ = select.select([fd], [], [], 0)
        check(fd in readable, 'launcher must prefill config before spawn', 'outcome_unknown')
        try:
            received = os.readv(fd, [view])
        except BlockingIOError:
            check(False, 'config preload changed', 'outcome_unknown')
        check(received > 0, 'config short/EOF', 'outcome_unknown')
        view = view[received:]
    return buffer


def fixed_file_digest(path, cap):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        check(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= cap, 'profile/lock/source file shape')
        value = hashlib.sha256()
        total = 0
        while True:
            raw = os.read(fd, 4096)
            if not raw:
                break
            total += len(raw)
            check(total <= cap, 'profile/lock/source grew')
            value.update(raw)
        after = os.fstat(fd)
        check(total == before.st_size == after.st_size and before.st_mtime_ns == after.st_mtime_ns,
              'profile/lock/source changed')
        return value.digest()
    finally:
        os.close(fd)


def verify_source_profile(expected, checkpoint):
    # Sole readonly path and fixed binary list; no caller-selected files.
    cap = 8 + 32 * len(SOURCE_FILES)
    fd = os.open(PROFILE, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        check(stat.S_ISREG(info.st_mode) and info.st_size == cap and not info.st_mode & 0o077,
              'source profile file shape')
        raw = bytearray(cap)
        view = memoryview(raw)
        while view:
            checkpoint()
            count = os.readv(fd, [view])
            check(count > 0, 'source profile short read')
            view = view[count:]
        check(os.read(fd, 1) == b'', 'source profile extra bytes')
        after = os.fstat(fd)
        check(info.st_size == after.st_size and info.st_mtime_ns == after.st_mtime_ns, 'source profile changed')
    finally:
        os.close(fd)
    check(raw[:8] == struct.pack('>4sHH', b'GFSP', 1, len(SOURCE_FILES))
          and hashlib.sha256(raw).digest() == expected, 'source profile identity')
    for number, name in enumerate(SOURCE_FILES):
        checkpoint()
        check(fixed_file_digest(ROOT / name, 131072) == raw[8 + 32 * number:40 + 32 * number],
              'worker Source digest differs')


def observe_runtime(checkpoint):
    actual = {name: importlib.metadata.version(name) for name in PINS}
    version = '.'.join(str(x) for x in sys.version_info[:3])
    check(actual == PINS and version == '3.12.12' and platform.system() == 'Linux'
          and platform.machine() == 'aarch64', 'actual runtime differs from fixed profile')
    locks = {}
    for name in LOCKS:
        checkpoint()
        locks[name] = fixed_file_digest(ROOT / name, 65536).hex()
    value = {'domain': 'guradb-fd-runtime-v1', 'python': version, 'system': platform.system(),
             'machine': platform.machine(), 'packages': actual, 'locks': locks}
    checkpoint()
    return hashlib.sha256(canonical(value)).digest()


def load_inherited():
    from modules.connectors.fixed_fd_protocol import Cancellation, Credit, Transport
    from modules.storage.fixed_anchor import TrustedLinuxAnchor
    from modules.storage.fixed_parent import ReadParent
    cancellation = Cancellation(2)
    os.set_blocking(0, False)
    raw_anchor = read_preloaded(0, 80, cancellation)
    check(raw_anchor[:8] == b'GLNA\x00\x02\x01\x02', 'anchor version')
    generation, _, cutoff = struct.unpack('>QQQ', raw_anchor[56:80])
    bootstrap = parse_bootstrap(read_preloaded(0, 256, cancellation, cutoff_ns=cutoff))
    token = TrustedLinuxAnchor(bytes(raw_anchor), session=bytes(raw_anchor[24:40]),
                               nonce=bytes(raw_anchor[40:56]), generation=generation)
    parent = ReadParent.from_linux_anchor(token, bootstrap['budget'], cancellation.cancelled)
    origin = parent.linux_origin
    metadata = Credit(bootstrap['metadata'], origin.session, origin.generation)
    # Root prepaid fixed80/256 before spawn. Mirror the known buffers and bound
    # further config/profile/runtime allocation before materialization.
    metadata.reserve(80 + 256 + bootstrap['config_length'] + 8 + 32 * len(SOURCE_FILES) + 4096)
    raw_config = read_preloaded(0, bootstrap['config_length'], cancellation, cutoff_ns=cutoff)
    parent.checkpoint()
    check(hashlib.sha256(raw_config).digest() == bootstrap['config_sha'], 'config hash differs')
    check(select.select([0], [], [], 0)[0] == [0] and os.read(0, 1) == b'',
          'launcher config must end at fixed length')
    config = decode_config(raw_config)
    wall_cutoff = parent.wall_ms() + max(0, (cutoff - time.clock_gettime_ns(time.CLOCK_MONOTONIC) + 999999) // 1000000)
    check(config.protection_ms >= wall_cutoff and (not config.expiry_ms or config.expiry_ms >= wall_cutoff),
          'trusted protection/credential ends before original query', 'expired_context')
    verify_source_profile(bootstrap['source_sha'], parent.checkpoint)
    io = Transport(1, 2, parent, Credit(bootstrap['control'], origin.session, origin.generation),
                   bootstrap_wire_bytes=336 + len(raw_config))
    return parent, io, bootstrap, config, hashlib.sha256(raw_anchor).digest(), metadata


def compose(parent, io, bootstrap, config):
    from psycopg.conninfo import make_conninfo
    from modules.catalog.cf1a_auth import FixedInputAuthority, TrustedPrincipal
    from modules.catalog.cf1a_catalog import FixedCatalog
    from modules.catalog.cf1a_control import CatalogReadControl
    from modules.connectors.fixed_fd_protocol import Credit
    from modules.connectors.fixed_fd_worker import FixedFdWorker
    from modules.storage.fixed_signing import CredentialSnapshot, FixedBackend
    values = config.values
    authority = FixedInputAuthority()
    authority.allow_fixture_target_sha256(config.target_sha256, config.protection_ms)
    principal = TrustedPrincipal(values['tenant_id'], values['subject_id'], values['delegation_ref'])
    dsn = make_conninfo(host='127.0.0.1', hostaddr='127.0.0.1', port=str(config.pg_port),
                        dbname=values['pg_dbname'], user=values['pg_user'], password=values['pg_password'],
                        sslmode='disable', application_name='gura-fixed-fd')
    # CatalogStore applies its existing normalized_dsn exactly once; feeding its
    # added internal options through that public-input validator again fails.
    catalog = FixedCatalog(dsn, authority)  # No initialize/provision/probe or extra PG query.
    control = CatalogReadControl(parent.checkpoint, parent.monotonic)
    reads = catalog.controlled_reads(principal, control)
    credentials = CredentialSnapshot(values['s3_access_key'], values['s3_secret_key'],
                                     values['s3_session_token'] or None, config.expiry_ms or None)
    backend = FixedBackend(values['backend_id'], 'm0-data', 'http://127.0.0.1:' + str(config.s3_port),
                           credentials, True)
    origin = parent.linux_origin
    arena = Credit(bootstrap['arena'], origin.session, origin.generation)
    worker = FixedFdWorker(io, reads, {backend.backend_id: backend}, arena,
                           request_decode_credit=2 * (256 * 57 + 4 * 1628 + 65536),
                           producer_credit=bootstrap['producer'])
    parent.checkpoint()
    return worker


def main():
    from modules.connectors.fixed_fd_protocol import encode, TYPES
    from modules.storage.fixed_anchor import current_boot, current_ns
    check(len(sys.argv) == 1, 'private worker takes no arguments')
    parent, io, bootstrap, config, anchor_sha, metadata = load_inherited()
    runtime_sha = observe_runtime(parent.checkpoint)
    worker = compose(parent, io, bootstrap, config)
    parent.checkpoint()
    hello = encode('hello', anchor_sha, runtime_sha, current_boot(), os.getpid(), current_ns())
    # Exactly one implicit176wire+176extra startup grant, prepaid by original
    # Rust Owner before spawn. control credit is separately a memory subgrant.
    io.send(TYPES['HELLO'], 0, 0, hello, 176, 176)
    return worker.serve()  # No native/reap/pin refund claim; process actually exits below.


if __name__ == '__main__':
    try:
        exit_code = main()
    except BaseException:
        exit_code = 1
    raise SystemExit(exit_code)
