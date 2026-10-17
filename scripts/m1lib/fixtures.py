"""Independent PyIceberg writer/reader and isolated PG/S3 environment."""
import hashlib
import json
from pathlib import Path
import secrets
import subprocess
import sys
import time

import pyarrow as pa
from pyiceberg.catalog import load_catalog
from pyiceberg.schema import Schema
from pyiceberg.types import NestedField, LongType, StringType, BooleanType

from m0lib.kit import DATASET, PG, ROOT, docker, laboratory, write
from modules.catalog.control import Control
from modules.common.contracts import digest, encoded, key


def iceberg(directory, count=12, properties=None, location=None):
    directory.mkdir(parents=True, exist_ok=True)
    catalog = load_catalog('oracle',type='sql',uri='sqlite:///'+str(directory/'catalog.db'),
                           warehouse=(directory/'warehouse').as_uri(),**(properties or {}))
    catalog.create_namespace('oracle')
    schema = Schema(NestedField(1,'id',LongType(),required=True),NestedField(2,'title',StringType()),NestedField(3,'active',BooleanType()))
    table = catalog.create_table('oracle.documents',schema=schema,location=location)
    arrow = pa.schema([pa.field('id',pa.int64(),nullable=False),pa.field('title',pa.string()),pa.field('active',pa.bool_())])
    rows = [{'id':i,'title': ['alpha alpha beta','beta','gamma database','database alpha'][i%4], 'active':i%2==0} for i in range(count)]
    first = pa.Table.from_pylist(rows[:count//2],schema=arrow)
    second = pa.Table.from_pylist(rows[count//2:],schema=arrow)
    table.append(first)
    old = table.current_snapshot().snapshot_id
    table.append(second)
    return table, old, rows


def feature_file(directory, rows, objects=None, media=None):
    values = {'model':'test-space-v1','dimension':2,'metric':'squared_l2','preprocessing':'identity-v1',
              'records':[{'logical_key':key(r['id'],'long'),'vector':[float(r['id']%4),float(r['id']%3)],'media':([media] if media and r['id']%2==0 else [])} for r in rows]}
    raw = encoded(values)
    if objects:
        objects.put_object(Bucket='m0-data',Key='lake/features.json',Body=raw)
        return 's3://m0-data/lake/features.json',digest(raw)
    path=directory/'features.json'
    path.write_bytes(raw)
    return path.as_uri(),digest(raw)


def pg(lab):
    name = lab.container(PG,options=('-e','POSTGRES_HOST_AUTH_METHOD=trust','-p','127.0.0.1::5432'))
    dsn = 'host=127.0.0.1 port='+lab.port(name,5432)+' user=postgres dbname=postgres'
    def ready():
        try:
            with Control(dsn).transaction() as conn:
                return conn.execute('SELECT 1').fetchone() is not None
        except Exception:
            return False
    lab.wait(ready)
    control=Control(dsn)
    control.initialize()
    return control,name,dsn


def target(table, features, snapshot_id=None, s3=None):
    uri=table.metadata_location
    if uri.startswith('s3://'):
        raw=s3.get_object(Bucket='m0-data',Key=uri.removeprefix('s3://m0-data/'))['Body'].read()
    else:
        raw=Path(uri.removeprefix('file://')).read_bytes()
    return {'metadata_uri':uri,'metadata_sha256':digest(raw),
            'snapshot_id':snapshot_id or table.current_snapshot().snapshot_id,
            'features_uri':features[0],'features_sha256':features[1]}


class HttpProcess:
    def __init__(self, directory, dsn):
        self.directory, self.dsn=directory,dsn
        self.process=None

    def start(self, entry=None):
        import os
        import socket
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        self.log=(self.directory/'http.log').open('ab')
        self.process=subprocess.Popen([sys.executable,str(entry or 'scripts/m1.py'),'--root',str(self.directory/'serving'),'serve','--port',str(port)],
                                      cwd=ROOT,env=dict(os.environ,GURADB_PG_DSN=self.dsn),stdout=self.log,stderr=self.log)
        self.url='http://127.0.0.1:'+str(port)
        from urllib.request import urlopen
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            try:
                if urlopen(self.url+'/healthz',timeout=1).status==200:return self
            except Exception:
                if self.process.poll() is not None:break
                time.sleep(.05)
        raise AssertionError((self.directory/'http.log').read_text())

    def stop(self, crash=False):
        if self.process and self.process.poll() is None:
            self.process.kill() if crash else self.process.terminate()
            self.process.wait(timeout=10)
        if hasattr(self,'log'):self.log.close()
