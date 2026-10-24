"""Independent P03 bytes/descriptors, not a certified source or catalog."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time

from modules.common.cf1a_wire import decode

ROOT = Path(__file__).resolve().parents[2]
TINY = b'0123456789abcdef'
SEED = 'guradb-p03-fixture-v1'
LARGE_SIZE = (2 << 20) + 17


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'),
                      allow_nan=False).encode('utf-8')


def sha(value):
    return hashlib.sha256(value).hexdigest()


def payload(size=LARGE_SIZE, seed=SEED):
    return hashlib.shake_256(seed.encode('utf-8')).digest(size)


def object_ref(data=TINY, *, version='v1', block_size=0, backend='local_s3',
               bucket='m0-data', key='object.bin'):
    blocks = [sha(data[start:start + block_size]) for start in range(0, len(data), block_size)] if block_size else []
    return {'backend_id': backend, 'bucket': bucket, 'key': key, 'version': version,
            'size_bytes': len(data), 'sha256': sha(data),
            'integrity': {'mode': 'block_sha256' if block_size else 'whole_sha256',
                          'block_size': block_size, 'block_sha256': blocks,
                          'proof_ref': 'registered-blocks-' + sha(encoded(blocks))[:16] if block_size else ''}}


def binding(ref, *, timeout_ms=3000, budget=None, now_ms=None):
    envelope = deepcopy(json.loads((ROOT/'api/cf1a/golden.json').read_text())[0])
    value = envelope['payload']['read_binding']
    now_ms = time.time_ns() // 1_000_000 if now_ms is None else now_ms
    expiry = now_ms + 60000
    refs = deepcopy(ref if type(ref) is list else [ref])
    value['revision']['objects'] = refs
    # This metadata reference is structural fixture input, never a P04 manifest claim.
    value['revision']['sources'][0]['metadata'] = object_ref(b'{}', key='metadata.fixture.json', version='metadata-v1')
    for source in value['revision']['sources']:
        source['protected_until_unix_ms'] = expiry
    value['indexes'] = []
    value['view']['required_artifact_ids'] = []
    value['view']['index_requirements'] = []
    context = value['context']
    context.update(bound_at_unix_ms=now_ms, deadline_unix_ms=now_ms + timeout_ms,
                   remaining_ttl_ms=timeout_ms, artifact_ids=[])
    context['auth']['expires_unix_ms'] = expiry
    context['pin']['expires_unix_ms'] = expiry
    context['budget'] = {'memory_bytes': 16 << 20, 'object_requests': 32, 'object_bytes': 64 << 20,
                         'candidates': 1, 'top_k': 1, 'graph_edges': 1, 'output_bytes': 16 << 20,
                         'concurrency': 1, 'temp_bytes': 1}
    context['budget'].update(budget or {})
    for name, field in (('revision', 'content_sha256'), ('view', 'descriptor_sha256')):
        value[name][field] = sha(encoded({key: item for key, item in value[name].items() if key != field}))
    return decode(encoded(envelope))


def input_manifest():
    records = [{'role': name, 'size_bytes': len(data), 'sha256': sha(data),
                'block_size': width, 'blocks': [sha(data[i:i + width]) for i in range(0, len(data), width)]}
               for name, data, width in [('hand-check', TINY, 4), ('large', payload(), 65536)]]
    value = {'scope': 'P03 synthetic module-only', 'seed': SEED, 'license': 'CC0-1.0', 'objects': records}
    return {'manifest': value, 'sha256': sha(encoded(value))}
