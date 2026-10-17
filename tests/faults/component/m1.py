"""Real PG/S3 and pipeline boundary faults: no incomplete/old publication or pin races."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import threading
import time
import shutil
import uuid
from unittest.mock import patch
from pathlib import Path

from m0lib.kit import DATASET, ROOT, docker, laboratory
from m1lib.fixtures import HttpProcess, feature_file, iceberg, pg, target
from modules.catalog.jobs import Jobs
from modules.common.contracts import Budget, Failure, digest
from modules.index.retrieval import load_bundle
from modules.query.service import Service
from modules.query.snapshot import collect, construct, publish


def reject(call,expected):
    try:call()
    except Failure as error:
        assert error.code==expected,(error.code,expected)
        return error.code
    raise AssertionError('fault did not reject: '+expected)


def run(directory):
    seed=17
    checks=0
    with laboratory(directory) as lab:
        control,pg_name,dsn=pg(lab)
        lab.s3()
        properties={'s3.endpoint':'http://127.0.0.1:'+lab.port(lab.store,8333),'s3.access-key-id':'m0-test-key',
                    's3.secret-access-key':'m0-test-secret','s3.region':'us-east-1','s3.force-virtual-addressing':'false'}
        table,_,rows=iceberg(directory/'lake',properties=properties,location='s3://m0-data/lake/table')
        assert sorted(table.scan().to_arrow().to_pylist(),key=lambda r:r['id'])==rows
        feature=feature_file(directory/'lake',rows,lab.client)
        selected=target(table,feature,s3=lab.client)
        control.register(DATASET,'tenant-a','documents',{'root':'s3://m0-data/lake','key_field':'id','text_field':'title'})
        first=construct(control,DATASET,'first',selected,directory/'builds',lab.client)
        publish(control,first['id'],0)
        initial=control.dataset(DATASET)['published']
        lab.event('s3_snapshot_published',run=str(initial),seed=seed)
        # An index-side failure after the source scan must not switch the published pointer.
        with patch('modules.query.snapshot.build',side_effect=Failure('injected_index_failure','single index failed')):
            reject(lambda:construct(control,DATASET,'failed-index',selected,directory/'builds',lab.client),'injected_index_failure')
        assert control.dataset(DATASET)['published']==initial
        failed=control.begin(DATASET,'failed-index',selected)
        assert failed['status']=='failed' and failed['artifact'] is None
        reject(lambda:publish(control,failed['id'],1),'not_ready')
        reject(lambda:construct(control,DATASET,'cancelled-build',selected,directory/'builds',lab.client,lambda:True),'cancelled')
        assert control.dataset(DATASET)['published']==initial
        older=construct(control,DATASET,'older-worker',selected,directory/'builds',lab.client)
        newer=construct(control,DATASET,'newer-worker',selected,directory/'builds',lab.client)
        assert older['artifact']['context']['data_revision_id']==newer['artifact']['context']['data_revision_id']
        reject(lambda:publish(control,older['id'],1),'stale_generation')
        reject(lambda:publish(control,newer['id'],0),'publication_conflict')
        # Transaction interruption between candidate mutation and pointer switch rolls back both.
        try:
            with control.transaction() as conn:
                conn.execute("UPDATE gura_m1.runs SET status='published' WHERE id=%s",(newer['id'],))
                conn.execute('UPDATE gura_m1.datasets SET published=%s,epoch=epoch+1 WHERE id=%s',(newer['id'],DATASET))
                raise RuntimeError('injected-before-commit')
        except RuntimeError:pass
        assert control.dataset(DATASET)['published']==initial and control.run(newer['id'])['status']=='ready'
        with ThreadPoolExecutor(2) as pool:
            results=list(pool.map(lambda _:publish(control,newer['id'],1),range(2)))
        assert results==[2,2]
        # The first response is deliberately discarded: replay reconciles exactly one epoch.
        assert publish(control,newer['id'],1)==2 and control.dataset(DATASET)['epoch']==2
        lab.event('publication_faults_checked',stale=str(older['id']),published=str(newer['id']),epoch=2)
        checks+=10
        control.pin(first['id'],'training-reader')
        reject(lambda:collect(control,first['id'],directory/'builds'),'still_pinned')
        control.unpin(first['id'],'training-reader')
        barrier=threading.Barrier(2)
        def pin():
            barrier.wait()
            try:control.pin(first['id'],'racing-reader');return 'pinned'
            except Failure as error:return error.code
        def retire():
            barrier.wait()
            try:control.retire(first['id']);return 'retiring'
            except Failure as error:return error.code
        with ThreadPoolExecutor(2) as pool:
            a,b=pool.submit(pin),pool.submit(retire)
            a,b=a.result(),b.result()
        assert (a,b) in [('pinned','still_pinned'),('not_ready','retiring')],(a,b)
        if a=='pinned':control.unpin(first['id'],'racing-reader')
        collect(control,first['id'],directory/'builds')
        assert not (directory/'builds'/str(first['id'])).exists()
        reject(lambda:control.pin(first['id'],'late-reader'),'not_ready')
        reject(lambda:collect(control,newer['id'],directory/'builds'),'still_referenced')
        assert sorted(table.scan().to_arrow().to_pylist(),key=lambda r:r['id'])==rows  # GC never touches lake.
        checks+=5
        # Corrupt a real derived file; do not fall back to a new snapshot or partial index.
        bundle=json.loads(Path(newer['artifact']['path']).read_bytes())
        path=Path(bundle['index_files'][0]['path']);raw=path.read_bytes();path.write_bytes(b'corrupt')
        try:reject(lambda:load_bundle(newer['artifact'],Budget()),'source_invalid')
        finally:path.write_bytes(raw)
        # A source object disappearing blocks the next import, while the copied published facts survive.
        source_file=next(d for d in bundle['source']['dependencies'] if d['uri'].endswith('.parquet'))
        key=source_file['uri'].removeprefix('s3://m0-data/')
        saved=lab.client.get_object(Bucket='m0-data',Key=key)['Body'].read()
        lab.client.delete_object(Bucket='m0-data',Key=key)
        try:
            try:construct(control,DATASET,'expired-source',selected,directory/'builds',lab.client)
            except Exception:pass
            else:raise AssertionError('missing source accepted')
            assert control.dataset(DATASET)['published']==newer['id']
            assert len(load_bundle(newer['artifact'],Budget())['rows'])==len(rows)
        finally:lab.client.put_object(Bucket='m0-data',Key=key,Body=saved)
        checks+=3
        token='fault-reader'
        control.grant(digest(token.encode()),'tenant-a','reader',DATASET)
        principal=control.principal(token)
        service=Service(control,directory/'jobs')
        def terminal(job):
            def done():
                row=service.jobs.get(job,principal)
                return row if row['status'] in ('succeeded','failed','cancelled') else None
            return lab.wait(done)
        try:
            # Deterministic queued cancellation while both real worker slots are occupied.
            gate=threading.Event()
            fillers=[service.pool.submit(gate.wait,10) for _ in range(2)]
            queued=service.submit(principal,DATASET,'search',{'text':'alpha'})
            service.jobs.cancel(queued['id'],principal)
            gate.set()
            assert terminal(queued['id'])['status']=='cancelled'
            # Running cancellation / revoke at the actual source/index execution boundary.
            original=__import__('modules.query.service',fromlist=['load_bundle']).load_bundle
            for action in ('cancel','revoke'):
                entered,release=threading.Event(),threading.Event()
                def stopped(reference,budget):
                    entered.set();assert release.wait(10)
                    budget.check()
                    return original(reference,budget)
                with patch('modules.query.service.load_bundle',stopped):
                    job=service.submit(principal,DATASET,'search',{'text':'alpha'})
                    assert entered.wait(10)
                    if action=='cancel':service.jobs.cancel(job['id'],principal)
                    else:control.revoke('tenant-a','reader',DATASET)
                    release.set()
                    if action=='revoke':
                        lab.wait(lambda:control.run(newer['id'])['status']=='published')
                        # Access is rejected immediately, even before the worker finishes.
                        reject(lambda:service.jobs.get(job['id'],principal),'not_found')
                        def failed():
                            with control.transaction() as conn:
                                return conn.execute('SELECT status FROM gura_m1.jobs WHERE id=%s',(job['id'],)).fetchone()['status']=='failed'
                        lab.wait(failed)
                        control.grant(digest(token.encode()),'tenant-a','reader',DATASET)
                    assert terminal(job['id'])['status']==('cancelled' if action=='cancel' else 'failed')
            # Accepted scan and training jobs keep the old view while a new source snapshot publishes.
            entered,release=threading.Event(),threading.Event()
            count=[0]
            def across_publish(reference,budget):
                count[0]+=1
                if count[0]>=2:entered.set()
                assert release.wait(15)
                return original(reference,budget)
            with patch('modules.query.service.load_bundle',across_publish):
                scan=service.submit(principal,DATASET,'scan',{'limit':100})
                training=service.submit(principal,DATASET,'export',{'seed':'during-publication'})
                assert entered.wait(10)
                import pyarrow as pa
                newrow={'id':999,'title':'new snapshot only','active':True}
                table.append(pa.Table.from_pylist([newrow],schema=table.scan().to_arrow().schema))
                extended=rows+[newrow]
                chosen=target(table,feature_file(directory/'lake',extended,lab.client),s3=lab.client)
                third=construct(control,DATASET,'concurrent-refresh',chosen,directory/'builds',lab.client)
                assert publish(control,third['id'],2)==3
                reject(lambda:collect(control,newer['id'],directory/'builds'),'still_pinned')
                release.set()
                assert terminal(scan['id'])['status']=='succeeded'
                assert terminal(training['id'])['status']=='succeeded'
                assert len(service.result(scan['id'],principal)['rows'])==len(rows)
                assert service.result(training['id'],principal)['rows']==len(rows)
                assert service.result(scan['id'],principal)['read_context']==scan['context']
            current=service.submit(principal,DATASET,'scan',{'limit':100})
            assert terminal(current['id'])['status']=='succeeded'
            assert len(service.result(current['id'],principal)['rows'])==len(rows)+1
            reject(lambda:collect(control,newer['id'],directory/'builds'),'still_pinned')
            real_cleanup=shutil.rmtree
            def interrupted_release(path):
                real_cleanup(path)
                raise RuntimeError('injected-release-before-db-commit')
            with patch('modules.query.service.shutil.rmtree',interrupted_release):
                try:service.release(training['id'],principal)
                except RuntimeError:pass
                else:raise AssertionError('release fault not injected')
            assert service.jobs.get(training['id'],principal)['status']=='succeeded'
            reject(lambda:collect(control,newer['id'],directory/'builds'),'still_pinned')
            service.release(training['id'],principal)
            collect(control,newer['id'],directory/'builds')
            checks+=8
            # Deadline is injected shorter, workload unchanged; no partial result is committed.
            with patch('modules.query.service.Budget',lambda *a,**kw:Budget(seconds=-1)):
                timed=service.submit(principal,DATASET,'search',{'text':'alpha'})
                assert terminal(timed['id'])['error']=='timeout'
            checks+=4
            # The deadline includes real time in the queue, and admission remains bounded.
            gate=threading.Event()
            fillers=[service.pool.submit(gate.wait,15) for _ in range(2)]
            queued=[service.submit(principal,DATASET,'scan',{'limit':100}) for _ in range(32)]
            reject(lambda:service.submit(principal,DATASET,'scan',{'limit':100}),'resource_limit')
            time.sleep(10.1)
            gate.set()
            for job in queued:
                outcome=terminal(job['id'])
                assert outcome['status']=='failed' and outcome['error']=='timeout'
            checks+=3
        finally:service.close()
        # Durable accepted job survives a real HTTP process crash as an explicit failure.
        marker=directory/'worker-entered'
        wrapper=directory/'crash-server.py'
        wrapper.write_text("import sys,time,runpy\nfrom pathlib import Path\nsys.path.insert(0,"+repr(str(ROOT))+")\nimport modules.query.service as service\noriginal=service.load_bundle\ndef stopped(reference,budget):\n Path("+repr(str(marker))+").write_text('entered')\n time.sleep(20)\n return original(reference,budget)\nservice.load_bundle=stopped\nrunpy.run_path("+repr(str(ROOT/'scripts/m1.py'))+",run_name='__main__')\n")
        process=HttpProcess(directory,dsn).start(wrapper)
        from clients.common.http import Client
        client=Client(process.url,token)
        abandoned=client.request('POST','/v1/search',{'dataset_id':DATASET,'query':{'text':'alpha'}})
        lab.wait(marker.exists)
        process.stop(crash=True)
        process.start()
        try:
            client=Client(process.url,token)
            recovered=client.request('GET','/v1/jobs/'+abandoned['query_id'])
            assert recovered['status']=='failed' and recovered['error']['code']=='worker_restarted'
            with control.transaction() as conn:
                assert conn.execute('SELECT 1 FROM gura_m1.pins WHERE owner=%s',(abandoned['query_id'],)).fetchone() is None
        finally:process.stop()
        # Real PG restart: pointer, epoch, grant and run persist on the existing data volume.
        lease_service=Service(control,directory/'lease-jobs')
        reject(lambda:Service(control,directory/'lease-jobs'),'service_already_running')
        entered,release=threading.Event(),threading.Event()
        original=__import__('modules.query.service',fromlist=['load_bundle']).load_bundle
        def before_lease_loss(reference,budget):
            entered.set();assert release.wait(15)
            return original(reference,budget)
        lease_patch=patch('modules.query.service.load_bundle',before_lease_loss)
        lease_patch.start()
        lease_job=lease_service.submit(principal,DATASET,'scan',{'limit':100})
        assert entered.wait(10)
        previous_port=lab.port(pg_name,5432)
        docker('restart',pg_name)
        control.dsn='host=127.0.0.1 port='+lab.port(pg_name,5432)+' user=postgres dbname=postgres'
        lab.event('pg_restarted',previous_port=previous_port,current_port=lab.port(pg_name,5432))
        def restarted():
            try:
                with control.transaction() as conn:
                    return conn.execute('SELECT 1').fetchone() is not None
            except Exception:
                return False
        lab.wait(restarted)
        assert control.dataset(DATASET)['published']==third['id'] and control.dataset(DATASET)['epoch']==3
        assert control.principal(token)['tenant']=='tenant-a'
        replacement=Service(control,directory/'lease-jobs')
        release.set()
        lease_service.close()
        lease_patch.stop()
        try:
            restored=replacement.jobs.get(lease_job['id'],principal)
            assert restored['status']=='failed' and restored['error']=='worker_restarted'
            # The old worker's late completion cannot resurrect an accepted job.
            lease_service.jobs.finish(lease_job['id'],principal,result={'path':'invalid','sha256':'0'*64})
            assert replacement.jobs.get(lease_job['id'],principal)['status']=='failed'
        finally:replacement.close()

        checks+=3
        lab.event('m1_faults_passed',assertions=checks,seed=seed)
    return {'passed':True,'suite':'stability-component','assertions':checks,'seed':seed,
            'scope':'M1 real S3/PG, publication fencing/CAS/rollback/reconcile, retention/GC, cancellation/revocation/restart'}
