import time
from typing import Any, Dict, Optional
import hashlib
import json

class Cache:
    """Simple in-memory cache with TTL support."""

    def __init__(self, default_ttl: int = 3600):
        self.store: Dict[str, tuple[Any, float]] = {}
        self.default_ttl = default_ttl

    def _key(self, *args, **kwargs) -> str:
        """Generate cache key from args and kwargs."""
        key_data = json.dumps({"args": args, "kwargs": kwargs}, sort_keys=True, default=str)
        return hashlib.md5(key_data.encode()).hexdigest()

    def get(self, *args, **kwargs) -> Optional[Any]:
        """Get cached value if not expired."""
        key = self._key(*args, **kwargs)
        if key in self.store:
            value, expiry = self.store[key]
            if time.time() < expiry:
                return value
            else:
                del self.store[key]
        return None

    def set(self, value: Any, ttl: int | None = None, *args, **kwargs) -> None:
        """Set cached value with TTL."""
        key = self._key(*args, **kwargs)
        expiry = time.time() + (ttl or self.default_ttl)
        self.store[key] = (value, expiry)

    def clear(self) -> None:
        """Clear all cached values."""
        self.store.clear()

    def cleanup_expired(self) -> None:
        """Remove expired entries."""
        now = time.time()
        expired_keys = [k for k, (_, expiry) in self.store.items() if now >= expiry]
        for key in expired_keys:
            del self.store[key]


# Global cache instances
wiki_search_cache = Cache(default_ttl=3600)  # 1 hour
wiki_page_cache = Cache(default_ttl=3600)  # 1 hour
class_combo_cache = Cache(default_ttl=86400)  # 24 hours
source_search_cache = Cache(default_ttl=3600)  # 1 hour
