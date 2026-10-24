"""Test-only SDK/loopback readiness probe, never a database query implementation."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys
import time

import boto3
from botocore.config import Config

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from modules.catalog.cf1a_control import CatalogReadControl
from modules.catalog.cf1a_pg import connect, normalized_dsn
from modules.storage.fixed_signing import CredentialSnapshot, FixedBackend


def main():
    expected = {'pyarrow': '22.0.0', 'boto3': '1.40.56', 'botocore': '1.40.76',
                'jmespath': '1.1.0', 's3transfer': '0.14.0', 'python-dateutil': '2.9.0.post0',
                'urllib3': '2.8.0', 'six': '1.17.0', 'psycopg': '3.2.10',
                'psycopg-binary': '3.2.10', 'typing-extensions': '4.16.0'}
    actual = {key: importlib.metadata.version(key) for key in expected}
    if actual != expected or sys.version_info[:3] != (3, 12, 12):
        raise RuntimeError('runtime pins differ from fixed profile')
    cutoff = time.monotonic() + 5

    def checkpoint():
        if time.monotonic() >= cutoff:
            raise TimeoutError('PG probe deadline')
        return cutoff

    control = CatalogReadControl(checkpoint, time.monotonic)
    dsn = normalized_dsn('host=127.0.0.1 port=5432 dbname=postgres user=postgres sslmode=disable')
    connection = connect(dsn, cutoff, control)
    try:
        pg = connection.execute("SELECT current_setting('server_version_num')::int AS version, "
                                "host(inet_server_addr()) AS address").fetchone()
        if not (180000 <= pg['version'] < 190000 and pg['address'] == '127.0.0.1'):
            raise RuntimeError('unexpected PG server profile')
    finally:
        connection.close()
    endpoint = 'http://127.0.0.1:8333'
    FixedBackend('p04_fixture', 'm0-data', endpoint,
                 CredentialSnapshot('m0-test-key', 'm0-test-secret'))
    client = boto3.client('s3', endpoint_url=endpoint, region_name='us-east-1',
                          aws_access_key_id='m0-test-key', aws_secret_access_key='m0-test-secret',
                          config=Config(signature_version='s3v4', proxies={},
                                        retries={'max_attempts': 0}, connect_timeout=1,
                                        read_timeout=2, s3={'addressing_style': 'path'}))
    client.create_bucket(Bucket='m0-data')
    client.put_bucket_versioning(Bucket='m0-data', VersioningConfiguration={'Status': 'Enabled'})
    if client.get_bucket_versioning(Bucket='m0-data')['Status'] != 'Enabled':
        raise RuntimeError('S3 versioning not enabled')
    first = client.put_object(Bucket='m0-data', Key='namespace-probe', Body=b'first-fixed-version')
    second = client.put_object(Bucket='m0-data', Key='namespace-probe', Body=b'second-fixed-version')
    versions = [first.get('VersionId'), second.get('VersionId')]
    if any(not v or v == 'null' for v in versions) or versions[0] == versions[1]:
        raise RuntimeError('missing distinct fixed object versions')
    response = client.get_object(Bucket='m0-data', Key='namespace-probe', VersionId=versions[0])
    try:
        body = response['Body'].read(len(b'first-fixed-version') + 1)
    finally:
        response['Body'].close()
    if body != b'first-fixed-version' or response['VersionId'] != versions[0]:
        raise RuntimeError('fixed object version changed after overwrite')
    print(json.dumps({'passed': True, 'pins': actual, 'pg': pg, 'pg_invoice': control.invoice,
                      's3_endpoint': endpoint, 'versions': versions,
                      'old_body_sha256': hashlib.sha256(body).hexdigest(),
                      'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                      'scope': 'runtime namespace SDK readiness only; no bind, P04, Rust query or IPC'}))


if __name__ == '__main__':
    main()
