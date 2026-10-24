"""Exact immutable A projection and cumulative execution witnesses."""
from dataclasses import replace
import tempfile
import unittest
from unittest.mock import patch

from modules.common.cf1a_primitives import ContractFailure
from modules.connectors.fixed_producer import FixedProducer
from modules.connectors.fixed_producer_credits import PreparedPermit, ProducerGrant
from modules.connectors.fixed_source_reader import FixedSourceReader
from tests.source_support.fixed_fixture import make_fixture, unit_objects


class ProducerObservationTests(unittest.TestCase):
    def page(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        fixture = make_fixture(temporary.name)
        objects, fetched, attempts = unit_objects(fixture)
        hook = patch('modules.storage.fixed_objects.fetch', side_effect=fetched)
        hook.start()
        self.addCleanup(hook.stop)
        producer = FixedProducer(FixedSourceReader(objects))
        grant = ProducerGrant(PreparedPermit('session', fixture['binding'].sha256, 1), 8 << 20)
        summary = producer.open(grant)
        opened = producer.observe()
        producer.acknowledge(*producer.completion)
        page = producer.read(summary.handle, 0, 2)
        self.addCleanup(producer.close, summary.handle)
        return producer, page, opened, attempts

    def test_open_fees_not_recharged_in_first_A_and_delivered_only_in_tail(self):
        producer, page, opened, attempts = self.page()
        record = page.prefix.validate(page.contract)
        self.assertEqual(len(attempts), 2)
        self.assertEqual(record.base.object_requests, opened.snapshot.object_requests)
        self.assertEqual(page.contract.value['usage']['object_requests'], 0)
        self.assertEqual(page.contract.value['usage']['object_bytes'], 0)
        self.assertEqual(record.usage_point.output_bytes, record.at_a.output_bytes)
        self.assertEqual(page.contract.value['usage']['output_bytes'], page.bytes)
        self.assertEqual(record.final.output_bytes - record.at_a.output_bytes, page.bytes)
        self.assertEqual(producer.observe().snapshot.output_bytes,
                         opened.snapshot.output_bytes + page.bytes)

    def test_witness_tamper_rejected_without_rewriting_A(self):
        _, page, _, _ = self.page()
        prefix, original = page.prefix, page.contract.encoded
        for altered in (replace(prefix, a_bytes=prefix.a_bytes + 1),
                        replace(prefix, batch_peak=prefix.batch_peak + 1),
                        replace(prefix, usage_point=replace(prefix.usage_point, output_bytes=
                                prefix.usage_point.output_bytes + prefix.a_bytes)),
                        replace(prefix, final=replace(prefix.final, object_bytes=-1))):
            with self.assertRaises(ContractFailure):
                altered.validate(page.contract)
        self.assertEqual(page.contract.encoded, original)

    def test_usage_point_is_the_actual_single_usage_call(self):
        producer, page, _, _ = self.page()
        # The stored snapshot used to derive A is the exact same capture object;
        # no later clock/usage call is substituted for its elapsed value.
        self.assertIs(page.prefix.usage_point, producer.reader.scope.last_usage_point)
        self.assertEqual(page.prefix.usage_point.elapsed_ms - page.prefix.base.elapsed_ms,
                         page.contract.value['usage']['elapsed_ms'])
        self.assertGreaterEqual(page.prefix.at_a.elapsed_ms, page.prefix.usage_point.elapsed_ms)
        self.assertGreaterEqual(page.prefix.final.elapsed_ms, page.prefix.at_a.elapsed_ms)
