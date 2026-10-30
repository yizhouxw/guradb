"""Standard-library install integrity and local Docker transport; no DB semantics."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def installation():
    root = Path(__file__).resolve().parent.parent
    manifest = root/'manifest.json'
    if manifest.is_symlink() or not manifest.is_file() or manifest.stat().st_size > 16384:
        raise ValueError('installation manifest must be a bounded regular file')
    raw = manifest.read_bytes()
    if len(raw) > 16384:
        raise ValueError('installation manifest exceeds 16 KiB')
    m = json.loads(raw)
    if type(m['format_version']) is not int or m['format_version'] != 1 or m['engine_arch'] != 'linux-arm64' or m['host'] != 'darwin-arm64' or set(m['files']) != {'bin/guradb', 'lib/engine', 'lib/launcher.py', 'lib/capabilities.json'}:
        raise ValueError('unsupported installation version/layout')
    limits = {'bin/guradb': 4096, 'lib/launcher.py': 65536, 'lib/capabilities.json': 65536, 'lib/engine': 1024**3}
    if type(m['runtime_image']) is not str or not m['runtime_image'].startswith('sha256:') or len(m['runtime_image']) != 71:
        raise ValueError('runtime requires a fixed image Id')
    if sum(row['bytes'] for row in m['files'].values()) > 1024**3:
        raise ValueError('installation expanded size exceeds 1 GiB')
    for name, row in m['files'].items():
        if type(row['bytes']) is not int or not 0 <= row['bytes'] <= limits[name] or type(row['sha256']) is not str or len(row['sha256']) != 64:
            raise ValueError('invalid installation file declaration')
        p = root/name
        if p.is_symlink() or not p.is_file() or p.stat().st_size != row['bytes'] or digest(p) != row['sha256']:
            raise ValueError('installation integrity failed: '+name)
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise ValueError('preview supports macOS arm64 host only; engine is Linux ARM64 via Docker')
    return root, m


def environment(m, cfg):
    docker = os.environ.get('GURADB_DOCKER') or shutil.which('docker')
    if not docker or not Path(docker).is_file():
        raise ValueError('Docker CLI missing; provide existing Docker CLI via PATH or GURADB_DOCKER')
    endpoint = os.environ.get('GURADB_DOCKER_HOST', 'unix:///var/run/docker.sock')
    if not endpoint.startswith('unix:///'):
        raise ValueError('only an existing local unix Docker endpoint is supported')
    prefix = [docker, '--config', cfg, '--host', endpoint]
    def check(args):
        p = subprocess.run(prefix+args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
        if p.returncode or len(p.stdout) > 65536:
            raise ValueError('Docker daemon/runtime unavailable: '+p.stderr[:512].decode('utf-8', 'replace'))
        return p.stdout.decode().strip()
    daemon = check(['info', '--format', '{{.OSType}} {{.Architecture}}'])
    if daemon not in ('linux aarch64', 'linux arm64'):
        raise ValueError('Docker daemon must be Linux ARM64')
    image = check(['image', 'inspect', m['runtime_image'], '--format', '{{.Id}} {{.Os}} {{.Architecture}}'])
    if image != m['runtime_image']+' linux arm64':
        raise ValueError('fixed local runtime image missing/incompatible; no automatic pull')
    return prefix, {'docker_cli': docker, 'endpoint': endpoint, 'daemon': daemon, 'runtime': image}


class Interrupted(BaseException):
    def __init__(self, signum):
        self.signum = signum


def run():
    def interrupt(sig, _frame):
        raise Interrupted(sig)
    signal.signal(signal.SIGINT, interrupt)
    signal.signal(signal.SIGTERM, interrupt)
    root, m = installation()
    args = sys.argv[1:]
    if args == ['capabilities']:
        print(json.dumps({'provenance': m, 'runtime_checked': False, 'optional_tools': 'data preparation/CLIP encoder/PyTorch reader not bundled or probed', 'capabilities': json.loads((root/'lib/capabilities.json').read_text())}), flush=True)
        return 0
    with tempfile.TemporaryDirectory(prefix='guradb-docker-config-') as cfg:
        prefix, env = environment(m, cfg)
        if args == ['doctor']:
            print(json.dumps({'passed': True, 'host': platform.platform(), 'python': sys.version,
                              'installation': str(root), 'environment': env, 'provenance': m,
                              'optional_tools': 'external and not bundled/probed', 'scope': 'read-only installation/runtime checks; no source or model scan'}), flush=True)
            return 0
        if len(args) < 3 or args[0] != '--data-root':
            raise ValueError('usage: guradb capabilities|doctor OR --data-root <existing directory> <Rust argv with /data paths>')
        data = Path(args[1]).resolve(strict=True)
        if not data.is_dir():
            raise ValueError('data-root must be an existing directory')
        name = 'guradb-preview-'+str(os.getpid())+'-'+uuid.uuid4().hex[:8]
        command = prefix+['run', '--rm', '--pull', 'never', '--name', name, '--label', 'guradb.preview.owner='+str(os.getpid()),
                          '--network', 'none', '--memory', '512m', '--cpus', '4', '--pids-limit', '128',
                          '-v', str(root/'lib/engine')+':/guradb:ro', '-v', str(data)+':/data', '-w', '/data',
                          m['runtime_image'], '/guradb']+args[2:]
        child = None
        try:
            child = subprocess.Popen(command, start_new_session=True)
            code = child.wait(timeout=20)
            return code if code >= 0 else 128-code
        finally:
            signal.alarm(10)
            try:
                try:
                    subprocess.run(prefix+['rm', '-f', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, check=False)
                finally:
                    if child is not None and child.poll() is None:
                        os.killpg(child.pid, signal.SIGTERM)
                        try:
                            child.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            os.killpg(child.pid, signal.SIGKILL)
                            child.wait(timeout=2)
            finally:
                signal.alarm(0)


def discard_output():
    # Never flush again at interpreter shutdown after cancel/closed output.
    fd = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(fd, 1)
        os.dup2(fd, 2)
    finally:
        os.close(fd)


def main():
    def timeout(_sig, _frame):
        raise TimeoutError('preview total operation deadline exceeded')
    signal.signal(signal.SIGALRM, timeout)
    signal.alarm(10 if sys.argv[1:] in (['doctor'], ['capabilities']) else 20)
    try:
        return run()
    except Interrupted as e:
        return 128+e.signum
    except BrokenPipeError:
        return 120
    except (TimeoutError, subprocess.TimeoutExpired) as e:
        print(json.dumps({'code': 'preview_timeout', 'message': str(e)}), file=sys.stderr, flush=True)
        return 124
    except Exception as e:
        print(json.dumps({'code': 'preview_error', 'message': str(e)}), file=sys.stderr, flush=True)
        return 1
    finally:
        discard_output()
        signal.alarm(0)


if __name__ == '__main__':
    sys.exit(main())
