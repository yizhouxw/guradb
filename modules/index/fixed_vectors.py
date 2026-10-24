"""Finite three-dimensional exact squared distances over explicit eligibility."""
import math
from modules.common.cf1a_primitives import canonical, require
from modules.index.fixed_layout import from_hex


def configuration():
    return {'model_id': 'outline-synthetic-zh-image3', 'model_version': '1', 'dimension': 3,
            'metric': 'squared_l2', 'analyzer': 'none',
            'processing_version': 'zh-CN-hand-segmented-v1', 'normalization': 'none',
            'null_policy': 'explicit-mask-exclude', 'component_bound': '1e150',
            'distance_sum': 'binary64-fsum-dimension-order'}


def validate_configuration(value):
    require(canonical(value) == canonical(configuration()), 'unsupported exact vector configuration')


def materialize(rows):
    values = [{'record_id': row['record_id'], 'record_version': row['record_version'],
               'vector_f64_hex': row['vector_f64_hex']} for row in rows if row['vector_state'] == 'present']
    return values, {'source_count': len(rows), 'vector_count': len(values),
                    'null_count': len(rows) - len(values)}


def validate_materialized(vectors, statistics, rows):
    expected_rows, expected_stats = materialize(rows)
    require(canonical(vectors) == canonical(expected_rows) and canonical(statistics) == canonical(expected_stats),
            'vector value/mask ledger mismatch')


def score(vectors, query_vector, checkpoint):
    require(len(query_vector) == 3, 'wrong exact vector dimension')
    query = [from_hex(value, True) for value in query_vector]
    for row in vectors:
        checkpoint()
        values = [from_hex(value, True) for value in row['vector_f64_hex']]
        distance = math.fsum((left - right) ** 2 for left, right in zip(values, query))
        require(math.isfinite(distance) and distance >= 0, 'invalid squared distance')
        yield row['record_id'], distance
