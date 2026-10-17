"""Frozen M1 8192-row component workload, independent quality and absolute budgets."""
from concurrent.futures import ThreadPoolExecutor
import threading
from unittest.mock import patch
import json
import platform
from pathlib import Path
import subprocess
import time

from clients.common.http import Client
from m0lib.kit import DATASET, laboratory
from m1lib.fixtures import HttpProcess, feature_file, iceberg, pg, target
from modules.common.contracts import digest, key
from modules.query.snapshot import construct, publish
from modules.index.retrieval import build as build_index


def run(directory):
    samples=[]
    with laboratory(directory) as lab:
        control,_,dsn=pg(lab)
        table,_,rows=iceberg(directory/'lake',8192)
        feature=feature_file(directory/'lake',rows)
        control.register(DATASET,'tenant-a','documents',{'root':(directory/'lake').as_uri(),'key_field':'id','text_field':'title'})
        token='m1-performance-token'
        control.grant(digest(token.encode()),'tenant-a','reader',DATASET)
        selected=target(table,feature)
        start=time.perf_counter()
        run=construct(control,DATASET,'measured',selected,directory/'builds')
        build_seconds=time.perf_counter()-start
        assert build_seconds<=60,build_seconds
        bundle=json.loads(Path(run['artifact']['path']).read_bytes())
        assert len(bundle['rows'])==8192
        # Read statistics exactly account for the dependency list, including repeated reads.
        assert bundle['stats']['source_reads']==len(bundle['source']['dependencies'])
        assert bundle['stats']['source_bytes']==sum(d['size_bytes'] for d in bundle['source']['dependencies'])
        publish(control,run['id'],0)
        truth=sorted(rows,key=lambda r:((r['id']%4)**2+(r['id']%3)**2,key(r['id'],'long')))[:10]
        for replica in range(5):
            process=HttpProcess(directory,dsn).start()
            try:
                client=Client(process.url,token)
                for mode in ('cold-process','warm-process'):
                    start=time.perf_counter()
                    handle=client.request('POST','/v1/search',{'dataset_id':DATASET,'query':
                        {'vector':[0,0],'model':'test-space-v1','top_k':10,'candidate_limit':100}})
                    result=client.wait(handle)
                    latency=(time.perf_counter()-start)*1000
                    rss=int(subprocess.check_output(['ps','-o','rss=','-p',str(process.process.pid)],text=True).strip())*1024
                    assert [int(r['values']['id']) for r in result['hits']]==[r['id'] for r in truth]
                    assert result['stats']['records_examined']==8192
                    references=[run['artifact'],bundle['manifest_reference']]+bundle['index_files']+[d['copy'] for d in bundle['source']['dependencies']]+[{'path':str(Path(bundle['manifest']['backend']['root'])/f['key'])} for f in bundle['manifest']['files']]
                    references += [bundle['bm25']['stats'], *bundle['bm25']['files']]
                    references += [shard['file'] for shard in bundle['shards']]
                    assert result['stats']['artifact_reads']==len(references)
                    assert result['stats']['artifact_bytes']==sum(Path(ref['path']).stat().st_size for ref in references)
                    assert latency<=10000 and rss<=512*(1<<20),(latency,rss)
                    samples.append({'replica':replica,'mode':mode,'latency_ms':latency,'rss_bytes':rss,
                                    'recall_at_10':1.0,**result['stats']})
                    client.request('DELETE','/v1/jobs/'+handle['query_id']+'/retention')
            finally:process.stop()
        # Same 8192-row workload: background rebuild overlaps search and training.
        entered,release=threading.Event(),threading.Event()
        def scheduled_build(*args):
            entered.set()
            assert release.wait(10)
            return build_index(*args)
        process=HttpProcess(directory,dsn).start()
        try:
            client=Client(process.url,token)
            with ThreadPoolExecutor(1) as pool, patch('modules.query.snapshot.build',scheduled_build):
                start=time.perf_counter()
                refreshing=pool.submit(construct,control,DATASET,'mixed-refresh',selected,directory/'builds')
                assert entered.wait(10)
                search_job=client.request('POST','/v1/search',{'dataset_id':DATASET,'query':
                    {'vector':[0,0],'model':'test-space-v1','top_k':10,'candidate_limit':100}})
                training_job=client.request('POST','/v1/exports',{'dataset_id':DATASET,'query':{'seed':'mixed-workload'}})
                release.set()
                result=client.wait(search_job)
                training=client.wait(training_job)
                refreshed=refreshing.result(timeout=60)
                elapsed=time.perf_counter()-start
                assert elapsed<=60
                assert [int(r['values']['id']) for r in result['hits']]==[r['id'] for r in truth]
                assert training['rows']==8192
                assert result['read_context']==training['read_context']==bundle['context']
                assert publish(control,refreshed['id'],1)==2
                assert client.request('GET','/v1/jobs/'+training_job['query_id']+'/results')['read_context']==bundle['context']
                rss=int(subprocess.check_output(['ps','-o','rss=','-p',str(process.process.pid)],text=True).strip())*1024
                assert rss<=512*(1<<20)
                mixed={'elapsed_seconds':elapsed,'rss_bytes':rss,'recall_at_10':1.0,'training_rows':8192,
                       'old_view':bundle['context']['read_view_id'],'new_view':refreshed['artifact']['context']['read_view_id']}
                client.request('DELETE','/v1/jobs/'+search_job['query_id']+'/retention')
                client.request('DELETE','/v1/jobs/'+training_job['query_id']+'/retention')
        finally:process.stop()
        lab.event('m1_performance_passed',samples=len(samples),rows=len(rows))
        return {'passed':True,'suite':'performance-smoke','scope':'M1 bounded single-node component, not product baseline',
                'environment':{'platform':platform.platform(),'source':'local Iceberg; PG18 Docker','cache':'new process / same process; OS cache not flushed'},
                'workload':{'rows':8192,'seed':0,'dimensions':2,'candidates':100,'top_k':10,'input':selected},
                'budgets':{'build_seconds':60,'latency_ms':10000,'rss_bytes':512*(1<<20),'required_recall_at_10':1.0},
                'build_seconds':build_seconds,'source_cost':bundle['stats'],'samples':samples,'mixed_workload':mixed}
