"""Bounded loopback PG transport for the pinned Psycopg 3.2.10 adapter.

Server statement_timeout alone does not bound a paused server or a handshake.
Drive public nonblocking pq/Connection generators under one monotonic deadline.
"""
import selectors
import time

import psycopg
from psycopg import pq
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row

from modules.common.cf1a_primitives import ContractFailure, require


def remaining(deadline):
    value = deadline - time.monotonic()
    require(value > 0, 'catalog deadline reached', 'deadline')
    return value


def normalized_dsn(dsn):
    try:
        params = conninfo_to_dict(dsn)
    except (psycopg.Error, TypeError):
        raise ContractFailure('invalid_contract', 'invalid catalog DSN') from None
    allowed = {'host', 'hostaddr', 'port', 'dbname', 'user', 'password', 'sslmode', 'application_name'}
    require(set(params) <= allowed and params.get('host') == '127.0.0.1' and
            params.get('hostaddr', '127.0.0.1') == '127.0.0.1' and
            params.get('sslmode', 'disable') == 'disable',
            'only explicit loopback plain PG is certified', 'unsupported_capability')
    port = params.get('port', '')
    require(port.isascii() and port.isdecimal() and 0 < int(port) < 65536 and
            bool(params.get('dbname')) and bool(params.get('user')), 'incomplete catalog DSN')
    params.update(hostaddr='127.0.0.1', sslmode='disable', gssencmode='disable',
                  client_encoding='UTF8')
    return make_conninfo(**params)


def _ready(fd, mask, deadline):
    require(mask in (selectors.EVENT_READ, selectors.EVENT_WRITE, 3), 'invalid PG wait state')
    with selectors.DefaultSelector() as selector:
        selector.register(fd, mask)
        events = selector.select(min(.01, remaining(deadline)))
    remaining(deadline)
    return events[0][1] if events else 0


class DeadlineConnection(psycopg.Connection):
    """Each instance owns one connection and one immutable operation deadline."""

    def __init__(self, pgconn, deadline):
        super().__init__(pgconn, row_factory=dict_row)
        self.deadline = deadline
        self.prepare_threshold = None

    def wait(self, gen, interval=.1):
        # The public Connection wait hook receives a libpq nonblocking generator.
        # It must never invoke psycopg's interrupt path, which may wait to cancel.
        try:
            state = next(gen)
            while True:
                state = gen.send(_ready(self.pgconn.socket, int(state), self.deadline))
        except StopIteration as result:
            remaining(self.deadline)
            return result.value
        except BaseException:
            self.close()
            raise
        finally:
            gen.close()
            if time.monotonic() >= self.deadline:
                self.close()


def connect(dsn, deadline):
    remaining(deadline)
    pgconn = None
    try:
        pgconn = pq.PGconn.connect_start(dsn.encode('utf-8'))
        while True:
            remaining(deadline)
            state = pgconn.connect_poll()
            if state == pq.PollingStatus.OK:
                remaining(deadline)
                pgconn.nonblocking = 1
                return DeadlineConnection(pgconn, deadline)
            if state == pq.PollingStatus.READING:
                _ready(pgconn.socket, selectors.EVENT_READ, deadline)
            elif state == pq.PollingStatus.WRITING:
                _ready(pgconn.socket, selectors.EVENT_WRITE, deadline)
            else:
                raise ContractFailure('backend_unavailable', 'catalog connection unavailable')
    except BaseException:
        if pgconn is not None:
            pgconn.finish()
        raise
