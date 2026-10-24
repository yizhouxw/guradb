# Test-only runtime; database capability and endpoint policy are unchanged.
FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c
LABEL org.guradb.purpose="fixed-chain-test-runtime"
COPY requirements-m0.lock /opt/guradb/requirements-m0.lock
RUN python -m pip install --no-cache-dir -r /opt/guradb/requirements-m0.lock \
    psycopg==3.2.10 psycopg-binary==3.2.10 typing-extensions==4.16.0 \
    && python -m pip check
ENV PYTHONUNBUFFERED=1
WORKDIR /workspace
