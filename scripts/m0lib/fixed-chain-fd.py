"""Thin host assembly using the existing OwnedLab, never another Lab/relay.

Artifact prototype, not run. Root copies this and the client to scripts/m0lib
only after docs-first/plan/review. A170s outer observation watchdog is PROPOSED,
not implemented/certified here (90 setup/run +60 cleanup +20 outer margin).
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time

IMAGE = 'sha256:b12433266fb4c63839b077165bee7c770ab8c0d3321d42b817b35232eb020350'
PG = 'sha256:afc7e2d441324c0388fa80c3d24f733b4194a4eb7f47dd8ee2b08eb1a24a647c'
S3 = 'sha256:bb05d66d2963b1cc48073190781c3dd29e2c4c88a2ae2986bf58e38c86d89c6e'
PROFILE_SHA = '2209c379e98051bf70814293776b750add62eb5331fcf8a5708b90d33ecbaef3'


def need(value):
    if not value:
        raise ValueError('fixed chain host contract')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


def write(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(canonical(value))
        stream.flush()
        os.fsync(stream.fileno())


def streaming_sha(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        need(stat.S_ISREG(before.st_mode))
        value, count = hashlib.sha256(), 0
        while True:
            block = os.read(fd, 65536)
            if not block:
                break
            value.update(block)
            count += len(block)
        after = os.fstat(fd)
        need((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
             (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) and count == before.st_size)
        return value.hexdigest()
    finally:
        os.close(fd)


def source_snapshot(root):
    names = subprocess.check_output(['git', 'ls-files', '-co', '--exclude-standard'], cwd=root,
                                    timeout=10).decode().splitlines()
    return {name: streaming_sha(root / name) for name in sorted(set(names)) if (root / name).is_file()}


def ownedlab(runtime, directory):
    # Exactly the existing implementation, including its nonce/preintent,
    # bounded Docker clients, known/unknown mutation handling and reverse close.
    source = runtime / 'scripts/m0lib/fixed-chain-topology.py'
    spec = importlib.util.spec_from_file_location('gura_fixed_chain_existing_topology', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    need((module.PG, module.S3) == (PG, S3))
    return module.OwnedLab(directory)


def client_projection(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        need(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= 65536)
        raw = os.read(fd, 65537)
        need(len(raw) == info.st_size and os.read(fd, 1) == b'')
    finally:
        os.close(fd)
    value = json.loads(raw)
    need(canonical(value) == raw and value['passed'] is True and value['hold'] is False
         and value['memory_certified'] is False and [row['case'] for row in value['cases']] == [
             'full11', 'dual130', 'full11-finish-only', 'dual130-finish-only'])
    return {'scope': value['scope'], 'memory_certified': False, 'cases': value['cases']}


def actual_cli_receipts(directory):
    receipts = []
    for path in sorted(directory.glob('command-*.result.json')):
        record = json.loads(path.read_text())
        need(record.get('client_reaped') is True)
        # Original receipts are private and preserve actual argv/partial/rc.
        receipts.append({'path': path.name, 'sha256': streaming_sha(path), 'pid': record.get('pid'),
                         'pgid': record.get('pgid'), 'returncode': record['returncode'], 'client_reaped': True})
    return receipts


def execute(p04, runtime, binary, profile, directory):
    os.umask(0o077)
    directory.mkdir(mode=0o700, parents=False, exist_ok=False)
    evidence, private = directory / 'evidence', directory / 'lab-private'
    evidence.mkdir(mode=0o700)
    private.mkdir(mode=0o700)
    lab, network_id = None, None
    result = {'passed': False, 'hold': True, 'scope': 'fixed actual FD assembly prototype NOT_CERTIFIED',
              'memory_certified': False, 'first_error_class': None}
    before, binary_sha, profile_sha = None, None, None
    try:
        need(all(path.is_absolute() and path.resolve() == path for path in (p04, runtime, binary, profile, directory)))
        need(binary.is_file() and os.access(binary, os.X_OK))
        before = {'p04': source_snapshot(p04), 'runtime': source_snapshot(runtime)}
        write(directory / 'source-before.json', before)
        binary_sha, profile_sha = streaming_sha(binary), streaming_sha(profile)
        need(profile_sha == PROFILE_SHA and profile.stat().st_size == 1384)
        write(directory / 'inputs.json', {'binary_sha256': binary_sha, 'profile_sha256': profile_sha,
              'profile_bytes': 1384, 'runtime_image': IMAGE, 'pg_image': PG, 's3_image': S3,
              'worker_arena_bytes': 15760640, 'worker_arena_certified': False})
        lab = ownedlab(runtime, private)
        for role, image in [('pg', PG), ('s3', S3), ('runtime', IMAGE)]:
            item = json.loads(lab.run(['image', 'inspect', image]).stdout)[0]
            need((item['Id'], item['Os'], item['Architecture']) == (image, 'linux', 'arm64'))
            write(directory / (role + '-image.json'), {key: item[key] for key in ('Id', 'Os', 'Architecture')})
        need(lab.inspect(lab.network, 'network') is None)
        lab.network_attempted = True
        network_id = lab.run(['network', 'create', *lab.labels, lab.network], mutation=True).stdout.strip()
        need(re.fullmatch('[0-9a-f]{64}', network_id) is not None)
        pg = lab.create(lab.network + '-pg', PG, ['--network', lab.network,
            '-p', '127.0.0.1::5432', '-p', '127.0.0.1::8333', '-e', 'POSTGRES_HOST_AUTH_METHOD=trust'])
        lab.wait_ready(lambda cutoff: lab.run(['exec', pg['id'], 'pg_isready', '-h', '127.0.0.1', '-U', 'postgres'],
                       check=False, timeout=min(2, cutoff - time.monotonic())).returncode == 0, seconds=15)
        s3config = private / 's3.json'
        write(s3config, {'identities': [{'name': 'test-driver', 'credentials': [
            {'accessKey': 'm0-test-key', 'secretKey': 'm0-test-secret'}],
            'actions': ['Admin', 'Read', 'Write', 'List', 'Tagging']}]})
        s3 = lab.create(lab.network + '-s3', S3, ['--network', 'container:' + pg['id'],
            '--mount', 'type=bind,src=' + str(s3config) + ',dst=/config/s3.json,readonly'],
            ['server', '-s3', '-ip=127.0.0.1', '-ip.bind=0.0.0.0', '-volume.max=1',
             '-master.volumeSizeLimitMB=32', '-master.telemetry=false', '-s3.config=/config/s3.json'])
        # Reuse the original namespace readiness operation; no new backend probe.
        published = lab.run(['port', pg['id'], '8333']).stdout.strip()
        need(re.fullmatch(r'127\.0\.0\.1:[1-9][0-9]{0,4}', published) is not None)
        import boto3
        from botocore.config import Config
        client = boto3.client('s3', endpoint_url='http://' + published, region_name='us-east-1',
            aws_access_key_id='m0-test-key', aws_secret_access_key='m0-test-secret',
            config=Config(proxies={}, retries={'max_attempts': 0}, connect_timeout=.3, read_timeout=.5))
        lab.wait_ready(lambda cutoff: client.list_buckets() is not None, seconds=30)
        mounts = [(p04, '/p04', True), (runtime, '/runtime', True),
                  (binary, '/query/fixed-chain-fd-binary', True),
                  (profile, '/run/gura-worker-profile/sha256.bin', True), (evidence, '/evidence', False)]
        options = ['--network', 'container:' + pg['id'], '--read-only', '--tmpfs', '/tmp',
                   '-e', 'PYTHONDONTWRITEBYTECODE=1', '-w', '/p04']
        for source, destination, readonly in mounts:
            options += ['--mount', 'type=bind,src=' + str(source) + ',dst=' + destination
                        + (',readonly' if readonly else '')]
        container = lab.create(lab.network + '-runtime', IMAGE, options,
                               ['python', '/runtime/scripts/m0lib/fixed-chain-fd-client.py'])
        write(directory / 'runtime-owned.json', {'nonce': lab.nonce, 'cid': container['id'], 'pg_cid': pg['id']})
        waited = lab.run(['wait', container['id']], timeout=max(0, lab.deadline - time.monotonic()))
        terminal = lab.inspect(container['id'])
        write(private / 'runtime-terminal.json', terminal)
        need(waited.stdout.strip() == '0' and terminal['State']['ExitCode'] == 0
             and terminal['State']['Running'] is False and terminal['Image'] == IMAGE)
        for entry in (s3, container):
            need(lab.inspect(entry['id'])['HostConfig']['NetworkMode'] == 'container:' + pg['id'])
        actual_mounts = {(m['Source'], m['Destination'], m['RW']) for m in terminal['Mounts']}
        need(actual_mounts == {(str(source), destination, not readonly) for source, destination, readonly in mounts}
             and terminal['HostConfig']['ReadonlyRootfs'] is True)
        result['client'] = client_projection(evidence / 'driver-summary.json')
        result['passed'] = True
    except BaseException as error:
        result['first_error_class'] = type(error).__name__
    finally:
        if lab is not None:
            try:
                lab.close()  # Original reverse exact-owned cleanup and independent60s cap.
                exact = []
                for entry in lab.containers:
                    identifier = entry.get('id')
                    need(type(identifier) is str and re.fullmatch('[0-9a-f]{64}', identifier) is not None)
                    need(lab.inspect(identifier) is None and lab.inspect(entry['name']) is None)
                    exact.append({'cid': identifier, 'name': entry['name'], 'absent': True})
                if network_id is not None:
                    need(lab.inspect(network_id, 'network') is None)
                result.update(ambiguous=lab.ambiguous, cleanup_error_count=len(lab.cleanup_errors),
                              exact_container_absence=exact, exact_network_absence=network_id,
                              cli=actual_cli_receipts(private))
                result['hold'] = lab.ambiguous or bool(lab.cleanup_errors)
            except BaseException as error:
                result.update(hold=True, cleanup_error_class=type(error).__name__)
        try:
            after = {'p04': source_snapshot(p04), 'runtime': source_snapshot(runtime)}
            write(directory / 'source-after.json', after)
            result['source_equal'] = before is not None and before == after
            result['binary_equal'] = binary_sha is not None and streaming_sha(binary) == binary_sha
            result['profile_equal'] = profile_sha is not None and streaming_sha(profile) == profile_sha
            result['passed'] &= result['source_equal'] and result['binary_equal'] and result['profile_equal']
        except BaseException as error:
            result.update(passed=False, source_identity_error_class=type(error).__name__, hold=True)
        # Original child failure retains HOLD even after known-owned removal.
        result['hold'] |= not result['passed']
        result['passed'] &= not result['hold']
        write(directory / 'result.json', result)
    return 0 if result['passed'] and not result['hold'] else 1


def main():
    parser = argparse.ArgumentParser()
    for name in ('p04', 'runtime', 'binary', 'profile', 'run-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    return execute(args.p04, args.runtime, args.binary, args.profile, args.run_dir)


if __name__ == '__main__':
    raise SystemExit(main())
