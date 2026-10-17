"""Durable bounded jobs and pins, shared by the single M1 serving process."""
import uuid

from psycopg.types.json import Jsonb

from modules.common.contracts import require
from modules.catalog.control import Control


class Jobs:
    def __init__(self, control, worker):
        self.control, self.worker = control, worker

    def submit(self, principal, dataset, kind, request, view=None):
        with self.control.transaction() as conn:
            conn.execute('SELECT pg_advisory_xact_lock(7101701)')
            require(conn.execute('SELECT count(*) AS n FROM gura_m1.jobs').fetchone()['n'] < 128, 'resource_limit')
            ds = Control.authorize(conn, principal, dataset)
            ds = conn.execute('SELECT * FROM gura_m1.datasets WHERE id=%s FOR UPDATE', (dataset,)).fetchone()
            require(ds['published'] is not None, 'not_ready')
            chosen = ds['published']
            if view is not None:
                require(isinstance(view, str) and view.startswith('view_'), 'invalid_request')
                chosen = uuid.UUID(view[5:])
            run = conn.execute('SELECT * FROM gura_m1.runs WHERE id=%s AND dataset=%s FOR UPDATE', (chosen,dataset)).fetchone()
            require(run is not None and run['status'] == 'published', 'view_unavailable')
            job = uuid.uuid4()
            conn.execute("INSERT INTO gura_m1.pins(run,owner,scope) VALUES(%s,%s,'job')", (run['id'], str(job)))
            return conn.execute("INSERT INTO gura_m1.jobs(id,dataset,run,tenant,subject,token_sha256,kind,status,request,context,worker) "
                                "VALUES(%s,%s,%s,%s,%s,%s,%s,'queued',%s,%s,%s) RETURNING *",
                                (job,dataset,run['id'],principal['tenant'],principal['subject'],principal['token_sha256'],kind,
                                 Jsonb(request),Jsonb(run['artifact']['context']),self.worker)).fetchone()

    def get(self, job, principal):
        with self.control.transaction() as conn:
            row = conn.execute('SELECT * FROM gura_m1.jobs WHERE id=%s', (job,)).fetchone()
            require(row is not None and (row['tenant'],row['subject']) == (principal['tenant'],principal['subject']), 'not_found')
            Control.authorize(conn, principal, row['dataset'])
            return row

    def active(self, job, principal):
        with self.control.transaction() as conn:
            row = conn.execute('SELECT * FROM gura_m1.jobs WHERE id=%s FOR UPDATE', (job,)).fetchone()
            require(row is not None and not row['cancelled'] and row['worker'] == self.worker and row['status'] in ('queued','running'), 'cancelled')
            Control.authorize(conn, principal, row['dataset'])
            conn.execute("UPDATE gura_m1.jobs SET status='running' WHERE id=%s AND status='queued'", (job,))
            return row

    def cancelled(self, job):
        with self.control.transaction() as conn:
            row = conn.execute('SELECT cancelled FROM gura_m1.jobs WHERE id=%s', (job,)).fetchone()
            return row is None or row['cancelled']

    def finish(self, job, principal, result=None, error=None):
        with self.control.transaction() as conn:
            row = conn.execute('SELECT * FROM gura_m1.jobs WHERE id=%s FOR UPDATE', (job,)).fetchone()
            if row is None or row['worker'] != self.worker or row['status'] not in ('queued','running'):
                return
            status = 'cancelled' if row['cancelled'] else ('failed' if error else 'succeeded')
            if not error and status != 'cancelled':
                # This authorization transaction is the result publication point.
                Control.authorize(conn, principal, row['dataset'])
            conn.execute('UPDATE gura_m1.jobs SET status=%s,result=%s,error=%s WHERE id=%s',
                         (status,Jsonb(result) if status=='succeeded' else None,error,job))
            if row['kind'] != 'export' or status != 'succeeded':
                conn.execute("DELETE FROM gura_m1.pins WHERE run=%s AND owner=%s AND scope='job'", (row['run'],str(job)))

    def cancel(self, job, principal):
        row = self.get(job, principal)
        with self.control.transaction() as conn:
            # Completion and cancel serialize on the job row, so terminal states never reverse.
            conn.execute("UPDATE gura_m1.jobs SET cancelled=true WHERE id=%s AND status IN ('queued','running')", (job,))
        return self.get(job, principal)

    def release(self, job, principal, cleanup):
        row = self.get(job, principal)
        require(row['status'] in ('succeeded','failed','cancelled'), 'not_ready')
        with self.control.transaction() as conn:
            current = conn.execute('SELECT * FROM gura_m1.jobs WHERE id=%s FOR UPDATE',(job,)).fetchone()
            require(current is not None, 'not_found')
            Control.authorize(conn, principal, current['dataset'])
            cleanup()  # A crash keeps the durable row/pin so release can be reconciled/retried.
            conn.execute("DELETE FROM gura_m1.pins WHERE run=%s AND owner=%s AND scope='job'", (row['run'],str(job)))
            conn.execute('DELETE FROM gura_m1.jobs WHERE id=%s', (job,))

    def recover(self):
        # Called only after acquiring the process-lifetime PG advisory lock.
        with self.control.transaction() as conn:
            rows = conn.execute("UPDATE gura_m1.jobs SET status='failed',error='worker_restarted' "
                                "WHERE status IN ('queued','running') RETURNING id,run").fetchall()
            for row in rows:
                conn.execute("DELETE FROM gura_m1.pins WHERE run=%s AND owner=%s AND scope='job'", (row['run'],str(row['id'])))
            conn.execute("DELETE FROM gura_m1.pins WHERE scope='query'")
            return len(rows)
