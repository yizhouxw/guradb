"""Immutable local serving partitions derived from one authoritative snapshot."""
from io import BytesIO
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from modules.common.contracts import MAX_BYTES, encoded, require
from modules.index.ann import build_many
from modules.storage.objects import put


def build(bundle, directory, budget):
    """Build three immutable serving files and optional per-partition ANN indexes."""
    directory = Path(directory)
    rows = sorted(bundle['rows'], key=lambda row: row['logical_key'])
    result, total, pending = [], 0, []
    for shard in range(3):
        budget.check()
        selected = rows[shard::3]
        table = pa.table({'row_json': pa.array([encoded(row).decode() for row in selected], type=pa.string())})
        sink = BytesIO()
        pq.write_table(table, sink, compression='snappy')
        raw = sink.getvalue()
        total += len(raw)
        require(total <= MAX_BYTES, 'resource_limit')
        item = {'shard': shard, 'rows': len(selected), 'revision': bundle['revision'],
                'file': put(directory/str(shard)/'rows.parquet', raw)}
        if 'ann' in bundle:
            partitions = bundle['ann']['partitions']
            if len(selected) >= partitions * 16:
                pending.append((item, directory/str(shard)/'ann', selected))
            else:
                item['vector_fallback'] = 'exact-small-shard'
        result.append(item)
    if pending:
        indexes = build_many([(path, selected) for _, path, selected in pending],
                             bundle['revision'], bundle['model'], {'partitions': partitions}, budget)
        for (item, _, _), index in zip(pending, indexes):
            item['ann'] = index
    return result
