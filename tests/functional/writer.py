"""Real PG/Iceberg writer test driver, including process-death source outcomes."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT/'scripts')]

from m0lib.kit import laboratory
from m1lib.fixtures import pg
from modules.catalog.managed import Managed
from modules.common.contracts import Failure
from modules.connectors.writer import Writer, validate


def row(n):
    return {'id': n, 'title': 'entry '+str(n), 'active': n % 2 == 0}


def reject(code, call):
    try:
        call()
    except Failure as error:
        assert error.code == code, (code, error.code)
    else:
        raise AssertionError('expected '+code)


def run(directory):
    directory = Path(directory).resolve()
    with laboratory(directory/'lab') as lab:
        _, _, dsn = pg(lab)
        managed = Managed(dsn)
        managed.initialize()
        writer = Writer(directory/'warehouse', 'documents')
        writer.initialize(managed)
        first = writer.append(managed, 'first', [row(1), row(2)])
        assert writer.append(managed, 'first', [row(1), row(2)])['snapshot_id'] == first['snapshot_id']
        reject('operation_conflict', lambda: writer.append(managed, 'first', [row(3)]))
        reject('duplicate_key', lambda: writer.append(managed, 'duplicate', [row(2)]))
        old = managed.prepare('documents', 'old', validate([row(4)]))
        managed.prepare('documents', 'new', validate([row(5)]))
        reject('stale_generation', lambda: writer.commit(managed, old, [row(4)]))
        writer.append(managed, 'new', [row(5)])
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _: Writer(writer.root, 'documents').append(managed, 'concurrent', [row(6)]), range(2)))
        assert results[0]['snapshot_id'] == results[1]['snapshot_id']
        # Real process death, not a rolled-back mock: parent intent survives,
        # and after_source leaves an actual committed Iceberg snapshot.
        for n, stage in ((7, 'before_source'), (8, 'after_source'), (9, 'after_confirm')):
            operation = 'crash-'+stage
            code = """
import os,sys,json
from modules.catalog.managed import Managed
from modules.connectors.writer import Writer
root,dsn,operation,rows,stage=sys.argv[1:]
def fault(point):
    if point == stage: os._exit(71)
Writer(root,'documents').append(Managed(dsn),operation,json.loads(rows),fault)
"""
            child = subprocess.run([sys.executable, '-c', code, str(writer.root), dsn, operation,
                                    json.dumps([row(n)]), stage], cwd=ROOT, capture_output=True, timeout=30)
            assert child.returncode == 71, child.stderr.decode()
            restored = Writer(writer.root, 'documents').append(Managed(dsn), operation, [row(n)])
            assert restored['snapshot_id']
        # Definitively uncommitted intent is durably aborted before a new op.
        def interrupted(stage):
            if stage == 'before_source':
                raise RuntimeError('injected interruption')
        try:
            writer.append(managed, 'abandoned', [row(12)], interrupted)
        except RuntimeError:
            pass
        writer.append(managed, 'replacement', [row(13)])
        reject('operation_aborted', lambda: writer.append(managed, 'abandoned', [row(12)]))
        # Original confirmed results remain byte-for-byte stable across appends.
        assert writer.append(managed, 'first', [row(1), row(2)]) == first
        # Independent fresh catalog/reader, separate from Writer.table/append.
        from pyiceberg.catalog import load_catalog
        oracle = load_catalog('managed', type='sql', uri='sqlite:///'+str(writer.root/'catalog.db'))
        table = oracle.load_table(('managed', 'documents'))
        actual = sorted(table.scan().to_arrow().to_pylist(), key=lambda r: r['id'])
        assert actual == [row(n) for n in (1, 2, 5, 6, 7, 8, 9, 13)], actual
        assert len(table.snapshots()) == 7
        # Detect unsupported mutation history/schema instead of accepting it.
        with table.update_schema() as update:
            from pyiceberg.types import StringType
            update.add_column('extra', StringType())
        reject('unsupported_source', lambda: writer.append(managed, 'schema-change', [row(10)]))
        delete_writer = Writer(directory/'delete-warehouse', 'deletes')
        delete_writer.initialize(managed)
        delete_writer.append(managed, 'seed', [row(1), row(2)])
        delete_writer.table().delete('id = 1')
        reject('unsupported_source', lambda: delete_writer.append(managed, 'after-delete', [row(3)]))
        head_writer = Writer(directory/'head-warehouse', 'heads')
        head_writer.initialize(managed)
        head_first = head_writer.append(managed, 'head-first', [row(1)])
        head_writer.append(managed, 'head-second', [row(2)])
        head_table = head_writer.table()
        from pyiceberg.table.update import SetSnapshotRefUpdate
        head_writer.catalog().commit_table(head_table, (), (SetSnapshotRefUpdate(
            ref_name='main', type='branch', snapshot_id=head_first['snapshot_id']),))
        reject('source_outcome_unknown', lambda: head_writer.append(managed, 'after-rollback', [row(3)]))
        budget_writer = Writer(directory/'budget-warehouse', 'budgets')
        budget_writer.initialize(managed)
        for n in range(4):
            budget_writer.append(managed, 'budget-'+str(n), [{'id': n, 'title': 'x'*(1800 << 10), 'active': True}])
        reject('resource_limit', lambda: budget_writer.append(managed, 'budget-overflow',
               [{'id': 5, 'title': 'x'*(1800 << 10), 'active': True}]))
        assert len(budget_writer.table().snapshots()) == 4
        report = {'status': 'passed', 'rows': len(actual), 'snapshots': 7,
                  'cases': ['independent-reader','duplicate','conflict','stale-generation',
                            'concurrent-identical','before-source-crash','after-source-crash',
                            'after-confirm-crash','schema-change-rejected','delete-history-rejected',
                            'definitive-abort','stable-confirmed-result','external-head-change-rejected','cross-batch-byte-budget']}
        (directory/'writer-report.json').write_text(json.dumps(report, indent=2)+'\n')
        return report


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-dir', required=True)
    print(json.dumps(run(parser.parse_args().run_dir)))
