"""
In-memory storage for conversation history with automatic expiration.

Uses cachetools.TTLCache instead of a manual cleanup thread: TTLCache
evicts entries lazily on read/write, which is simpler and race-free.

IMPORTANT: this store is in-memory and single-process. For production
deployments with multiple workers/instances, swap it for Redis or another
shared backend that implements the same interface.
"""
from threading import Lock
from typing import Any

from cachetools import TTLCache


class SessionStore:
    """Per-user message history with idle-based expiration."""

    def __init__(self, ttl_minutes: int, maxsize: int = 10_000) -> None:
        # TTL is in seconds; maxsize guards against unbounded growth.
        self._cache: TTLCache = TTLCache(maxsize=maxsize, ttl=ttl_minutes * 60)
        self._lock = Lock()

    def get_history(self, user_id: str) -> list[dict[str, Any]]:
        """Return the user's message history (empty list if none)."""
        with self._lock:
            return list(self._cache.get(user_id, []))

    def append(self, user_id: str, message: dict[str, Any]) -> None:
        """Append a single message to the user's history."""
        with self._lock:
            history = self._cache.get(user_id, [])
            history.append(message)
            self._cache[user_id] = history

    def replace(self, user_id: str, history: list[dict[str, Any]]) -> None:
        """Replace the user's entire history."""
        with self._lock:
            self._cache[user_id] = history

    def reset(self, user_id: str) -> None:
        """Drop the user's history."""
        with self._lock:
            self._cache.pop(user_id, None)

    def active_count(self) -> int:
        """Return the number of currently active (non-expired) sessions."""
        with self._lock:
            return len(self._cache)
