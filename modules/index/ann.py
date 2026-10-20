"""Immutable derived Lance IVF_FLAT with source-key mapping and exact reranking."""
import math
import sys
from pathlib import Path


from modules.common.contracts import MAX_BYTES, MAX_ROWS, encoded, require
from modules.common.process import run_process
from modules.storage.objects import get, put


def _task(directory, rows, revision, model, config, budget):
    require(isinstance(config, dict) and set(config) == {'partitions'}, 'invalid_request')
    partitions = config['partitions']
    require(type(partitions) is int and 1 <= partitions <= 64 and
            partitions * 16 <= len(rows) <= MAX_ROWS, 'resource_limit', 'ANN needs at least 16 rows per partition')
    budget.check()
    directory = Path(directory).resolve()
    require(not directory.exists(), 'artifact_conflict')
    return {'kind': 'build', 'path': str(directory), 'rows': [
            {'logical_key': row['logical_key'], 'vector': row['vector'], 'record_version': row.get('record_version', revision)} for row in rows],
            'revision': revision, 'model': model, 'partitions': partitions}


def _finish(task, version, native_rss, budget):
    directory = Path(task['path'])
    files, size = [], 0
    for path in sorted(directory.rglob('*')):
        budget.check()
        if path.is_file():
            size += path.stat().st_size
            require(size <= MAX_BYTES and len(files) < 128, 'resource_limit', 'ANN artifact budget exceeded')
            files.append(put(path, path.read_bytes()))
    require(len(files) <= 128, 'resource_limit')
    return {'format': 'lance-ivf-flat-v1', 'path': str(directory), 'version': version,
            'revision': task['revision'], 'partitions': task['partitions'], 'rows': len(task['rows']), 'model': task['model'],
            'files': files, 'native_rss_bytes': native_rss, 'index_bytes': sum(Path(ref['path']).stat().st_size for ref in files)}


def build(directory, rows, revision, model, config, budget):
    task = _task(directory, rows, revision, model, config, budget)
    native = run_process([sys.executable, '-m', 'modules.index.ann_worker'], task, budget)
    return _finish(task, native['value']['version'], native['native_rss_bytes'], budget)


def build_many(entries, revision, model, config, budget):
    """Build up to three independent shard indexes with one bounded native call."""
    require(isinstance(entries, list) and 1 <= len(entries) <= 3, 'invalid_request')
    tasks = [_task(directory, rows, revision, model, config, budget) for directory, rows in entries]
    require(len({task['path'] for task in tasks}) == len(tasks), 'artifact_conflict')
    payload = {'kind': 'build-many', 'tasks': tasks}
    if len(encoded(payload)) > MAX_BYTES:
        # Preserve the original per-index input envelope for large vectors.
        return [build(directory, rows, revision, model, config, budget) for directory, rows in entries]
    native = run_process([sys.executable, '-m', 'modules.index.ann_worker'], payload, budget)
    require(isinstance(native['value'], list) and len(native['value']) == len(tasks), 'native_failed')
    return [_finish(task, value['version'], native['native_rss_bytes'], budget)
            for task, value in zip(tasks, native['value'])]


def candidates(bundle, query, allowed, limit, nprobes, budget):
    index = bundle.get('ann')
    require(index is not None, 'index_unavailable', 'view has no ANN index')
    require(index['format'] == 'lance-ivf-flat-v1' and index['revision'] == bundle['revision'] and
            index['model'] == bundle['model'], 'source_invalid')
    probes = nprobes if nprobes is not None else min(8, index['partitions'])
    require(type(probes) is int and 1 <= probes <= index['partitions'], 'invalid_request')
    budget.check()
    if not allowed:
        return [], {'ann_candidates': 0, 'nprobes': probes, 'native_rss_bytes': 0}
    input_bytes = 0
    for reference in index['files']:
        raw = get(reference)
        budget.artifact(len(raw))
        input_bytes += len(raw)
    # Logical keys are canonical hex, not caller-provided SQL expressions.
    require(all(isinstance(key, str) and key and all(c in '0123456789abcdef' for c in key) for key in allowed), 'source_invalid')
    condition = 'logical_key IN (' + ','.join("'" + key + "'" for key in sorted(allowed)) + ')'
    native = run_process([sys.executable, '-m', 'modules.index.ann_worker'],
        {'kind': 'query', 'index': {name: index[name] for name in ('path','version','rows')},
         'condition': condition, 'query': query, 'limit': min(limit, len(allowed)), 'probes': probes}, budget)
    budget.check()
    found = native['value']
    by_key = {row['logical_key']: row for row in bundle['rows']}
    seen, ranked = set(), []
    for hit in found:
        budget.check()
        logical = hit['logical_key']
        require(logical in allowed and logical not in seen and hit['record_version'] == by_key[logical].get('record_version', bundle['revision']), 'source_invalid')
        seen.add(logical)
        distance = math.fsum((a-b)**2 for a, b in zip(by_key[logical]['vector'], query))
        ranked.append((logical, -distance))
    return sorted(ranked, key=lambda hit: (-hit[1], hit[0])), {'ann_candidates': len(found), 'ann_input_files': len(index['files']), 'ann_input_bytes': input_bytes, 'nprobes': probes, 'native_rss_bytes': native['native_rss_bytes']}
