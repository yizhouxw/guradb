"""Independent global-statistics BM25 truth under skewed disjoint partitions."""
from collections import Counter
import math
from pathlib import Path
import re
import tempfile
import unittest

from modules.common.contracts import Budget, Failure, key
from modules.index.bm25 import build, ranked
from modules.index.retrieval import search
from modules.query.distributed import execute


class GlobalBM25(unittest.TestCase):
    def test_global_statistics_and_filtered_rrf(self):
        texts = ['alpha '*19, 'beta', None, 'gamma alpha', 'alpha beta', 'gamma '*7, 'beta beta alpha']
        rows = [{'logical_key':key(i,'long'), 'record_version':'stable-'+str(i),
                 'values':{'title':text,'id':i,'active':i%2==0}, 'vector':[float(i),0.], 'media':[]}
                for i,text in enumerate(texts)]
        with tempfile.TemporaryDirectory() as directory:
            bundle = {'rows':rows, 'revision':'revision', 'context':{'read_view_id':'fixed'},
                      'model':{'model':'test','dimension':2},'retention_mode':'managed-copy',
                      'index_path':'unused', 'index_files':[], 'manifest':{'dataset_id':'dataset',
                      'schema':[{'name':'title','data_type':'text'},{'name':'id','data_type':'int8'},{'name':'active','data_type':'bool'}]},
                      'bm25':build(Path(directory)/'index',rows,'title',Budget())}
            query = 'alpha beta'
            tokens = [re.findall('[a-z0-9]+', (text or '').lower()) for text in texts]
            avg = sum(map(len,tokens))/len(tokens)
            truth = []
            for i,document in enumerate(tokens):
                frequencies = Counter(document)
                score = 0.
                for word in query.split():
                    count = frequencies[word]
                    df = sum(word in doc for doc in tokens)
                    if count:
                        score += math.log((len(tokens)+1)/(df+.5))*count*2.2/(count+1.2*(.25+.75*len(document)/avg))
                if score:
                    truth.append((rows[i]['logical_key'],score))
            truth.sort(key=lambda hit:(-hit[1],hit[0]))
            actual = ranked(bundle,query,{row['logical_key'] for row in rows},Budget())
            self.assertEqual([k for k,_ in actual],[k for k,_ in truth])
            for a,b in zip(actual,truth):
                self.assertAlmostEqual(a[1],b[1],places=14)
            requests = [{'text':query,'top_k':4,'candidate_limit':5},
                        {'text':query,'filter':{'field':'active','equals':True},'top_k':4,'candidate_limit':5},
                        {'text':query,'vector':[2.,0.],'model':'test','top_k':4,'candidate_limit':5}]
            for request in requests:
                single = search(bundle,request,Budget())
                parallel = execute(bundle,request=request,kind='search',budget=Budget(),root=Path(directory)/'jobs',
                                   principal={'tenant':'t','subject':'s'})
                self.assertEqual(single['hits'],parallel['hits'])
                self.assertEqual(len(parallel['execution']['workers']),3)
            # Same-length statistics corruption is detected by the immutable reference.
            path=Path(bundle['bm25']['stats']['path'])
            path.write_bytes(path.read_bytes().replace(b'1.2',b'9.9'))
            with self.assertRaises(Failure) as caught:
                search(bundle,{'text':query},Budget())
            self.assertEqual(caught.exception.code,'source_invalid')


if __name__ == '__main__':
    unittest.main()
