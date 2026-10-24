"""Private real-chain pin cleanup; never proves worker exit or credit release."""
import argparse
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import time

PRIVATE = Path('/evidence/private')
P04 = Path('/p04')
CODES = {'invalid_contract', 'resource_limit', 'deadline', 'unauthorized',
         'conflict', 'backend_unavailable', 'outcome_unknown', 'revoked'}
PHASES = ('connect_attempt', 'connect_success', 'connect_failure', 'wait',
          'sql_attempt', 'sql_success', 'sql_failure', 'commit_attempt',
          'commit_success', 'commit_failure', 'closed')
SAFE = (1 << 53) - 1


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


def require(value):
    if not value:
        raise ValueError('private cleanup contract')


def project_invoice(invoice):
    """Integer-only observation; absent control is unknown, never eleven zeroes."""
    if invoice is None:
        return None
    require(type(invoice) is dict and type(invoice.get('counts')) is dict)
    seconds = invoice.get('seconds', {})
    require(type(seconds) is dict and set(invoice['counts']) <= set(PHASES)
            and set(seconds) <= set(PHASES)
            and invoice.get('pg_native_memory_bytes') is None)
    counts, phase_us = [], []
    for phase in PHASES:
        count, elapsed = invoice['counts'].get(phase, 0), seconds.get(phase, 0)
        require(type(count) is int and 0 <= count <= SAFE
                and type(elapsed) in (int, float) and math.isfinite(elapsed) and elapsed >= 0)
        # Bound the observed binary float itself; multiplication may round just
        # above an integer microsecond down to that integer before math.ceil.
        numerator, denominator = elapsed.as_integer_ratio() if type(elapsed) is float else (elapsed, 1)
        micros = (numerator * 1_000_000 + denominator - 1) // denominator
        require(0 <= micros <= SAFE)
        counts.append(count)
        phase_us.append(micros)
    return {'version': 1, 'counts': counts, 'phase_us': phase_us, 'native_memory_bytes': None}


class Cutoff:
    """Caller supplies the original cleanup cutoff, never a fresh duration."""
    def __init__(self, raw):
        require(type(raw) is int and 0 < raw < 1 << 64)
        now = time.clock_gettime_ns(time.CLOCK_MONOTONIC)
        require(now < raw <= now + 5_000_000_000)
        self.ns = raw

    def checkpoint(self):
        if time.clock_gettime_ns(time.CLOCK_MONOTONIC) >= self.ns:
            raise TimeoutError('cleanup deadline')
        return self.ns / 1_000_000_000


def bounded_private(path, cap, cutoff):
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts and path.is_relative_to(PRIVATE))
    cutoff.checkpoint()
    require(path.resolve(strict=True).is_relative_to(PRIVATE.resolve(strict=True)))
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
    fd = os.open(path, flags)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= cap)
        raw = bytearray(before.st_size)
        view = memoryview(raw)
        while view:
            cutoff.checkpoint()
            count = os.readv(fd, [view])
            require(count > 0)
            view = view[count:]
        require(os.read(fd, 1) == b'' and os.fstat(fd).st_size == before.st_size)
        cutoff.checkpoint()
        return raw
    finally:
        os.close(fd)


def sha(value):
    return type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None and value != '0' * 64


def readback_identity(row, stored_request, binding, original_request, expected_binding_sha):
    """Compare the durable row with the exact canonical binding, not ID shapes alone."""
    from modules.common.cf1a_primitives import validate_shape
    require(stored_request.encoded == original_request.encoded
            and stored_request.sha256 == original_request.sha256)
    require(sha(expected_binding_sha) and binding.sha256 == expected_binding_sha
            and row['binding_sha256'] == expected_binding_sha and row['released'] is True)
    pin = binding.value['context']['pin']
    validate_shape(row['pin_id'], 'id')
    validate_shape(row['lease_id'], 'id')
    require((row['pin_id'], row['lease_id']) == (pin['pin_id'], pin['lease_id']))
    return row['pin_id'], row['lease_id']


