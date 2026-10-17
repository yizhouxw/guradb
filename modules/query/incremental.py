"""Explicit append-only refresh with durable operation reconciliation and CAS publication."""
from pathlib import Path

from modules.common.contracts import Budget, Failure, digest, encoded, require
from modules.connectors.incremental import validate, verify_identity
from modules.index.retrieval import load_bundle
from modules.query.snapshot import construct
from modules.storage.objects import Objects, put


class _BuildControl:
    def __init__(self, control, run, proof, root, objects, inherited):
        self.control, self.fixed_run, self.proof, self.root = control, run, proof, root
        self.objects, self.inherited = objects, inherited

    def __getattr__(self, name):
        return getattr(self.control, name)

    def begin(self, dataset, operation, target):
        return self.fixed_run

    def ready(self, run, artifact):
        bundle = load_bundle(artifact, Budget())
        actual = {d['uri']: d['sha256'] for d in bundle['source']['dependencies']}
        # Current source objects read during validation must retain the checked bytes.
        for dependency in self.proof['dependencies']:
            if dependency['uri'] in actual:
                require(actual[dependency['uri']] == dependency['sha256'], 'source_invalid', 'source changed during refresh')
        for dependency in self.inherited['source']['dependencies']:
            if dependency['uri'] in self.proof['old_files']:
                verify_identity(self.objects, dependency)
        proof = put(Path(self.root).resolve()/str(run)/'incremental.json', encoded(self.proof))
        self.control.ready(run, dict(artifact, incremental=proof))


def refresh(control, dataset, operation, target, root, s3=None, cancelled=lambda: False):
    """Build a fixed append descendant. Publish separately via snapshot.publish."""
    require(isinstance(operation, str) and 0 < len(operation) <= 128, 'invalid_request')
    # Keep identical concurrent notifications from sharing a building directory or
    # marking the owner's run failed. A crashed owner releases this transaction lock.
    with control.transaction() as conn:
        locked = conn.execute('SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 7101712)) AS locked',
                              (str(dataset) + ':' + operation,)).fetchone()['locked']
        require(locked, 'operation_busy', 'same incremental operation is already executing')
        return _refresh(control, dataset, operation, target, root, s3, cancelled)


def _refresh(control, dataset, operation, target, root, s3, cancelled):
    required = {'metadata_uri', 'metadata_sha256', 'snapshot_id', 'features_uri', 'features_sha256'}
    require(required <= set(target) <= required | {'ann'}, 'invalid_request')
    # Reconcile before resolving current published: retries must retain their original base.
    with control.transaction() as conn:
        previous = conn.execute('SELECT * FROM gura_m1.runs WHERE dataset=%s AND operation=%s',
                                (dataset, operation)).fetchone()
    if previous:
        fixed = previous['target']
        require('incremental' in fixed and {k:v for k,v in fixed.items() if k != 'incremental'} == target,
                'operation_conflict')
        return previous
    ds = control.dataset(dataset)
    require(ds['published'] is not None, 'not_ready', 'incremental refresh requires published base')
    base_run = control.run(ds['published'])
    fixed = dict(target, incremental={'base_run': str(base_run['id']), 'definition': ds['definition']})
    run = control.begin(dataset, operation, fixed)
    if run['status'] != 'building':
        return run
    owner = 'incremental:' + str(run['id'])
    pinned = False
    try:
        control.pin(base_run['id'], owner)
        pinned = True
        base = load_bundle(base_run['artifact'], Budget(cancelled))
        require(base['source']['key_field'] == ds['definition']['key_field'], 'unsupported_change')
        objects = Objects(ds['definition']['root'], Budget(cancelled), s3)
        proof = validate(objects, base, target)
        proof['base_run'] = str(base_run['id'])
        proof['definition_sha256'] = digest(encoded(ds['definition']))
        return construct(_BuildControl(control, run, proof, root, objects, base), dataset, operation, target, root, s3, cancelled,
                         inherited=base, added_files=set(proof['added_files']))
    except Exception as error:
        control.fail(run['id'], error.code if isinstance(error, Failure) else 'build_failed')
        raise
    finally:
        if pinned:
            control.unpin(base_run['id'], owner)


def progress(control, run_id):
    run = control.run(run_id)
    require('incremental' in run['target'], 'invalid_request')
    target = str(run['target']['snapshot_id'])
    ready = run['artifact'] is not None and run['status'] in ('ready', 'published', 'retiring', 'retired')
    return {'run_id': str(run['id']), 'status': run['status'], 'target_snapshot': target,
            'base_run': run['target']['incremental']['base_run'], 'discovered': target,
            'applied': target if ready else None, 'indexed': target if ready else None,
            'published': target if run['published_epoch'] is not None else None,
            'error': run['error'], 'execution': 'append_data_and_index_rebuild'}
