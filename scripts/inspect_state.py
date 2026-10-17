#!/usr/bin/env python3
"""Read-only local operator snapshot; never export credentials, queries or source URIs."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sys

import psycopg
from psycopg.rows import dict_row

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

WARNING = '这是当前状态快照不是不可篡改/全历史安全审计'


ERROR_CODES = frozenset(('source_invalid source_unavailable source_conflict source_outcome_unknown '
                         'history_gap unsupported_change unsupported_source invalid_request invalid_key '
                         'invalid_features invalid_vector model_mismatch resource_limit cancelled build_failed '
                         'worker_failed worker_mismatch not_found not_ready operation_conflict operation_busy '
                         'index_unavailable artifact_conflict stale_generation invalid_definition').split())


def _code(value):
    return value if value in ERROR_CODES else 'redacted'


def inspect(dsn):
    """Take one repeatable-read transaction, selecting only operational fields."""
    with psycopg.connect(dsn, connect_timeout=3, row_factory=dict_row) as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        conn.execute("SET LOCAL statement_timeout='5s'")
        at = conn.execute('SELECT transaction_timestamp() AS at').fetchone()['at'].isoformat()
        datasets = conn.execute('SELECT id,generation,epoch,published FROM gura_m1.datasets ORDER BY id').fetchall()
        runs = conn.execute("SELECT id,dataset,status,published_epoch,artifact IS NOT NULL AS ready,"
                            "target ? 'incremental' AS incremental,"
                            "CASE WHEN jsonb_typeof(target->'snapshot_id')='number' THEN target->>'snapshot_id' END AS snapshot,"
                            "error FROM gura_m1.runs ORDER BY created,id").fetchall()
        pins = conn.execute('SELECT run,scope,count(*) AS count FROM gura_m1.pins GROUP BY run,scope ORDER BY run,scope').fetchall()
        jobs = conn.execute('SELECT kind,status,error FROM gura_m1.jobs').fetchall()
        grants = conn.execute('SELECT count(*) AS count FROM gura_m1.grants').fetchone()['count']
        managed = conn.execute("SELECT to_regclass('gura_managed.intents') AS relation").fetchone()['relation']
        intents = conn.execute('SELECT status,count(*) AS count FROM gura_managed.intents GROUP BY status ORDER BY status').fetchall() if managed else []
    freshness = []
    for run in runs:
        applied = run['ready'] and run['status'] in ('ready', 'published', 'retiring', 'retired')
        freshness.append({'run_id': str(run['id']), 'dataset_id': str(run['dataset']), 'status': run['status'],
                          'incremental': run['incremental'], 'discovered': run['snapshot'],
                          'applied': run['snapshot'] if applied else None,
                          'indexed': run['snapshot'] if applied else None,
                          'published': run['snapshot'] if run['published_epoch'] is not None else None,
                          'error_code': _code(run['error']) if run['error'] else None})
    job_counts, errors = Counter(), Counter()
    for job in jobs:
        kind = job['kind'] if job['kind'] in ('scan', 'search', 'graph', 'export') else 'other'
        status = job['status'] if job['status'] in ('queued', 'running', 'succeeded', 'failed', 'cancelled') else 'other'
        job_counts[kind, status] += 1
        if job['error']:
            errors[_code(job['error'])] += 1
    return {'format': 'guradb-inspection-v1', 'warning': WARNING, 'captured_at': at,
            'datasets': [{**row, 'id': str(row['id']), 'published': str(row['published']) if row['published'] else None} for row in datasets],
            'freshness': freshness, 'pins': [{**row, 'run': str(row['run'])} for row in pins],
            'jobs': [{'kind': kind, 'status': status, 'count': count} for (kind, status), count in sorted(job_counts.items())],
            'job_errors': dict(sorted(errors.items())), 'grant_count': grants, 'managed_intents': intents}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dsn-env', default='GURADB_PG_DSN')
    args = parser.parse_args()
    try:
        result = inspect(os.environ[args.dsn_env])
    except (KeyError, psycopg.Error):
        print(json.dumps({'error': 'inspection_unavailable'}))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
