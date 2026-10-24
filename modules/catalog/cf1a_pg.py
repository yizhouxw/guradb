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
from modules.catalog.cf1a_control import CatalogReadControl


def remaining(deadline, control=None):
    if control is not None:
        require(type(control) is CatalogReadControl, 'expected private parent control')
        return control.remaining(deadline)
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


def _ready(fd, mask, deadline, control=None):
    require(mask in (selectors.EVENT_READ, selectors.EVENT_WRITE, 3), 'invalid PG wait state')
    if control is not None:
        remaining(deadline, control)
    started = time.monotonic()
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(fd, mask)
            events = selector.select(min(.01, remaining(deadline, control)))
        remaining(deadline, control)
    finally:
        if control is not None:
            control.mark('wait', started)
    return events[0][1] if events else 0


class DeadlineConnection(psycopg.Connection):
    """Each instance owns one connection and one immutable operation deadline."""

    def __init__(self, pgconn, deadline, control=None):
        super().__init__(pgconn, row_factory=dict_row)
        self.deadline = deadline
        self.prepare_threshold = None
        self.control, self.phase = control, 'sql'

    def close(self):
        was_closed = self.closed
        super().close()
        control = getattr(self, 'control', None)
        if control is not None and not was_closed:
            control.mark('closed')

    def wait(self, gen, interval=.1):
        # The public Connection wait hook receives a libpq nonblocking generator.
        # It must never invoke psycopg's interrupt path, which may wait to cancel.
        started = time.monotonic()
        control = self.control
        try:
            if control is not None:
                remaining(self.deadline, control)
                control.mark(self.phase + '_attempt')
            state = next(gen)
            while True:
                ready = (_ready(self.pgconn.socket, int(state), self.deadline) if control is None else
                         _ready(self.pgconn.socket, int(state), self.deadline, control))
                state = gen.send(ready)
        except StopIteration as result:
            try:
                remaining(self.deadline, control)
            except BaseException:
                if control is not None:
                    control.mark(self.phase + '_failure', started)
                self.close()
                raise
            if control is not None:
                control.mark(self.phase + '_success', started)
            return result.value
        except BaseException:
            if control is not None:
                control.mark(self.phase + '_failure', started)
            self.close()
            raise
        finally:
            gen.close()
            if time.monotonic() >= self.deadline:
                self.close()


def connect(dsn, deadline, control=None):
    remaining(deadline, control)
    pgconn = None
    started = time.monotonic()
    if control is not None:
        control.mark('connect_attempt')
    try:
        pgconn = pq.PGconn.connect_start(dsn.encode('utf-8'))
        while True:
            remaining(deadline, control)
            state = pgconn.connect_poll()
            if state == pq.PollingStatus.OK:
                remaining(deadline, control)
                pgconn.nonblocking = 1
                if control is not None:
                    control.mark('connect_success', started)
                    remaining(deadline, control)
                    return DeadlineConnection(pgconn, deadline, control)
                return DeadlineConnection(pgconn, deadline)
            if state == pq.PollingStatus.READING:
                _ready(pgconn.socket, selectors.EVENT_READ, deadline, control)
            elif state == pq.PollingStatus.WRITING:
                _ready(pgconn.socket, selectors.EVENT_WRITE, deadline, control)
            else:
                raise ContractFailure('backend_unavailable', 'catalog connection unavailable')
    except BaseException:
        if control is not None:
            control.mark('connect_failure', started)
        if pgconn is not None:
            pgconn.finish()
            if control is not None:
                control.mark('closed')
        raise
