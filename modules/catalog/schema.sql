-- M1 schema version 1. Explicit operator initialization; never rewrites a source lake.
CREATE SCHEMA IF NOT EXISTS gura_m1;
CREATE TABLE IF NOT EXISTS gura_m1.version (id boolean PRIMARY KEY DEFAULT true CHECK(id), version integer NOT NULL CHECK(version=1));
INSERT INTO gura_m1.version VALUES (true,1) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS gura_m1.datasets (
 id uuid PRIMARY KEY, tenant text NOT NULL, name text NOT NULL,
 definition jsonb NOT NULL, generation bigint NOT NULL DEFAULT 0,
 epoch bigint NOT NULL DEFAULT 0, published uuid, UNIQUE(tenant,name));
CREATE TABLE IF NOT EXISTS gura_m1.runs (
 id uuid PRIMARY KEY, dataset uuid NOT NULL REFERENCES gura_m1.datasets(id),
 operation text NOT NULL, fingerprint text NOT NULL, generation bigint NOT NULL,
 target jsonb NOT NULL, status text NOT NULL CHECK(status IN ('building','ready','published','failed','retiring','retired')),
 artifact jsonb, error text, published_epoch bigint, created timestamptz NOT NULL DEFAULT now(),
 UNIQUE(dataset,operation));
CREATE TABLE IF NOT EXISTS gura_m1.pins (
 run uuid NOT NULL REFERENCES gura_m1.runs(id), owner text NOT NULL,
 scope text NOT NULL DEFAULT 'manual' CHECK(scope IN ('manual','job','query')),
 PRIMARY KEY(run,scope,owner));
CREATE TABLE IF NOT EXISTS gura_m1.principals (
 token_sha256 text PRIMARY KEY, tenant text NOT NULL, subject text NOT NULL,
 UNIQUE(tenant,subject,token_sha256));
CREATE TABLE IF NOT EXISTS gura_m1.grants (
 tenant text NOT NULL, subject text NOT NULL, dataset uuid NOT NULL REFERENCES gura_m1.datasets(id),
 PRIMARY KEY(tenant,subject,dataset));
CREATE TABLE IF NOT EXISTS gura_m1.jobs (
 id uuid PRIMARY KEY, dataset uuid NOT NULL REFERENCES gura_m1.datasets(id), run uuid NOT NULL REFERENCES gura_m1.runs(id),
 tenant text NOT NULL, subject text NOT NULL, token_sha256 text NOT NULL, kind text NOT NULL,
 status text NOT NULL CHECK(status IN ('queued','running','succeeded','failed','cancelled')),
 request jsonb NOT NULL, context jsonb NOT NULL, result jsonb, error text, cancelled boolean NOT NULL DEFAULT false,
 worker uuid NOT NULL, created timestamptz NOT NULL DEFAULT now());
