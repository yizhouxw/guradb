"""Live PG/HTTP/CLI/MCP integration and three actual shard processes."""
import json
import math
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import threading
from pathlib import Path
import subprocess
import sys
import uuid

from m0lib.kit import DATASET, laboratory
from m1lib.fixtures import iceberg, pg, target
from m2lib.fixtures import Serving, edges, features, query, workers
from modules.common.contracts import Budget, digest, key
from modules.index.graph import expand
from modules.index.retrieval import load_bundle, search
from modules.query.snapshot import construct, publish
from modules.query.incremental import refresh
from modules.catalog.managed import Managed
from modules.connectors.writer import Writer


def run(directory):
    with laboratory(directory) as lab:
        control,_,dsn=pg(lab)
        table,_,rows=iceberg(directory/'lake',256)
        feature,vectors=features(directory/'lake',rows)
        control.register(DATASET,'tenant-a','documents',{'root':(directory/'lake').as_uri(),'key_field':'id','text_field':'title'})
        token='m2-integration'
        control.grant(digest(token.encode()),'tenant-a','reader',DATASET)
        selected=dict(target(table,feature),ann={'partitions':4})
        built=construct(control,DATASET,'ann-first',selected,directory/'builds')
        publish(control,built['id'],0)
        bundle=load_bundle(built['artifact'],Budget())
        serving=Serving(control,directory/'jobs',token)
        client=serving.client
        try:
            vector=vectors[19]
            request={'vector':vector,'model':'m2-test-17','top_k':10,'candidate_limit':100}
            _,parallel=query(client,DATASET,'search',request)
            exact=search(bundle,request,Budget())
            assert parallel['hits']==exact['hits']
            evidence=workers(parallel,len(rows))
            _,ann=query(client,DATASET,'search',dict(request,vector_index='ann',nprobes=4))
            expected=sorted(vectors,key=lambda i:(math.fsum((a-b)**2 for a,b in zip(vectors[i],vector)),key(i,'long')))[:10]
            assert [int(hit['values']['id']) for hit in ann['hits']]==expected
            filtered=dict(request,filter={'field':'active','equals':True})
            _,filtered_result=query(client,DATASET,'search',filtered)
            assert filtered_result['hits']==search(bundle,filtered,Budget())['hits']
            _,fused=query(client,DATASET,'search',dict(request,text='alpha'))
            assert fused['hits']==search(bundle,dict(request,text='alpha'),Budget())['hits']
            _,scan=query(client,DATASET,'scan',{'limit':1000})
            assert [int(r['values']['id']) for r in scan['rows']]==list(range(256))
            workers(scan,len(rows))
            export_handle,exported=query(client,DATASET,'export',{'seed':'fixed-three'})
            workers(exported,len(rows))
            assert exported['rows']==len(rows) and exported['read_context']==parallel['read_context']
            entered, released = threading.Event(), threading.Event()
            from modules.query.distributed import execute as original_execute
            def gated(*args, **kwargs):
                entered.set()
                assert released.wait(8)
                return original_execute(*args, **kwargs)
            with patch('modules.query.service.distributed', gated):
                handle = client.request('POST','/v1/exports',{'dataset_id':DATASET,'query':{'seed':'racing'}})
                assert entered.wait(5)
                try:
                    newer=construct(control,DATASET,'publish-during-export',selected,directory/'builds')
                    publish(control,newer['id'],1)
                finally:
                    released.set()
                raced=client.wait(handle)
            assert raced['read_context']==bundle['context']
            assert client.request('GET','/v1/jobs/'+export_handle['query_id']+'/results')['read_context']==bundle['context']
            assert client.request('GET','/v1/datasets/'+DATASET)['read_context']==newer['artifact']['context']
            workers(raced,len(rows))
            from tests.functional.mcp import run as mcp_run
            mcp=mcp_run(client.url,token,DATASET)
            assert mcp
            # Same HTTP semantics through CLI; no direct catalog access.
            import os
            command=[sys.executable,'clients/cli/m1.py','--url',client.url,'scan','--dataset',DATASET,'--query','{"limit":3}']
            cli=subprocess.run(command,env=dict(os.environ,GURADB_TOKEN=token),capture_output=True,text=True,check=True)
            assert len(json.loads(cli.stdout)['rows'])==3
            edge_id=str(uuid.uuid4())
            edge_table,edge_rows=edges(directory/'edge-lake')
            edge_features,_=features(directory/'edge-lake',edge_rows)
            control.register(edge_id,'tenant-a','relations',{'root':(directory/'edge-lake').as_uri(),'key_field':'id','text_field':'kind'})
            control.grant(digest(token.encode()),'tenant-a','reader',edge_id)
            edge_run=construct(control,edge_id,'edges',target(edge_table,edge_features),directory/'builds')
            publish(control,edge_run['id'],0)
            graph={'source_field':'source','target_field':'target','type_field':'kind','seeds':['0','2'],'type':'link',
                   'direction':'both','max_edges':100,'max_fanout':100}
            _,paths=query(client,edge_id,'graph',graph)
            oracle=expand(load_bundle(edge_run['artifact'],Budget()),graph,Budget())
            assert paths['paths']==oracle['paths']
            workers(paths,len(edge_rows))
            # Full bounded write -> snapshot/ANN -> trigger refresh -> three-worker read/export.
            managed=Managed(dsn);managed.initialize()
            writer=Writer(directory/'managed-lake','managed_docs');writer.initialize(managed)
            first_source=writer.append(managed,'batch-one',rows[:128])
            managed_feature,_=features(writer.root,rows[:128])
            managed_id=str(uuid.uuid4())
            control.register(managed_id,'tenant-a','managed_docs',{'root':writer.root.as_uri(),'key_field':'id','text_field':'title'})
            control.grant(digest(token.encode()),'tenant-a','reader',managed_id)
            managed_target=dict(first_source,features_uri=managed_feature[0],features_sha256=managed_feature[1],ann={'partitions':4})
            managed_run=construct(control,managed_id,'managed-first',managed_target,directory/'builds')
            publish(control,managed_run['id'],0)
            second_source=writer.append(managed,'batch-two',rows[128:])
            all_features,_=features(writer.root,rows)
            refreshed=refresh(control,managed_id,'managed-refresh',dict(second_source,features_uri=all_features[0],
                              features_sha256=all_features[1],ann={'partitions':4}),directory/'builds')
            assert control.dataset(managed_id)['published']==managed_run['id']
            publish(control,refreshed['id'],1)
            _,managed_scan=query(client,managed_id,'scan',{'limit':1000})
            assert [int(r['values']['id']) for r in managed_scan['rows']]==list(range(256))
            workers(managed_scan,256)
            _,managed_export=query(client,managed_id,'export',{'seed':'managed'})
            assert managed_export['rows']==256 and managed_export['read_context']==managed_scan['read_context']
            workers(managed_export,256)
            lab.event('three_worker_integration',workers=evidence,ann_recall=1.0,graph_paths=len(paths['paths']))
            return {'passed':True,'suite':'functional','scope':'bounded M2 and local three-process integration',
                    'rows':len(rows),'workers':evidence,'ann_recall_at_10':1.0,'graph_paths':len(paths['paths']),
                    'mcp':True,'cli':True,'training_rows':exported['rows'],'concurrent_publish':True,'managed_refresh_export_rows':256}
        finally:
            serving.close()
