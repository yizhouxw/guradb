"""Real PG inspection truth and CLI redaction of credentials and source details."""
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

from psycopg.types.json import Jsonb

from m0lib.kit import DATASET, laboratory
from m1lib.fixtures import pg
from modules.catalog.managed import Managed
from modules.common.contracts import digest
from scripts.inspect_state import inspect, WARNING


def run(directory):
    with laboratory(Path(directory).resolve()) as lab:
        control, _, dsn = pg(lab)
        control.register(DATASET, 'private-tenant', 'secret_dataset',
                         {'root': 'file:///secret-source?credential=secret', 'key_field': 'id', 'text_field': 'title'})
        control.grant(digest(b'secret-token'), 'private-tenant', 'secret-subject', DATASET)
        run = control.begin(DATASET, 'private-operation', {'snapshot_id': 123, 'incremental': {}, 'secret-query': 'select secret'})
        control.fail(run['id'], 'source_invalid')
        ready = control.begin(DATASET, 'published-operation', {'snapshot_id': 124})
        control.ready(ready['id'], {'context': {'view': 'state-contract'}})
        control.publish(ready['id'], 0)
        with control.transaction() as conn:
            conn.execute("INSERT INTO gura_m1.pins(run,owner,scope) VALUES(%s,%s,'job')",
                         (ready['id'], 'secret-owner'))
            for kind, status, error in [('export', 'succeeded', None), ('search', 'failed', 'secret-query')]:
                conn.execute("INSERT INTO gura_m1.jobs(id,dataset,run,tenant,subject,token_sha256,kind,status,request,context,error,worker) "
                             "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                             (uuid.uuid4(), DATASET, ready['id'], 'private-tenant', 'secret-subject', digest(b'secret-token'),
                              kind, status, Jsonb({'secret-query': 'select secret'}), Jsonb({}), error, uuid.uuid4()))
        managed = Managed(dsn)
        managed.initialize()
        managed.register('secret_table', '/secret-managed-path')
        managed.prepare('secret_table', 'secret_operation', digest(b'secret rows'))
        result = inspect(dsn)
        assert result['warning'] == WARNING and result['grant_count'] == 1
        assert result['datasets'][0]['generation'] == 2
        assert result['freshness'][0]['discovered'] == '123'
        assert result['freshness'][0]['applied'] is None
        assert result['freshness'][0]['error_code'] == 'source_invalid'
        assert result['freshness'][1]['published'] == '124'
        assert result['pins'] == [{'run': str(ready['id']), 'scope': 'job', 'count': 1}]
        assert result['jobs'] == [{'kind': 'export', 'status': 'succeeded', 'count': 1},
                                  {'kind': 'search', 'status': 'failed', 'count': 1}]
        assert result['job_errors'] == {'redacted': 1}
        assert result['managed_intents'] == [{'status': 'prepared', 'count': 1}]
        command = [sys.executable, str(Path(__file__).resolve().parents[2]/'scripts/inspect_state.py')]
        child = subprocess.run(command, env=dict(os.environ, GURADB_PG_DSN=dsn), text=True,
                               capture_output=True, check=True, timeout=10)
        serialized = child.stdout
        for forbidden in ('secret', 'private', 'file://', 'select ', dsn, digest(b'secret-token')):
            assert forbidden not in serialized, forbidden
        assert json.loads(serialized)['freshness'] == result['freshness']
        missing = subprocess.run(command + ['--dsn-env', 'GURADB_INSPECTION_ABSENT_TEST'],
                                 env={k:v for k,v in os.environ.items() if k != 'GURADB_INSPECTION_ABSENT_TEST'},
                                 text=True, capture_output=True, timeout=10)
        assert missing.returncode == 1 and not missing.stderr
        assert json.loads(missing.stdout) == {'error': 'inspection_unavailable'}
        return {'passed': True, 'scope': 'read-only current PG state and redaction; not historical security audit'}
