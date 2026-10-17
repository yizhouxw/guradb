"""Real Iceberg/PG/HTTP/CLI interoperability, negative cases and training truth."""
from copy import deepcopy
from io import BytesIO
import json
import math
import os
from pathlib import Path
import subprocess
import sys

from jsonschema import Draft202012Validator
import fastavro
import pyarrow.parquet as pq

from clients.common.http import Client
from m0lib.kit import DATASET, ROOT, laboratory, mapped, truth
from m1lib.negative import mutated
from m1lib.fixtures import HttpProcess, feature_file, iceberg, pg, target
from modules.common.contracts import Budget, Failure, digest, encoded, key
from modules.connectors.iceberg import snapshot
from modules.query.snapshot import construct, publish
from modules.storage.objects import Objects


def rejects(call, code=None):
    try:call()
    except Failure as error:
        assert code is None or error.code==code,(code,error.code)
        return
    raise AssertionError('unsupported operation accepted')


def public(row):
    return {k:str(v) if type(v) is int else v for k,v in row.items()}


def run(directory):
    checks=0
    with laboratory(directory) as lab:
        control,_,dsn=pg(lab)
        lake=directory/'lake'
        table,old,rows=iceberg(lake)
        # PyIceberg is the independent writer/reader; no use of our metadata planner.
        assert sorted(table.scan().to_arrow().to_pylist(),key=lambda r:r['id'])==rows
        assert sorted(table.scan(snapshot_id=old).to_arrow().to_pylist(),key=lambda r:r['id'])==rows[:len(rows)//2]
        media_path=lake/'media.bin';media_path.write_bytes(b'externally-versioned-media-fixture')
        media={'uri':media_path.as_uri(),'sha256':digest(media_path.read_bytes()),'size_bytes':media_path.stat().st_size}
        full=feature_file(lake,rows,media=media)
        definition={'root':lake.as_uri(),'key_field':'id','text_field':'title'}
        control.register(DATASET,'tenant-a','documents',definition)
        selected=target(table,full)
        run=construct(control,DATASET,'first',selected,directory/'builds')
        assert run['status']=='ready'
        assert control.dataset(DATASET)['published'] is None
        assert publish(control,run['id'],0)==1
        assert publish(control,run['id'],0)==1  # response-lost reconciliation
        assert construct(control,DATASET,'first',selected,directory/'builds')['id']==run['id']
        rejects(lambda:control.begin(DATASET,'first',dict(selected,snapshot_id=old)),'operation_conflict')
        bundle=json.loads(Path(run['artifact']['path']).read_bytes())
        assert [r['values'] for r in bundle['rows']]==rows
        assert bundle['context']['source_versions'][0]['version']==str(table.current_snapshot().snapshot_id)
        # Existing Rust/M0 HTTP independently scans the normalized Parquet artifact.
        lab.manifest=deepcopy(bundle['manifest'])
        lab.manifest['backend']['root']=mapped(Path(lab.manifest['backend']['root']))
        lab.start()
        assert lab.query()[1]['rows']==truth(rows)
        checks+=9
        token='test-m1-reader-token'
        control.grant(digest(token.encode()),'tenant-a','reader',DATASET)
        media_payload=media_path.read_bytes()
        media_path.unlink()  # A retained training copy survives upstream expiration.
        process=HttpProcess(directory,dsn).start()
        try:
            client=Client(process.url,token)
            description=client.request('GET','/v1/datasets/'+DATASET)
            assert description['retention_mode']=='managed-copy' and description['read_context']==bundle['context']
            def query(kind,value,view=None):
                body={'dataset_id':DATASET,'query':value}
                if view is not None:body['read_view_id']=view
                handle=client.request('POST','/v1/'+kind,body)
                api=json.loads((ROOT/'api/http/m1-openapi.json').read_text())
                Draft202012Validator(dict(api,**{'$ref':'#/components/schemas/Job'})).validate(handle)
                shared=json.loads((ROOT/'api/http/openapi.json').read_text())
                Draft202012Validator(dict(shared,**{'$ref':'#/components/schemas/ReadContext'})).validate(handle['read_context'])
                result=client.wait(handle)
                assert result['read_context']==handle['read_context']
                return handle,result
            handle,scan=query('scan',{'limit':100})
            assert [r['values'] for r in scan['rows']]==list(map(public,rows))
            for vector in ([0,0],[2,1],[1,2]):
                _,result=query('search',{'vector':vector,'model':'test-space-v1','top_k':8,'candidate_limit':12})
                independent=sorted(rows,key=lambda r:(sum((a-b)**2 for a,b in zip([r['id']%4,r['id']%3],vector)),key(r['id'],'long')))[:8]
                assert [int(r['values']['id']) for r in result['hits']]==[r['id'] for r in independent]
                checks+=1
            _,text=query('search',{'text':'gamma','top_k':12,'candidate_limit':12})
            assert [int(r['values']['id']) for r in text['hits']]==[r['id'] for r in rows if 'gamma' in r['title']]
            expected_bm25=math.log(1+(len(rows)-len(rows)//4+.5)/(len(rows)//4+.5))
            assert all(abs(hit['score']-expected_bm25)<1e-5 for hit in text['hits'])
            _,int_filter=query('search',{'vector':[0,0],'model':'test-space-v1','filter':{'field':'id','equals':'1'}})
            assert [r['values']['id'] for r in int_filter['hits']]==['1']
            _,filtered=query('search',{'vector':[0,0],'model':'test-space-v1','top_k':12,'candidate_limit':12,
                                       'filter':{'field':'active','equals':False}})
            assert all(not r['values']['active'] for r in filtered['hits'])
            _,fused=query('search',{'text':'database','vector':[0,0],'model':'test-space-v1','top_k':12,'candidate_limit':12})
            # Independent RRF ranking from separate single-mode results.
            _,bm=query('search',{'text':'database','top_k':12,'candidate_limit':12})
            _,vec=query('search',{'vector':[0,0],'model':'test-space-v1','top_k':12,'candidate_limit':12})
            scores={}
            for result in (bm,vec):
                for rank,hit in enumerate(result['hits'],1):scores[hit['logical_key']]=scores.get(hit['logical_key'],0)+1/(60+rank)
            assert [hit['logical_key'] for hit in fused['hits']]==sorted(scores,key=lambda k:(-scores[k],k))
            export_handle,export=query('exports',{'seed':'fixed-seed','train_basis_points':7000})
            assert client.request('GET','/v1/jobs/'+export_handle['query_id']+'/objects/'+media['sha256'])==media_payload
            parquet=client.request('GET','/v1/jobs/'+export_handle['query_id']+'/parquet')
            exported=pq.read_table(BytesIO(parquet)).to_pylist()
            assert exported==export['samples'] and len(exported)==len(rows)
            for row in exported:
                identity=[DATASET,'record',row['logical_key']]
                bucket=int.from_bytes(__import__('hashlib').sha256(encoded(['fixed-seed',identity])).digest()[:8],'big')%10000
                assert row['split']==('train' if bucket<7000 else 'validation')
                original=next(r for r in rows if key(r['id'],'long')==row['logical_key'])
                assert json.loads(row['values_json'])==public(original) and row['record_version']==bundle['revision']
                assert json.loads(row['media_json'])==([media] if original['id']%2==0 else [])
            _,repeat=query('exports',{'seed':'fixed-seed','train_basis_points':7000})
            assert repeat['samples']==export['samples']
            checks+=9
            env=dict(os.environ,GURADB_TOKEN=token)
            cli=subprocess.run([sys.executable,'clients/cli/m1.py','--url',process.url,'search','--dataset',DATASET,
                                '--query','{"text":"gamma"}'],cwd=ROOT,env=env,capture_output=True,text=True,timeout=20)
            assert cli.returncode==0,cli.stderr
            assert json.loads(cli.stdout)['hits']
            # All lifecycle/byte downloads reauthorize; a different principal cannot inspect handles.
            control.grant(digest(b'other-token'),'tenant-a','other',DATASET)
            other=Client(process.url,'other-token')
            try:other.request('GET','/v1/jobs/'+handle['query_id'])
            except RuntimeError as error:assert 'not_found' in str(error)
            else:raise AssertionError('cross-principal handle leaked')
            for bad in [{'vector':[1],'model':'test-space-v1'},{'vector':[1,2],'model':'wrong'},
                        {'text':'*'},{'text':'gamma','top_k':0},{'text':'gamma','candidate_limit':1001},
                        {'text':'gamma','filter':{'field':'missing','equals':1}},{'text':'gamma','unknown':True},{'text':'gamma','filter':{'field':'active','equals':'true'}},
                        {'text':'gamma','filter':{'field':'id','equals':'01'}}]:
                h=client.request('POST','/v1/search',{'dataset_id':DATASET,'query':bad})
                try:client.wait(h)
                except RuntimeError:pass
                else:raise AssertionError(bad)
                checks+=1
            old_features=feature_file(lake,rows[:len(rows)//2])
            history=construct(control,DATASET,'historical',target(table,old_features,old),directory/'builds')
            assert publish(control,history['id'],1)==2
            _,current=query('scan',{'limit':100})
            assert [r['values'] for r in current['rows']]==list(map(public,rows[:len(rows)//2]))
            _,pinned=query('scan',{'limit':100},handle['read_context']['read_view_id'])
            assert [r['values'] for r in pinned['rows']]==list(map(public,rows))
            assert client.request('GET','/v1/jobs/'+export_handle['query_id']+'/results')['samples']==export['samples']
            checks+=4
            control.revoke('tenant-a','reader',DATASET)
            for suffix in ('','/results','/parquet','/objects/'+media['sha256']):
                try:client.request('GET','/v1/jobs/'+export_handle['query_id']+suffix)
                except RuntimeError as error:assert 'not_found' in str(error)
                else:raise AssertionError('revocation bypass')
            control.grant(digest(token.encode()),'tenant-a','reader',DATASET)
        finally:process.stop()
        # Explicit historical selection and rejection before data reads.
        old_features=feature_file(lake,rows[:len(rows)//2])
        history=construct(control,DATASET,'historical',target(table,old_features,old),directory/'builds')
        historical=json.loads(Path(history['artifact']['path']).read_bytes())
        assert [r['values'] for r in historical['rows']]==rows[:len(rows)//2]
        metadata=Path(selected['metadata_uri'].removeprefix('file://'))
        original=json.loads(metadata.read_bytes())
        for mutate in [lambda m:m.update(**{'format-version':1}), lambda m:m['schemas'].append(deepcopy(m['schemas'][0])),
                       lambda m:m['partition-specs'][0]['fields'].append({'name':'x'}),
                       lambda m:m['schemas'][0]['fields'][0].update(type='double'),
                       lambda m:m.update(snapshots=[]),lambda m:m['snapshots'][-1].update(**{'schema-id':999})]:
            bad=deepcopy(original);mutate(bad)
            path=lake/'negative.metadata.json';path.write_bytes(encoded(bad))
            rejects(lambda:snapshot(Objects(lake.as_uri(),Budget()),path.as_uri(),digest(path.read_bytes()),
                                    selected['snapshot_id'],DATASET,'documents','id',directory/'rejected'))
            checks+=1
        rejects(lambda:snapshot(Objects(lake.as_uri(),Budget()),metadata.as_uri(),'0'*64,selected['snapshot_id'],
                                DATASET,'documents','id',directory/'rejected'),'source_invalid')
        for name in ('position-delete','equality-delete','duplicate-file','oversized-records','incorrect-size','cross-root',
                     'field-id-mismatch','missing-field-id','duplicate-key','null-key','reordered-fields'):
            uri,sha=mutated(lake,selected,name)
            rejects(lambda:snapshot(Objects(lake.as_uri(),Budget()),uri,sha,selected['snapshot_id'],
                                    DATASET,'documents','id',directory/'rejected'))
            checks+=1
        # Rejected embedding coverage and malformed model data cannot become ready.
        features_value=json.loads(Path(feature_file(lake,rows,media=media)[0].removeprefix('file://')).read_bytes())
        for n,mutate in enumerate([lambda f:f['records'].pop(),lambda f:f.update(dimension=257),
                                   lambda f:f['records'][0].update(vector=[True,1]),lambda f:f.update(metric='cosine')]):
            bad=deepcopy(features_value);mutate(bad)
            path=lake/'bad-features.json';path.write_bytes(encoded(bad))
            chosen=dict(selected,features_uri=path.as_uri(),features_sha256=digest(path.read_bytes()))
            rejects(lambda:construct(control,DATASET,'bad-features-'+str(n),chosen,directory/'builds'))
            checks+=1
        # Real Avro deletion manifest marker is rejected before a data GET.
        selected_meta=next(s for s in original['snapshots'] if s['snapshot-id']==selected['snapshot_id'])
        list_path=Path(selected_meta['manifest-list'].removeprefix('file://'))
        reader=fastavro.reader(BytesIO(list_path.read_bytes()));records=list(reader)
        records[0]['content']=1
        out=BytesIO();fastavro.writer(out,reader.writer_schema,records,metadata=reader.metadata)
        original_list=list_path.read_bytes();list_path.write_bytes(out.getvalue())
        objects=Objects(lake.as_uri(),Budget())
        try:
            rejects(lambda:snapshot(objects,metadata.as_uri(),digest(metadata.read_bytes()),selected['snapshot_id'],
                                    DATASET,'documents','id',directory/'rejected'))
            assert objects.budget.reads==2
        finally:list_path.write_bytes(original_list)
        checks+=3
        lab.event('m1_functional_passed',assertions=checks)
    return {'passed':True,'suite':'functional','assertions':checks,'oracles':['PyIceberg 0.10.0','PyArrow 22','independent exhaustive L2/RRF/split'],
            'scope':'M1 local Iceberg -> PG -> Tantivy/exact/RRF -> HTTP/CLI -> training'}
