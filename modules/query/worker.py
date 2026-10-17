"""Trusted local shard worker, without catalog credentials or external listeners."""
import os
from io import BytesIO
import resource
from pathlib import Path
import sys
import time

from modules.common.contracts import Budget, Failure, decode_json, digest, encoded, key, public_values, public_media, require
from modules.connectors.training import samples_for
from modules.index.graph import expand
from modules.index.retrieval import search
from modules.storage.objects import get, put


def execute(task):
    require(isinstance(task, dict) and type(task.get('deadline')) in (float,int), 'worker_mismatch')
    budget = Budget(seconds=task['deadline']-time.monotonic())
    budget.check()
    require(isinstance(task, dict) and {'task_id','shard','deadline','payload','fingerprint'} <= set(task) <= {'task_id','shard','deadline','payload','fingerprint','limits'} and
            isinstance(task['task_id'], str) and len(task['task_id']) == 32 and
            type(task['shard']) is int and 0 <= task['shard'] < 3, 'worker_mismatch')
    if 'limits' in task:
        require(isinstance(task['limits'], dict) and set(task['limits']) == set(budget.limits) and
                all(type(value) is int and 0 <= value <= budget.limits[name] for name,value in task['limits'].items()), 'worker_mismatch')
        budget.limits = task['limits']
    payload = task['payload']
    require(isinstance(payload, dict) and set(payload) <= {'bundle','kind','request','scope','ann_partitions'} and {'bundle','kind','request','scope'} <= set(payload) and
            isinstance(payload['bundle'], dict) and isinstance(payload['request'], dict), 'worker_mismatch')
    require(digest(encoded(payload)) == task['fingerprint'], 'worker_mismatch')
    bundle, request, kind = payload['bundle'], payload['request'], payload['kind']
    require(isinstance(payload['scope'], dict) and set(payload['scope']) == {'tenant','subject','dataset'}, 'worker_mismatch')
    require(payload['scope']['dataset'] == bundle['manifest']['dataset_id'], 'worker_mismatch')
    shard_bytes = 0
    if 'serving_shard' in bundle:
        import pyarrow.parquet as pq
        descriptor = bundle['serving_shard']
        require(descriptor['shard'] == task['shard'] and descriptor['revision'] == bundle['revision'], 'worker_mismatch')
        raw = get(descriptor['file'])
        budget.account(len(raw))
        shard_bytes = len(raw)
        table = pq.ParquetFile(BytesIO(raw)).read()
        require(table.column_names == ['row_json'] and table.nbytes <= 64 << 20 and
                len(table) == descriptor['rows'], 'source_invalid')
        bundle['rows'] = [decode_json(value.encode()) for value in table['row_json'].to_pylist()]
        keys = [row['logical_key'] for row in bundle['rows']]
        require(keys == sorted(set(keys)), 'source_invalid')
        if 'ann' in descriptor:
            bundle['ann'] = descriptor['ann']

    work = {'index_queries': 0, 'source_files': int(shard_bytes > 0), 'source_bytes': shard_bytes}
    if kind == 'search':
        # Validate the whole request before splitting independent retrieval routes.
        require('text' in request or 'vector' in request, 'invalid_request')
        output = {}
        for route in ('text', 'vector'):
            if route not in request:
                continue
            selected = dict(request)
            if route == 'text':
                for name in ('vector','model','vector_index','nprobes'):
                    selected.pop(name, None)
            else:
                selected.pop('text', None)
            if route == 'vector' and selected.get('vector_index') == 'ann' and 'serving_shard' in bundle:
                descriptor = bundle['serving_shard']
                if 'ann' not in descriptor:
                    require(descriptor.get('vector_fallback') == 'exact-small-shard', 'index_unavailable')
                    # Validate probes against the original declared partition count before fallback.
                    probes = selected.pop('nprobes', None)
                    require(probes is None or type(probes) is int and 1 <= probes <= payload['ann_partitions'], 'invalid_request')
                    selected['vector_index'] = 'exact'
                    work['vector_index'] = 'exact-small-shard'
                else:
                    work['vector_index'] = 'ann-shard'
            found = search(bundle, selected, budget)
            output[route] = found['hits']
            work.setdefault('search', {})[route] = found['stats']
            work['index_queries'] += 1
        # Search validation must also reject vector options on a text-only request.
        if 'vector' not in request:
            search(bundle, request, budget)

    elif kind == 'graph':
        output = expand(bundle, request, budget)
    elif kind == 'scan':
        limit = request.get('limit', 100)
        require(set(request) <= {'limit'} and type(limit) is int and 1 <= limit <= 1000, 'invalid_request')
        output = {'rows': [{'logical_key': r['logical_key'], 'record_version': r.get('record_version', bundle['revision']),
                            'values': public_values(r['values']), 'media': public_media(r['media'])}
                           for r in bundle['rows'][:limit]]}
    else:
        require(kind == 'export', 'invalid_request')
        import pyarrow.parquet as pq
        owned = {row['logical_key']: row for row in bundle['rows']}
        seen = set()
        for fragment in bundle.get('source_files', []):
            budget.check()
            raw = get({'path': str(Path(bundle['manifest']['backend']['root']) / fragment['key']),
                       'sha256': fragment['sha256']})
            budget.account(len(raw))
            require(len(raw) == fragment['size_bytes'], 'source_invalid')
            table = pq.ParquetFile(BytesIO(raw)).read()
            require(table.nbytes <= 64 << 20, 'resource_limit')
            for values in table.to_pylist():
                logical = key(values[bundle['source_key']['key_field']], bundle['source_key']['key_type'])
                if logical in owned:
                    require(logical not in seen and values == owned[logical]['values'], 'source_invalid')
                    seen.add(logical)
                    owned[logical]['values'] = values
            work['source_files'] += 1
            work['source_bytes'] += len(raw)
        require('serving_shard' in bundle or seen == set(owned), 'source_invalid', 'training file tasks did not cover assigned keys')
        output = {'samples': samples_for(bundle, request, budget)}
    budget.check()
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    rss_bytes = int(rss if sys.platform == 'darwin' else rss*1024)
    require(rss_bytes <= 512 << 20, 'resource_limit')
    work['budget'] = budget.counters()
    return {'work': work, 'rss_bytes': rss_bytes, 'output': output, 'records': len(bundle['rows']), 'read_context': bundle['context']}


def main():
    task = decode_json(get({'path': sys.argv[1], 'sha256': sys.argv[2]}))
    result = {name: task[name] for name in ('task_id','fingerprint','shard')}
    result['pid'] = os.getpid()
    try:
        result.update(execute(task))
    except Failure as error:
        result['error'] = error.code
    raw = encoded(result)
    require(len(raw) <= 32 << 20, 'resource_limit')
    put(Path(sys.argv[3]), raw)


if __name__ == '__main__':
    main()
