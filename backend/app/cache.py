"""Content-addressed plan cache.

Every solver is deterministic (fixed seeds and iteration budgets), so the plan for a
given (scenario, weights, algorithm, solver budget, engine version) never changes. The
key is a SHA-256 of that input as canonical JSON. Two tiers:

1. an in-process LRU: microseconds, per instance. It absorbs slider back-and-forth.
2. the database ``plan_cache`` table: shared by every instance, so a serverless cold
   start or a second viewer gets a plan someone else already computed.

Bump ``ENGINE_VERSION`` whenever solver behaviour changes; old entries then simply stop
matching.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
from typing import Any

ENGINE_VERSION = "2026.10.1"


def plan_key(**parts: Any) -> str:
    blob = json.dumps({"v": ENGINE_VERSION, **parts}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


class LRU:
    def __init__(self, maxsize: int = 512):
        self._data: OrderedDict[str, Any] = OrderedDict()
        self._max = maxsize
        self._lock = threading.Lock()
        self.hits = self.misses = 0

    def get(self, key: str) -> Any | None:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                self.hits += 1
                return self._data[key]
            self.misses += 1
            return None

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = value
            self._data.move_to_end(key)
            while len(self._data) > self._max:
                self._data.popitem(last=False)

    def stats(self) -> dict:
        return {"size": len(self._data), "hits": self.hits, "misses": self.misses}
