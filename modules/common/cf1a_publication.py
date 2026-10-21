"""Pure checks for catalog intents/receipts; no catalog state machine."""
from modules.common.cf1a_primitives import digest, require, unique, validate_shape


def validate_publication(kind, value):
    if kind == 'publish_intent':
        require(unique(value['artifact_ids']), 'duplicate publication artifacts')
        require(value['expected_generation'] > 0 or value['expected_view_id'] == '',
                'zero generation cannot have a prior view')
        require(value['target_view_id'] != value['expected_view_id'], 'publication must advance view')
    elif kind == 'mutation_receipt':
        state, result, error = value['state'], value['result_id'], value['error_code']
        require((state == 'applied' and bool(result) and error == 'none' and value['generation'] > 0)
                or (state == 'rejected' and not result and error in ('conflict', 'stale_generation', 'idempotency_conflict'))
                or (state == 'outcome_unknown' and not result and error == 'outcome_unknown'), 'invalid receipt state')
    elif kind == 'mutation_auth':
        require(unique(value['actions']), 'duplicate mutation authorization action')
    elif kind == 'contract_error':
        require(not value['retryable'] or value['code'] in ('backend_unavailable',), 'unsafe automatic retry')
        require((value['code'] == 'outcome_unknown') == bool(value['reconcile_ref']), 'unknown result requires reconciliation')


def check_cas(intent, actual_generation, actual_owner_epoch, actual_view_id='', actual_sequence=0):
    validate_shape(intent, 'PublishIntent' if 'expected_view_id' in intent else 'RegisterIntent')
    validate_shape(actual_generation, 'n')
    validate_shape(actual_owner_epoch, 'positive')
    validate_shape(actual_sequence, 'n')
    validate_shape(actual_view_id, 'text')
    require(intent['owner_epoch'] == actual_owner_epoch, 'stale publication owner', 'stale_generation')
    require(intent['expected_generation'] == actual_generation, 'catalog generation conflict', 'conflict')
    if 'expected_view_id' in intent:
        require(intent['expected_view_id'] == actual_view_id and intent['publication_sequence'] > actual_sequence,
                'publication cannot roll back a newer view', 'conflict')


def check_receipt(intent, receipt):
    validate_shape(intent, 'PublishIntent' if 'expected_view_id' in intent else 'RegisterIntent')
    validate_shape(receipt, 'MutationReceipt')
    validate_publication('mutation_receipt', receipt)
    require(receipt['operation_id'] == intent['operation_id'] and receipt['request_sha256'] == digest(intent),
            'receipt does not identify the immutable intent')
    if receipt['state'] == 'applied':
        require(receipt['generation'] == intent['expected_generation'] + 1, 'receipt generation mismatch')
        require(receipt['result_id'] == intent.get('target_view_id', intent['target_revision_id']),
                'receipt target mismatch')
    return receipt['state'] != 'outcome_unknown'


def check_replay(original, replay):
    for value in (original, replay):
        validate_shape(value, 'PublishIntent' if 'expected_view_id' in value else 'RegisterIntent')
    require(original['operation_id'] == replay['operation_id'] and digest(original) == digest(replay),
            'operation ID reused with a different request', 'conflict')


def check_target(intent_contract, binding_contract):
    require(intent_contract.kind in ('register_intent', 'publish_intent') and
            binding_contract.kind == 'read_descriptors', 'wrong target contract kinds')
    intent, binding = intent_contract.value, binding_contract.value
    require(intent['target_descriptors_sha256'] == digest(binding), 'target descriptor content mismatch')
    require(intent['tenant_id'] == binding['resource']['tenant_id'] and
            intent['dataset_id'] == binding['resource']['dataset_id'] and
            intent['target_revision_id'] == binding['revision']['data_revision_id'], 'target resource mismatch')
    if intent_contract.kind == 'register_intent':
        require(intent['revision_sha256'] == binding['revision']['content_sha256'], 'registered revision mismatch')
    else:
        require(intent['target_revision_sha256'] == binding['revision']['content_sha256'] and
                intent['target_view_sha256'] == binding['view']['descriptor_sha256'] and
                intent['target_view_id'] == binding['view']['read_view_id'] and
                binding['view']['publication_generation'] == intent['expected_generation'] + 1 and
                intent['publication_sequence'] == binding['view']['publication_sequence'] and
                set(intent['artifact_ids']) == set(binding['view']['required_artifact_ids']), 'publication target mismatch')


def check_mutation_auth(intent_contract, authorization_contract, now_unix_ms, current_policy_epoch, reconcile=False):
    require(intent_contract.kind in ('register_intent', 'publish_intent') and
            authorization_contract.kind == 'mutation_auth', 'wrong mutation authorization kinds')
    intent, auth = intent_contract.value, authorization_contract.value
    validate_shape(now_unix_ms, 'n')
    validate_shape(current_policy_epoch, 'positive')
    action = 'reconcile' if reconcile else ('register' if intent_contract.kind == 'register_intent' else 'publish')
    require(auth['tenant_id'] == intent['tenant_id'] and auth['dataset_id'] == intent['dataset_id'] and
            action in auth['actions'], 'unauthorized mutation scope', 'unauthorized')
    require(type(current_policy_epoch) is int and current_policy_epoch > 0 and
            current_policy_epoch == auth['policy_epoch'], 'mutation authorization revoked', 'revoked')
    require(type(now_unix_ms) is int and 0 <= now_unix_ms < auth['expires_unix_ms'],
            'mutation authorization expired', 'expired_context')