def cleanup(request_path, config_path, absolute_cutoff_ns, expected_binding_sha, observed):
    cutoff = Cutoff(absolute_cutoff_ns)
    require(expected_binding_sha is None or sha(expected_binding_sha))
    request_raw = bounded_private(request_path, 65536, cutoff)
    config_raw = bounded_private(config_path, 4096, cutoff)
    # This process runs only beside the fixed, read-only P04 source mount.
    from modules.connectors.fixed_fd_entry import decode_config
    from modules.common.cf1a_wire import Contract
    from modules.catalog.cf1a_auth import FixedInputAuthority, TrustedPrincipal
    from modules.catalog.cf1a_catalog import FixedCatalog
    from modules.catalog.cf1a_control import CatalogReadControl
    from psycopg.conninfo import make_conninfo

    config = decode_config(config_raw)
    request = Contract(bytes(request_raw))
    require(request.kind == 'bind_request' and request.encoded == request_raw)
    value, fields = request.value, config.values
    principal = TrustedPrincipal(fields['tenant_id'], fields['subject_id'], fields['delegation_ref'])
    require((value['tenant_id'], value['subject_id'], value['delegation_ref']) ==
            (principal.tenant_id, principal.subject_id, principal.delegation_ref))
    authority = FixedInputAuthority()
    authority.allow_fixture_target_sha256(config.target_sha256, config.protection_ms)
    dsn = make_conninfo(host='127.0.0.1', hostaddr='127.0.0.1', port=str(config.pg_port),
        dbname=fields['pg_dbname'], user=fields['pg_user'], password=fields['pg_password'],
        sslmode='disable', application_name='gura-fixed-fd-cleanup')
    # CatalogStore performs the sole normalization; feeding it normalized
    # internal-only options would violate the original external DSN whitelist.
    catalog = FixedCatalog(dsn, authority)
    original_control = CatalogReadControl(cutoff.checkpoint, time.monotonic)
    control = CatalogReadControl(cutoff.checkpoint, time.monotonic)
    reads = catalog.controlled_reads(principal, original_control)
    complete = False
    try:
        cutoff.checkpoint()
        result = reads.close_bind_request(request, control)
        require(result.state == 'released' and result.request_sha256 == request.sha256
                and sha(result.binding_sha256))
        require(expected_binding_sha is None or result.binding_sha256 == expected_binding_sha)
        # Separate durable readback, same original cutoff and controlled PG adapter.
        with catalog.store.transaction(cutoff.checkpoint(), control) as connection:
            dataset = catalog.store.dataset(connection, value['tenant_id'], value['dataset_id'])
            row, stored_request, binding = catalog.bindings.stored(connection, dataset['dataset'], value['query_id'])
            pin, lease = readback_identity(row, stored_request, binding, request, result.binding_sha256)
        cutoff.checkpoint()
        complete = True
        return {'version': 1, 'state': 'released', 'request_sha256': request.sha256,
                'binding_sha256': result.binding_sha256, 'pin_id': pin, 'lease_id': lease,
                'scope': 'pin-cleanup-only'}
    finally:
        observed.update(pg=control.invoice, complete=complete)


class Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's default error text can reproduce an unexpected secret argv.
        raise ValueError('private cleanup arguments')


def main(arguments=None):
    observed = {}
    try:
        parser = Parser(add_help=False)
        for name in ('request', 'config', 'cutoff-ns'):
            parser.add_argument('--' + name, required=True)
        parser.add_argument('--expected-binding-sha')
        args = parser.parse_args(arguments)
        require(args.cutoff_ns.isascii() and args.cutoff_ns.isdecimal() and len(args.cutoff_ns) <= 20)
        sys.path.insert(0, str(P04))
        result = cleanup(args.request, args.config, int(args.cutoff_ns), args.expected_binding_sha, observed)
        code = 0
    except BaseException as error:
        candidate = getattr(error, 'code', None)
        code_name = candidate if type(candidate) is str and candidate in CODES else (
            'deadline' if isinstance(error, TimeoutError) else 'outcome_unknown')
        result = {'version': 1, 'state': 'cleanup_unconfirmed', 'code': code_name,
                  'error_type': type(error).__name__, 'scope': 'pin-cleanup-only'}
        code = 1
    try:
        invoice = project_invoice(observed.get('pg'))
        if code == 0:
            require(invoice is not None and observed.get('complete') is True)
    except BaseException as error:
        # Preserve an earlier cleanup failure; an invalid invoice cannot confirm release.
        if code == 0:
            result = {'version': 1, 'state': 'cleanup_unconfirmed', 'code': 'invalid_contract',
                      'error_type': type(error).__name__, 'scope': 'pin-cleanup-only'}
        invoice, code = None, 1
        observed['complete'] = False
    result['cleanup_pg'] = invoice
    result['cleanup_pg_complete'] = observed.get('complete', False)
    raw = canonical(result)
    if len(raw) > 4096:
        raw = canonical({'version': 1, 'state': 'cleanup_unconfirmed', 'code': 'resource_limit',
                         'error_type': 'ReportTooLarge', 'scope': 'pin-cleanup-only',
                         'cleanup_pg': None, 'cleanup_pg_complete': False})
        code = 1
    sys.stdout.buffer.write(raw + b'\n')
    return code


if __name__ == '__main__':
    raise SystemExit(main())
