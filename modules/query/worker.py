"""Trusted local shard worker, without catalog credentials or external listeners."""
import os
import resource
from pathlib import Path
import sys
import time

from modules.common.contracts import Budget, Failure, decode_json, digest, encoded, public_values, public_media, require
from modules.connectors.training import samples_for
from modules.index.graph import expand
from modules.index.retrieval import search
from modules.storage.objects import get, put


def execute(task):
    budget = Budget(seconds=task['deadline']-time.monotonic())
    budget.check()
    payload = task['payload']
    require(digest(encoded(payload)) == task['fingerprint'], 'worker_mismatch')
    bundle, request, kind = payload['bundle'], payload['request'], payload['kind']
    require(isinstance(payload['scope'], dict) and set(payload['scope']) == {'tenant','subject','dataset'}, 'worker_mismatch')
    require(payload['scope']['dataset'] == bundle['manifest']['dataset_id'], 'worker_mismatch')
    if kind == 'search':
        output = search(bundle, request, budget)
    elif kind == 'graph':
        output = expand(bundle, request, budget)
    elif kind == 'scan':
        limit = request.get('limit', 100)
        require(set(request) <= {'limit'} and type(limit) is int and 1 <= limit <= 1000, 'invalid_request')
        output = {'rows': [{'logical_key': r['logical_key'], 'record_version': bundle['revision'],
                            'values': public_values(r['values']), 'media': public_media(r['media'])}
                           for r in bundle['rows'][:limit]]}
    else:
        require(kind == 'export', 'invalid_request')
        output = {'samples': samples_for(bundle, request, budget)}
    budget.check()
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    rss_bytes = int(rss if sys.platform == 'darwin' else rss*1024)
    require(rss_bytes <= 512 << 20, 'resource_limit')
    return {'rss_bytes': rss_bytes, 'output': output, 'records': len(bundle['rows']), 'read_context': bundle['context']}


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
