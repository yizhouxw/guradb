"""Immutable acceptance evidence archives keyed by every preserved file's content."""

from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from .policy import HarnessError


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _source(directory):
    directory = Path(directory).absolute()
    if directory.resolve(strict=True) != directory or not directory.is_dir():
        raise HarnessError('acceptance evidence root must be a canonical directory')
    result = directory/'result.json'
    inventory = list(directory.rglob('*'))
    if any(path.is_symlink() for path in inventory):
        raise HarnessError('acceptance evidence tree cannot contain symlinks')
    paths = {result, *(path for path in inventory if path.name == 'trace.json' or path.suffix == '.log')}
    content = {}
    for path in sorted(paths):
        if path.is_symlink() or not path.is_file() or path.resolve(strict=True) != path:
            raise HarnessError('acceptance evidence file missing, nonregular or symlinked')
        relative = path.relative_to(directory).as_posix()
        content[relative] = path.read_bytes()
    return content


def _expected_entries(content):
    entries = set(content)
    for name in content:
        entries.update(parent.as_posix() for parent in Path(name).parents if parent != Path('.'))
    return entries


def _verify(destination, content):
    if destination.is_symlink() or not destination.is_dir() or destination.resolve() != destination:
        raise HarnessError('existing acceptance archive is not a canonical directory')
    paths = list(destination.rglob('*'))
    if ({path.relative_to(destination).as_posix() for path in paths} != _expected_entries(content)
            or any(path.is_symlink() or not (path.is_file() or path.is_dir()) for path in paths)):
        raise HarnessError('existing acceptance archive has missing, extra or unsafe entries; preserve it')
    for name, raw in content.items():
        path = destination/name
        if not path.is_file() or path.read_bytes() != raw:
            raise HarnessError('existing acceptance archive differs or is corrupt; preserve it')


def _write(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _sync(directory):
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextmanager
def _locked(base):
    path = base/'.publish.lock'
    if path.is_symlink():
        raise HarnessError('acceptance archive lock cannot be a symlink')
    with path.open('a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def archive_run(common, family, run_dir):
    """Reuse identical complete evidence; never repair or overwrite an old archive.

    Trace/log bytes and relative names are part of identity: equal result.json
    alone does not imply equal executions. Legacy result-keyed archives remain
    untouched. A driver may omit trace.json, but result.json is always required.
    """
    if not isinstance(family, str) or re.fullmatch(r'[a-z][a-z0-9-]*', family) is None:
        raise HarnessError('invalid acceptance archive family')
    content = _source(run_dir)
    manifest = {'schema_version': 2, 'result_sha256': _digest(content['result.json']),
                'files': {name: _digest(raw) for name, raw in sorted(content.items())}}
    raw = (json.dumps(manifest, sort_keys=True, separators=(',', ':'))+'\n').encode()
    identity = _digest(raw)
    content['manifest.json'] = raw
    base = Path(common).absolute()/'guradb'/(family+'-evidence')/'v2'
    if base.resolve() != base:
        raise HarnessError('acceptance archive parent cannot contain symlinks')
    base.mkdir(parents=True, exist_ok=True)
    if base.resolve(strict=True) != base:
        raise HarnessError('acceptance archive parent cannot contain symlinks')
    destination = base/identity
    with _locked(base):
        if destination.exists() or destination.is_symlink():
            _verify(destination, content)
            return destination
        staging = Path(tempfile.mkdtemp(prefix='.staging-', dir=base))
        try:
            for name, data in sorted(content.items()):
                _write(staging/name, data)
            # Persist nested directories before publishing the complete tree.
            for directory in sorted((p for p in staging.rglob('*') if p.is_dir()),
                                    key=lambda p: len(p.parts), reverse=True):
                _sync(directory)
            _sync(staging)
            _verify(staging, content)
            os.rename(staging, destination)
            _sync(base)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    return destination
