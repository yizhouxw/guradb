"""Trusted-checksum zipapp installation to a fresh local prefix only."""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import stat
import sys
import tempfile
import zipfile


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def install(archive, expected, prefix):
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise ValueError('preview host requires macOS arm64')
    if archive.stat().st_size > 1024**3 or digest(archive) != expected:
        raise ValueError('archive SHA/size differs; obtain trusted expected SHA and check externally first')
    prefix = prefix.absolute()
    if prefix.exists() or prefix.is_symlink() or not prefix.parent.is_dir():
        raise ValueError('prefix must not exist and parent must already exist')
    stage = Path(tempfile.mkdtemp(prefix='.guradb-install-', dir=prefix.parent))
    try:
        with zipfile.ZipFile(archive) as z:
            names = ['bin/guradb', 'lib/engine', 'lib/launcher.py', 'lib/capabilities.json']
            required = {'__main__.py', 'payload/manifest.json'} | {'payload/'+n for n in names}
            if set(z.namelist()) != required or len(z.infolist()) != len(required) or sum(i.file_size for i in z.infolist()) > 1024**3:
                raise ValueError('invalid archive layout/expanded byte limit')
            for i in z.infolist():
                if stat.S_ISLNK(i.external_attr >> 16):
                    raise ValueError('archive links unsupported')
            if z.getinfo('payload/manifest.json').file_size > 16384 or z.getinfo('__main__.py').file_size > 65536:
                raise ValueError('archive metadata exceeds bound')
            raw = z.read('payload/manifest.json')
            if len(raw) > 16384:
                raise ValueError('manifest exceeds bound')
            m = json.loads(raw)
            if type(m['format_version']) is not int or m['format_version'] != 1 or m['host'] != 'darwin-arm64' or m['engine_arch'] != 'linux-arm64' or set(m['files']) != set(names):
                raise ValueError('unsupported archive version/architecture')
            for name in names:
                row = m['files'][name]
                if type(row['bytes']) is not int or not 0 <= row['bytes'] <= 1024**3 or type(row['sha256']) is not str or len(row['sha256']) != 64 or z.getinfo('payload/'+name).file_size != row['bytes']:
                    raise ValueError('declared file size differs')
                p = stage/name
                p.parent.mkdir(parents=True, exist_ok=True)
                h = hashlib.sha256()
                with z.open('payload/'+name) as src, p.open('xb') as dst:
                    for block in iter(lambda: src.read(1024 * 1024), b''):
                        h.update(block)
                        dst.write(block)
                    dst.flush()
                    os.fsync(dst.fileno())
                if h.hexdigest() != row['sha256']:
                    raise ValueError('payload integrity mismatch: '+name)
            elf = (stage/'lib/engine').open('rb')
            with elf:
                header = elf.read(64)
            if header[:6] != b'\x7fELF\x02\x01' or int.from_bytes(header[18:20], 'little') != 183:
                raise ValueError('engine is not Linux ARM64 ELF')
            (stage/'manifest.json').write_bytes(raw)
            (stage/'bin/guradb').chmod(0o755)
            (stage/'lib/engine').chmod(0o755)
        # Darwin SDK sys/stdio.h: RENAME_EXCL=4, no overwrite even for empty dirs.
        libc = ctypes.CDLL(None, use_errno=True)
        rename = libc.renamex_np
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        if rename(os.fsencode(stage), os.fsencode(prefix), 4) != 0:
            raise OSError(ctypes.get_errno(), 'atomic fresh-prefix publication failed')
        return {'installed': str(prefix), 'engine_sha256': m['files']['lib/engine']['sha256'], 'runtime_image': m['runtime_image']}
    finally:
        if stage.exists():
            signal.alarm(10)
            try:
                shutil.rmtree(stage)
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
    def stop(sig, _frame):
        raise SystemExit(128+sig)
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    def deadline(_sig, _frame):
        raise TimeoutError('installation deadline exceeded')
    signal.signal(signal.SIGALRM, deadline)
    signal.alarm(60)
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['install'])
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--prefix', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = install(Path(sys.argv[0]).resolve(strict=True), args.sha256, args.prefix)
        print(json.dumps(result))
        sys.stdout.flush()
        return 0
    except BrokenPipeError:
        return 120
    except Exception as e:
        print(json.dumps({'code': 'install_failed', 'message': str(e)}), file=sys.stderr, flush=True)
        return 1
    finally:
        discard_output()
        signal.alarm(0)


if __name__ == '__main__':
    sys.exit(main())
