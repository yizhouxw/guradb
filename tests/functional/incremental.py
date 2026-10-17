"""Real PG refresh/replay/CAS and independent Iceberg append truth."""
import pyarrow as pa

from m0lib.kit import DATASET, laboratory
from m1lib.fixtures import feature_file, iceberg, pg, target
from modules.common.contracts import Budget, Failure
from modules.index.retrieval import load_bundle
from modules.query.incremental import progress, refresh
from modules.query.snapshot import construct, publish


def run(directory):
    with laboratory(directory) as lab:
        control, _, _ = pg(lab)
        lake = directory/'lake'
        table, _, rows = iceberg(lake)
        control.register(DATASET, 'tenant-a', 'documents',
                         {'root': lake.as_uri(), 'key_field': 'id', 'text_field': 'title'})
        first = construct(control, DATASET, 'base', target(table, feature_file(lake, rows)), directory/'builds')
        publish(control, first['id'], 0)
        old = load_bundle(first['artifact'], Budget())
        control.pin(first['id'], 'retained-old')
        extra = [{'id': 100, 'title': 'new database', 'active': True}]
        table.append(pa.Table.from_pylist(extra, schema=pa.schema([pa.field('id', pa.int64(), nullable=False), pa.field('title', pa.string()), pa.field('active', pa.bool_())])))
        selected = target(table, feature_file(lake, rows+extra))
        candidate = refresh(control, DATASET, 'append', selected, directory/'builds')
        assert candidate['status'] == 'ready'
        state = progress(control, candidate['id'])
        assert state['discovered'] == state['applied'] == state['indexed'] == str(selected['snapshot_id'])
        assert state['published'] is None and control.dataset(DATASET)['published'] == first['id']
        actual = load_bundle(candidate['artifact'], Budget())
        assert sorted([r['values'] for r in actual['rows']], key=lambda r:r['id']) == sorted(
            table.scan().to_arrow().to_pylist(), key=lambda r:r['id'])
        old_versions = {r['logical_key']: r['record_version'] for r in old['rows']}
        assert all(r['record_version'] == old_versions[r['logical_key']] for r in actual['rows']
                   if r['logical_key'] in old_versions)
        assert publish(control, candidate['id'], 1) == 2
        assert refresh(control, DATASET, 'append', selected, directory/'builds')['id'] == candidate['id']
        assert publish(control, candidate['id'], 1) == 2
        assert progress(control, candidate['id'])['published'] == str(selected['snapshot_id'])
        assert load_bundle(first['artifact'], Budget())['rows'] == old['rows']
        # A new append with a duplicate stable key is rejected by the full reader.
        table.append(pa.Table.from_pylist(extra, schema=pa.schema([pa.field('id', pa.int64(), nullable=False), pa.field('title', pa.string()), pa.field('active', pa.bool_())])))
        duplicate = target(table, feature_file(lake, rows+extra))
        try:
            refresh(control, DATASET, 'duplicate', duplicate, directory/'builds')
        except Failure as error:
            assert error.code == 'invalid_key', error.code
        else:
            raise AssertionError('duplicate logical key accepted')
        assert control.dataset(DATASET)['published'] == candidate['id']
        control.unpin(first['id'], 'retained-old')
    return {'passed': True, 'suite': 'incremental', 'assertions': 14,
            'oracles': ['PyIceberg independent append and scan', 'real PG CAS/replay'],
            'execution': 'append_data_and_index_rebuild'}
