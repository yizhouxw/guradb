"""Explicit-root bounded reads and immutable artifacts; never list a lake."""
from pathlib import Path
from urllib.parse import unquote, urlsplit
import os

from modules.common.contracts import MAX_BYTES, Failure, digest, require


class Objects:
    def __init__(self, root, budget, s3=None, archive=None):
        self.root, self.budget, self.s3 = root.rstrip('/'), budget, s3
        self.dependencies = []
        self.archive = Path(archive) if archive is not None else None
        parsed = urlsplit(self.root)
        require(parsed.scheme in ('file', 's3'))
        require(not parsed.query and not parsed.fragment and not parsed.username)
        self.parsed = parsed
        if parsed.scheme == 'file':
            require(parsed.netloc == '' and Path(unquote(parsed.path)).is_absolute())
            self.local = Path(unquote(parsed.path)).resolve(strict=True)
            require(Path(unquote(parsed.path)) == self.local, 'source_invalid', 'source root must be canonical without symlinks')
        else:
            require(s3 is not None and parsed.netloc)

    def read(self, uri, limit=4 << 20, expected=None):
        try:
            return self._read(uri, limit, expected)
        except Failure:
            raise
        except Exception:
            raise Failure('source_unavailable', 'pinned source object is unavailable or unreadable') from None

    def _read(self, uri, limit, expected):
        self.budget.check()
        require(self.budget.reads < 128 and self.budget.bytes < MAX_BYTES, 'resource_limit')
        p = urlsplit(uri)
        require(p.scheme == self.parsed.scheme and p.netloc == self.parsed.netloc)
        require(not p.query and not p.fragment and uri.startswith(self.root + '/'))
        require(all(part not in ('', '.', '..') for part in unquote(p.path).lstrip('/').split('/')))
        if p.scheme == 'file':
            path = Path(unquote(p.path))
            require(path.resolve(strict=True).is_relative_to(self.local), 'source_invalid')
            current = path
            while current != self.local:
                require(not current.is_symlink(), 'source_invalid', 'symlink source rejected')
                current = current.parent
            with path.open('rb') as stream:
                before = os.fstat(stream.fileno())
                raw = stream.read(min(limit, MAX_BYTES - self.budget.bytes) + 1)
                raw_digest = digest(raw)
                stat = os.fstat(stream.fileno())
                identity_fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
                current_stat = path.stat()
                require(all(getattr(before, name) == getattr(stat, name) == getattr(current_stat, name)
                            for name in identity_fields), 'source_invalid', 'source changed while reading')
        else:
            response = self.s3.get_object(Bucket=p.netloc, Key=unquote(p.path).lstrip('/'))
            with response['Body'] as stream:
                require(response['ContentLength'] <= limit, 'resource_limit')
                raw = stream.read(min(limit, MAX_BYTES - self.budget.bytes) + 1)
        if p.scheme != 'file':
            raw_digest = digest(raw)
        require(0 < len(raw) <= limit, 'resource_limit', 'object exceeds byte limit')
        self.budget.account(len(raw))
        require(expected is None or raw_digest == expected, 'source_invalid', 'pinned object changed')
        dependency = {'uri': uri, 'sha256': raw_digest, 'size_bytes': len(raw)}
        if p.scheme == 'file':
            dependency['identity'] = {'kind': 'file-stat-v1', 'device': stat.st_dev, 'inode': stat.st_ino,
                                      'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns, 'ctime_ns': stat.st_ctime_ns}
        else:
            dependency['identity'] = {'kind': 's3-head-v1', 'etag': response.get('ETag'),
                                      'version': response.get('VersionId'), 'size': response['ContentLength']}
        if self.archive is not None:
            dependency['copy'] = put(self.archive/raw_digest, raw)
        self.dependencies.append(dependency)
        return raw


def put(path, raw):
    """Create once, fsync before publication; identical retries are safe."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except FileExistsError:
        require(not path.is_symlink() and path.read_bytes() == raw, 'artifact_conflict')
    return {'path': str(path.resolve()), 'sha256': digest(raw)}


def get(reference, limit=MAX_BYTES):
    path = Path(reference['path'])
    require(not path.is_symlink(), 'source_invalid')
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    require(len(raw) <= limit and digest(raw) == reference['sha256'], 'source_invalid', 'artifact mismatch')
    return raw
