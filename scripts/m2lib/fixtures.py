"""Deterministic ANN vectors, true relation fixtures and live service helpers."""
import json
from pathlib import Path
import random
import threading

import pyarrow as pa
from pyiceberg.catalog import load_catalog
from pyiceberg.schema import Schema
from pyiceberg.types import NestedField, LongType, StringType

from clients.common.http import Client
from modules.common.contracts import digest, encoded, key
from modules.gateway.m1 import Server
from modules.query.service import Service


def features(directory, rows, dimensions=16):
    rng = random.Random(17)
    vectors = {r['id']:[rng.uniform(-1,1) for _ in range(dimensions)] for r in rows}
    value = {'model':'m2-test-17','dimension':dimensions,'metric':'squared_l2','preprocessing':'identity-v1',
             'records':[{'logical_key':key(r['id'],'long'),'vector':vectors[r['id']],'media':[]} for r in rows]}
    raw = encoded(value)
    path = directory/'ann-features.json'
    path.write_bytes(raw)
    return (path.as_uri(),digest(raw)), vectors


def edges(directory, count=60):
    directory.mkdir(parents=True)
    cat = load_catalog('edges',type='sql',uri='sqlite:///'+str(directory/'cat.db'),warehouse=(directory/'warehouse').as_uri())
    cat.create_namespace('edges')
    schema = Schema(NestedField(1,'id',LongType(),required=True),NestedField(2,'source',LongType(),required=True),
                    NestedField(3,'target',LongType(),required=True),NestedField(4,'kind',StringType(),required=True))
    table = cat.create_table('edges.relations',schema=schema)
    rows = [{'id':i,'source':i%10,'target':(i+1)%13,'kind':'link' if i%2==0 else 'other'} for i in range(count)]
    arrow = pa.schema([pa.field('id',pa.int64(),False),pa.field('source',pa.int64(),False),pa.field('target',pa.int64(),False),pa.field('kind',pa.string(),False)])
    table.append(pa.Table.from_pylist(rows,schema=arrow))
    return table, rows


class Serving:
    def __init__(self, control, root, token, workers=3, worker_endpoints=None, worker_secret=None):
        self.service = Service(control,root,workers=workers,worker_endpoints=worker_endpoints,worker_secret=worker_secret)
        self.server = Server(('127.0.0.1',0),self.service)
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.client = Client('http://127.0.0.1:'+str(self.server.server_port),token)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.service.close()


def query(client, dataset, kind, query):
    route = 'exports' if kind == 'export' else kind
    handle = client.request('POST','/v1/'+route,{'dataset_id':dataset,'query':query})
    result = client.wait(handle)
    return handle,result


def workers(result, count):
    evidence = result['execution']['workers']
    assert len(evidence)==3 and len({worker['pid'] for worker in evidence})==3
    assert all(worker['records']>0 for worker in evidence)
    assert sum(worker['records'] for worker in evidence)==count
    return evidence
