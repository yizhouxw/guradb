"""Tantivy BM25 + exhaustive L2 + deterministic RRF on one immutable bundle."""
import json
import math
from pathlib import Path
import re

import tantivy

from modules.common.contracts import MAX_ROWS, encoded, public_media, public_values, require
from modules.storage.objects import get, put
from modules.index.ann import candidates

ANALYZER = 'ascii-alnum-lower-v1'


def analyzer():
    return tantivy.TextAnalyzerBuilder(tantivy.Tokenizer.regex('[A-Za-z0-9]+')).filter(tantivy.Filter.lowercase()).build()


def vector(value, dimension):
    require(isinstance(value, list) and len(value) == dimension, 'invalid_vector')
    require(all(type(v) in (int, float) and abs(v) <= 1e6 and math.isfinite(v) for v in value), 'invalid_vector')
    return [float(v) for v in value]


def features(rows, value, text_field):
    require(set(value) == {'model', 'dimension', 'metric', 'preprocessing', 'records'}, 'invalid_features')
    require(isinstance(value['model'], str) and 0 < len(value['model']) <= 128, 'invalid_features')
    require(type(value['dimension']) is int and 1 <= value['dimension'] <= 256 and
            value['metric'] == 'squared_l2' and value['preprocessing'] == 'identity-v1', 'invalid_features')
    require(len(value['records']) == len(rows) <= MAX_ROWS, 'invalid_features')
    mapping = {}
    for record in value['records']:
        require(set(record) == {'logical_key', 'vector', 'media'} and record['logical_key'] not in mapping, 'invalid_features')
        require(isinstance(record['media'], list) and len(record['media']) <= 4, 'invalid_features')
        for media in record['media']:
            require(set(media) == {'uri', 'sha256', 'size_bytes'} and isinstance(media['uri'], str) and
                    isinstance(media['sha256'], str) and len(media['sha256']) == 64 and
                    type(media['size_bytes']) is int and media['size_bytes'] > 0, 'invalid_features')
        mapping[record['logical_key']] = {'vector': vector(record['vector'], value['dimension']), 'media': record['media']}
    require(set(mapping) == {r['logical_key'] for r in rows}, 'invalid_features', 'feature identity coverage differs from snapshot')
    for row in rows:
        text = row['values'].get(text_field)
        require(text_field in row['values'] and (text is None or isinstance(text, str)), 'invalid_features')
        row.update(mapping[row['logical_key']])
    return {k: value[k] for k in ('model', 'dimension', 'metric', 'preprocessing')}


def build(directory, rows, text_field, budget):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    schema = tantivy.SchemaBuilder()
    schema.add_text_field('logical_key', stored=True, tokenizer_name='raw')
    schema.add_text_field('body', tokenizer_name=ANALYZER)
    schema = schema.build()
    index = tantivy.Index(schema, path=str(directory), reuse=False)
    index.register_tokenizer(ANALYZER, analyzer())
    writer = index.writer(heap_size=16_000_000, num_threads=1)
    for row in rows:
        budget.check()
        writer.add_document(tantivy.Document.from_dict({'logical_key': row['logical_key'], 'body': row['values'][text_field] or ''}, schema))
    writer.commit()
    writer.wait_merging_threads()
    return [put(path, path.read_bytes()) for path in sorted(directory.iterdir()) if path.is_file() and not path.name.startswith('.')]


def load_bundle(reference, budget):
    def read(reference):
        budget.check()
        raw = get(reference)
        budget.artifact(len(raw))
        return raw
    raw = read(reference)
    if 'incremental' in reference:
        read(reference['incremental'])
    bundle = json.loads(raw)
    require(bundle['version'] == 1 and 0 < len(bundle['rows']) <= MAX_ROWS, 'source_invalid')
    for dependency in bundle['source']['dependencies']:
        budget.check()
        read(dependency['copy'])
    for reference in bundle['index_files'] + bundle.get('ann', {}).get('files', []):
        budget.check()
        read(reference)
    require(read(bundle['manifest_reference']) == encoded(bundle['manifest']), 'source_invalid')
    for fragment in bundle['manifest']['files']:
        budget.check()
        read({'path': str(Path(bundle['manifest']['backend']['root']) / fragment['key']), 'sha256': fragment['sha256']})
    return bundle


