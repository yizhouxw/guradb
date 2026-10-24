"""Discardable immutable LRU; neither contents nor a cache hit grant access."""
from collections import OrderedDict
import threading

from modules.common.cf1a_primitives import digest, require


class VerifiedCache:
    def __init__(self, capacity=256 << 10):
        require(type(capacity) is int and 0 <= capacity <= 16 << 20, 'invalid cache capacity')
        self.capacity = capacity
        self.size = self.hits = self.evictions = 0
        self._entries = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def key(ref, offset, length):
        return digest(ref), offset, length

    def get(self, key):
        with self._lock:
            value = self._entries.get(key)
            if value is not None:
                self._entries.move_to_end(key)
                self.hits += 1
            return value

    def put(self, key, value):
        require(type(value) is bytes and len(value) > 0, 'cache requires immutable nonempty bytes')
        # Account per-entry metadata and immutable bytes, including small entries.
        cost = len(value) + 1024
        if cost > self.capacity:
            return
        with self._lock:
            previous = self._entries.pop(key, None)
            if previous is not None:
                self.size -= len(previous) + 1024
            while self.size + cost > self.capacity:
                _, removed = self._entries.popitem(last=False)
                self.size -= len(removed) + 1024
                self.evictions += 1
            self._entries[key] = value
            self.size += cost

    def clear(self):
        with self._lock:
            self._entries.clear()
            self.size = 0
