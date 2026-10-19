"""Strict boundary fakes: consume declared SQL responses without implementing SQL."""
from contextlib import contextmanager
from copy import deepcopy
from unittest.mock import Mock


class Connection:
    def __init__(self, steps=()):
        self.steps = list(steps)
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if not self.steps:
            raise AssertionError(f'unexpected SQL: {sql}')
        fragment, value = self.steps.pop(0)
        if fragment not in str(sql):
            raise AssertionError(f'expected {fragment!r}, got {sql!r}')
        if isinstance(value, Exception):
            raise value
        result = Mock()
        result.fetchone.return_value = deepcopy(value)
        result.fetchall.return_value = deepcopy(value)
        result.__iter__ = lambda _: iter(deepcopy(value))
        return result

    def complete(self):
        if self.steps:
            raise AssertionError(f'unused SQL responses: {self.steps}')


@contextmanager
def transaction(conn):
    yield conn


def control_for(conn):
    control = Mock()
    control.transaction.side_effect = lambda: transaction(conn)
    return control
