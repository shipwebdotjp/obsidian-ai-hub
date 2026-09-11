"""Regression tests for cross-thread vault search (sqlite3 thread affinity).

md-hybrid-search opens its SQLite connection with sqlite3's default
check_same_thread=True, so an index built in one thread cannot be searched
from another. FastAPI runs sync routes in a threadpool, so the retriever must
pin all index access to a single dedicated worker thread.
"""

import json
import sqlite3
import threading
from types import SimpleNamespace

from obsidian_ai_hub.handler import obsidian_vault_retriever as retriever


class ThreadBoundFakeIndex:
    """Mimics md-hybrid-search's single-thread SQLite connection contract."""

    def __init__(self):
        self.created_in = threading.get_ident()
        self.search_threads = []

    def search(self, query, limit=10, mode="hybrid"):
        if threading.get_ident() != self.created_in:
            raise sqlite3.ProgrammingError(
                "SQLite objects created in a thread can only be used in that "
                "same thread."
            )
        self.search_threads.append(threading.get_ident())
        return []


class FakeIndexFactory:
    def __init__(self):
        self.index = None

    def __call__(self):
        self.index = ThreadBoundFakeIndex()
        return self.index


def _assert_no_error(payload: str):
    data = json.loads(payload)
    assert not (isinstance(data, dict) and "error" in data), data
    return data


def test_search_from_multiple_caller_threads_stays_on_worker_thread(monkeypatch):
    factory = FakeIndexFactory()
    monkeypatch.setattr(retriever, "_vault_index", None)
    monkeypatch.setattr(retriever, "build_vault_search_index", factory)

    caller_threads = set()
    results = {}

    def call(name, query):
        caller_threads.add(threading.get_ident())
        results[name] = retriever._search_obsidian_vault_core_sync(query, k=5)

    t1 = threading.Thread(target=call, args=("a", "query-a"))
    t2 = threading.Thread(target=call, args=("b", "query-b"))
    t1.start()
    t1.join()
    t2.start()
    t2.join()

    for payload in results.values():
        _assert_no_error(payload)

    index = factory.index
    assert index is not None
    worker = index.created_in
    # Index was built and searched on a single worker thread, distinct from
    # every caller thread.
    assert worker not in caller_threads
    assert index.search_threads == [worker, worker]


def test_search_result_formatting(monkeypatch):
    hit = SimpleNamespace(
        content="本文", metadata={"file_path": "a.md"}, score=0.9
    )

    def search_with_hit(self, query, limit=10, mode="hybrid"):
        self.search_threads.append(threading.get_ident())
        return [hit]

    factory = FakeIndexFactory()
    monkeypatch.setattr(retriever, "_vault_index", None)
    monkeypatch.setattr(retriever, "build_vault_search_index", factory)
    monkeypatch.setattr(ThreadBoundFakeIndex, "search", search_with_hit)

    data = _assert_no_error(retriever._search_obsidian_vault_core_sync("q", k=3))
    assert data == [
        {"content": "本文", "metadata": {"file_path": "a.md"}, "score": 0.9}
    ]


def test_search_error_returns_error_json(monkeypatch):
    def boom(query, limit=10, mode="hybrid"):
        raise RuntimeError("boom")

    bad_index = SimpleNamespace(search=boom)
    monkeypatch.setattr(retriever, "_vault_index", None)
    monkeypatch.setattr(retriever, "build_vault_search_index", lambda: bad_index)

    data = json.loads(retriever._search_obsidian_vault_core_sync("q"))
    assert data == {"error": "Unexpected error: RuntimeError: boom"}
