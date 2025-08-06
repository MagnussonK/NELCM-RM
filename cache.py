import os
import json
import zlib
import logging
from typing import Any, Optional

import redis

# Setup logger with fallback if logging isn't configured yet
logger = logging.getLogger("cache")
if not logger.hasHandlers():
    logging.basicConfig(level=logging.INFO)
logger.setLevel(logging.INFO)

# --- Configurable environment variables ---
REDIS_HOST: str = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT: int = int(os.environ.get("REDIS_PORT", 6379))
REDIS_PASS: Optional[str] = os.environ.get("REDIS_PASS", None)
USE_CACHE: bool = os.environ.get("USE_CACHE", "1") == "1"
CACHE_DEFAULT_TTL: int = int(os.environ.get("CACHE_DEFAULT_TTL", 3600))
CACHE_KEY_PREFIX: str = os.environ.get("CACHE_KEY_PREFIX", "")  # For multi-env separation

# Use a connection pool (recommended for Flask/FastAPI/Gunicorn/etc.)
_redis_pool = None

def get_redis_connection() -> Optional[redis.Redis]:
    """Get a Redis connection (with connection pool). Returns None if cache disabled."""
    global _redis_pool
    if not USE_CACHE:
        logger.info("[Cache] USE_CACHE is disabled.")
        return None
    if _redis_pool is None:
        _redis_pool = redis.ConnectionPool(
            host=REDIS_HOST,
            port=REDIS_PORT,
            password=REDIS_PASS,
            decode_responses=False,
            socket_timeout=5,
        )
    return redis.Redis(connection_pool=_redis_pool)

def make_key(key: str) -> str:
    """Prepend prefix if set for cache key."""
    return f"{CACHE_KEY_PREFIX}{key}"

def set_cache(key: str, value: Any, ex: Optional[int] = None) -> None:
    """
    Set a key in Redis cache with (optional) expiration (TTL in seconds).
    Serializes and compresses the value.
    """
    if not USE_CACHE:
        return
    try:
        r = get_redis_connection()
        payload = zlib.compress(json.dumps(value, default=str).encode("utf-8"))
        ttl = ex if ex is not None else CACHE_DEFAULT_TTL
        r.set(make_key(key), payload, ex=ttl)
        logger.info(f"[Cache] Set {key} (TTL: {ttl}s)")
    except Exception as e:
        logger.warning(f"[Cache] Set failed for {key}: {e}")

def get_cache(key: str) -> Optional[Any]:
    """
    Get and decompress a key from Redis cache.
    Returns None if not found or if cache disabled.
    """
    if not USE_CACHE:
        return None
    try:
        r = get_redis_connection()
        val = r.get(make_key(key))
        if val is None:
            logger.info(f"[Cache] Miss for {key}")
            return None
        logger.info(f"[Cache] Hit for {key}")
        return json.loads(zlib.decompress(val).decode("utf-8"))
    except Exception as e:
        logger.warning(f"[Cache] Get failed for {key}: {e}")
        return None

def delete_cache(key: str) -> None:
    """
    Delete a key from Redis cache.
    """
    if not USE_CACHE:
        return
    try:
        r = get_redis_connection()
        r.delete(make_key(key))
        logger.info(f"[Cache] Deleted {key}")
    except Exception as e:
        logger.warning(f"[Cache] Delete failed for {key}: {e}")
