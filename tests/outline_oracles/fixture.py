"""Strict byte/identity validation for the private P01 synthetic fixture."""
from collections import Counter
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path, PurePosixPath

from .training import validate_training


ROOT = Path(__file__).resolve().parents[1] / 'fixtures' / 'outline'
# Updated only with a reviewed fixture-version change, never at read time.
MANIFEST_SHA256 = '455fc7a3e8c75a1c5446ecc52a3ead105f930607957f8f10eaaca8ffb1d32f94'
DOCUMENTS = {'corpus': 'corpus.json', 'assets': 'assets.json', 'fragments': 'fragments.json',
             'features': 'features.json', 'edges': 'edges.json', 'groups': 'groups.json',
             'training': 'training.json', 'golden': 'golden.json', 'budgets': 'budgets.json',
             'comparisons': 'comparisons.json', 'negatives': 'negative-cases.json',
             'token_index': 'token-index.json'}
MAX_FILE_BYTES = 1048576
MAX_TOTAL_BYTES = 2097152


class FixtureError(ValueError):
    """Stable fixture-only rejection code; not a public database error."""

    def __init__(self, code, detail):
        super().__init__(f'{code}: {detail}')
        self.code = code


def require(condition, code, detail):
    if not condition:
        raise FixtureError(code, detail)


def identity(value, fields=('record_id', 'record_version')):
    require(isinstance(value, dict) and all(isinstance(value.get(f), str) and value[f]
                                          for f in fields), 'invalid_identity', str(fields))
    return tuple(value[f] for f in fields)


def ref(key):
    return dict(zip(('record_id', 'record_version'), key))


def unique(items, fields, code):
    result = {}
    for item in items:
        key = identity(item, fields)
        require(key not in result, code, str(key))
        result[key] = item
    return result


def local_path(root, name):
    require(isinstance(name, str), 'invalid_path', 'path must be string')
    relative = PurePosixPath(name)
    require(not relative.is_absolute() and relative.parts and
            all(p not in ('.', '..') for p in relative.parts) and
            str(relative) == name and '\\' not in name, 'invalid_path', name)
    current = root
    for part in relative.parts:
        current = current / part
        require(not current.is_symlink(), 'invalid_path', 'symlink')
    require(current.is_file(), 'missing_input', name)
    return current


def read_bounded(path):
    require(path.stat().st_size <= MAX_FILE_BYTES, 'input_budget', str(path))
    return path.read_bytes()


def load_fixture(root=ROOT):
    """Read only frozen bounded files; reject a modified manifest and unknown inputs."""
    root = Path(root)
    manifest_bytes = read_bounded(local_path(root, 'manifest.json'))
    digest = hashlib.sha256(manifest_bytes).hexdigest()
    require(digest == MANIFEST_SHA256, 'manifest_mismatch', digest)
    manifest = json.loads(manifest_bytes)
    payloads, total = {}, 0
    for item in manifest['inputs']:
        name = item['path']
        require(name not in payloads, 'duplicate_input', name)
        raw = read_bounded(local_path(root, name))
        total += len(raw)
        require(total <= MAX_TOTAL_BYTES, 'input_budget', 'total bytes')
        require(len(raw) == item['size_bytes'] and hashlib.sha256(raw).hexdigest() == item['sha256'],
                'input_mismatch', name)
        payloads[name] = raw
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    require(actual == set(payloads) | {'manifest.json'}, 'unexpected_input', str(actual - set(payloads)))
    documents = {name: json.loads(payloads[path]) for name, path in DOCUMENTS.items()}
    documents['manifest'] = manifest
    documents['manifest_sha256'] = digest
    validate_fixture(documents, root)
    return documents


