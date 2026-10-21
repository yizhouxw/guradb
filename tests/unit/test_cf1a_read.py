"""Independent mutations exercise shared-read boundaries and trusted inputs."""
from copy import deepcopy
import unittest
from test_cf1a_wire import GOLDEN, contract
from modules.common.cf1a_wire import ContractFailure, canonical, decode, digest
from modules.common.cf1a_read import (validate_access, validate_batch_for, validate_range, without)


class Cf1aReadTests(unittest.TestCase):
    def test_binding_refuses_mismatched_identities_versions_and_retention(self):
        changes = [
            lambda x:x['resource']['fields'][1].update(field_id=1),
            lambda x:x['resource']['fields'][1].update(role='value'),
            lambda x:x['resource'].update(schema_sha256='b'*64),
            lambda x:x['context'].update(dataset_id='other'),
            lambda x:x['context'].update(tenant_id='other'),
            lambda x:x['context']['auth'].update(dataset_id='other'),
            lambda x:x['context']['pin'].update(data_revision_id='other'),
            lambda x:x['context']['pin'].update(read_view_id='other'),
            lambda x:x['revision'].update(parent_revision_ids=['revision-1']),
            lambda x:x['revision'].update(sources=x['revision']['sources']*2),
            lambda x:x['context'].update(source_version_ids=['other']),
            lambda x:x['context'].update(deadline_unix_ms=32000),
            lambda x:x['context']['auth'].update(expires_unix_ms=1000),
            lambda x:x['context']['pin'].update(expires_unix_ms=1000),
            lambda x:x['revision']['sources'][0].update(format_version='2'),
            lambda x:x['revision']['sources'][0].update(resource_schema_sha256='b'*64),
            lambda x:x['revision']['sources'][0]['field_mapping'][0].update(type='int8'),
            lambda x:x['revision']['sources'][0].update(protected_until_unix_ms=99999),
            lambda x:x['revision'].update(objects=x['revision']['objects']*2),
            lambda x:x['indexes'][0].update(data_revision_id='other'),
            lambda x:x['indexes'][0].update(source_version_ids=['other']),
            lambda x:x['view'].update(index_requirements=[]),
            lambda x:x['indexes'][0].update(model_version='other'),
            lambda x:x['indexes'][0].update(deletion_watermark=1),
            lambda x:x['indexes'][0].update(shard_count=2),
            lambda x:x['indexes'][0].update(shards=x['indexes'][0]['shards']*2,shard_count=2),
            lambda x:x['indexes'][0].update(reader_capabilities=['other']),
            lambda x:x['indexes'][0].update(kind='bm25'),
            lambda x:x['context'].update(artifact_ids=[]),
            lambda x:x['context']['budget'].update(top_k=100),
        ]
        for number, change in enumerate(changes):
            with self.subTest(change=number), self.assertRaises(ContractFailure):
                contract(0, change)
        for name in ('revision', 'view'):
            with self.subTest(digest=name), self.assertRaises(ContractFailure):
                contract(0, lambda x:x[name].update(**{'content_sha256' if name=='revision' else 'descriptor_sha256':'b'*64}),False)
        def bm25(x):
            x['indexes'][0].update(kind='bm25',metric='bm25',dimension=1,analyzer='pretokenized-v1')
            x['view']['index_requirements'][0].update(metric='bm25',dimension=1,analyzer='pretokenized-v1')
            x['revision']['sources'][0].update(format='iceberg',format_version='2')
        self.assertEqual(contract(0,bm25).kind,'read_binding')

    def test_whole_and_trusted_block_range_contract(self):
        ref = deepcopy(GOLDEN[0]['payload']['read_binding']['revision']['objects'][0])
        validate_range(ref,0,8)
        for offset,length in ((0,4),(1,7),(-1,8),(0,0),(8,1),(True,1),(0,9)):
            with self.subTest(offset=offset,length=length), self.assertRaises(ContractFailure):
                validate_range(ref,offset,length)
        ref['integrity'].update(mode='block_sha256',block_size=3,block_sha256=['a'*64]*3,proof_ref='trusted-blocks-1')
        for offset,length in ((0,3),(3,3),(6,2),(0,8)):
            validate_range(ref,offset,length)
        for offset,length in ((1,3),(0,2),(3,4)):
            with self.assertRaises(ContractFailure):validate_range(ref,offset,length)
        for change in (lambda x:x.update(key=''),lambda x:x['integrity'].update(block_size=0),
                       lambda x:x['integrity'].update(block_sha256=[]),
                       lambda x:x['integrity'].update(proof_ref=''),
                       lambda x:x['integrity'].update(mode='whole_sha256')):
            bad=deepcopy(ref);change(bad)
            with self.assertRaises(ContractFailure):validate_range(bad,0,8)
        self.assertTrue(ref['integrity']['proof_ref'])  # This still does not authenticate the proof.

    def test_batches_context_schema_null_order_and_budgets(self):
        validate_batch_for(contract(0),contract(1))
        changes=[lambda x:x.update(content_sha256='b'*64),
                 lambda x:x['rows'][0].update(cells=x['rows'][0]['cells'][:-1]),
                 lambda x:x['rows'][0]['cells'][2].update(type='bool',value=False),
                 lambda x:x['rows'][0].update(record_version='other'),
                 lambda x:x['rows'].append(deepcopy(x['rows'][0])),
                 lambda x:x['rows'].reverse(),lambda x:x.update(truncated=True,last=False)]
        for number,change in enumerate(changes):
            with self.subTest(change=number), self.assertRaises(ContractFailure):
                contract(1,change,number!=0)
        for change in (lambda x:x.update(context_sha256='b'*64),lambda x:x.update(schema_version=2),
                       lambda x:x['usage'].update(memory_bytes=4097)):
            with self.assertRaises(ContractFailure):validate_batch_for(contract(0),contract(1,change))
        with self.assertRaises(ContractFailure):validate_batch_for(contract(1),contract(0))
        self.assertEqual(contract(1,lambda x:x.update(ordering='unspecified')).kind,'read_batch')
        self.assertEqual(contract(1,lambda x:x.update(truncated=True)).kind,'read_batch')

    def test_access_requires_current_authority_and_same_deadline(self):
        binding=contract(0).value
        validate_access(binding,1001,1)
        for now,epoch,code in ((999,1,'invalid_contract'),(1001,2,'revoked'),(31000,1,'deadline')):
            with self.assertRaises(ContractFailure) as caught:validate_access(binding,now,epoch)
            self.assertEqual(caught.exception.code,code)
        for change in (lambda x:x.update(max_batch_rows=1025),lambda x:x.update(capabilities=['fixed_read'])):
            with self.assertRaises(ContractFailure):contract(5,change)

    def test_source_identity_transforms_and_immutable_reference_agreement(self):
        def transforms(x):
            mappings=x['revision']['sources'][0]['field_mapping']
            mappings[0].update(source_type='int8',transform='key_v1')
            mappings[1].update(source_field_id=0,source_type='none',transform='revision_version')
        binding=contract(0,transforms)
        with self.assertRaises(ContractFailure):validate_batch_for(binding,contract(1))
        for change in (lambda x:x['revision']['sources'][0]['field_mapping'][0].update(transform='revision_version'),
                       lambda x:x['revision']['sources'][0]['field_mapping'][2].update(source_field_id=1),
                       lambda x:x['revision']['objects'][0].update(size_bytes=9)):
            with self.assertRaises(ContractFailure):contract(0,change)
        def mixed(x):
            source=deepcopy(x['revision']['sources'][0]);source.update(source_id='source-2',source_version_id='source-version-2')
            source['field_mapping'][1].update(source_field_id=0,source_type='none',transform='revision_version')
            x['revision']['sources'].append(source)
            x['indexes'][0]['source_version_ids'].append('source-version-2')
            x['context']['source_version_ids'].append('source-version-2')
        with self.assertRaises(ContractFailure):contract(0,mixed)
        self.assertNotIn('context',contract(11).value)
        opaque=contract(0,lambda x:x['revision']['sources'][0]['metadata'].update(bucket='legal.bucket',version='opaque+/=version'))
        self.assertIn('+/',opaque.value['revision']['sources'][0]['metadata']['version'])
        for invalid in ('','bad\nversion','a'*1025):
            with self.assertRaises(ContractFailure):contract(0,lambda x:x['revision']['sources'][0]['metadata'].update(version=invalid))

    def test_bind_request_published_and_explicit(self):
        self.assertEqual(contract(7).value['view_mode'],'published')
        contract(7,lambda x:x.update(view_mode='explicit',read_view_id='view-1'))
        for change in (lambda x:x.update(timeout_ms=30001),lambda x:x.update(read_view_id='view-1'),
                       lambda x:x.update(view_mode='explicit'),lambda x:x.update(view_mode='explicit',read_view_id='latest')):
            with self.assertRaises(ContractFailure):contract(7,change)

    def test_index_query_candidates_and_model_filter_binding(self):
        from modules.common.cf1a_read import validate_candidates_for
        binding,query,batch=contract(0),contract(10),contract(8)
        validate_candidates_for(binding,query,batch)
        for change in (lambda x:x.update(complete=False),lambda x:x.update(score_order='descending'),
                       lambda x:x['rows'][0].update(score_f64_hex='7ff0000000000000'),
                       lambda x:x['rows'][0].update(score_f64_hex='bff0000000000000')):
            with self.assertRaises(ContractFailure):contract(8,change)
        for change in (lambda x:x.update(candidate_limit=2),lambda x:x.update(query_text='undeclared'),
                       lambda x:x.update(allowed_record_ids=['x']),
                       lambda x:x.update(query_vector_f64_hex=['7fefffffffffffff']*3)):
            with self.assertRaises(ContractFailure):contract(10,change)
        for change in (lambda x:x.update(artifact_id='other'),lambda x:x['rows'][0]['locator'].update(source_version_id='other'),
                       lambda x:x['usage'].update(output_bytes=99999)):
            with self.assertRaises(ContractFailure):validate_candidates_for(binding,query,contract(8,change))
        with self.assertRaises(ContractFailure):validate_candidates_for(query,binding,batch)
        with self.assertRaises(ContractFailure):validate_candidates_for(binding,contract(10,lambda x:x.update(candidate_limit=17)),batch)
        filtered=contract(10,lambda x:x.update(filter_mode='ids',allowed_record_ids=['other']))
        filteredbatch=contract(8,lambda x:x.update(index_query_sha256=filtered.sha256))
        with self.assertRaises(ContractFailure):validate_candidates_for(binding,filtered,filteredbatch)
        def ordered(x):
            second=deepcopy(x['rows'][0]);second.update(record_id='record-2',score_f64_hex='3ff0000000000000');x['rows'].append(second)
        contract(8,ordered)
        with self.assertRaises(ContractFailure):contract(8,lambda x:(ordered(x),x['rows'].reverse()))
        contract(10,lambda x:x.update(kind='bm25',metric='bm25',dimension=1,query_text='test',query_vector_f64_hex=[]))
