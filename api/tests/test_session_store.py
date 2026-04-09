"""Tests for the in-memory session store."""
import time

import pytest

from app.session_store import SessionStore


def test_empty_history_returns_empty_list() -> None:
    store = SessionStore(ttl_minutes=10)
    assert store.get_history("user1") == []


def test_append_and_read_history() -> None:
    store = SessionStore(ttl_minutes=10)
    store.append("user1", {"role": "user", "content": "hi"})
    store.append("user1", {"role": "assistant", "content": "hello"})

    history = store.get_history("user1")
    assert len(history) == 2
    assert history[0]["content"] == "hi"
    assert history[1]["content"] == "hello"


def test_reset_clears_history() -> None:
    store = SessionStore(ttl_minutes=10)
    store.append("user1", {"role": "user", "content": "hi"})
    store.reset("user1")
    assert store.get_history("user1") == []


def test_multiple_users_are_isolated() -> None:
    store = SessionStore(ttl_minutes=10)
    store.append("user1", {"role": "user", "content": "from user1"})
    store.append("user2", {"role": "user", "content": "from user2"})

    assert store.get_history("user1")[0]["content"] == "from user1"
    assert store.get_history("user2")[0]["content"] == "from user2"
    assert store.active_count() == 2


def test_get_history_returns_copy_not_reference() -> None:
    # Guarantees the caller can't mutate internal state by holding the list.
    store = SessionStore(ttl_minutes=10)
    store.append("user1", {"role": "user", "content": "hi"})

    history = store.get_history("user1")
    history.append({"role": "user", "content": "injected"})

    assert len(store.get_history("user1")) == 1


def test_entries_expire_after_ttl() -> None:
    # Build a store with a tiny TTL directly on the underlying cache.
    # cachetools.TTLCache evicts lazily on read, so we read after sleeping.
    from cachetools import TTLCache

    store = SessionStore(ttl_minutes=1)
    store._cache = TTLCache(maxsize=100, ttl=0.1)
    store.append("user1", {"role": "user", "content": "hi"})
    time.sleep(0.2)
    assert store.get_history("user1") == []