def validate_fixture(documents, root=ROOT):
    """Validate independent source facts, without any production implementation."""
    corpus = documents['corpus']
    require(corpus['fixture_schema'] == 'outline-synthetic-v1' and corpus['language'] == 'zh-CN',
            'unsupported_fixture', 'version or language')
    rows = unique(corpus['records'], ('record_id', 'record_version'), 'duplicate_record')
    require(len(rows) <= 100, 'input_budget', 'record count')
    for row in rows.values():
        priority = row['priority']
        require(priority is None or type(priority) is int and -(2**63) <= priority < 2**63,
                'invalid_int8', str(priority))
        require(row['active'] is None or type(row['active']) is bool, 'invalid_type', 'active')
        require(row['title'] is None or isinstance(row['title'], str), 'invalid_type', 'title')
        require(isinstance(row['tokens'], list) and all(isinstance(t, str) and t for t in row['tokens']),
                'invalid_tokens', row['record_id'])
    views = unique(corpus['views'], ('read_view_id',), 'duplicate_view')
    for view in views.values():
        identity(view, ('data_revision_id', 'source_version_id'))
        keys = [identity(r) for r in view['records']]
        require(len(set(keys)) == len(keys) and set(keys) <= rows.keys(), 'invalid_view', 'members')
        require(len({k[0] for k in keys}) == len(keys), 'invalid_view', 'multiple record versions')
    assets = unique(documents['assets'], ('asset_id', 'asset_version'), 'duplicate_asset')
    for asset in assets.values():
        raw = read_bounded(local_path(Path(root), asset['relative_path']))
        require(len(raw) == asset['size_bytes'] and hashlib.sha256(raw).hexdigest() == asset['sha256'],
                'asset_mismatch', asset['asset_id'])
        require(asset['license'] == 'CC0-1.0', 'invalid_license', asset['asset_id'])
    for row in rows.values():
        for name in ('text_asset', 'image_asset'):
            if row[name] is not None:
                require(identity(row[name], ('asset_id', 'asset_version')) in assets,
                        'unknown_asset', row['record_id'])
    fragments = unique(documents['fragments'], ('fragment_id', 'fragment_version'), 'duplicate_fragment')
    for fragment in fragments.values():
        parent = identity(fragment['parent'])
        require(parent in rows, 'unknown_record', str(parent))
        asset_key = identity(fragment['asset'], ('asset_id', 'asset_version'))
        require(asset_key in assets, 'unknown_asset', str(asset_key))
        asset = assets[asset_key]
        kind = fragment['kind']
        if kind == 'text_utf8_bytes':
            require(rows[parent]['text_asset'] == fragment['asset'], 'wrong_parent_asset', str(parent))
            raw = read_bounded(local_path(Path(root), asset['relative_path']))
            start, end = fragment['start'], fragment['end']
            require(type(start) is int and type(end) is int and 0 <= start < end <= len(raw),
                    'invalid_coordinate', str(parent))
            try:
                raw[:start].decode('utf-8')
                raw[start:end].decode('utf-8')
            except UnicodeDecodeError as error:
                raise FixtureError('invalid_coordinate', 'UTF-8 boundary') from error
        elif kind == 'image_xywh':
            require(rows[parent]['image_asset'] == fragment['asset'], 'missing_modality', str(parent))
            x, y, width, height = fragment['box']
            require(all(type(v) is int for v in (x, y, width, height)) and
                    x >= 0 and y >= 0 and width > 0 and height > 0 and
                    x + width <= fragment['image_width'] and y + height <= fragment['image_height'],
                    'invalid_coordinate', str(parent))
            require(asset['media_type'] == 'image/svg+xml', 'invalid_media_type', str(asset_key))
        else:
            raise FixtureError('invalid_coordinate', kind)
    space = documents['features']
    require((space['space_id'], space['model_version'], space['dimension'], space['metric']) ==
            ('outline-synthetic-zh-image3', '1', 3, 'squared_l2'), 'wrong_feature_space', 'header')
    features = unique(space['features'], ('feature_id', 'feature_version'), 'duplicate_feature')
    feature_parents = set()
    for feature in features.values():
        parent = identity(feature['parent'])
        require(parent in rows, 'unknown_record', str(parent))
        require(parent not in feature_parents, 'duplicate_feature', str(parent))
        feature_parents.add(parent)
        require(all(feature[name] == space[name] for name in ('space_id', 'model_version', 'dimension', 'metric')) and
                len(feature['vector']) == space['dimension'] and all(type(v) in (int, float) and math.isfinite(v)
                                                                       for v in feature['vector']),
                'wrong_feature_space', str(parent))
    unique(documents['edges'], ('edge_id', 'edge_version'), 'duplicate_edge')
    for edge in documents['edges']:
        require(edge['relation'] == 'cites', 'unsupported_relation', edge['relation'])
        require(identity(edge['source']) in rows and identity(edge['target']) in rows, 'unknown_record', edge['edge_id'])
    token_index = documents['token_index']
    require(token_index['kind'] == 'synthetic-reference-postings-not-production-index' and
            (token_index['view_id'],) in views, 'index_view_mismatch', 'reference postings')
    expected_postings = {}
    for member in views[(token_index['view_id'],)]['records']:
        key = identity(member)
        for token, frequency in Counter(rows[key]['tokens']).items():
            expected_postings.setdefault(token, []).append((key, frequency))
    actual_postings = {}
    for token, postings in token_index['postings'].items():
        actual_postings[token] = [(identity(posting), posting['tf']) for posting in postings]
        require(all(type(tf) is int and tf > 0 for _, tf in actual_postings[token]),
                'invalid_postings', token)
    normalize = lambda index: {token: sorted(postings) for token, postings in index.items()}
    require(normalize(actual_postings) == normalize(expected_postings), 'invalid_postings', 'source comparison')
    validate_training(documents, rows, views, fragments, feature_parents, require, identity)
    return deepcopy(documents)
