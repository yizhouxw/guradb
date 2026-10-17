"""Build independently encoded negative Iceberg/Parquet fixtures from ecosystem output."""
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path

import fastavro
import pyarrow as pa
import pyarrow.parquet as pq

from modules.common.contracts import digest, encoded


def mutated(lake, target, name):
    meta=json.loads(Path(target['metadata_uri'].removeprefix('file://')).read_bytes())
    snap=next(s for s in meta['snapshots'] if s['snapshot-id']==target['snapshot_id'])
    lists=fastavro.reader(BytesIO(Path(snap['manifest-list'].removeprefix('file://')).read_bytes()))
    manifests=list(lists)
    reader=fastavro.reader(BytesIO(Path(manifests[0]['manifest_path'].removeprefix('file://')).read_bytes()))
    entries=list(reader)
    header=dict(reader.metadata)
    live=next(e for e in entries if e['status']!=2)
    data=live['data_file']
    if name in ('position-delete','equality-delete'):
        data['content']=1 if name=='position-delete' else 2
    elif name=='duplicate-file':
        entries.append(deepcopy(live))
    elif name=='oversized-records':
        data['record_count']=10001
    elif name=='incorrect-size':
        data['file_size_in_bytes']+=1
    elif name=='cross-root':
        data['file_path']='file:///tmp/never-read-guradb.parquet'
    else:
        table=pq.read_table(Path(data['file_path'].removeprefix('file://')))
        fields=list(table.schema)
        values=table.to_pylist()
        if name=='field-id-mismatch':
            fields[0]=fields[0].with_metadata({b'PARQUET:field_id':b'99'})
        elif name=='missing-field-id':
            fields[0]=fields[0].with_metadata(None)
        elif name=='duplicate-key':
            values[1]['id']=values[0]['id']
        elif name=='reordered-fields':
            fields=fields[::-1]
        elif name=='null-key':
            values[0]['id']=None
            fields[0]=pa.field(fields[0].name,fields[0].type,nullable=True,metadata=fields[0].metadata)
            meta['schemas'][0]['fields'][0]['required']=False
            source_schema=json.loads(header['schema']);source_schema['fields'][0]['required']=False
            header['schema']=json.dumps(source_schema)
        else:raise AssertionError(name)
        source=lake/(name+'.parquet')
        pq.write_table(pa.Table.from_pylist(values,schema=pa.schema(fields)),source)
        data['file_path']=source.as_uri()
        data['file_size_in_bytes']=source.stat().st_size
    raw=BytesIO();fastavro.writer(raw,reader.writer_schema,entries,metadata=header)
    manifest=lake/(name+'.avro');manifest.write_bytes(raw.getvalue())
    manifests[0]['manifest_path']=manifest.as_uri()
    manifests[0]['manifest_length']=len(raw.getvalue())
    raw=BytesIO();fastavro.writer(raw,lists.writer_schema,manifests,metadata=lists.metadata)
    manifest_list=lake/(name+'-list.avro');manifest_list.write_bytes(raw.getvalue())
    snap['manifest-list']=manifest_list.as_uri()
    path=lake/(name+'.metadata.json');path.write_bytes(encoded(meta))
    return path.as_uri(),digest(path.read_bytes())
