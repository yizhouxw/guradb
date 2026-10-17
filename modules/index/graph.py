"""Bounded typed-edge one-hop expansion over one immutable fact bundle."""
import re

from modules.common.contracts import MAX_ROWS, public_values, require

MAX_PATHS = 1000
MAX_SEEDS = 128


def _value(value, kind, code, public=False):
    if kind == 'text':
        require(isinstance(value, str) and 0 < len(value.encode('utf-8')) <= 4096, code)
        return value
    require(kind == 'int8', code)
    if public and isinstance(value, str):
        require(len(value) <= 20 and re.fullmatch(r'-?(0|[1-9][0-9]*)', value) is not None, code)
        parsed = int(value)
        require(str(parsed) == value, code)
    else:
        require(type(value) is int, code)
        parsed = value
        if public:
            require(abs(parsed) <= 9007199254740991, code)
    require(-(1 << 63) <= parsed < (1 << 63), code)
    return parsed


def expand(bundle, request, budget):
    """Return all matching paths or fail closed; no partial/truncated results."""
    budget.check()
    required = {'source_field', 'target_field', 'type_field', 'seeds', 'type'}
    require(isinstance(request, dict) and required <= set(request) <=
            required | {'direction', 'max_edges', 'max_fanout'}, 'invalid_request')
    names = [request[name] for name in ('source_field', 'target_field', 'type_field')]
    require(all(isinstance(name, str) for name in names) and len(set(names)) == 3, 'invalid_request')
    schema = {field['name']: field['data_type'] for field in bundle['manifest']['schema']}
    source, target, type_field = names
    require(all(name in schema for name in names), 'invalid_request')
    kind = schema[source]
    require(kind in ('text', 'int8') and schema[target] == kind and schema[type_field] == 'text', 'invalid_request')
    direction = request.get('direction', 'out')
    require(direction in ('out', 'in', 'both'), 'invalid_request')
    limits = [request.get('max_edges', 100), request.get('max_fanout', 100)]
    require(all(type(limit) is int and 1 <= limit <= MAX_PATHS for limit in limits), 'resource_limit')
    max_edges, max_fanout = limits
    raw_seeds = request['seeds']
    require(isinstance(raw_seeds, list) and 1 <= len(raw_seeds) <= MAX_SEEDS, 'invalid_request')
    seeds = set()
    for raw in raw_seeds:
        budget.check()
        seed = _value(raw, kind, 'invalid_request', public=True)
        require(seed not in seeds, 'invalid_request')
        seeds.add(seed)
    edge_type = _value(request['type'], 'text', 'invalid_request')
    rows = bundle['rows']
    require(isinstance(rows, list) and len(rows) <= MAX_ROWS, 'resource_limit')
    paths, keys, fanouts = [], set(), {seed: 0 for seed in seeds}
    for row in rows:
        budget.check()
        logical = row['logical_key']
        require(isinstance(logical, str) and 0 < len(logical) <= 16384 and logical not in keys, 'source_invalid')
        keys.add(logical)
        values = row['values']
        require(all(name in values for name in names), 'source_invalid')
        left = _value(values[source], kind, 'source_invalid')
        right = _value(values[target], kind, 'source_invalid')
        label = _value(values[type_field], 'text', 'source_invalid')
        if label != edge_type:
            continue
        matches = []
        if direction in ('out', 'both') and left in seeds:
            matches.append((left, right, 'out'))
        if direction in ('in', 'both') and right in seeds and not (direction == 'both' and left == right):
            matches.append((right, left, 'in'))
        for seed, neighbor, traversal in matches:
            budget.check()
            fanouts[seed] += 1
            require(fanouts[seed] <= max_fanout and len(paths) < max_edges, 'resource_limit',
                    'graph path or fanout budget exceeded')
            paths.append({'logical_key': logical, 'record_version': row.get('record_version', bundle['revision']),
                          'source': left, 'target': right, 'type': label,
                          'seed': seed, 'neighbor': neighbor, 'direction': traversal})
    paths.sort(key=lambda path: (path['logical_key'], path['seed'], path['direction']))
    budget.check()
    return {'paths': [public_values(path) for path in paths], 'read_context': bundle['context'],
            'truncated': False, 'stats': {'records_examined': len(rows), 'paths': len(paths),
                                        'max_edges': max_edges, 'max_fanout': max_fanout}}
