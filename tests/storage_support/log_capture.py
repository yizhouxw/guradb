"""Actual acceptance composition logging policy and in-memory canary audit."""
import hashlib
import io
import logging
from urllib.parse import quote

from modules.storage.fixed_signing import CredentialSnapshot, FixedBackend
from tests.storage_support.fixtures import object_ref


class PrivateLogs:
    """Only the process composition root changes logger policy, never storage."""
    def __enter__(self):
        self.root = logging.getLogger()
        self.previous_level = self.root.level
        self.output = io.StringIO()
        self.handler = logging.StreamHandler(self.output)
        self.root.addHandler(self.handler)
        self.root.setLevel(logging.DEBUG)
        self.previous = {}
        for name in ('botocore', 'boto3', 'urllib3'):
            logger = logging.getLogger(name)
            self.previous[name] = logger.level
            logger.setLevel(logging.WARNING)
        self.auth = logging.getLogger('botocore.auth')
        self.previous_disabled = self.auth.disabled
        self.auth.disabled = True
        self.secrets = ['P03-ACCESS-CANARY', 'P03-SECRET-CANARY', 'P03-TOKEN-CANARY',
                        'P03-URL-CANARY', 'm0-test-secret']
        backend = FixedBackend('local_s3', 'm0-data', 'http://127.0.0.1:1',
                               CredentialSnapshot(*self.secrets[:3]), True)
        signed = backend.request(object_ref(key='api_key=P03-URL-CANARY'), 0, 16, 1000)
        assert b'X-Amz-Security-Token: P03-TOKEN-CANARY' in signed
        signature = signed.split(b'Signature=', 1)[1].split(b'\r\n', 1)[0].decode()
        self.secrets.append(signature)
        return self

    def audit(self):
        raw = self.output.getvalue()
        for secret in self.secrets:
            assert secret not in raw and quote(secret, safe='') not in raw, 'protected logging audit failed'
        assert 'Authorization:' not in raw and 'X-Amz-Security-Token:' not in raw, 'signed headers entered logs'
        return {'root_level': 'DEBUG', 'signer_debug_disabled': self.auth.disabled,
                'session_token_injection_checked': True, 'credential_canary_absent': True,
                'captured_bytes': len(raw.encode()), 'capture_sha256': hashlib.sha256(raw.encode()).hexdigest(),
                'short_lived_credential_service_certified': False}

    def __exit__(self, kind, value, traceback):
        self.root.removeHandler(self.handler)
        self.handler.close()
        self.root.setLevel(self.previous_level)
        for name, level in self.previous.items():
            logging.getLogger(name).setLevel(level)
        self.auth.disabled = self.previous_disabled
