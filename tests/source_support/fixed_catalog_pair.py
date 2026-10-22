"""C3 composition root: real PG-issued identity and one pre-bind parent ledger."""
from copy import deepcopy
from dataclasses import asdict
import time
import uuid

import psycopg

from modules.catalog.cf1a_auth import TrustedPrincipal
from modules.catalog.cf1a_codec import contract
from modules.catalog.cf1a_control import CatalogReadControl
from modules.common.cf1a_primitives import ContractFailure, digest
from modules.common.cf1a_read import without
from modules.connectors.fixed_source_reader import FixedSourceReader
from modules.connectors.fixed_source_scope import SourceScope
from modules.storage.fixed_parent import ControlledAuthority, ReadParent
from modules.storage.fixed_objects import FixedObjects
from modules.storage.fixed_signing import CredentialSnapshot, FixedBackend
from tests.catalog_support.fixed_fixture import authorization, intents, request
from tests.source_support.fixed_acceptance import expected_rows, save_case_input
from tests.source_support.fixed_evidence import error_record, write
from tests.source_support.fixed_catalog_pair_measure import measured
from tests.source_support.fixed_located_acceptance import measured_located


def prepare(catalog, authority, principal, fixture, dataset):
    """Register complete immutable actual uploaded targets; never issue a context."""
    value = fixture['binding'].value
    target = {key: deepcopy(value[key]) for key in ('resource', 'revision', 'view', 'indexes')}
    target['resource']['dataset_id'] = dataset
    target['revision']['dataset_id'] = dataset
    for source in target['revision']['sources']:
        source['protected_until_unix_ms'] = time.time_ns() // 1_000_000 + 300000
    target['revision']['content_sha256'] = digest(without(target['revision'], 'content_sha256'))
    target['view'].update(publication_generation=2, publication_sequence=1)
    target['view']['descriptor_sha256'] = digest(without(target['view'], 'descriptor_sha256'))
    target = contract('read_descriptors', target)
    now = time.time_ns() // 1_000_000
    catalog.provision(principal, 'provision-' + dataset, dataset, principal.subject_id)
    catalog.grant(principal, 'grant-' + dataset, dataset, principal.subject_id,
        principal.delegation_ref, ['read', 'register', 'publish', 'reconcile'], now + 300000)
    authority.allow(target)
    reg, pub = intents(target, 'register-' + dataset, 'publish-' + dataset)
    auth = authorization(principal, now, dataset=dataset)
    catalog.port(principal).register(reg, auth, target)
    catalog.port(principal).publish(pub, auth, target)
    return target


def query_row(dsn, dataset, query):
    # Independent read-only oracle, not a second catalog implementation.
    with psycopg.connect(dsn, connect_timeout=2) as connection:
        return connection.execute('SELECT binding_sha256,released,pin_id,lease_id FROM '
            'gura_cf1a.queries WHERE dataset=%s AND query_id=%s', (dataset, query)).fetchone()


