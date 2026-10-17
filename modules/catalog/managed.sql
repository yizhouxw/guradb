-- Independent managed-writer v1 state. Never alters M1 read-view schema.
CREATE SCHEMA IF NOT EXISTS gura_managed;
CREATE TABLE IF NOT EXISTS gura_managed.tables (
 name text PRIMARY KEY, root text NOT NULL UNIQUE, generation bigint NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS gura_managed.intents (
 name text NOT NULL REFERENCES gura_managed.tables(name), operation text NOT NULL,
 fingerprint text NOT NULL, generation bigint NOT NULL, parent bigint,
 status text NOT NULL CHECK(status IN ('prepared','committing','committed','aborted')),
 snapshot bigint, metadata text, metadata_sha256 text, PRIMARY KEY(name,operation));
