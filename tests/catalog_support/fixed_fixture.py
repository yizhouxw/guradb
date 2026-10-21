"""Bounded synthetic A targets with explicitly trusted local protection, not real I1."""
from copy import deepcopy
import json
from pathlib import Path
import time
from modules.catalog.cf1a_auth import FixedInputAuthority, TrustedPrincipal
from modules.catalog.cf1a_catalog import FixedCatalog
from modules.catalog.cf1a_codec import contract
from modules.common.cf1a_primitives import digest
from modules.common.cf1a_read import without

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = json.loads((ROOT / 'api/cf1a/golden.json').read_text())


def target(now, view='view-a', revision='revision-a', parents=(), generation=2, sequence=1, dataset='dataset-1'):
    value = deepcopy(GOLDEN[11]['payload']['read_descriptors'])
    value['resource']['display_name'] = '目录\x00合成图文'
    value['resource']['dataset_id'] = dataset
    rev = value['revision']
    rev.update(dataset_id=dataset, data_revision_id=revision, parent_revision_ids=list(parents))
    source = rev['sources'][0]
    source.update(source_version_id='source-' + revision, snapshot_id='snapshot-' + revision,
                  protected_until_unix_ms=now + 300000)
    for artifact in value['indexes']:
        artifact.update(artifact_id='artifact-' + view, build_id='build-' + view,
                        data_revision_id=revision, source_version_ids=[source['source_version_id']])
    value['view'].update(read_view_id=view, data_revision_id=revision, publication_generation=generation,
                         publication_sequence=sequence, required_artifact_ids=[x['artifact_id'] for x in value['indexes']])
    value['view']['index_requirements'][0]['artifact_id'] = value['indexes'][0]['artifact_id']
    rev['content_sha256'] = digest(without(rev, 'content_sha256'))
    value['view']['descriptor_sha256'] = digest(without(value['view'], 'descriptor_sha256'))
    return contract('read_descriptors', value)


def intents(value, register_id='register-a', publish_id='publish-a', expected_generation=0,
            owner_epoch=1, prior_view=''):
    t = value.value
    shared = {'tenant_id': t['resource']['tenant_id'], 'dataset_id': t['resource']['dataset_id'],
              'owner_epoch': owner_epoch, 'target_revision_id': t['revision']['data_revision_id'],
              'target_descriptors_sha256': digest(t)}
    registration = contract('register_intent', {**shared, 'operation_id': register_id,
        'expected_generation': expected_generation, 'revision_sha256': t['revision']['content_sha256']})
    publication = contract('publish_intent', {**shared, 'operation_id': publish_id,
        'expected_generation': expected_generation + 1, 'expected_view_id': prior_view,
        'target_view_id': t['view']['read_view_id'], 'target_revision_sha256': t['revision']['content_sha256'],
        'target_view_sha256': t['view']['descriptor_sha256'], 'publication_sequence': t['view']['publication_sequence'],
        'artifact_ids': t['view']['required_artifact_ids']})
    return registration, publication


def authorization(principal, now, epoch=2, actions=('register', 'publish', 'reconcile'), dataset='dataset-1'):
    return contract('mutation_auth', {'tenant_id': principal.tenant_id, 'dataset_id': dataset,
        'subject_id': principal.subject_id, 'delegation_ref': principal.delegation_ref, 'policy_epoch': epoch,
        'expires_unix_ms': now + 90000, 'actions': list(actions)})


def request(principal, query='query-a', timeout_ms=30000, explicit='', dataset='dataset-1'):
    value = deepcopy(GOLDEN[7]['payload']['bind_request'])
    value.update(tenant_id=principal.tenant_id, subject_id=principal.subject_id,
                  delegation_ref=principal.delegation_ref, query_id=query, request_id='request-' + query,
                  timeout_ms=timeout_ms, view_mode='explicit' if explicit else 'published', read_view_id=explicit,
                  dataset_id=dataset)
    return contract('bind_request', value)


def configure(catalog, principal, now):
    first = catalog.provision(principal, 'provision-a', 'dataset-1', principal.subject_id)
    granted = catalog.grant(principal, 'grant-a', 'dataset-1', principal.subject_id, principal.delegation_ref,
                            ['read', 'register', 'publish', 'reconcile'], now + 90000)
    return first, granted


def new_catalog(dsn, now=None):
    now = int(time.time() * 1000) if now is None else now
    authority = FixedInputAuthority()
    principal = TrustedPrincipal('tenant-1', 'operator-1', 'operator-session-1', administrator=True)
    catalog = FixedCatalog(dsn, authority)
    return catalog, authority, principal, now