def search(bundle, request, budget):
    require(set(request) <= {'text', 'vector', 'model', 'top_k', 'candidate_limit', 'filter', 'vector_index', 'nprobes'}, 'invalid_request')
    mode = request.get('vector_index', 'exact')
    require(mode in ('exact', 'ann'), 'invalid_request')
    require(('vector_index' not in request and 'nprobes' not in request) or 'vector' in request, 'invalid_request')
    require('nprobes' not in request or mode == 'ann', 'invalid_request')
    k, limit = request.get('top_k', 10), request.get('candidate_limit', 100)
    require(type(k) is int and type(limit) is int and 1 <= k <= limit <= 1000, 'resource_limit')
    require('text' in request or 'vector' in request, 'invalid_request')
    rows = {row['logical_key']: row for row in bundle['rows']}
    allowed = set(rows)
    if 'filter' in request:
        selected = request['filter']
        require(isinstance(selected, dict) and set(selected) == {'field','equals'}, 'invalid_request')
        require(selected['field'] in {field['name'] for field in bundle['manifest']['schema']} and
                type(selected['equals']) in (str, int, bool, type(None)), 'invalid_request')
        value = selected['equals']
        field = next(f for f in bundle['manifest']['schema'] if f['name'] == selected['field'])
        if field['data_type'] == 'int8' and value is not None:
            if isinstance(value, str):
                require(re.fullmatch(r'-?(0|[1-9][0-9]*)',value) is not None and len(value) <= 20, 'invalid_request')
                parsed = int(value)
                require(str(parsed) == value and -(1<<63) <= parsed < (1<<63), 'invalid_request')
                value = parsed
            else:
                require(type(value) is int and abs(value) <= 9007199254740991, 'invalid_request')
        if value is not None and field['data_type'] != 'int8':
            require(type(value) is ({'text': str, 'bool': bool}[field['data_type']]), 'invalid_request')
        allowed = {key for key, row in rows.items() if type(row['values'][selected['field']]) is type(value) and
                   row['values'][selected['field']] == value}
    ranks, costs = [], {'records_examined': len(rows), 'candidate_limit': limit, 'artifact_reads': budget.artifact_reads, 'artifact_bytes': budget.artifact_bytes}
    if 'text' in request:
        text = request['text']
        require(isinstance(text, str) and len(text) <= 512 and re.fullmatch(r'[A-Za-z0-9 ]+', text) is not None, 'invalid_request')
        tokens = text.lower().split()
        require(0 < len(tokens) <= 16 and all(len(t) <= 40 for t in tokens), 'invalid_request')
        index = tantivy.Index.open(bundle['index_path'])
        index.register_tokenizer(ANALYZER, analyzer())
        index.reload()
        searcher = index.searcher()
        query = index.parse_query(' '.join(tokens), ['body'])
        hits = searcher.search(query, limit=len(rows)).hits
        ranked = [(searcher.doc(address).to_dict()['logical_key'][0], float(score)) for score, address in hits]
        ranked = sorted(((key, score) for key, score in ranked if key in allowed), key=lambda hit: (-hit[1], hit[0]))[:limit]
        ranks.append(ranked)
        costs['bm25_matches'] = len(hits)
    if 'vector' in request:
        require(request.get('model') == bundle['model']['model'], 'model_mismatch')
        query = vector(request['vector'], bundle['model']['dimension'])
        ranked = []
        if mode == 'ann':
            ranked, ann_costs = candidates(bundle, query, allowed, limit, request.get('nprobes'), budget)
            costs.update(ann_costs)
        else:
            for key in allowed:
                budget.check()
                distance = math.fsum((a-b)**2 for a,b in zip(rows[key]['vector'], query))
                ranked.append((key, -distance))
        ranks.append(sorted(ranked, key=lambda hit: (-hit[1], hit[0]))[:limit])
    else:
        require('model' not in request, 'invalid_request')
    scores = {}
    for ranked in ranks:
        for rank, (key, _) in enumerate(ranked, 1):
            scores[key] = scores.get(key, 0.0) + 1.0 / (60 + rank)
    if len(ranks) == 1:
        scores = dict(ranks[0])
    ordered = sorted(scores, key=lambda key: (-scores[key], key))[:k]
    budget.check()
    return {'hits': [{'logical_key': key, 'record_version': bundle['revision'], 'score': scores[key],
                      'values': public_values(rows[key]['values']), 'media': public_media(rows[key]['media'])} for key in ordered],
            'read_context': bundle['context'], 'stats': costs,
            'ranking': ('rrf-k60-ann' if mode == 'ann' else 'rrf-k60') if len(ranks) == 2 else ('bm25' if 'text' in request else mode+'-squared-l2')}
