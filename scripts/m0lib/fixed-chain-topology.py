"""Owned test-only PG namespace + Seaweed + fixed Python runtime preflight."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time
import uuid

import boto3
from botocore.config import Config

ROOT = Path(__file__).resolve().parents[2]
PG = 'sha256:afc7e2d441324c0388fa80c3d24f733b4194a4eb7f47dd8ee2b08eb1a24a647c'
S3 = 'sha256:bb05d66d2963b1cc48073190781c3dd29e2c4c88a2ae2986bf58e38c86d89c6e'


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


class OwnedLab:
    def __init__(self, directory):
        self.directory = directory
        self.nonce = uuid.uuid4().hex
        self.network = 'gura-chain-' + self.nonce[:12]
        self.containers = []
        self.commands = 0
        self.ambiguous = False
        self.cleanup_errors = []
        self.deadline = time.monotonic() + 90
        self.labels = ['--label', 'gura.owner=fixed-chain-runtime',
                       '--label', 'gura.run=' + self.nonce]
        self.network_attempted = False
        self.pending_clients = []
        write(directory / 'ownership-intent.json', {'nonce': self.nonce, 'network': self.network,
                                                    'labels': self.labels})

    @staticmethod
    def reap(process):
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=2)
        if process.returncode is None:
            raise RuntimeError('owned Docker client not reaped')

    def run(self, args, *, check=True, timeout=20, mutation=False):
        timeout = min(timeout, self.deadline - time.monotonic())
        if timeout <= 0:
            raise TimeoutError('topology phase deadline')
        prefix = self.directory / f'command-{self.commands:03d}'
        self.commands += 1
        record = {'argv': ['docker', *args], 'timeout_seconds': timeout,
                  'mutation': mutation, 'new_session': True, 'started_monotonic': time.monotonic()}
        process, primary = None, None
        record['secondary_errors'] = []
        try:
            # Ownership and command intent survive even a failed post-spawn journal.
            write(prefix.with_suffix('.intent.json'), record)
            with prefix.with_suffix('.stdout').open('w') as out, prefix.with_suffix('.stderr').open('w') as err:
                process = subprocess.Popen(record['argv'], stdout=out, stderr=err, start_new_session=True)
                record['pid'] = process.pid
                record['expected_pgid'] = process.pid
                record['pgid'] = os.getpgid(process.pid)
                if record['pgid'] != process.pid:
                    raise RuntimeError('new-session Docker client group mismatch')
                write(prefix.with_suffix('.started.json'), record)
                code = process.wait(timeout=timeout)
        except BaseException as error:
            primary = error
            record['primary_error'] = type(error).__name__ + ': ' + str(error)
            if process is not None:
                self.ambiguous |= mutation
                try:
                    self.reap(process)
                except BaseException as secondary:
                    record['secondary_errors'].append(type(secondary).__name__ + ': ' + str(secondary))
                    self.pending_clients.append(process)
            code = 124 if isinstance(error, subprocess.TimeoutExpired) else -1
        record.update(returncode=code, finished_monotonic=time.monotonic(),
                      client_reaped=process is not None and process.returncode is not None)
        stdout = stderr = ''
        try:
            stdout, stderr = (prefix.with_suffix('.' + s).read_text()
                              if prefix.with_suffix('.' + s).exists() else '' for s in ('stdout', 'stderr'))
        except BaseException as error:
            record['secondary_errors'].append('log read: ' + str(error))
            primary = primary or error
            self.ambiguous |= mutation and process is not None
        try:
            write(prefix.with_suffix('.result.json'), {**record,
                  'stdout_sha256': hashlib.sha256(stdout.encode()).hexdigest(),
                  'stderr_sha256': hashlib.sha256(stderr.encode()).hexdigest()})
        except BaseException as error:
            self.ambiguous |= mutation and process is not None
            if primary is None:
                primary = error
        if primary is not None:
            raise primary
        if code and mutation:
            self.ambiguous = True
        if code and check:
            raise RuntimeError(f'docker command {self.commands - 1} failed rc={code}')
        return subprocess.CompletedProcess(record['argv'], code, stdout, stderr)

    def inspect(self, name, kind='container'):
        result = self.run([kind, 'inspect', name], check=False)
        if result.returncode:
            diagnostics = {
                'container': {f'Error response from daemon: No such container: {name}',
                              f'Error: No such container: {name}'},
                'network': {f'Error response from daemon: network {name} not found'},
                'volume': {f'Error response from daemon: get {name}: no such volume'},
            }
            if (result.returncode == 1 and result.stdout.strip() == '[]'
                    and result.stderr.strip() in diagnostics.get(kind, set())):
                return None
            raise RuntimeError('resource inspect unavailable')
        decoded = json.loads(result.stdout)
        if not isinstance(decoded, list) or len(decoded) != 1 or not isinstance(decoded[0], dict):
            raise RuntimeError('malformed resource inspect shape')
        item = decoded[0]
        if kind == 'volume':
            valid = (item.get('Name') == name and isinstance(item.get('Driver'), str)
                     and isinstance(item.get('Mountpoint'), str))
        else:
            identifier = item.get('Id')
            resource_name = item.get('Name')
            valid = (isinstance(identifier, str) and re.fullmatch(r'[0-9a-f]{64}', identifier)
                     and isinstance(resource_name, str)
                     and (identifier == name or resource_name == ('/' + name if kind == 'container' else name)))
            if kind == 'container':
                config = item.get('Config')
                valid = (valid and isinstance(config, dict) and isinstance(item.get('Image'), str)
                         and isinstance(item.get('Mounts'), list)
                         and (config.get('Labels') is None or isinstance(config.get('Labels'), dict)))
            elif kind == 'network':
                valid = (valid and isinstance(item.get('Containers'), dict)
                         and (item.get('Labels') is None or isinstance(item.get('Labels'), dict)))
            else:
                valid = False
        if not valid:
            raise RuntimeError('malformed or mismatched resource inspect identity')
        return item

    def owned(self, item, *, network=False):
        labels = (item.get('Labels') if network else item.get('Config', {}).get('Labels')) or {}
        return labels.get('gura.owner') == 'fixed-chain-runtime' and labels.get('gura.run') == self.nonce

    def wait_ready(self, callback, seconds=15):
        cutoff = min(self.deadline, time.monotonic() + seconds)
        while time.monotonic() < cutoff:
            try:
                ready = callback(cutoff)
            except Exception:
                ready = False
            # A late successful callback cannot extend startup's original cap.
            if time.monotonic() >= cutoff:
                raise TimeoutError('service startup deadline')
            if ready:
                return
            time.sleep(min(.1, max(0, cutoff - time.monotonic())))
        raise TimeoutError('service startup deadline')

    def create(self, name, image, options, command=()):
        if self.inspect(name) is not None:
            raise RuntimeError('preexisting container; refusing ownership')
        entry = {'name': name, 'id': None, 'image': image}
        self.containers.append(entry)
        write(self.directory / 'owned-resources.json', self.containers)
        result = self.run(['create', '--pull=never', '--platform', 'linux/arm64',
                           '--name', name, *self.labels, *options, image, *command], mutation=True)
        entry['id'] = result.stdout.strip()
        item = self.inspect(name)
        if not item or not self.owned(item) or item['Id'] != entry['id'] or item['Image'] != image:
            raise RuntimeError('created container identity mismatch')
        entry['volumes'] = [mount['Name'] for mount in item.get('Mounts', []) if mount['Type'] == 'volume']
        write(self.directory / 'owned-resources.json', self.containers)
        self.run(['start', entry['id']], mutation=True)
        return entry

    def close(self):
        self.deadline = time.monotonic() + 60
        readbacks = []
        for process in self.pending_clients:
            try:
                self.reap(process)
            except BaseException:
                self.cleanup_errors.append('Docker mutation client unresolved; preserve all resources')
        if self.cleanup_errors:
            write(self.directory / 'cleanup.json', {'readbacks': [], 'errors': self.cleanup_errors,
                                                   'ambiguous_mutation': True})
            return
        for entry in reversed(self.containers):
            try:
                item = self.inspect(entry['name'])
                if item is not None:
                    if (not self.owned(item) or item['Image'] != entry['image']
                            or (entry['id'] and item['Id'] != entry['id'])):
                        raise RuntimeError('foreign container; preserved')
                    volumes = [m['Name'] for m in item.get('Mounts', []) if m['Type'] == 'volume']
                    if 'volumes' in entry and set(volumes) != set(entry['volumes']):
                        raise RuntimeError('container volume provenance changed; preserved')
                    entry['volumes'] = volumes
                    self.run(['logs', item['Id']], check=False)
                    self.run(['rm', '-f', '-v', item['Id']], mutation=True)
                if self.inspect(entry['name']) is not None:
                    raise RuntimeError('container removal not confirmed')
                readbacks.append({'name': entry['name'], 'absent': True})
                for volume in entry.get('volumes', []):
                    if self.inspect(volume, 'volume') is not None:
                        raise RuntimeError('anonymous volume still exists/shared; preserved: ' + volume)
                    readbacks.append({'volume': volume, 'origin_cid': entry['id'], 'absent': True})
            except Exception as error:
                self.cleanup_errors.append(str(error))
        if self.network_attempted:
            try:
                item = self.inspect(self.network, 'network')
                if item is not None:
                    if not self.owned(item, network=True) or item.get('Containers'):
                        raise RuntimeError('foreign/nonempty network; preserved')
                    self.run(['network', 'rm', item['Id']], mutation=True)
                if self.inspect(self.network, 'network') is not None:
                    raise RuntimeError('network removal not confirmed')
                readbacks.append({'network': self.network, 'absent': True})
            except Exception as error:
                self.cleanup_errors.append(str(error))
        write(self.directory / 'cleanup.json', {'readbacks': readbacks, 'errors': self.cleanup_errors,
                                               'ambiguous_mutation': self.ambiguous})


def execute(directory, image):
    if re.fullmatch(r'sha256:[0-9a-f]{64}', image) is None:
        raise ValueError('exact local runtime image ID required')
    directory.mkdir(parents=True, exist_ok=False)
    lab = OwnedLab(directory)
    result = {'passed': False, 'scope': 'namespace readiness only', 'failure': None}
    try:
        for role, identifier in [('pg', PG), ('s3', S3), ('runtime', image)]:
            info = json.loads(lab.run(['image', 'inspect', identifier]).stdout)[0]
            if info['Id'] != identifier or info['Os'] != 'linux' or info['Architecture'] != 'arm64':
                raise RuntimeError('fixed linux/arm64 image mismatch')
            write(directory / (role + '-image.json'), {k: info[k] for k in ('Id', 'Os', 'Architecture')})
        if lab.inspect(lab.network, 'network') is not None:
            raise RuntimeError('preexisting network')
        lab.network_attempted = True
        lab.run(['network', 'create', *lab.labels, lab.network], mutation=True)
        pg = lab.create(lab.network + '-pg', PG, ['--network', lab.network,
                       '-p', '127.0.0.1::5432', '-p', '127.0.0.1::8333',
                       '-e', 'POSTGRES_HOST_AUTH_METHOD=trust'])
        lab.wait_ready(lambda cutoff: lab.run(
            ['exec', pg['id'], 'pg_isready', '-h', '127.0.0.1', '-U', 'postgres'],
            check=False, timeout=min(2, cutoff - time.monotonic())).returncode == 0)
        config = directory / 'private-s3.json'
        write(config, {'identities': [{'name': 'test-driver', 'credentials': [
              {'accessKey': 'm0-test-key', 'secretKey': 'm0-test-secret'}],
              'actions': ['Admin', 'Read', 'Write', 'List', 'Tagging']}]})
        s3 = lab.create(lab.network + '-s3', S3, ['--network', 'container:' + pg['id'],
                        '-v', str(config.resolve()) + ':/config/s3.json:ro'],
                        ['server', '-s3', '-ip=127.0.0.1', '-ip.bind=0.0.0.0', '-volume.max=1',
                         '-master.volumeSizeLimitMB=32', '-master.telemetry=false', '-s3.config=/config/s3.json'])
        port = lab.run(['port', pg['id'], '8333']).stdout.strip().rsplit(':', 1)[1]
        client = boto3.client('s3', endpoint_url='http://127.0.0.1:' + port, region_name='us-east-1',
                              aws_access_key_id='m0-test-key', aws_secret_access_key='m0-test-secret',
                              config=Config(proxies={}, retries={'max_attempts': 0}, connect_timeout=.3, read_timeout=.5))
        lab.wait_ready(lambda cutoff: client.list_buckets() is not None, seconds=30)
        runtime = lab.create(lab.network + '-runtime', image, ['--network', 'container:' + pg['id'],
                             '--read-only', '--tmpfs', '/tmp', '-v', str(ROOT) + ':/workspace:ro'],
                             ['python', '/workspace/scripts/m0lib/fixed-chain-client.py'])
        waited = lab.run(['wait', runtime['id']], timeout=30)
        if waited.stdout.strip() != '0':
            raise RuntimeError('namespace SDK client failed')
        logs = lab.run(['logs', runtime['id']])
        report = json.loads(logs.stdout)
        if report.get('passed') is not True:
            raise RuntimeError('namespace client did not attest success')
        for entry in [s3, runtime]:
            info = lab.inspect(entry['name'])
            if info['HostConfig']['NetworkMode'] != 'container:' + pg['id']:
                raise RuntimeError('sidecar network namespace differs')
        result.update(passed=True, client=report)
    except Exception as error:
        result['failure'] = type(error).__name__ + ': ' + str(error)
    finally:
        lab.close()
        result['passed'] &= not lab.cleanup_errors and not lab.ambiguous
        result.update(cleanup_errors=lab.cleanup_errors, hold=lab.ambiguous or bool(lab.cleanup_errors))
        write(directory / 'report.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--image', required=True)
    parser.add_argument('--run-dir', type=Path, required=True)
    arguments = parser.parse_args()
    outcome = execute(arguments.run_dir, arguments.image)
    print(json.dumps({'passed': outcome['passed'], 'hold': outcome['hold']}))
    raise SystemExit(0 if outcome['passed'] else 1)
