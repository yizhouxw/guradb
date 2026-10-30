"""Independent offline application composition, not native PyArrow/NumPy FTS.

PyArrow decodes the raw pinned Parquet and NumPy holds f64 vectors. This
application owns tokenization, BM25, full-rank fusion, identity/retention checks,
asset lookup and grouped membership. It never reads Rust results or gold data.
The fixed comparison is projection-only SQL and the declared small corpus;
there is no general SQL parser, model execution, persistent DB or index here.
"""
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import unicodedata

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

SOURCE_LIMIT = 32 << 20
DECODE_LIMIT = 64 << 20
FEATURE_LIMIT = 8 << 20
MEDIA_LIMIT = 512 << 10
HEX = re.compile(r'[0-9a-f]{64}\Z')
IDENTIFIER = re.compile(r'[A-Za-z0-9._-]{1,64}\Z')
WORDS = re.compile(r'[A-Za-z0-9]+')
SPACE_KEYS = {'id', 'dimensions', 'dtype', 'metric', 'normalization', 'origin',
              'model_id', 'model_revision', 'preprocessing_id', 'license'}
TEXT_FIELDS = {'doc_id', 'text', 'text_version'}
MEDIA_FIELDS = {'image_id', 'image_path', 'media_version', 'media_bytes', 'media_sha256'}


class ReferenceError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(code + ': ' + message)


def require(condition, code, message):
    if not condition:
        raise ReferenceError(code, message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'invalid_input', 'duplicate JSON key')
        result[key] = value
    return result


def _constant(_):
    raise ReferenceError('invalid_input', 'nonfinite JSON constant')


def decode_json(raw):
    try:
        return json.loads(raw, object_pairs_hook=_object, parse_constant=_constant)
    except (ValueError, UnicodeError, RecursionError) as error:
        if isinstance(error, ReferenceError):
            raise
        raise ReferenceError('invalid_input', 'invalid bounded UTF8 JSON') from error


def closed(value, keys, code='invalid_input'):
    require(type(value) is dict and set(value) == set(keys), code, 'unknown/missing object keys')


def uint(value, low, high):
    return type(value) is int and low <= value <= high


def digest(value):
    return type(value) is str and HEX.fullmatch(value) is not None


def identifier(value):
    return type(value) is str and IDENTIFIER.fullmatch(value) is not None


def printable(value):
    return type(value) is str and all(32 <= ord(char) <= 126 or char in '\t\n\r' for char in value)


def tokens(text, query=False):
    require(printable(text), 'invalid_search_query' if query else 'invalid_search_input',
            'text requires printable ASCII')
    require(len(text) <= (256 if query else 8192), 'resource_limit', 'text/query exceeds byte bound')
    result = WORDS.findall(text.lower())
    require(bool(result) and len(result) <= (8 if query else 2048)
            and all(len(word) <= 64 for word in result),
            'invalid_search_query' if query else 'invalid_search_input', 'invalid token count/length')
    # The current public analyzer counts the original query tokens for its
    # bound, then deduplicates and uses sorted ASCII term order.
    return sorted(set(result)) if query else result


def sum_f64(values):
    # Explicit dimension-order binary64 additions; Python 3.12 sum and NumPy
    # reductions may use a different reduction tree. No tolerance is used here.
    total = 0.0
    for value in values:
        total += float(value)
    return total


def normalize(values, dimensions):
    require(type(values) is list and len(values) == dimensions
            and all(type(x) in (int, float) for x in values),
            'invalid_vector', 'vector requires numeric components and exact dimensions')
    try:
        array = np.asarray(values, dtype=np.float64)
    except (OverflowError, ValueError, TypeError) as error:
        raise ReferenceError('invalid_vector', 'components cannot be represented as f64') from error
    require(bool(np.isfinite(array).all()), 'invalid_vector', 'nonfinite vector')
    maximum = float(np.max(np.abs(array)))
    require(maximum != 0.0, 'invalid_vector', 'zero vector')
    scaled = array / maximum
    norm = math.sqrt(sum_f64(float(x) * float(x) for x in scaled))
    normalized = scaled / norm
    require(bool(np.isfinite(normalized).all()), 'invalid_vector', 'nonfinite normalized vector')
    normalized.setflags(write=False)
    return normalized


