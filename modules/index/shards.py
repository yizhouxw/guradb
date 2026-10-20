"""Immutable local serving partitions derived from one authoritative snapshot."""
from io import BytesIO
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from modules.common.contracts import MAX_BYTES, encoded, require
from modules.index.ann import build_many, partitions_for
from modules.storage.objects import put


def build(bundle, directory, budget):
    """Build three immutable serving files and optional per-partition ANN indexes."""
    return _build(bundle, directory, budget)['shards']


def build_snapshot(bundle, root, budget, ann_config=None):
    """Construct global and serving indexes together without sharing datasets."""
    global_ann = (Path(root)/'lance', ann_config) if ann_config is not None else None
    return _build(bundle, Path(root)/'shards', budget, global_ann)


def _build(bundle, directory, budget, global_ann=None):
    directory = Path(directory)
    rows = sorted(bundle['rows'], key=lambda row: row['logical_key'])
    partitions = (partitions_for(global_ann[1], len(rows)) if global_ann is not None else
                  bundle.get('ann', {}).get('partitions'))
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
        if partitions is not None:
            if len(selected) >= partitions * 16:
                pending.append((item, directory/str(shard)/'ann', selected))
            else:
                item['vector_fallback'] = 'exact-small-shard'
        result.append(item)
    entries = [(path, selected) for _, path, selected in pending]
    if global_ann is not None:
        entries.insert(0, (global_ann[0], rows))
    snapshot = {'shards': result}
    if entries:
        indexes = build_many(entries,
                             bundle['revision'], bundle['model'], {'partitions': partitions}, budget)
        if global_ann is not None:
            snapshot['ann'] = indexes.pop(0)
        for (item, _, _), index in zip(pending, indexes):
            item['ann'] = index
    return snapshot
