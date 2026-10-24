"""Reuse actual P04 Parquet fixture algorithms with mocked transport only."""
from copy import deepcopy
import tempfile
import unittest
from unittest.mock import patch

from modules.common.cf1a_primitives import ContractFailure
from modules.connectors.fixed_producer import FixedProducer
from modules.connectors.fixed_producer_credits import PreparedPermit, ProducerGrant
from modules.connectors.fixed_source_reader import FixedSourceReader
from tests.source_support.fixed_fixture import facts, make_fixture, unit_objects


class ProducerLifecycleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = temporary.name

    def producer(self, fixture=None, amount=8 << 20):
        fixture = fixture or make_fixture(self.root)
        objects, fetched, attempts = unit_objects(fixture)
        hook = patch('modules.storage.fixed_objects.fetch', side_effect=fetched)
        hook.start()
        self.addCleanup(hook.stop)
        producer = FixedProducer(FixedSourceReader(objects))
        grant = ProducerGrant(PreparedPermit('fixture-session', fixture['binding'].sha256, 1), amount)
        return fixture, producer, grant, attempts

    def ack(self, producer):
        sequence, response_digest = producer.completion
        self.assertTrue(producer.acknowledge(sequence, response_digest))
        self.assertFalse(producer.acknowledge(sequence, response_digest))

    def test_open_actual11_read_and_credit_only_after_consumer_release(self):
        fixture, producer, grant, attempts = self.producer()
        summary = producer.open(grant)
        self.assertEqual((summary.total_rows, summary.page_count), (11, 1))
        self.assertEqual(len(attempts), 2)
        self.assertIs(producer.open(grant), summary)
        self.ack(producer)
        page = producer.read(summary.handle, 0, 2)
        self.assertEqual([row['record_id'] for row in page.contract.value['rows']],
                         sorted(row['record_id'] for row in facts()))
        self.assertIs(producer.read(summary.handle, 0, 2), page)
        with self.assertRaises(ContractFailure):
            page.release()
        self.ack(producer)
        before = producer.reader.scope.memory_current
        producer.close(summary.handle)
        self.assertEqual(producer.reader.scope.memory_current, before)
        self.assertGreater(grant.current, 0)
        self.assertIsNone(producer.observe().native_memory_bytes)
        self.assertTrue(page.release())
        self.assertFalse(page.release())
        self.assertEqual(grant.current, 0)
        self.assertEqual(producer.close(summary.handle).state, 'closed')

    def test_actual130_count_and_all_rows_three_pages(self):
        base = facts()
        rows = [{**deepcopy(base[i % 11]), 'record_id': f'r-{i:04d}'} for i in range(130)]
        fixture = make_fixture(self.root, rows=rows, split=[rows[:65], rows[65:]],
                               writer_options={'row_group_size': 16})
        _, producer, grant, _ = self.producer(fixture)
        summary = producer.open(grant)
        self.assertEqual((summary.total_rows, summary.page_count), (130, 3))
        self.ack(producer)
        actual, counts = [], []
        for ordinal in range(3):
            page = producer.read(summary.handle, ordinal, ordinal + 2)
            actual.extend(row['record_id'] for row in page.contract.value['rows'])
            counts.append(len(page.contract.value['rows']))
            self.ack(producer)
            page.release()
        self.assertEqual(counts, [64, 64, 2])
        self.assertEqual(actual, sorted(row['record_id'] for row in rows))
        producer.close(summary.handle)
        self.assertEqual(grant.current, 0)

    def test_failed_open_is_consumed_observable_and_closeable(self):
        _, producer, grant, attempts = self.producer(amount=1024)
        with self.assertRaises(ContractFailure):
            producer.open(grant)
        self.assertEqual(attempts, [])
        self.assertEqual(producer.observe().state, 'failed')
        self.assertFalse(producer.observe().producer_observation_complete)
        with self.assertRaises(ContractFailure):
            producer.open(grant, 2)
        producer.close(producer.handle)
        self.assertEqual(grant.current, 0)

    def test_registry_foreign_ack_close_and_owner_rejection(self):
        _, producer, grant, attempts = self.producer()
        summary = producer.open(grant)
        with self.assertRaises(ContractFailure):
            producer.read(summary.handle, 0, 2)
        with self.assertRaises(ContractFailure):
            producer.acknowledge(1, 'f' * 64)
        self.assertEqual(len(attempts), 2)
        self.ack(producer)
        with self.assertRaises(ContractFailure):
            producer.read('foreign', 0, 2)
        with self.assertRaises(ContractFailure):
            producer.reader.read_batch(producer.binding, 0)
        producer._lock.acquire()
        try:
            with self.assertRaises(ContractFailure):
                producer.close(summary.handle)
        finally:
            producer._lock.release()
        with self.assertRaises(ContractFailure):
            producer.close('foreign')
        producer.close(summary.handle)
        with self.assertRaises(ContractFailure):
            producer.read(summary.handle, 0, 2)

    def test_load_failure_retains_cost_and_no_reopen(self):
        _, producer, grant, _ = self.producer()
        with patch('modules.connectors.fixed_source_reader.footer', side_effect=RuntimeError('bad footer')):
            with self.assertRaises(RuntimeError):
                producer.open(grant)
        observed = producer.observe()
        self.assertGreater(observed.snapshot.object_requests, 0)
        self.assertGreater(observed.snapshot.object_bytes, 0)
        with self.assertRaises(ContractFailure):
            producer.open(grant, 2)
        producer.close(producer.handle)
        self.assertEqual(grant.current, 0)

    def test_failed_foreign_grant_claim_cannot_close_owner_credit(self):
        fixture, owner, grant, _ = self.producer()
        summary = owner.open(grant)
        live = grant.current
        objects, _, _ = unit_objects(fixture)
        other = FixedProducer(FixedSourceReader(objects))
        with self.assertRaises(ContractFailure):
            other.open(grant)
        other.close(other.handle)
        self.assertEqual(grant.current, live)
        self.assertFalse(grant.snapshot()['closed'])
        owner.close(summary.handle)
        self.assertEqual(grant.current, 0)
