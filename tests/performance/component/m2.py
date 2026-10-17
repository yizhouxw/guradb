"""Fixed-seed actual ANN and three-process cost/quality measurements."""
import math
import os
from pathlib import Path
import platform
import subprocess
import time

from m0lib.kit import DATASET, laboratory
from m1lib.fixtures import iceberg, pg, target
from m2lib.fixtures import Serving, features, query, workers
from modules.common.contracts import Budget, digest, key
from modules.index.retrieval import load_bundle
from modules.query.snapshot import construct, publish


def run(directory):
    samples=[]
    with laboratory(directory) as lab:
        control,_,_=pg(lab)
        table,_,rows=iceberg(directory/'lake',8192)
        feature,vectors=features(directory/'lake',rows)
        control.register(DATASET,'tenant-a','documents',{'root':(directory/'lake').as_uri(),'key_field':'id','text_field':'title'})
        token='m2-performance';control.grant(digest(token.encode()),'tenant-a','reader',DATASET)
        selected=dict(target(table,feature),ann={'partitions':8})
        started=time.perf_counter();built=construct(control,DATASET,'measured',selected,directory/'builds')
        elapsed=time.perf_counter()-started
        assert elapsed<=60,elapsed
        bundle=load_bundle(built['artifact'],Budget());publish(control,built['id'],0)
        for replica in range(2):
            serving=Serving(control,directory/'jobs',token)
            try:
                for mode in ('first-query','repeated-query'):
                    for probes in (4,8):
                        vector=vectors[17+replica]
                        truth=sorted(vectors,key=lambda i:(math.fsum((a-b)**2 for a,b in zip(vectors[i],vector)),key(i,'long')))[:10]
                        started=time.perf_counter()
                        handle,result=query(serving.client,DATASET,'search',{'vector':vector,'model':'m2-test-17','top_k':10,
                                                                          'candidate_limit':100,'vector_index':'ann','nprobes':probes})
                        latency=(time.perf_counter()-started)*1000
                        actual=[int(hit['values']['id']) for hit in result['hits']]
                        recall=len(set(actual)&set(truth))/10
                        assert latency<=10000 and (probes!=8 or recall>=.95),(latency,recall)
                        samples.append({'replica':replica,'mode':mode,'nprobes':probes,'latency_ms':latency,'recall_at_10':recall,**result['stats']})
                        serving.client.request('DELETE','/v1/jobs/'+handle['query_id']+'/retention')
                started=time.perf_counter()
                handle,result=query(serving.client,DATASET,'search',{'vector':vectors[17],'model':'m2-test-17','top_k':10,'candidate_limit':100})
                parallel_seconds=time.perf_counter()-started
                assert parallel_seconds<=10
                worker_memory = workers(result,8192)
                assert all(0 < w['rss_bytes'] <= 512*(1<<20) for w in worker_memory)
                rss=int(subprocess.check_output(['ps','-o','rss=','-p',str(os.getpid())],text=True).strip())*1024
                assert rss<=512*(1<<20),rss
            finally:serving.close()
        return {'passed':True,'suite':'performance-smoke','scope':'component measurement; not production baseline',
                'environment':platform.platform(),'cache':'fresh native ANN subprocess per query; OS cache not flushed',
                'workload':{'rows':8192,'dimensions':16,'seed':17,'partitions':8,'candidates':100,'top_k':10},
                'build_seconds':elapsed,'index_bytes':bundle['ann']['index_bytes'],
                'index_to_raw_f32_vector_ratio':bundle['ann']['index_bytes']/(8192*16*4),
                'coordinator_rss_bytes':rss,'worker_peak_rss_bytes':[w['rss_bytes'] for w in worker_memory],
                'sum_of_process_peaks_bytes':rss+sum(w['rss_bytes'] for w in worker_memory),'parallel_seconds':parallel_seconds,'samples':samples}
