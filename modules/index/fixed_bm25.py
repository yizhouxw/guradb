"""Materialized term frequencies with complete-source BM25 statistics, not seek."""
from collections import Counter
import math
from modules.common.cf1a_primitives import canonical, require
from modules.index.fixed_layout import closed, count, f64_hex, tokens


def configuration(text_field_id):
    count(text_field_id, (1 << 53) - 1)
    require(text_field_id > 0, 'missing BM25 source field')
    return {'model_id': 'bm25-fixed-tokens', 'model_version': '1', 'dimension': 1,
            'metric': 'bm25', 'analyzer': 'fixed-whitespace-v1',
            'processing_version': 'zh-CN-hand-segmented-v1', 'text_field_id': text_field_id,
            'k1_f64_hex': f64_hex(1.2), 'b_f64_hex': f64_hex(.75),
            'statistics': 'all-source-rows-before-filter', 'null_policy': 'count-empty',
            'query_terms': 'preserve-duplicates', 'normalization': 'none'}


def validate_configuration(value):
    require(type(value) is dict and 'text_field_id' in value, 'missing BM25 configuration')
    require(canonical(value) == canonical(configuration(value['text_field_id'])), 'unsupported BM25 configuration')


def materialize(rows):
    documents, dfs, total = [], Counter(), 0
    for row in rows:
        tf = Counter(row['tokens'])
        documents.append({'record_id': row['record_id'], 'record_version': row['record_version'],
                          'length': len(row['tokens']), 'terms': [[term, tf[term]] for term in sorted(tf)]})
        dfs.update(tf.keys())
        total += len(row['tokens'])
    require(len(dfs) <= 4096, 'too many BM25 terms')
    return documents, {'document_count': len(rows), 'total_tokens': total,
                       'document_frequencies': [[term, dfs[term]] for term in sorted(dfs)]}


def validate_materialized(documents, statistics, rows):
    expected_rows, expected_stats = materialize(rows)
    require(canonical(documents) == canonical(expected_rows) and canonical(statistics) == canonical(expected_stats),
            'BM25 ledger/statistics mismatch')


def score(documents, statistics, query_text, checkpoint):
    query_terms = tokens(query_text)
    require(bool(query_terms), 'BM25 query has no tokens')
    closed(statistics, ('document_count', 'total_tokens', 'document_frequencies'))
    n, total = statistics['document_count'], statistics['total_tokens']
    df = dict(statistics['document_frequencies'])
    if not total:
        return
    average = total / n
    for row in documents:
        checkpoint()
        tf = dict(row['terms'])
        value = 0.0
        for term in query_terms:
            frequency = tf.get(term, 0)
            if frequency:
                inverse = math.log1p((n - df[term] + .5) / (df[term] + .5))
                denominator = frequency + 1.2 * (.25 + .75 * row['length'] / average)
                value += inverse * frequency * 2.2 / denominator
        require(math.isfinite(value) and value >= 0, 'invalid BM25 score')
        if value > 0:
            yield row['record_id'], value