def validate_space(space):
    closed(space, SPACE_KEYS, 'invalid_features')
    require(identifier(space['id']) and uint(space['dimensions'], 1, 1024)
            and space['dtype'] == 'f64' and space['metric'] == 'cosine'
            and space['normalization'] == 'l2-scaled-f64-v1'
            and space['origin'] in ('numerical-fixture', 'external-declared'),
            'invalid_features', 'unsupported space declaration')
    for name in ('model_id', 'model_revision', 'preprocessing_id', 'license'):
        value = space[name]
        require(type(value) is str and 0 < len(value.encode('utf8')) <= 256
                and not any(unicodedata.category(char) == 'Cc' for char in value),
                'invalid_features', 'invalid model/preprocessing/license declaration')


def directory(path):
    """Open directory components without following any symlink (Unix only)."""
    path = Path(path).absolute()
    require('..' not in path.parts, 'invalid_path', 'parent traversal is outside this comparison layout')
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(path.anchor, flags)
    try:
        for component in path.parts[1:]:
            next_fd = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


class Reference:
    def __init__(self, config: Path, features: Path, features_sha: str):
        self.io = {'read_calls': 0, 'read_bytes': 0, 'validation_reads': 0, 'parquet_materializations': 0}
        self.config_path = Path(config).absolute()
        self.feature_path = Path(features).absolute()
        require(digest(features_sha), 'invalid_features', 'invalid feature pin')
        self.feature_sha = features_sha
        self._config_raw = self._read(self.config_path, 16 << 10)
        configuration = decode_json(self._config_raw)
        require(type(configuration) is dict and {'source', 'sha256'} <= set(configuration)
                and not set(configuration) - {'source', 'sha256', 'timeout_ms'},
                'invalid_config', 'invalid config keys')
        require(type(configuration['source']) is str and configuration['source']
                and '\0' not in configuration['source'] and digest(configuration['sha256'])
                and uint(configuration.get('timeout_ms', 5000), 1, 10000),
                'invalid_config', 'invalid source/SHA256/timeout')
        self.source_sha = configuration['sha256']
        source = Path(configuration['source'])
        self.source_path = source if source.is_absolute() else self.config_path.parent / source
        # Public CLI anchors media to config.parent, independently of source's
        # relative/absolute path. Prepared comparison layouts place both here.
        self.media_root = self.config_path.parent
        raw = self._snapshot(self.source_path, SOURCE_LIMIT, self.source_sha, 'source_changed')
        self._load_documents(raw)
        feature_raw = self._snapshot(self.feature_path, FEATURE_LIMIT, self.feature_sha, 'feature_changed')
        self._load_features(feature_raw)
        self._check()

    @property
    def docs(self):
        return [dict(row) for row in self._docs]

    @property
    def space(self):
        return dict(self._space)

    @property
    def logical_read_bytes(self):
        """Actual bytes read by this object; never physical disk/cache I/O."""
        return self.io['read_bytes']

    @property
    def validation_reads(self):
        """File reads used for source/feature/media SHA validation."""
        return self.io['validation_reads']

    def _read_at(self, parent, name, limit, expected_size=None):
        require(type(name) is str and name and '/' not in name and name not in ('.', '..'),
                'invalid_path', 'invalid leaf name')
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
        try:
            fd = os.open(name, flags, dir_fd=parent)
            try:
                metadata = os.fstat(fd)
                require(stat.S_ISREG(metadata.st_mode), 'invalid_input', 'input must be a regular file')
                require(metadata.st_size <= limit, 'resource_limit', 'input exceeds byte bound')
                require(expected_size is None or metadata.st_size == expected_size,
                        'media_changed', 'media size differs from source binding')
                blocks, count = [], 0
                while True:
                    block = os.read(fd, min(65536, limit + 1 - count))
                    if not block:
                        break
                    count += len(block)
                    require(count <= limit, 'resource_limit', 'input grew beyond byte bound')
                    blocks.append(block)
                raw = b''.join(blocks)
                require(expected_size is None or len(raw) == expected_size,
                        'media_changed', 'media size changed during read')
                self.io['read_calls'] += 1
                self.io['read_bytes'] += len(raw)
                return raw
            finally:
                os.close(fd)
        except OSError as error:
            raise ReferenceError('invalid_input', 'input unavailable, linked or unreadable') from error

    def _read(self, path, limit):
        path = Path(path).absolute()
        try:
            parent = directory(path.parent)
        except OSError as error:
            raise ReferenceError('invalid_path', 'input parent unavailable or linked') from error
        try:
            return self._read_at(parent, path.name, limit)
        finally:
            os.close(parent)

    def _snapshot(self, path, limit, expected, code):
        raw = self._read(path, limit)
        self.io['validation_reads'] += 1
        require(sha(raw) == expected, code, 'input bytes differ from pinned identity')
        return raw

    def _check(self):
        require(self._read(self.config_path, 16 << 10) == self._config_raw,
                'invalid_config', 'reference configuration changed')
        self._snapshot(self.source_path, SOURCE_LIMIT, self.source_sha, 'source_changed')
        self._snapshot(self.feature_path, FEATURE_LIMIT, self.feature_sha, 'feature_changed')

    def _load_documents(self, raw):
        try:
            parquet = pq.ParquetFile(pa.BufferReader(raw))
            require(uint(parquet.metadata.num_rows, 1, 200), 'resource_limit', 'corpus requires 1..200 rows')
            names = parquet.schema_arrow.names
            required = TEXT_FIELDS | MEDIA_FIELDS if set(names) & MEDIA_FIELDS else TEXT_FIELDS
            require(len(names) == len(required) and set(names) == required,
                    'unsupported_search_contract', 'unsupported corpus layout')
            declared = 0
            for group in range(parquet.metadata.num_row_groups):
                metadata = parquet.metadata.row_group(group)
                for column in range(metadata.num_columns):
                    size = metadata.column(column).total_uncompressed_size
                    require(type(size) is int and size >= 0, 'source_invalid', 'invalid column size')
                    declared += size
                    require(declared <= DECODE_LIMIT, 'resource_limit', 'declared decode exceeds 64MiB')
            table = parquet.read(use_threads=False)
        except Exception as error:
            if isinstance(error, ReferenceError):
                raise
            raise ReferenceError('source_invalid', 'invalid Parquet input') from error
        require(table.nbytes <= DECODE_LIMIT, 'resource_limit', 'decoded data exceeds 64MiB')
        names = table.column_names
        has_media = bool(set(names) & MEDIA_FIELDS)
        required = TEXT_FIELDS | MEDIA_FIELDS if has_media else TEXT_FIELDS
        require(len(names) == len(required) and set(names) == required,
                'unsupported_search_contract', 'unsupported corpus layout')
        for field, column in zip(table.schema, table.columns):
            kind = pa.int64() if field.name in {'text_version', 'image_id', 'media_version', 'media_bytes'} else pa.string()
            require(field.type == kind and column.null_count == 0,
                    'unsupported_search_contract', 'wrong column type or NULL')
        self._docs = table.to_pylist()
        self.io['parquet_materializations'] += 1
        self._by_id, self._tokens, self._assets = {}, {}, {}
        total_bytes = total_tokens = 0
        for row in self._docs:
            key = row['doc_id']
            require(identifier(key) and key not in self._by_id and uint(row['text_version'], 1, 1),
                    'invalid_search_input', 'duplicate/invalid identity or text version')
            words = tokens(row['text'])
            total_bytes += len(row['text'])
            total_tokens += len(words)
            require(total_bytes <= 256 << 10 and total_tokens <= 65536,
                    'resource_limit', 'corpus text/token bound exceeded')
            self._by_id[key] = row
            self._tokens[key] = Counter(words)
            if has_media:
                asset = row['image_id']
                require(uint(asset, 1, 999999999999) and uint(row['media_version'], 1, 1)
                        and uint(row['media_bytes'], 1, MEDIA_LIMIT)
                        and row['image_path'] == f'images/{asset:012d}.jpg' and digest(row['media_sha256']),
                        'invalid_media_binding', 'invalid asset description')
                description = (row['image_path'], row['media_bytes'], row['media_sha256'])
                require(asset not in self._assets or self._assets[asset] == description,
                        'invalid_media_binding', 'conflicting asset identity')
                self._assets[asset] = description
                require(len(self._assets) <= 3, 'resource_limit', 'more than three assets')
        self._ids = set(self._by_id)
        self._has_media = has_media
        self._length = {key: sum(counts.values()) for key, counts in self._tokens.items()}

    def _load_features(self, raw):
        try:
            lines = raw.decode('utf8').splitlines()
        except UnicodeError as error:
            raise ReferenceError('invalid_features', 'non-UTF8 feature data') from error
        require(bool(lines) and len(lines[0].encode('utf8')) <= 16384,
                'invalid_features', 'missing/oversize feature header')
        header = decode_json(lines[0])
        closed(header, {'format_version', 'source_sha256', 'documents', 'space'}, 'invalid_features')
        require(uint(header['format_version'], 1, 1) and uint(header['documents'], len(self._ids), len(self._ids)),
                'invalid_features', 'feature version/Docset count mismatch')
        require(header['source_sha256'] == self.source_sha, 'source_mismatch', 'feature source differs')
        validate_space(header['space'])
        self._space = dict(header['space'])
        self._vectors = {}
        for line in lines[1:]:
            require(len(line.encode('utf8')) <= 65536, 'resource_limit', 'feature row exceeds 64KiB')
            if not line.strip():
                continue
            row = decode_json(line)
            closed(row, {'doc_id', 'vector'}, 'invalid_features')
            key = row['doc_id']
            require(type(key) is str and key in self._ids and key not in self._vectors,
                    'invalid_features', 'duplicate/extra feature Doc')
            self._vectors[key] = normalize(row['vector'], self._space['dimensions'])
        require(set(self._vectors) == self._ids, 'invalid_features', 'missing feature Doc')

    @staticmethod
    def _top_k(top_k):
        require(uint(top_k, 1, 20), 'invalid_config', 'top_k requires 1..20')

    def query(self):
        self._check()
        result = [{'doc_id': key, 'text': self._by_id[key]['text']} for key in sorted(self._ids)]
        self._check()
        return result

    def _bm25(self, text):
        terms = tokens(text, query=True)
        count = len(self._ids)
        average = sum(self._length.values()) / count
        frequencies = {term: sum(self._tokens[key][term] > 0 for key in self._ids) for term in terms}
        inverse = {term: math.log(1.0 + (count - frequencies[term] + 0.5) / (frequencies[term] + 0.5))
                   for term in terms}
        result = []
        for key in self._ids:
            score = 0.0
            for term in terms:
                frequency = self._tokens[key][term]
                if frequency:
                    score += inverse[term] * frequency * (1.2 + 1.0) / (
                        frequency + 1.2 * (1.0 - 0.75 + 0.75 * self._length[key] / average))
            require(math.isfinite(score), 'invalid_score', 'nonfinite BM25 score')
            if score > 0.0:
                result.append({'doc_id': key, 'score': score})
        return sorted(result, key=lambda row: (-row['score'], row['doc_id']))

    def search(self, text, top_k=20):
        self._top_k(top_k)
        self._check()
        result = self._bm25(text)[:top_k]
        self._check()
        return result

    def _vector(self, query_path):
        query = decode_json(self._read(query_path, 65536))
        closed(query, {'format_version', 'source_sha256', 'space', 'vector'}, 'invalid_features')
        require(uint(query['format_version'], 1, 1), 'invalid_features', 'unsupported query version')
        require(query['source_sha256'] == self.source_sha, 'source_mismatch', 'query source differs')
        validate_space(query['space'])
        require(query['space'] == self._space, 'space_mismatch', 'query space differs')
        value = normalize(query['vector'], self._space['dimensions'])
        result = []
        for key in self._ids:
            score = sum_f64(float(a) * float(b) for a, b in zip(self._vectors[key], value))
            require(math.isfinite(score), 'invalid_score', 'nonfinite cosine')
            score = max(-1.0, min(1.0, score))
            result.append({'doc_id': key, 'score': 0.0 if score == 0.0 else score})
        return sorted(result, key=lambda row: (-row['score'], row['doc_id']))

    def vector(self, query_path, top_k=20):
        self._top_k(top_k)
        self._check()
        result = self._vector(query_path)[:top_k]
        self._check()
        return result

    def hybrid(self, query_path, text, top_k=20):
        self._top_k(top_k)
        self._check()
        vector = self._vector(query_path)
        text_rank = {row['doc_id']: rank for rank, row in enumerate(self._bm25(text), 1)}
        result = []
        for rank, row in enumerate(vector, 1):
            lexical = 1.0 / (60.0 + text_rank[row['doc_id']]) if row['doc_id'] in text_rank else 0.0
            result.append({'doc_id': row['doc_id'], 'score': lexical + 1.0 / (60.0 + rank)})
        result.sort(key=lambda row: (-row['score'], row['doc_id']))
        self._check()
        return result[:top_k]

    def _asset_bytes(self, asset):
        require(asset in self._assets, 'asset_missing', 'asset absent from complete source')
        _, expected_size, expected_sha = self._assets[asset]
        try:
            root = directory(self.media_root)
            try:
                images = os.open('images', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                 dir_fd=root)
            finally:
                os.close(root)
            try:
                raw = self._read_at(images, f'{asset:012d}.jpg', MEDIA_LIMIT, expected_size)
            finally:
                os.close(images)
        except OSError as error:
            raise ReferenceError('media_invalid', 'media root unavailable or linked') from error
        self.io['validation_reads'] += 1
        require(sha(raw) == expected_sha, 'media_changed', 'media differs from source SHA256')
        return raw

    def media(self, assetid):
        require(type(assetid) in (int, str) and not isinstance(assetid, bool), 'invalid_media_binding', 'invalid asset ID')
        if type(assetid) is str:
            require(re.fullmatch(r'[1-9][0-9]{0,11}', assetid) is not None,
                    'invalid_media_binding', 'asset ID requires canonical positive decimal')
        asset = int(assetid)
        require(uint(asset, 1, 999999999999), 'invalid_media_binding', 'asset ID out of range')
        self._check()
        raw = self._asset_bytes(asset)
        self._check()
        return {'asset_id': str(asset), 'bytes': raw, 'sha256': sha(raw)}

    def sample(self, selection_path):
        self._check()
        raw = self._read(selection_path, 65536)
        selection = decode_json(raw)
        closed(selection, {'format_version', 'source_sha256', 'seed', 'doc_ids'}, 'invalid_sample_selection')
        require(uint(selection['format_version'], 1, 1) and uint(selection['seed'], 0, (1 << 32) - 1),
                'invalid_sample_selection', 'invalid format or seed')
        require(selection['source_sha256'] == self.source_sha, 'source_mismatch', 'selection source differs')
        selected = selection['doc_ids']
        require(type(selected) is list and 1 <= len(selected) <= 200 and all(identifier(key) for key in selected)
                and len(set(selected)) == len(selected) and set(selected) <= self._ids and self._has_media,
                'invalid_sample_selection', 'duplicate/missing Doc or unsupported selection')
        groups = {self._by_id[key]['image_id'] for key in selected}
        require(len(groups) >= 2, 'invalid_sample_selection', 'at least two asset groups required')
        ranked = []
        for asset in groups:
            self._asset_bytes(asset)
            group = f"guradb-sample-group-v1\n{selection['seed']}\n{asset}\n".encode('ascii')
            ranked.append((sha(group), asset))
        validation = min(ranked)[1]
        result = {'train': [], 'validation': []}
        for key in sorted(selected):
            result['validation' if self._by_id[key]['image_id'] == validation else 'train'].append(key)
        self._check()
        require(self._read(selection_path, 65536) == raw, 'invalid_sample_selection', 'selection changed')
        return result
