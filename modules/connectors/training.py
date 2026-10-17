"""Deterministic training splits and aligned Parquet export of a fixed view."""
from io import BytesIO
import hashlib
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from modules.common.contracts import MAX_BYTES, digest, encoded, public_media, public_values, require
from modules.storage.objects import put


def export(bundle, request, directory, budget):
    require(set(request) <= {'seed','train_basis_points'}, 'invalid_request')
    seed, threshold = request.get('seed', '0'), request.get('train_basis_points', 8000)
    require(isinstance(seed, str) and len(seed) <= 128 and type(threshold) is int and 0 <= threshold <= 10000, 'invalid_request')
    samples = []
    for row in sorted(bundle['rows'], key=lambda row: row['logical_key']):
        budget.check()
        identity = [bundle['manifest']['dataset_id'], 'record', row['logical_key']]
        bucket = int.from_bytes(hashlib.sha256(encoded([seed, identity])).digest()[:8], 'big') % 10000
        samples.append({'dataset_id': identity[0], 'entity_kind': 'record', 'logical_key': row['logical_key'],
                        'record_version': bundle['revision'], 'split': 'train' if bucket < threshold else 'validation',
                        'values_json': encoded(public_values(row['values'])).decode(), 'vector': row['vector'],
                        'media_json': encoded(public_media(row['media'])).decode()})
    schema = pa.schema([pa.field('dataset_id', pa.string(), False), pa.field('entity_kind', pa.string(), False),
                        pa.field('logical_key', pa.string(), False), pa.field('record_version', pa.string(), False),
                        pa.field('split', pa.string(), False), pa.field('values_json', pa.string(), False),
                        pa.field('vector', pa.list_(pa.float64()), False), pa.field('media_json', pa.string(), False)])
    table = pa.Table.from_pylist(samples, schema=schema)
    require(table.nbytes <= 64 << 20, 'resource_limit', 'training Arrow budget exceeded')
    sink = BytesIO()
    pq.write_table(table, sink, compression='snappy')
    parquet = sink.getvalue()
    require(len(parquet) <= MAX_BYTES, 'resource_limit', 'training Parquet exceeds download budget')
    artifact = put(Path(directory) / (digest(parquet)+'.parquet'), parquet)
    manifest = {'version': 1, 'read_context': bundle['context'], 'model': bundle['model'],
                'retention_mode': bundle['retention_mode'], 'seed': seed, 'train_basis_points': threshold,
                'rows': len(samples), 'samples': samples, 'parquet': artifact}
    raw = encoded(manifest)
    require(len(raw) <= MAX_BYTES-4096, 'resource_limit', 'training manifest exceeds response budget')
    return {'manifest': put(Path(directory)/(digest(raw)+'.json'), raw), 'parquet': artifact,
            'read_context': bundle['context'], 'rows': len(samples)}
