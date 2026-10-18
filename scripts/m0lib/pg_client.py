"""Test-only JSON bridge around the real psycopg SDK, inside the server netns."""
import json
import sys
import threading
import time

import psycopg
from psycopg.types.numeric import Int2, Int4, Int8
from pg_raw import RawClient, malformed_startup


def parameters(values):
    types = {'int2': Int2, 'int4': Int4, 'int8': Int8}
    return [types[v['type']](v['value']) if isinstance(v, dict) else v for v in values]


def error(exc):
    return {'ok': False, 'sqlstate': getattr(exc, 'sqlstate', None), 'type': type(exc).__name__}


def execute(connection, request):
    started = time.perf_counter()
    try:
        with connection.cursor(binary=request.get('binary', False)) as cursor:
            params = parameters(request['parameters']) if 'parameters' in request else None
            cursor.execute(request['sql'], params, prepare=request.get('prepare'))
            rows = cursor.fetchall() if cursor.description is not None else []
            return {'ok': True, 'rows': rows, 'columns': [c.name for c in cursor.description or []],
                    'oids': [c.type_code for c in cursor.description or []],
                    'status': cursor.statusmessage, 'latency_ms': (time.perf_counter() - started) * 1000}
    except Exception as exc:
        return error(exc)


def main():
    connection = None
    raw = None
    pending = None
    outcome = {}
    for line in sys.stdin:
        request = json.loads(line)
        try:
            command = request['command']
            if command == 'connect':
                connection = psycopg.connect(host='127.0.0.1', port=5433, dbname=request.get('database', 'guradb'),
                    user=request.get('user', 'reader'), password=request['password'], sslmode=request.get('sslmode', 'disable'),
                    autocommit=request.get('autocommit', True), connect_timeout=5, application_name='guradb-pg-acceptance')
                response = {'ok': True, 'server_version': connection.info.server_version, 'backend_pid': connection.info.backend_pid}
            elif command == 'query':
                response = execute(connection, request)
            elif command == 'prepare':
                result = connection.pgconn.prepare(request['name'].encode(), request['sql'].encode(), request.get('oids'))
                sqlstate = result.error_field(ord('C'))
                response = {'ok': result.status == psycopg.pq.ExecStatus.COMMAND_OK,
                            'sqlstate': sqlstate.decode() if sqlstate else None}
                if response['ok']:
                    result = connection.pgconn.describe_prepared(request['name'].encode())
                    response.update(parameter_oids=[result.param_type(i) for i in range(result.nparams)],
                                    column_oids=[result.ftype(i) for i in range(result.nfields)])
            elif command == 'close_prepared':
                result = connection.pgconn.close_prepared(request['name'].encode())
                response = {'ok': result.status == psycopg.pq.ExecStatus.COMMAND_OK}
            elif command == 'raw_connect':
                if raw is not None:
                    raw.close()
                raw = RawClient(request['password'], request.get('encoding', 'UTF8'),
                                request.get('user', 'reader'), request.get('database', 'guradb'), request.get('version', 196608))
                response = {'messages': raw.ready}
            elif command == 'raw':
                response = {'messages': raw.action(request)}
            elif command == 'raw_startup':
                response = malformed_startup(request['mode'])
            elif command == 'connection_capacity':
                if raw is not None:
                    raw.close()
                    raw = None
                opened = []
                try:
                    for _ in range(63):
                        opened.append(RawClient(request['password']))
                        assert opened[-1].ready[-1]['type'] == 'Z', opened[-1].ready
                    overflow = RawClient(request['password'])
                    response = {'accepted': len(opened), 'overflow': overflow.ready[-1]}
                    overflow.close()
                    opened.pop().close()
                    restored = RawClient(request['password'])
                    response['recovered'] = restored.ready[-1]['type'] == 'Z'
                    restored.close()
                finally:
                    for item in opened:
                        item.close()
            elif command == 'start':
                if pending is not None and pending.is_alive():
                    raise RuntimeError('one operation per connection')
                outcome.clear()
                pending = threading.Thread(target=lambda: outcome.update(execute(connection, request)))
                pending.start()
                response = {'ok': True}
            elif command == 'poll':
                response = {'running': pending.is_alive(), 'result': None if pending.is_alive() else outcome}
            elif command == 'cancel':
                connection.cancel()
                response = {'ok': True}
            elif command == 'close':
                connection.close()
                response = {'ok': True}
            else:
                raise ValueError('unknown bridge operation')
        except Exception as exc:
            response = error(exc)
        print(json.dumps(response), flush=True)
    if connection is not None:
        connection.close()
    if raw is not None:
        raw.close()


if __name__ == '__main__':
    main()
