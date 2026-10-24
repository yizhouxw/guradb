CREATE SCHEMA IF NOT EXISTS gura_cf1a;
CREATE TABLE IF NOT EXISTS gura_cf1a.version (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    version integer NOT NULL
);
INSERT INTO gura_cf1a.version VALUES (true, 1) ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS gura_cf1a.datasets (
    dataset text PRIMARY KEY,
    tenant text NOT NULL,
    generation bigint NOT NULL DEFAULT 0 CHECK (generation BETWEEN 0 AND 9007199254740991),
    owner_subject text NOT NULL,
    owner_epoch bigint NOT NULL DEFAULT 1 CHECK (owner_epoch BETWEEN 1 AND 9007199254740991),
    policy_epoch bigint NOT NULL DEFAULT 1 CHECK (policy_epoch BETWEEN 1 AND 9007199254740991),
    sequence bigint NOT NULL DEFAULT 0 CHECK (sequence BETWEEN 0 AND 9007199254740991),
    head_revision text NOT NULL DEFAULT '',
    published text NOT NULL DEFAULT '',
    active_plan text NOT NULL DEFAULT '',
    metadata_bytes bigint NOT NULL DEFAULT 0 CHECK (metadata_bytes BETWEEN 0 AND 8388608)
);
CREATE TABLE IF NOT EXISTS gura_cf1a.identities (
    dataset text NOT NULL REFERENCES gura_cf1a.datasets(dataset),
    kind text NOT NULL CHECK (kind IN ('resource','revision','view','source','artifact')),
    id text NOT NULL,
    body bytea NOT NULL,
    sha256 text NOT NULL,
    PRIMARY KEY(dataset,kind,id)
);
CREATE TABLE IF NOT EXISTS gura_cf1a.grants (
    dataset text NOT NULL REFERENCES gura_cf1a.datasets(dataset),
    subject text NOT NULL,
    delegation text NOT NULL,
    body bytea NOT NULL,
    sha256 text NOT NULL,
    PRIMARY KEY(dataset,subject,delegation)
);
CREATE TABLE IF NOT EXISTS gura_cf1a.targets (
    dataset text NOT NULL REFERENCES gura_cf1a.datasets(dataset),
    view_id text NOT NULL,
    revision_id text NOT NULL,
    body bytea NOT NULL,
    sha256 text NOT NULL,
    register_operation text NOT NULL,
    register_generation bigint NOT NULL,
    owner_subject text NOT NULL,
    owner_epoch bigint NOT NULL,
    prior_view text NOT NULL,
    publish_generation bigint NOT NULL,
    publication_sequence bigint NOT NULL,
    state text NOT NULL CHECK (state IN ('registered','superseded','fenced','published')),
    PRIMARY KEY(dataset,view_id)
);
CREATE TABLE IF NOT EXISTS gura_cf1a.operations (
    dataset text NOT NULL REFERENCES gura_cf1a.datasets(dataset),
    operation_id text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('admin','register_intent','publish_intent')),
    subject text NOT NULL,
    delegation text NOT NULL,
    terminalized boolean NOT NULL,
    intent bytea NOT NULL,
    intent_sha256 text NOT NULL,
    receipt bytea NOT NULL,
    receipt_sha256 text NOT NULL,
    PRIMARY KEY(dataset,operation_id)
);
CREATE TABLE IF NOT EXISTS gura_cf1a.queries (
    dataset text NOT NULL REFERENCES gura_cf1a.datasets(dataset),
    query_id text NOT NULL,
    subject text NOT NULL,
    delegation text NOT NULL,
    request bytea NOT NULL,
    request_sha256 text NOT NULL,
    binding bytea NOT NULL,
    binding_sha256 text NOT NULL,
    pin_id text NOT NULL,
    lease_id text NOT NULL,
    expires_unix_ms bigint NOT NULL,
    released boolean NOT NULL DEFAULT false,
    PRIMARY KEY(dataset,query_id),
    UNIQUE(dataset,pin_id),
    UNIQUE(dataset,lease_id)
);