class PairQuery:
    def __init__(self, catalog, principal, fixture, dataset, endpoint, directory, *,
                 cache=None, timeout_ms=5000, cancelled=lambda: False):
        self.catalog, self.principal, self.fixture = catalog, principal, fixture
        self.dataset, self.endpoint, self.directory, self.cache = dataset, endpoint, directory, cache
        self.directory.mkdir(parents=True, exist_ok=False)
        budget = deepcopy(fixture['binding'].value['context']['budget'])
        self.parent = ReadParent(timeout_ms, budget, cancelled)
        self.initial_deadline = self.parent.deadline
        self.control = CatalogReadControl(self.parent.checkpoint, self.parent.monotonic)
        self.parent.catalog(self.control)
        self.reads = catalog.controlled_reads(principal, self.control)
        value = request(principal, 'c3-q-' + uuid.uuid4().hex, timeout_ms=timeout_ms, dataset=dataset).value
        value['budget'] = budget
        self.request = contract('bind_request', value)
        (directory/'request.json').write_bytes(self.request.encoded)
        self.binding = self.reader = None
        self.cleanup = None

    def bind(self):
        self.binding = self.reads.bind(self.request)
        (self.directory/'issued-binding.json').write_bytes(self.binding.encoded)
        admission_wall_ms = self.parent.wall_ms()
        admission_mono = self.parent.monotonic()
        scope = SourceScope(self.binding, parent=self.parent)
        backend = FixedBackend('p04_fixture', 'm0-data', self.endpoint,
                               CredentialSnapshot('m0-test-key', 'm0-test-secret'), True)
        objects = FixedObjects(scope, {'p04_fixture': backend}, cache=self.cache,
                               controlled=ControlledAuthority(self.parent, self.reads.reauthorize))
        self.reader = FixedSourceReader(objects)
        self.reader.acceptance_admission = {'t0': self.parent.started,
            'initial_deadline': self.initial_deadline,
            'monotonic': admission_mono, 'wall_ms': admission_wall_ms,
            'issued_deadline_wall_ms': self.binding.value['context']['deadline_unix_ms']}
        write(self.directory/'admission.json', self.reader.acceptance_admission)
        self.reader.acceptance_parent = self.parent
        self.reader.acceptance_timeout_ms = self.request.value['timeout_ms']
        self.reader.acceptance_cohort_started = None
        self.reader.acceptance_journal = []
        save_case_input(self.reader, self.fixture, self.directory/'read')
        return self.reader

    def finish(self):
        # A fresh cleanup parent cannot restore execution. Its PG invoice is separate.
        started = time.monotonic()
        control = CatalogReadControl(lambda: started + 5, time.monotonic)
        primary = None
        try:
            if self.binding is not None:
                result = self.reads.release_pin(self.binding, control)
                row = query_row(self.catalog.store.dsn, self.dataset, self.request.value['query_id'])
                context = self.binding.value['context']
                assert row == (self.binding.sha256, True, context['pin']['pin_id'], context['pin']['lease_id'])
                self.cleanup = {'state': 'released', 'exact_pin_confirmed': True}
            else:
                result = self.reads.close_bind_request(self.request, control)
                self.cleanup = asdict(result)
        except BaseException as error:
            primary = error
            raise
        finally:
            write(self.directory/'parent-invoice.json', self.parent.invoice)
            write(self.directory/'cleanup.json', {'result': self.cleanup, 'catalog': control.invoice,
                'elapsed_ms': (time.monotonic() - started) * 1000,
                'primary_error': error_record(primary) if primary else None})
        return self.cleanup


def positive(query, *, located=False, expected_sizes=(11,)):
    reader, pages, ordinal = query.bind(), [], 0
    while True:
        if located:
            _, page = measured_located(reader, query.fixture, ordinal)
        else:
            _, page = measured(reader, ordinal)
        pages.append(page)
        if page['last']:
            break
        ordinal += 1
        assert ordinal < len(expected_sizes)
    assert [len(page['rows']) for page in pages] == list(expected_sizes)
    assert [row for page in pages for row in page['rows']] == expected_rows(query.fixture)
    assert [page['ordinal'] for page in pages] == list(range(len(expected_sizes)))
    if located:
        _, replay = measured_located(reader, query.fixture, 0)
        assert replay['provenance']['rows'] == pages[0]['provenance']['rows']
    else:
        _, replay = measured(reader, 0)
    assert replay['rows'] == pages[0]['rows']
    assert replay['usage']['object_requests'] == replay['usage']['object_bytes'] == 0
    try:
        reader.port.read_batch(query.binding, len(pages))
    except ContractFailure as error:
        assert error.code == 'invalid_contract'
    else:
        raise AssertionError('ordinal beyond terminal returned a page')
    return {'pages': pages, 'replay': replay, 'terminal_ordinal_rejected': True,
            'parent_invoice': query.parent.invoice}
