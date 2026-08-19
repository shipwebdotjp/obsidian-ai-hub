from __future__ import annotations

import time
from typing import Any, Callable, Optional

CACHE_TTL_SECONDS = 60.0

_cache: dict[tuple, tuple[float, Any]] = {}


def get_cached(key: tuple) -> Optional[Any]:
    """Return the cached value for key if it is fresh, otherwise None."""
    entry = _cache.get(key)
    if entry is None:
        return None
    stored_at, value = entry
    if time.time() - stored_at > CACHE_TTL_SECONDS:
        return None
    return value


def put_cached(key: tuple, value: Any) -> None:
    _cache[key] = (time.time(), value)


def cached_or_fetch(key: tuple, fetcher: Callable[[], Any]) -> Any:
    """Return the fresh cached value or fetch, store, and return it."""
    value = get_cached(key)
    if value is None:
        value = fetcher()
        put_cached(key, value)
    return value


def invalidate(key: Optional[tuple] = None) -> None:
    """Drop a single cache entry or the whole cache when key is None."""
    if key is None:
        _cache.clear()
    else:
        _cache.pop(key, None)


def invalidate_all() -> None:
    _cache.clear()