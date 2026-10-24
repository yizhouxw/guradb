"""Owned nonblocking loopback sockets under one absolute execution deadline."""
import asyncio
import socket

from modules.common.cf1a_primitives import ContractFailure, require
from modules.storage.fixed_http import HEADER_LIMIT, response_headers, validate_response

IO_RESERVE_SECONDS = 0.200
POLL_SECONDS = 0.005
CHUNK_BYTES = 65536


def fetch(scope, backend, ref, offset, length):
    scope.request(length)
    raw_request = backend.request(ref, offset, length, scope.context['deadline_unix_ms'])
    scope.check(slack=IO_RESERVE_SECONDS)
    try:
        return asyncio.run(_receive(scope, backend.address, raw_request, ref, offset, length))
    except TimeoutError:
        raise ContractFailure('deadline', 'fixed object transport deadline reached') from None
    except OSError:
        raise ContractFailure('backend_unavailable', 'fixed object connection unavailable') from None


async def _receive(scope, address, raw_request, ref, offset, length):
    loop = asyncio.get_running_loop()
    owner = asyncio.current_task()
    reason = None
    monitor_handle = None
    owned_socket = None

    def monitor():
        nonlocal reason, monitor_handle
        try:
            scope.check(slack=IO_RESERVE_SECONDS)
        except ContractFailure as error:
            reason = error
            owner.cancel()
        else:
            monitor_handle = loop.call_later(POLL_SECONDS, monitor)

    try:
        scope.check(slack=IO_RESERVE_SECONDS)
        # Convert a remaining duration, without assuming a shared loop time epoch.
        expires = loop.time() + max(0, scope.deadline - scope.monotonic() - IO_RESERVE_SECONDS)
        monitor_handle = loop.call_later(POLL_SECONDS, monitor)
        owned_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        owned_socket.setblocking(False)
        async with asyncio.timeout_at(expires):
            await loop.sock_connect(owned_socket, address)
            scope.event('socket_connected')
            scope.check(slack=IO_RESERVE_SECONDS)
            await loop.sock_sendall(owned_socket, raw_request)
            scope.event('request_sent')
            headers = bytearray()
            while not headers.endswith(b'\r\n\r\n'):
                scope.check(slack=IO_RESERVE_SECONDS)
                require(len(headers) < HEADER_LIMIT, 'response header limit exceeded', 'corrupt_object')
                part = await loop.sock_recv(owned_socket, 1)
                scope.received(len(part), header=True)
                require(bool(part), 'incomplete response headers', 'corrupt_object')
                headers.extend(part)
                if len(headers) % 64 == 0:
                    await asyncio.sleep(0)
            scope.event('headers_received')
            status, metadata = response_headers(headers)
            validate_response(status, metadata, ref, offset, length)
            scope.check(slack=IO_RESERVE_SECONDS)
            body = bytearray(length)
            position = 0
            while position < length:
                scope.check(slack=IO_RESERVE_SECONDS)
                view = memoryview(body)[position:position + min(CHUNK_BYTES, length - position)]
                count = await loop.sock_recv_into(owned_socket, view)
                scope.received(count)
                require(count > 0, 'fixed object body ended early', 'corrupt_object')
                position += count
                scope.check(slack=IO_RESERVE_SECONDS)
                await asyncio.sleep(0)
            scope.event('body_received')
            extra = await loop.sock_recv(owned_socket, 1)
            scope.received(len(extra))
            require(not extra, 'fixed object body exceeds declared length', 'corrupt_object')
            scope.check(slack=IO_RESERVE_SECONDS)
            return bytes(body)
    except asyncio.CancelledError:
        if reason is not None:
            raise reason from None
        raise
    finally:
        if monitor_handle is not None:
            monitor_handle.cancel()
        if owned_socket is not None:
            owned_socket.close()
            scope.event('socket_closed')
        # Run cancellation callbacks removing socket watchers before loop teardown.
        await asyncio.sleep(0)
