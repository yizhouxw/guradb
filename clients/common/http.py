"""Thin HTTP transport; never retries POST or bypasses server limits."""
import json
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class Client:
    def __init__(self, url, token):
        self.url, self.token = url.rstrip('/'), token

    def request(self, method, path, body=None):
        request = Request(self.url+path, method=method,
                          headers={'Authorization':'Bearer '+self.token, 'Content-Type':'application/json'},
                          data=json.dumps(body,allow_nan=False).encode() if body is not None else None)
        try:
            with urlopen(request, timeout=12) as response:
                raw = response.read((32 << 20)+1)
                if len(raw) > 32 << 20:
                    raise RuntimeError('response exceeds client byte budget')
                return json.loads(raw) if response.headers['Content-Type']=='application/json' else raw
        except HTTPError as error:
            raise RuntimeError(error.read(65536).decode()) from None

    def wait(self, handle, seconds=12):
        deadline = time.monotonic()+seconds
        job = handle['query_id']
        try:
            while handle['status'] in ('queued','running'):
                if time.monotonic() >= deadline:
                    self.request('DELETE','/v1/jobs/'+job)
                    raise RuntimeError('client deadline exceeded; cancellation requested: '+job)
                time.sleep(.05)
                handle = self.request('GET','/v1/jobs/'+job)
        except KeyboardInterrupt:
            self.request('DELETE','/v1/jobs/'+job)
            raise
        if handle['status'] != 'succeeded':
            raise RuntimeError(json.dumps(handle))
        return self.request('GET','/v1/jobs/'+job+'/results')
