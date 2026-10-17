"""One fixed-view local three-process plan and deterministic global merges."""
from collections import Counter

from modules.cluster.local import fanout
from modules.cluster.transport import fanout_remote
from modules.common.contracts import public_media, public_values, require
from modules.connectors.training import export
from modules.index.retrieval import search


def execute(bundle, kind, request, budget, root, principal, transport=None):
    scope = {name: principal[name] for name in ('tenant','subject')}
    scope['dataset'] = bundle['manifest']['dataset_id']
    original_request = request
    if kind == 'search':
        require(set(request) <= {'text','vector','model','top_k','candidate_limit','filter','vector_index','nprobes'}, 'invalid_request')
        k, limit = request.get('top_k',10), request.get('candidate_limit',100)
        require(type(k) is int and type(limit) is int and 1 <= k <= limit <= 1000, 'resource_limit')
        request = dict(request, top_k=limit)
    rows = sorted(bundle['rows'], key=lambda row: row['logical_key'])
    tasks = []
    for shard in range(3):
        part = {name: bundle[name] for name in ('revision','context','model','manifest','retention_mode')}
        part['rows'] = rows[shard::3]
        if 'shards' in bundle:
            descriptor = bundle['shards'][shard]
            require(descriptor['shard'] == shard and descriptor['revision'] == bundle['revision'] and
                    descriptor['rows'] == len(part['rows']), 'source_invalid')
            part['serving_shard'] = descriptor
            part.pop('rows')
        if kind == 'search':
            part.update({name: bundle[name] for name in ('index_path','index_files')})
            part['global_rows'] = len(rows)
            if 'bm25' in bundle:
                part['bm25'] = dict(bundle['bm25'], files=[bundle['bm25']['files'][shard]])
            if 'ann' in bundle and 'shards' not in bundle:
                part['ann'] = bundle['ann']
        if kind == 'export' and 'shards' not in bundle:
            part['source_files'] = bundle['manifest']['files']
            part['source_key'] = {name: bundle['source'][name] for name in ('key_field','key_type')}
        tasks.append({'bundle': part, 'kind': kind, 'request': request, 'scope': scope,
                      'ann_partitions': bundle.get('ann', {}).get('partitions')})
    parts = (fanout('modules.query.worker', tasks, budget, root) if transport is None else
             fanout_remote(tasks, budget, root, *transport))
    require(all(part['read_context'] == bundle['context'] for part in parts) and
            sum(part['records'] for part in parts) == len(rows), 'worker_mismatch')
    evidence = {'mode': 'local-processes' if transport is None else 'loopback-http', 'workers': [{name: part[name] for name in ('shard','pid','records','task_id','rss_bytes','work')} for part in parts]}
    if transport is not None:
        for item, part in zip(evidence['workers'], parts):
            item['server_pid'] = part['server_pid']
    if kind == 'search':
        ranks = []
        for route in ('text', 'vector'):
            if route in original_request:
                ranks.append(sorted([hit for part in parts for hit in part['output'][route]],
                                    key=lambda hit: (-hit['score'], hit['logical_key']))[:limit])
        scores = {}
        for ranked in ranks:
            for rank, hit in enumerate(ranked, 1):
                key = hit['logical_key']
                scores[key] = scores.get(key,0.0) + 1/(60+rank) if len(ranks)>1 else hit['score']
        mapping = {row['logical_key']: row for row in rows}
        keys = sorted(scores, key=lambda key: (-scores[key],key))[:k]
        result = {'hits': [{'logical_key':key,'record_version':mapping[key].get('record_version',bundle['revision']),'score':scores[key],
                            'values':public_values(mapping[key]['values']),'media':public_media(mapping[key]['media'])} for key in keys],
                  'ranking': ('rrf-k60-ann' if original_request.get('vector_index') == 'ann' else 'rrf-k60') if len(ranks)>1 else ('bm25' if 'text' in original_request else original_request.get('vector_index','exact')+'-squared-l2'),
                  'stats':{'records_examined':len(rows),'candidate_limit':limit}}
    elif kind == 'graph':
        paths = [path for part in parts for path in part['output']['paths']]
        require(len(paths) <= request.get('max_edges',100) and
                all(n <= request.get('max_fanout',100) for n in Counter(path['seed'] for path in paths).values()), 'resource_limit')
        # Canonical endpoint strings sort identically on all workers. Restore numeric seed order for int8.
        field = next(f for f in bundle['manifest']['schema'] if f['name'] == request['source_field'])
        paths.sort(key=lambda p:(p['logical_key'],int(p['seed']) if field['data_type']=='int8' else p['seed'],p['direction']))
        result = {'paths':paths,'truncated':False,'stats':{'records_examined':len(rows),'paths':len(paths)}}
    elif kind == 'scan':
        found = sorted([row for part in parts for row in part['output']['rows']], key=lambda row:row['logical_key'])
        result = {'rows':found[:request.get('limit',100)],'truncated':len(rows)>request.get('limit',100)}
    else:
        samples = sorted([sample for part in parts for sample in part['output']['samples']], key=lambda sample:sample['logical_key'])
        require([sample['logical_key'] for sample in samples] == [row['logical_key'] for row in rows], 'worker_mismatch')
        result = export(bundle, request, root, budget, prepared=samples)
    budget.check()
    result.setdefault('stats', {}).update(source_reads=budget.reads, source_bytes=budget.bytes,
                                          artifact_reads=budget.artifact_reads, artifact_bytes=budget.artifact_bytes)
    result['read_context'] = bundle['context']
    result['execution'] = evidence
    return result
