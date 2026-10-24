"""CF1-A facade for a bounded independent PG catalog, injected by a trusted host."""
from modules.common.cf1a_ports import CatalogReadPort
from modules.common.cf1a_primitives import require
from modules.catalog.cf1a_admin import AdminOperations
from modules.catalog.cf1a_auth import FixedInputAuthority, TrustedPrincipal
from modules.catalog.cf1a_binding import Bindings
from modules.catalog.cf1a_mutation import Mutations
from modules.catalog.cf1a_store import CatalogStore


class FixedCatalog:
    def __init__(self, dsn, protection):
        require(type(protection) is FixedInputAuthority, 'only bounded local fixture authority is certified')
        self.store = CatalogStore(dsn, protection)
        self.admin = AdminOperations(self.store)
        self.mutations = Mutations(self.store)
        self.bindings = Bindings(self.store)

    def initialize(self):
        self.store.initialize()

    def provision(self, principal, operation_id, dataset_id, owner_subject):
        return self.admin.execute(principal, operation_id, dataset_id, 'provision', {'owner_subject': owner_subject})

    def grant(self, principal, operation_id, dataset_id, subject_id, delegation_ref, actions,
              expires_unix_ms, publish_plan_id=''):
        return self.admin.execute(principal, operation_id, dataset_id, 'grant',
            {'subject_id': subject_id, 'delegation_ref': delegation_ref, 'actions': actions,
             'expires_unix_ms': expires_unix_ms, 'publish_plan_id': publish_plan_id})

    def revoke(self, principal, operation_id, dataset_id, subject_id, delegation_ref):
        return self.admin.execute(principal, operation_id, dataset_id, 'revoke',
                                  {'subject_id': subject_id, 'delegation_ref': delegation_ref})

    def rotate_owner(self, principal, operation_id, dataset_id, owner_subject):
        return self.admin.execute(principal, operation_id, dataset_id, 'rotate_owner', {'owner_subject': owner_subject})

    def admin_status(self, principal, operation_id, dataset_id, action, parameters):
        return self.admin.execute(principal, operation_id, dataset_id, action, parameters, status=True)

    def _mutation(self, principal, kind, intent, auth, target):
        require(intent.kind == kind, 'mutation intent does not match catalog port')
        return self.mutations.execute(principal, intent, auth, target)

    def port(self, principal):
        require(type(principal) is TrustedPrincipal, 'expected authenticated trusted host principal', 'unauthorized')
        return CatalogReadPort(bind=lambda request: self.bindings.bind(principal, request),
            reauthorize=lambda binding: self.bindings.reauthorize(principal, binding),
            register=lambda intent, auth, target: self._mutation(principal, 'register_intent', intent, auth, target),
            publish=lambda intent, auth, target: self._mutation(principal, 'publish_intent', intent, auth, target),
            release_pin=lambda binding: self.bindings.release(principal, binding),
            reconcile=lambda intent, auth: self.mutations.reconcile(principal, intent, auth))
