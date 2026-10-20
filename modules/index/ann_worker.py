"""Private native Lance worker, called only with trusted bounded local task files."""
from pathlib import Path
import sys
import resource

from modules.common.contracts import MAX_BYTES, Failure, decode_json, encoded, require


def execute(task):
    import lance
    import pyarrow as pa

    if task['kind'] == 'build-many':
        tasks = task['tasks']
        require(isinstance(tasks, list) and 1 <= len(tasks) <= 4 and
                all(value['kind'] == 'build' for value in tasks), 'invalid_request')
        return [execute(value) for value in tasks]
    if task['kind'] == 'build':
        model, rows = task['model'], task['rows']
        schema = pa.schema([pa.field('logical_key', pa.string(), nullable=False),
                            pa.field('record_version', pa.string(), nullable=False),
                            pa.field('vector', pa.list_(pa.float32(), model['dimension']), nullable=False)])
        table = pa.Table.from_pylist([{'logical_key': r['logical_key'], 'record_version': r.get('record_version', task['revision']),
                                      'vector': r['vector']} for r in rows], schema=schema)
        dataset = lance.write_dataset(table, task['path'], mode='create')
        dataset.create_index('vector', index_type='IVF_FLAT', metric='l2', num_partitions=task['partitions'])
        return {'version': dataset.version}
    require(task['kind'] == 'query', 'invalid_request')
    index = task['index']
    dataset = lance.dataset(index['path'], version=index['version'])
    require(dataset.count_rows() == index['rows'], 'source_invalid')
    return dataset.to_table(columns=['logical_key', 'record_version', '_distance'],
        filter=task['condition'], prefilter=True,
        nearest={'column': 'vector', 'q': task['query'], 'k': task['limit'],
                 'nprobes': task['probes'], 'use_index': True}).to_pylist()


def main():
    try:
        with Path(sys.argv[1]).open('rb') as source:
            raw = source.read(MAX_BYTES+1)
        require(len(raw) <= MAX_BYTES, 'resource_limit')
        value = execute(decode_json(raw))
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        native_rss = int(rss if sys.platform == 'darwin' else rss * 1024)
        require(native_rss <= 512 << 20, 'resource_limit', 'native RSS budget exceeded')
        result = {'result': {'value': value, 'native_rss_bytes': native_rss}}
    except Exception as error:
        result = {'error': error.code if isinstance(error, Failure) else 'native_failed'}
    raw = encoded(result)
    require(len(raw) <= MAX_BYTES, 'resource_limit')
    Path(sys.argv[2]).write_bytes(raw)


if __name__ == '__main__':
    main()
