"""Independent literal quota oracles and bounded synthetic descriptor inputs."""
from copy import deepcopy
import hashlib
import json

from modules.catalog.cf1a_codec import contract
from tests.catalog_support.fixed_fixture import intents


TABLES = (
    ('identities', 'kind,id', (('body', 'sha256'),)),
    ('grants', 'subject,delegation', (('body', 'sha256'),)),
    ('targets', 'view_id', (('body', 'sha256'),)),
    ('operations', 'operation_id', (('intent', 'intent_sha256'), ('receipt', 'receipt_sha256'))),
    ('queries', 'query_id', (('request', 'request_sha256'), ('binding', 'binding_sha256'))),
)


def encoded(value):
    # Independent implementation of the documented wire canonicalization.
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def state(cases, dataset=None):
    """Read real PG bytes; no production LIMITS, counter or accounting helpers."""
    where, parameters = (' WHERE dataset=%s', (dataset,)) if dataset else ('', ())
    datasets = cases.sql('SELECT * FROM gura_cf1a.datasets' + where + ' ORDER BY dataset', parameters)
    measured = {row['dataset']: 0 for row in datasets}
    result = {'datasets': datasets}
    for table, order, bodies in TABLES:
        rows = cases.sql('SELECT * FROM gura_cf1a.' + table + where + ' ORDER BY dataset,' + order, parameters)
        for row in rows:
            for column, hash_column in bodies:
                raw = bytes(row[column])
                assert encoded(json.loads(raw)) == raw
                assert sha(raw) == row[hash_column]
                measured[row['dataset']] += len(raw)
                row[column] = {'sha256': sha(raw), 'size_bytes': len(raw)}
        result[table] = rows
    for row in datasets:
        assert measured[row['dataset']] == row['metadata_bytes'] <= 8 * 1024 * 1024
    return result


def counts(cases, dataset):
    return cases.sql('SELECT d.*, '
        '(SELECT count(*) FROM gura_cf1a.identities x WHERE x.dataset=d.dataset) AS identities, '
        '(SELECT count(*) FROM gura_cf1a.grants x WHERE x.dataset=d.dataset) AS grants, '
        '(SELECT count(*) FROM gura_cf1a.targets x WHERE x.dataset=d.dataset) AS targets, '
        '(SELECT count(*) FROM gura_cf1a.operations x WHERE x.dataset=d.dataset) AS operations, '
        '(SELECT count(*) FROM gura_cf1a.queries x WHERE x.dataset=d.dataset) AS queries '
        'FROM gura_cf1a.datasets d WHERE d.dataset=%s', (dataset,))[0]


def expect(cases, dataset, **literal_expected):
    actual = counts(cases, dataset)
    for name, expected in literal_expected.items():
        assert actual[name] == expected, (dataset, name, actual[name], expected)
    assert actual['metadata_bytes'] < 8 * 1024 * 1024
    return actual


def note(cases, name, dataset, **fields):
    actual = state(cases, dataset)
    retain(cases, actual)
    cases.event(name, state='pass', dataset=dataset, independent_sql_sha256=sha(encoded(actual)),
                actual_counts=counts(cases, dataset), **fields)


def retain(cases, value):
    identity = sha(encoded(value))
    known = getattr(cases, '_quota_witnesses', set())
    if identity not in known:
        cases.inputs.append({'kind': 'independent-canonical-sql-witness', 'sha256': identity, 'state': value})
        known.add(identity)
        cases._quota_witnesses = known
    return identity


def same_state(cases, name, before, after, dataset):
    assert after == before
    identity = retain(cases, before)
    cases.event(name, state='pass', dataset=dataset, sql_before_sha256=identity, sql_after_sha256=identity)


def unchanged(cases, name, callback, dataset, codes=('resource_limit',)):
    before = state(cases, dataset)
    cases.reject(name, callback, set(codes))
    same_state(cases, name + '-no-partial-effect', before, state(cases, dataset), dataset)


def exact_release(cases, port, binding, name):
    dataset = binding.value['context']['dataset_id']
    before = state(cases, dataset)
    expected = deepcopy(before)
    chosen = [row for row in expected['queries'] if row['query_id'] == binding.value['context']['query_id']]
    assert len(chosen) == 1
    chosen[0]['released'] = True
    port.release_pin(binding)
    after = state(cases, dataset)
    assert after == expected
    cases.event(name, state='pass', dataset=dataset, sql_before_sha256=retain(cases, before),
                sql_after_sha256=retain(cases, after))


def target_guard(cases, value, dataset):
    assert value.encoded == encoded(value.document) and len(value.encoded) < 1024 * 1024
    def arrays(item):
        if isinstance(item, list):
            assert len(item) <= 128
            for child in item:
                arrays(child)
        elif isinstance(item, dict):
            for child in item.values():
                arrays(child)
    arrays(value.document)
    row = counts(cases, dataset)
    # Full duplicate target plus all identity bodies fit inside this conservative
    # envelope allowance; stable small op IDs keep the two receipts under16KiB.
    assert row['metadata_bytes'] + 3 * len(value.encoded) + 16384 < 8 * 1024 * 1024
    assert row['operations'] + 2 <= 512 and row['grants'] <= 64 and row['queries'] < 1024


def rebuild(seed, view_id, generation, sequence, artifacts=None):
    value = deepcopy(seed.value)
    if artifacts is not None:
        value['indexes'] = deepcopy(artifacts)
    view = value['view']
    template = seed.value['view']['index_requirements'][0]
    view.update(read_view_id=view_id, publication_generation=generation, publication_sequence=sequence,
                required_artifact_ids=[item['artifact_id'] for item in value['indexes']],
                index_requirements=[{key: item[key] for key in template} for item in value['indexes']])
    view['descriptor_sha256'] = sha(encoded({key: item for key, item in view.items()
                                          if key != 'descriptor_sha256'}))
    return contract('read_descriptors', value)


def artifacts(seed, prefix, amount):
    result = []
    for ordinal in range(amount):
        item = deepcopy(seed.value['indexes'][0])
        item.update(artifact_id=f'{prefix}-artifact-{ordinal:03d}', build_id=f'{prefix}-build-{ordinal:03d}')
        result.append(item)
    return result


def publish(cases, auth, value, generation, previous):
    dataset, view_id = value.value['resource']['dataset_id'], value.value['view']['read_view_id']
    target_guard(cases, value, dataset)
    cases.authority.allow(value)
    register, publication = intents(value, view_id + '-register', view_id + '-publish',
                                   generation, prior_view=previous)
    cases.inputs.append({'dataset': dataset, 'target': value.document,
                        'authorization': auth.document, 'intents': [register.document, publication.document]})
    port = cases.catalog.port(cases.principal)
    registered, published = port.register(register, auth, value), port.publish(publication, auth, value)
    assert registered.value['state'] == published.value['state'] == 'applied'
    assert registered.value['generation'] == generation + 1
    assert published.value['generation'] == generation + 2
    return register, publication, registered, published
