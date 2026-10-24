"""Trusted local backend configuration and the locked SDK's S3 SigV4 signer."""
from dataclasses import dataclass, field
import logging
import re
from urllib.parse import quote, urlsplit

from botocore.auth import S3SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials

from modules.common.cf1a_primitives import require


def validate_key(key):
    require(not any(part in {'.', '..'} for part in key.split('/')),
            'literal dot segments are outside certified backend scope', 'unsupported_capability')


@dataclass(frozen=True)
class CredentialSnapshot:
    access_key: str = field(repr=False)
    secret_key: str = field(repr=False)
    token: str | None = field(default=None, repr=False)
    expires_unix_ms: int | None = None

    def frozen(self, deadline_ms):
        for value in (self.access_key, self.secret_key):
            require(type(value) is str and 0 < len(value) <= 1024 and
                    all(33 <= ord(char) < 127 for char in value), 'invalid credential snapshot', 'unauthorized')
        require(self.token is None or (type(self.token) is str and 0 < len(self.token) <= 4096 and
                all(33 <= ord(char) < 127 for char in self.token)), 'invalid credential token', 'unauthorized')
        require(self.expires_unix_ms is None or (type(self.expires_unix_ms) is int and
                self.expires_unix_ms >= deadline_ms), 'credential expires before fixed execution', 'unauthorized')
        return Credentials(self.access_key, self.secret_key, self.token).get_frozen_credentials()


@dataclass(frozen=True)
class FixedBackend:
    backend_id: str
    bucket: str
    endpoint: str
    credentials: CredentialSnapshot = field(repr=False)
    versioning_certified: bool = False
    region: str = 'us-east-1'

    def __post_init__(self):
        require(type(self.endpoint) is str and
                re.fullmatch(r'http://127\.0\.0\.1:[1-9][0-9]{0,4}', self.endpoint) is not None,
                'only the certified numeric loopback endpoint is supported', 'unsupported_capability')
        parsed = urlsplit(self.endpoint)
        try:
            port = parsed.port
        except ValueError:
            port = None
        require(type(port) is int and 0 < port <= 65535 and self.endpoint == f'http://127.0.0.1:{port}',
                'invalid loopback endpoint', 'unsupported_capability')
        require(type(self.backend_id) is str and re.fullmatch(r'[A-Za-z0-9_-]{1,128}', self.backend_id) is not None and
                self.bucket == 'm0-data' and self.region == 'us-east-1',
                'invalid trusted backend configuration', 'unsupported_capability')
        require(type(self.versioning_certified) is bool, 'invalid backend certification')
        require(type(self.credentials) is CredentialSnapshot, 'explicit credential snapshot required', 'unauthorized')

    @property
    def address(self):
        return '127.0.0.1', urlsplit(self.endpoint).port

    def request(self, ref, offset, length, deadline_ms):
        validate_key(ref['key'])
        require(self.versioning_certified and ref['backend_id'] == self.backend_id and
                ref['bucket'] == self.bucket and ref['version'] != 'null',
                'backend or immutable version is not certified', 'unsupported_capability')
        # The composition root owns this rule. Never mutate any global logger here.
        require(not logging.getLogger('botocore.auth').isEnabledFor(logging.DEBUG),
                'signer debug logging must be disabled by trusted composition', 'unsupported_capability')
        path = '/' + self.bucket + '/' + quote(ref['key'], safe='/-_.~')
        query = 'versionId=' + quote(ref['version'], safe='-_.~')
        target = path + '?' + query
        headers = {'Host': urlsplit(self.endpoint).netloc, 'Connection': 'close',
                   'Accept-Encoding': 'identity'}
        if offset != 0 or length != ref['size_bytes']:
            headers['Range'] = f'bytes={offset}-{offset + length - 1}'
        request = AWSRequest(method='GET', url=self.endpoint + target, headers=headers)
        credentials = self.credentials.frozen(deadline_ms)
        S3SigV4Auth(credentials, 's3', self.region).add_auth(request)
        prepared = request.prepare()
        require(prepared.url == self.endpoint + target and prepared.body is None,
                'signer changed fixed request target', 'unsupported_capability')
        raw = ('GET ' + target + ' HTTP/1.1\r\n' + ''.join(
            name + ': ' + value + '\r\n' for name, value in prepared.headers.items()) + '\r\n').encode('ascii')
        require(len(raw) <= 16384, 'signed request exceeds finite limit', 'resource_limit')
        return raw
