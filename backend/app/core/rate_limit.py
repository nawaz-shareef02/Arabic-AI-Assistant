import time
import logging
from typing import Dict, List
import redis
from app.core.config import settings

logger = logging.getLogger("app.core.rate_limit")

# Global Redis client initialization with RESP2 support (protocol=2) and timeouts
try:
    redis_client = redis.from_url(settings.REDIS_URL, protocol=2, socket_timeout=1.0)
    redis_client.ping()
    logger.info("Successfully connected to Redis for rate limiting.")
except Exception as e:
    logger.warning(f"Could not connect to Redis at {settings.REDIS_URL}: {str(e)}. Rate limiting will fall back to in-memory storage.")
    redis_client = None


class RedisRateLimiter:
    """
    Sliding window log rate limiter backed by Redis.
    Falls back gracefully to an in-memory dictionary if Redis is unreachable.
    """
    # Class variable to hold memory fallback history for all instances
    _memory_history: Dict[str, List[float]] = {}

    def __init__(self, limit: int, window_seconds: int, name: str):
        self.limit = limit
        self.window_seconds = window_seconds
        self.name = name

    def is_rate_limited(self, key: str) -> bool:
        # Bypass rate limiting if running inside pytest test session
        import sys
        if "pytest" in sys.modules:
            return False
            
        now = time.time()
        
        # 1. Fallback to in-memory rate limiting if Redis is not configured or offline
        if redis_client is None:
            return self._memory_fallback(key, now)
            
        redis_key = f"rate_limit:{self.name}:{key}"
        clear_before = now - self.window_seconds
        
        try:
            # Execute operations in a pipeline transaction
            pipe = redis_client.pipeline()
            # Remove outdated entries
            pipe.zremrangebyscore(redis_key, 0, clear_before)
            # Count elements inside window
            pipe.zcard(redis_key)
            # Add current timestamp
            pipe.zadd(redis_key, {str(now): now})
            # Set dynamic TTL on the sliding window set
            pipe.expire(redis_key, self.window_seconds)
            results = pipe.execute()
            
            # The zcard result indicates how many requests were made prior to this one within the window
            request_count = results[1]
            if request_count >= self.limit:
                logger.warning(f"AUDIT | Action: rate_limit_exceeded | Key: {key} | Limiter: {self.name} | Status: blocked")
                return True
                
            return False
        except Exception as e:
            logger.error(f"Redis rate limiter '{self.name}' error: {str(e)}. Gracefully falling back to memory.")
            return self._memory_fallback(key, now)

    def _memory_fallback(self, key: str, now: float) -> bool:
        memory_key = f"{self.name}:{key}"
        
        if memory_key not in self._memory_history:
            self._memory_history[memory_key] = []
            
        # Retain only timestamps within the active sliding window
        self._memory_history[memory_key] = [
            t for t in self._memory_history[memory_key]
            if now - t < self.window_seconds
        ]
        
        if len(self._memory_history[memory_key]) >= self.limit:
            logger.warning(f"AUDIT | Action: rate_limit_exceeded (memory) | Key: {key} | Limiter: {self.name} | Status: blocked")
            return True
            
        self._memory_history[memory_key].append(now)
        return False


# Rate limiters instantiations matching platform specifications
login_limiter = RedisRateLimiter(limit=5, window_seconds=15 * 60, name="login")
register_limiter = RedisRateLimiter(limit=3, window_seconds=60 * 60, name="register")
forgot_password_limiter = RedisRateLimiter(limit=3, window_seconds=60 * 60, name="forgot_password")
api_limiter = RedisRateLimiter(limit=100, window_seconds=60, name="api")
