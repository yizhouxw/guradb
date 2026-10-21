"""Catalog authority values, unknown outcomes and idempotency fail closed."""
from copy import deepcopy
import unittest
from test_cf1a_wire import contract
from modules.common.cf1a_ports import ArtifactReadPort, CatalogReadPort, ObjectReadPort, SourceReadPort
from modules.common.cf1a_publication import check_cas, check_receipt, check_replay, check_target
from modules.common.cf1a_wire import ContractFailure, digest


class Cf1aPublicationTests(unittest.TestCase):
    def test_compare_and_swap_owner_and_monotonic_publication(self):
        register,publish=contract(2).value,contract(3).value
        check_cas(register,0,1)
        check_cas(publish,1,1)
        check_replay(publish,deepcopy(publish))
        for args,code in (((publish,1,2),'stale_generation'),((publish,2,1),'conflict'),
                          ((publish,1,1,'new-view',0),'conflict'),((publish,1,1,'',1),'conflict')):
            with self.assertRaises(ContractFailure) as caught:check_cas(*args)
            self.assertEqual(caught.exception.code,code)
        changed=deepcopy(publish);changed['owner_epoch']=2
        with self.assertRaises(ContractFailure):check_replay(publish,changed)
        for change in (lambda x:x.update(artifact_ids=['x','x']),lambda x:x.update(expected_generation=0,expected_view_id='other'),
                       lambda x:x.update(target_view_id='view-1',expected_view_id='view-1',expected_generation=1)):
            with self.assertRaises(ContractFailure):contract(3,change)

    def test_receipts_are_tied_to_intent_and_unknown_requires_reconcile(self):
        publish=contract(3).value
        self.assertTrue(check_receipt(publish,contract(4).value))
        for state,error in (('rejected','conflict'),('outcome_unknown','outcome_unknown')):
            receipt=contract(4,lambda x:x.update(state=state,error_code=error,result_id='')).value
            self.assertEqual(check_receipt(publish,receipt),state!='outcome_unknown')
        for change in (lambda x:x.update(generation=3),lambda x:x.update(result_id='wrong'),
                       lambda x:x.update(operation_id='other'),lambda x:x.update(request_sha256='b'*64)):
            with self.assertRaises(ContractFailure):check_receipt(publish,contract(4,change).value)
        for change in (lambda x:x.update(state='outcome_unknown'),lambda x:x.update(state='rejected'),
                       lambda x:x.update(result_id=''),lambda x:x.update(error_code='conflict')):
            with self.assertRaises(ContractFailure):contract(4,change)
        register=contract(2).value
        receipt=contract(4,lambda x:x.update(operation_id=register['operation_id'],request_sha256=digest(register),result_id='revision-1',generation=1)).value
        self.assertTrue(check_receipt(register,receipt))
        for change in (lambda x:x.update(retryable=True),lambda x:x.update(reconcile_ref='')):
            with self.assertRaises(ContractFailure):contract(6,change)
        contract(6,lambda x:x.update(code='backend_unavailable',retryable=True,reconcile_ref=''))

    def test_intents_bind_reviewed_immutable_descriptors(self):
        for index in (2,3):check_target(contract(index),contract(11))
        with self.assertRaises(ContractFailure):check_target(contract(4),contract(11))
        for change in (lambda x:x.update(dataset_id='other'),lambda x:x.update(revision_sha256='b'*64)):
            with self.assertRaises(ContractFailure):check_target(contract(2,change),contract(11))
        with self.assertRaises(ContractFailure):check_target(contract(3,lambda x:x.update(target_view_sha256='b'*64)),contract(11))

    def test_ports_are_only_injected_dependency_contracts(self):
        def bind(request):
            self.assertEqual(request.kind,'bind_request')
            return contract(0)
        def mutation(intent,authorization,target):
            self.assertIn(intent.kind,('register_intent','publish_intent'))
            self.assertEqual(authorization.kind,'mutation_auth')
            self.assertEqual(target.kind,'read_descriptors')
            return contract(4)
        def reconcile(intent,authorization):
            self.assertIn(intent.kind,('register_intent','publish_intent'))
            self.assertEqual(authorization.kind,'mutation_auth')
            return contract(4)
        catalog=CatalogReadPort(bind,lambda x:1,mutation,mutation,lambda x:None,reconcile)
        self.assertEqual(catalog.bind(contract(7)).kind,'read_binding')
        self.assertEqual(catalog.reauthorize(contract(0)),1)
        for callback in (catalog.register,catalog.publish):self.assertEqual(callback(contract(3),contract(9),contract(11)).kind,'mutation_receipt')
        self.assertIsNone(catalog.release_pin(contract(0)))
        from modules.common.cf1a_ports import reauthorize_read, release_bound_pin
        reauthorize_read(catalog,contract(0),1001)
        release_bound_pin(catalog,contract(0))
        with self.assertRaises(ContractFailure):reauthorize_read(catalog,contract(3),1001)
        with self.assertRaises(ContractFailure):release_bound_pin(catalog,contract(3))
        self.assertEqual(catalog.reconcile(contract(3),contract(9)).kind,'mutation_receipt')
        objects=ObjectReadPort(lambda x:None,lambda binding,ref,start,length:b'x'*length)
        self.assertIsNone(objects.verify_proof({}))
        self.assertEqual(objects.read(contract(0),{},0,1),b'x')
        self.assertEqual(SourceReadPort(lambda binding,ordinal:contract(1)).read_batch(contract(0),0).kind,'read_batch')
        self.assertEqual(ArtifactReadPort(lambda binding,query:contract(8),lambda binding,name:b'x').read_artifact(contract(0),'artifact-1'),b'x')

    def test_mutation_authorization_is_separate_and_revalidated(self):
        from modules.common.cf1a_publication import check_mutation_auth
        for index in (2,3):
            check_mutation_auth(contract(index),contract(9),1000,1)
            check_mutation_auth(contract(index),contract(9),1000,1,reconcile=True)
        for change,now,epoch in ((lambda x:x.update(dataset_id='other'),1000,1),
                                 (lambda x:x.update(actions=['register']),1000,1),
                                 (lambda x:x.update(policy_epoch=2),1000,1),
                                 (lambda x:None,100000,1)):
            with self.assertRaises(ContractFailure):check_mutation_auth(contract(3),contract(9,change),now,epoch)
        with self.assertRaises(ContractFailure):check_mutation_auth(contract(0),contract(9),1000,1)
        with self.assertRaises(ContractFailure):contract(9,lambda x:x.update(actions=['publish','publish']))

    def test_authoritative_port_numbers_do_not_accept_bool_or_overflow(self):
        for number in (True,-1,1<<53):
            with self.assertRaises(ContractFailure):check_cas(contract(3).value,number,1)
            with self.assertRaises(ContractFailure):check_cas(contract(3).value,1,number)
        from modules.common.cf1a_read import validate_access
        for epoch in (True,0,-1,1<<53):
            with self.assertRaises(ContractFailure):validate_access(contract(0).value,1001,epoch)
