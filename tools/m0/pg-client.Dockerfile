# Test-only SDK client. Shares the server's network namespace; publishes no ports.
FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c
RUN python -m pip install --no-cache-dir psycopg==3.2.10 psycopg-binary==3.2.10
WORKDIR /workspace
