"""One fixed-view async search/scan/export executor, with durable job outcomes."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import threading
import shutil
import time
import uuid

import psycopg

from modules.cluster.transport import endpoint, signature
from modules.catalog.control import Control
from modules.catalog.jobs import Jobs
from modules.common.contracts import Budget, Failure, encoded, public_media, public_values, require
from modules.connectors.training import export
from modules.index.retrieval import load_bundle, search
from modules.index.graph import expand
from modules.storage.objects import get, put
from modules.query.distributed import execute as distributed


class Service:
    def __init__(self, control, root, workers=0, worker_endpoints=None, worker_secret=None):
        require(workers in (0,3), 'invalid_request')
        self.workers = workers
        self.transport = None
        if worker_endpoints is not None:
            require(workers == 3 and len(worker_endpoints) == 3 and len(set(worker_endpoints)) == 3, 'invalid_request')
            for value in worker_endpoints:
                endpoint(value)
            signature(worker_secret, '', b'')
            self.transport = (worker_endpoints, worker_secret)
        self.control, self.root = control, Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.worker = uuid.uuid4()
        self.lease = psycopg.connect(control.dsn, connect_timeout=3, autocommit=True)
        if not self.lease.execute('SELECT pg_try_advisory_lock(7101702)').fetchone()[0]:
            self.lease.close()
            require(False, 'service_already_running')
        self.lease_lock = threading.Lock()
        self.failed = threading.Event()
        self.jobs = Jobs(control, self.worker)
        self.jobs.recover()
        self.pool = ThreadPoolExecutor(max_workers=2)
        self.capacity = threading.BoundedSemaphore(32)

    def check_lease(self):
        require(not self.failed.is_set(), 'service_unavailable', 'job persistence failed; restart required')
        with self.lease_lock:
            self.lease.execute('SELECT 1')

    def close(self):
        self.pool.shutdown(wait=True, cancel_futures=False)
        self.lease.close()

    def describe(self, principal, dataset):
        owner = 'describe-'+str(uuid.uuid4())
        with self.control.transaction() as conn:
            ds = Control.authorize(conn, principal, dataset)
            ds = conn.execute('SELECT * FROM gura_m1.datasets WHERE id=%s FOR UPDATE', (dataset,)).fetchone()
            require(ds['published'] is not None, 'not_ready')
            run = conn.execute('SELECT * FROM gura_m1.runs WHERE id=%s FOR UPDATE', (ds['published'],)).fetchone()
            require(run['status'] == 'published', 'not_ready')
            conn.execute("INSERT INTO gura_m1.pins(run,owner,scope) VALUES(%s,%s,'query')", (run['id'], owner))
        try:
            bundle = load_bundle(run['artifact'], Budget(seconds=10))
            return {'dataset_id': str(ds['id']), 'name': ds['name'], 'schema': bundle['manifest']['schema'],
                    'model': bundle['model'], 'read_context': bundle['context'], 'retention_mode': bundle['retention_mode']}
        finally:
            with self.control.transaction() as conn:
                conn.execute("DELETE FROM gura_m1.pins WHERE run=%s AND owner=%s AND scope='query'",(run['id'],owner))

    def submit(self, principal, dataset, kind, request, view=None):
        deadline = time.monotonic()+10
        self.check_lease()
        require(kind in ('search','scan','export','graph'), 'invalid_request')
        require(isinstance(request, dict), 'invalid_request')
        require(self.capacity.acquire(blocking=False), 'resource_limit')
        try:
            row = self.jobs.submit(principal, dataset, kind, request, view)
        except Exception:
            self.capacity.release()
            raise
        row['deadline_at'] = deadline
        self.pool.submit(self.execute, row, principal)
        return row

    def execute(self, row, principal):
        job = row['id']
        last = [0.0, False]
        def cancelled():
            if time.monotonic() - last[0] >= .05:
                last[:] = [time.monotonic(), self.jobs.cancelled(job)]
            return last[1]
        try:
            self.check_lease()
            self.jobs.active(job, principal)
            budget = Budget(cancelled, seconds=row['deadline_at']-time.monotonic())
            budget.check()
            run = self.control.run(row['run'])
            bundle = load_bundle(run['artifact'], budget)
            if self.workers == 3:
                output = distributed(bundle, row['kind'], row['request'], budget, self.root/str(job), principal, transport=self.transport)
            elif row['kind'] == 'search':
                output = search(bundle, row['request'], budget)
            elif row['kind'] == 'graph':
                output = expand(bundle, row['request'], budget)
            elif row['kind'] == 'scan':
                require(set(row['request']) <= {'limit'}, 'invalid_request')
                limit = row['request'].get('limit', 100)
                require(type(limit) is int and 1 <= limit <= 1000, 'resource_limit')
                output = {'rows': [{'logical_key': r['logical_key'], 'values': public_values(r['values']), 'record_version': r.get('record_version', bundle['revision']),
                                    'media': public_media(r['media'])} for r in sorted(bundle['rows'], key=lambda r:r['logical_key'])[:limit]],
                          'truncated': len(bundle['rows']) > limit, 'read_context': bundle['context']}
            else:
                output = export(bundle, row['request'], self.root/str(job), budget)
            raw = encoded(output)
            require(len(raw) <= 2 << 20, 'resource_limit', 'result byte budget exceeded')
            budget.check()
            reference = put(self.root/str(job)/'result.json', raw)
            self.check_lease()
            self.jobs.finish(job, principal, result=reference)
        except Exception as error:
            try:
                self.jobs.finish(job, principal, error=error.code if isinstance(error, Failure) else 'execution_failed')
            except Exception:
                # DB outage leaves a durable nonterminal job; restart recovery marks it failed.
                self.failed.set()
        finally:
            self.capacity.release()

    def media(self, job, principal, sha256):
        row = self.jobs.get(job, principal)
        require(row['kind'] == 'export' and row['status'] == 'succeeded', 'not_ready')
        bundle = load_bundle(self.control.run(row['run'])['artifact'], Budget())
        for sample in bundle['rows']:
            for media in sample['media']:
                if media['sha256'] == sha256:
                    return get(media['copy'])
        require(False, 'not_found')

    def release(self, job, principal):
        def cleanup():
            directory = self.root/str(uuid.UUID(str(job)))
            require(not directory.is_symlink() and directory.resolve().parent == self.root, 'source_invalid')
            if directory.exists():
                shutil.rmtree(directory)
        self.jobs.release(job, principal, cleanup)

    def result(self, job, principal, parquet=False):
        self.check_lease()
        row = self.jobs.get(job, principal)
        require(row['status'] == 'succeeded', 'not_ready')
        result = json.loads(get(row['result']))
        if row['kind'] == 'export':
            if parquet:
                return get(result['parquet'])
            manifest = json.loads(get(result['manifest']))
            manifest['query_id'] = str(job)
            if 'execution' in result:
                manifest['execution'] = result['execution']
            manifest['parquet'] = {'sha256': result['parquet']['sha256'], 'download': f'/v1/jobs/{job}/parquet'}
            return manifest
        require(not parquet, 'not_found')
        result['query_id'] = str(job)
        return result
