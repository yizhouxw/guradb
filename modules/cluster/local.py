"""Bounded local process fanout; the upper layer selects the trusted worker module."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import uuid

from modules.common.contracts import Failure, MAX_BYTES, digest, encoded, decode_json, require
from modules.storage.objects import get, put


def fanout(module, payloads, budget, root):
    require(len(payloads) == 3, 'invalid_request')
    budget.check()
    total = sum(len(encoded(payload)) for payload in payloads)
    require(total <= MAX_BYTES, 'resource_limit', 'worker input budget exceeded')
    processes, outputs, identities = [], [], []
    Path(root).mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='shards-', dir=root) as directory:
        try:
            for shard, payload in enumerate(payloads):
                budget.check()
                identity = uuid.uuid4().hex
                envelope = {'task_id': identity, 'shard': shard, 'deadline': budget.deadline,
                            'payload': payload, 'fingerprint': digest(encoded(payload)), 'limits': budget.allocation(3)}
                input_ref = put(Path(directory)/f'{shard}.input', encoded(envelope))
                output = Path(directory)/f'{shard}.output'
                log = (Path(directory)/f'{shard}.log').open('wb')
                try:
                    process = subprocess.Popen([sys.executable, '-m', module, input_ref['path'],
                                                input_ref['sha256'], str(output)],
                                               stdout=log, stderr=log, start_new_session=True, cwd=Path(__file__).resolve().parents[2],
                                               env={k:v for k,v in os.environ.items() if k in ('PATH','LANG','LC_ALL','TMPDIR','VIRTUAL_ENV')})
                finally:
                    log.close()
                processes.append(process)
                outputs.append(output)
                identities.append((identity, envelope['fingerprint']))
            budget.check()
            while any(process.poll() is None for process in processes):
                budget.check()
                require(all(process.poll() in (None, 0) for process in processes), 'worker_failed')
                for path in Path(directory).glob('*.log'):
                    require(path.stat().st_size <= 65536, 'resource_limit', 'worker log budget exceeded')
                time.sleep(.01)
            results, bytes_read = [], 0
            for shard, (process, output, identity) in enumerate(zip(processes, outputs, identities)):
                require(process.returncode == 0 and output.is_file(), 'worker_failed')
                with output.open('rb') as stream:
                    raw = stream.read(MAX_BYTES + 1)
                bytes_read += len(raw)
                require(bytes_read <= MAX_BYTES, 'resource_limit', 'worker output budget exceeded')
                result = decode_json(raw)
                require(isinstance(result, dict) and {'task_id','fingerprint','shard','pid'} <= set(result), 'worker_mismatch')
                require((result['task_id'],result['fingerprint']) == identity and result['shard'] == shard and
                        result['pid'] == process.pid, 'worker_mismatch')
                if 'error' in result:
                    raise Failure(result['error'], 'worker rejected task')
                require({'output','read_context','records','rss_bytes','work'} <= set(result) and
                        type(result['records']) is int and result['records'] >= 0 and
                        type(result['rss_bytes']) is int and 0 < result['rss_bytes'] <= 512 << 20 and
                        isinstance(result['output'], dict), 'worker_mismatch')
                budget.merge(result['work']['budget'])
                results.append(result)
            budget.check()
            require(len({result['pid'] for result in results}) == 3, 'worker_mismatch')
            return results
        finally:
            for process in processes:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=5)
