"""Process exit/cancellation and cross-shard graph budgets fail the entire job."""
from pathlib import Path
import threading
from unittest.mock import patch

from modules.cluster.local import fanout
from modules.common.contracts import Budget, Failure, key
from modules.query.distributed import execute


def rejected(code, call):
    try:call()
    except Failure as error:assert error.code==code,(error.code,code)
    else:raise AssertionError('expected '+code)


def run(directory):
    root=Path(directory);root.mkdir(parents=True,exist_ok=True)
    cancelled=threading.Event()
    original=__import__('subprocess').Popen
    processes=[]
    def start(*args,**kwargs):
        p=original(*args,**kwargs);processes.append(p)
        if len(processes)==3:cancelled.set()
        return p
    with patch('modules.cluster.local.subprocess.Popen',start):
        rejected('cancelled',lambda:fanout('modules.query.worker',[{}]*3,Budget(cancelled.is_set),root))
    assert len(processes)==3 and all(p.poll() is not None for p in processes)
    rejected('worker_failed',lambda:fanout('modules.no_such_worker',[{}]*3,Budget(),root))
    rows=[{'logical_key':key(i,'long'),'values':{'id':i,'s':1,'t':i,'kind':'link'}} for i in range(9)]
    bundle={'rows':rows,'revision':'rev','context':{'read_view_id':'view'},'model':{},'retention_mode':'managed-copy',
            'manifest':{'dataset_id':'d','schema':[{'name':'s','data_type':'int8'},{'name':'t','data_type':'int8'},{'name':'kind','data_type':'text'}]}}
    query={'source_field':'s','target_field':'t','type_field':'kind','seeds':[1],'type':'link','max_edges':10,'max_fanout':4}
    # Every local shard has only three matches, but the global fanout is nine.
    rejected('resource_limit',lambda:execute(bundle,'graph',query,Budget(),root,{'tenant':'t','subject':'s'}))
    rejected('timeout',lambda:execute(bundle,'graph',query,Budget(seconds=-1),root,{'tenant':'t','subject':'s'}))
    return {'passed':True,'suite':'stability-component','seed':17,'checks':['actual-worker-cancel-and-reap','worker-exit','global-fanout','deadline']}
