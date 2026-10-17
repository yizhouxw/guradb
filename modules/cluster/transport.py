"""Authenticated, bounded loopback HTTP tasks; no dependency on query semantics."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import http.client
from pathlib import Path
import socket
import threading
import time
from urllib.parse import urlsplit
import uuid

from modules.common.contracts import MAX_BYTES, Failure, decode_json, digest, encoded, require


def endpoint(value):
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except (TypeError,ValueError):
        raise Failure('unsupported_transport', 'invalid worker endpoint') from None
    require(parsed.scheme == 'http' and parsed.hostname == '127.0.0.1' and port is not None and
            parsed.username is None and parsed.password is None and parsed.path in ('', '/') and
            not parsed.query and not parsed.fragment, 'unsupported_transport')
    return parsed.hostname, port


def signature(secret, route, raw):
    require(isinstance(secret, str) and len(secret.encode()) >= 32, 'invalid_worker_secret')
    return hmac.new(secret.encode(), route.encode()+b'\n'+raw, hashlib.sha256).hexdigest()


def request(url, route, value, secret, timeout, cancelled=None, response_limit=MAX_BYTES):
    host, port = endpoint(url)
    raw = encoded(value)
    require(len(raw) <= MAX_BYTES, 'resource_limit')
    deadline = time.monotonic()+max(.01, timeout)
    cancelled = cancelled or threading.Event()
    connection = http.client.HTTPConnection(host, port, timeout=min(.2, max(.01, timeout)))
    finished, watcher, response = threading.Event(), None, None

    def check():
        require(not cancelled.is_set(), 'cancelled')
        require(time.monotonic() < deadline, 'timeout')

    try:
        check()
        connection.connect()
        active_socket = connection.sock
        active_socket.settimeout(max(.01, deadline-time.monotonic()))

        def interrupt():
            while not finished.wait(.01):
                if cancelled.is_set() or time.monotonic() >= deadline:
                    try:
                        active_socket.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    return

        watcher = threading.Thread(target=interrupt)
        watcher.start()
        connection.request('POST', route, raw, {'Content-Type': 'application/json',
                            'X-Gura-Signature': signature(secret, route, raw)})
        response = connection.getresponse()
        declared = response.getheader('Content-Length')
        require(declared is not None and declared.isdigit() and int(declared) <= response_limit, 'resource_limit')
        chunks, received = [], 0
        while received < int(declared):
            check()
            chunk = response.read1(min(65536, int(declared)-received))
            check()
            require(chunk, 'worker_unavailable')
            received += len(chunk)
            require(received <= response_limit, 'resource_limit')
            chunks.append(chunk)
        check()
        result = b''.join(chunks)
        require(hmac.compare_digest(response.getheader('X-Gura-Signature', ''),
                                    signature(secret, route, result)), 'worker_unauthorized')
        value = decode_json(result)
        require(isinstance(value, dict), 'worker_mismatch')
        if 'error' in value:
            raise Failure(value['error'], 'remote worker rejected task')
        require(response.status == 200, 'worker_failed')
        return value
    except (OSError, http.client.HTTPException):
        check()
        raise Failure('worker_unavailable', 'loopback worker transport failed') from None
    finally:
        finished.set()
        if watcher is not None:
            watcher.join(timeout=.5)
            require(not watcher.is_alive(), 'worker_failed')
        if response is not None:
            response.close()
        connection.close()


def fanout_remote(payloads, budget, root, endpoints, secret):
    """Return three worker envelopes, rejecting expired, foreign, or oversized results."""
    require(len(payloads) == len(endpoints) == 3 and len(set(endpoints)) == 3, 'invalid_request')
    for url in endpoints:
        endpoint(url)
    budget.check()
    Path(root).mkdir(parents=True, exist_ok=True)
    require(sum(len(encoded(payload)) for payload in payloads) <= MAX_BYTES, 'resource_limit')
    owner = uuid.uuid4().hex
    expires = time.time() + max(0, budget.deadline-time.monotonic())
    tasks = [{'task_id': uuid.uuid4().hex, 'owner': owner, 'shard': shard,
              'expires_at': expires, 'payload': payload, 'fingerprint': digest(encoded(payload)),
              'limits': budget.allocation(3)} for shard,payload in enumerate(payloads)]
    require(sum(len(encoded(task)) for task in tasks) <= MAX_BYTES, 'resource_limit')
    stopped = threading.Event()
    pool = ThreadPoolExecutor(max_workers=3)
    futures = [pool.submit(request, url, '/v1/tasks', task, secret,
                           max(.05, budget.deadline-time.monotonic()), stopped, MAX_BYTES//3) for url,task in zip(endpoints,tasks)]
    try:
        while not all(future.done() for future in futures):
            budget.check()
            for future in futures:
                if future.done():
                    future.result()
            time.sleep(.01)
        budget.check()
        results, total = [], 0
        for task,future in zip(tasks,futures):
            result = future.result()
            require(all(result.get(name) == task[name] for name in ('task_id','owner','shard','fingerprint')) and
                    type(result.get('pid')) is int and result['pid'] > 0 and
                    type(result.get('server_pid')) is int and result['server_pid'] > 0 and
                    result.get('read_context') == task['payload']['bundle']['context'] and
                    type(result.get('records')) is int and result['records'] >= 0 and
                    type(result.get('rss_bytes')) is int and 0 < result['rss_bytes'] <= 512 << 20 and
                    isinstance(result.get('output'), dict) and isinstance(result.get('work'), dict), 'worker_mismatch')
            total += len(encoded(result))
            require(total <= MAX_BYTES, 'resource_limit')
            budget.merge(result['work'].get('budget'))
            results.append(result)
        require(len({result['pid'] for result in results}) == 3 and
                len({result['server_pid'] for result in results}) == 3, 'worker_mismatch')
        budget.check()
        return results
    finally:
        stopped.set()
        # Separate connections can cancel an active handler while its response is pending.
        def cancel_remote(pair):
            url, task = pair
            try:
                request(url, '/v1/cancel', {'task_id': task['task_id'], 'owner': owner}, secret, .5)
            except Failure:
                pass
        with ThreadPoolExecutor(max_workers=3) as cancellation:
            list(cancellation.map(cancel_remote, zip(endpoints,tasks)))
        pool.shutdown(wait=True, cancel_futures=True)
