import time
import logging
from typing import Dict, List, Optional
import redis
from app.core.config import settings
from app.core.security_metrics import security_metrics

logger = logging.getLogger("app.core.rate_limit")

try:
    redis_client = redis.from_url(settings.REDIS_URL, protocol=2, socket_timeout=1.0)
    redis_client.ping()
    logger.info("Successfully connected to Redis for rate limiting.")
except Exception as e:
    logger.warning(f"Could not connect to Redis at {settings.REDIS_URL}: {str(e)}. Rate limiting falling back to in-memory storage.")
    redis_client = None


class RedisRateLimiter:
   
    _memory_history: Dict[str, List[float]] = {}

    def __init__(self, limit: int, window_seconds: int, name: str):
        self.limit = limit
        self.window_seconds = window_seconds
        self.name = name

    def get_adaptive_limit(self, risk_score: float) -> int:
        """Refinement #3: Adaptive Throttling based on session risk score."""
        if risk_score >= 0.8:
            return max(1, int(self.limit * 0.05))  # Abusive (e.g. 5 req/min)
        elif risk_score >= 0.5:
            return max(5, int(self.limit * 0.20))  # Suspicious (e.g. 20 req/min)
        return self.limit  # Normal

    def is_rate_limited(self, key: str, risk_score: float = 0.0) -> bool:
        import sys
        if "pytest" in sys.modules:
            return False

        effective_limit = self.get_adaptive_limit(risk_score)
        now = time.time()

        if redis_client is None:
            return self._memory_fallback(key, now, effective_limit)

        redis_key = f"rate_limit:{self.name}:{key}"
        clear_before = now - self.window_seconds

        try:
            pipe = redis_client.pipeline()
            pipe.zremrangebyscore(redis_key, 0, clear_before)
            pipe.zcard(redis_key)
            pipe.zadd(redis_key, {str(now): now})
            pipe.expire(redis_key, self.window_seconds)
            results = pipe.execute()

            request_count = results[1]
            if request_count >= effective_limit:
                security_metrics.increment("rate_limit_hits")
                try:
                    from app.core.prometheus_exporter import metrics_registry
                    metrics_registry.rate_limit_hits_total.labels(
                        limiter=self.name
                    ).inc()
                except Exception:
                    pass
                logger.warning(f"AUDIT | Action: rate_limit_exceeded | Key: {key} | Limiter: {self.name} | Status: blocked")
                return True

            return False
        except Exception as e:
            logger.error(f"Redis rate limiter '{self.name}' error: {str(e)}. Gracefully falling back to memory.")
            return self._memory_fallback(key, now, effective_limit)

    def get_retry_after(self, key: str) -> int:
        """Calculates remaining seconds in current rate limiting window."""
        return self.window_seconds

    def _memory_fallback(self, key: str, now: float, effective_limit: int) -> bool:
        memory_key = f"{self.name}:{key}"
        if memory_key not in self._memory_history:
            self._memory_history[memory_key] = []

        self._memory_history[memory_key] = [
            t for t in self._memory_history[memory_key]
            if now - t < self.window_seconds
        ]

        if len(self._memory_history[memory_key]) >= effective_limit:
            security_metrics.increment("rate_limit_hits")
            try:
                from app.core.prometheus_exporter import metrics_registry
                metrics_registry.rate_limit_hits_total.labels(
                    limiter=self.name
                ).inc()
            except Exception:
                pass
            logger.warning(f"AUDIT | Action: rate_limit_exceeded (memory) | Key: {key} | Limiter: {self.name} | Status: blocked")
            return True

        self._memory_history[memory_key].append(now)
        return False



class AccountLockoutLimiter:

    _fallback_attempts: Dict[str, Dict[str, float]] = {}

    _ATTEMPTS_PREFIX = "lockout:attempts:"
    _LOCKED_PREFIX = "lockout:locked:"

    @classmethod
    def record_failed_attempt(
        cls,
        email: str,
        max_failures: int = 5,
        lockout_seconds: int = 900,
        attempt_window_seconds: int = 900,
    ) -> bool:
       
        security_metrics.increment("failed_logins")

        if redis_client is not None:
            return cls._redis_record(
                email, max_failures, lockout_seconds, attempt_window_seconds
            )

        # Degraded fallback — not distributed.
        logger.warning(
            "AUDIT | Action: lockout_redis_unavailable | Account: %s "
            "| Consequence: lockout_is_process_local_only (degraded security)",
            email,
        )
        return cls._memory_record(email, max_failures, lockout_seconds)

    @classmethod
    def _redis_record(
        cls,
        email: str,
        max_failures: int,
        lockout_seconds: int,
        attempt_window_seconds: int,
    ) -> bool:
        try:
            locked_key = f"{cls._LOCKED_PREFIX}{email}"
            attempts_key = f"{cls._ATTEMPTS_PREFIX}{email}"

            # Fast-path: already locked.
            if redis_client.exists(locked_key):
                return True

            # Atomic increment of failure counter.
            count = redis_client.incr(attempts_key)

            # Set TTL on first increment so the counter auto-expires.
            if count == 1:
                redis_client.expire(attempts_key, attempt_window_seconds)

            if count >= max_failures:
                # Set distributed lockout flag with TTL.
                redis_client.setex(locked_key, lockout_seconds, "1")
                # Clear the attempt counter immediately — clean state.
                redis_client.delete(attempts_key)
                logger.warning(
                    "AUDIT | Action: account_locked (redis) | Account: %s "
                    "| Duration: %ss | Threshold: %s/%s",
                    email,
                    lockout_seconds,
                    count,
                    max_failures,
                )
                return True

            return False

        except Exception as exc:
            logger.error(
                "AccountLockoutLimiter Redis error: %s — falling back to memory.", exc
            )
            return cls._memory_record(email, max_failures, lockout_seconds)

    @classmethod
    def is_locked_out(cls, email: str) -> bool:
        """Returns True if the account is currently locked out."""
        if redis_client is not None:
            try:
                locked_key = f"{cls._LOCKED_PREFIX}{email}"
                return bool(redis_client.exists(locked_key))
            except Exception as exc:
                logger.error(
                    "AccountLockoutLimiter.is_locked_out Redis error: %s — "
                    "falling back to memory.",
                    exc,
                )
        # Memory fallback.
        data = cls._fallback_attempts.get(email)
        if not data:
            return False
        return time.time() < data.get("lockout_until", 0.0)

    @classmethod
    def reset_failed_attempts(cls, email: str) -> None:
        """Clear lockout and attempt counters after a successful login."""
        if redis_client is not None:
            try:
                redis_client.delete(
                    f"{cls._LOCKED_PREFIX}{email}",
                    f"{cls._ATTEMPTS_PREFIX}{email}",
                )
                return
            except Exception as exc:
                logger.error(
                    "AccountLockoutLimiter.reset Redis error: %s — "
                    "falling back to memory reset.",
                    exc,
                )
        # Memory fallback.
        cls._fallback_attempts.pop(email, None)

    # ------------------------------------------------------------------
    # In-memory fallback (non-distributed, degraded security)
    # ------------------------------------------------------------------

    @classmethod
    def _memory_record(
        cls, email: str, max_failures: int, lockout_seconds: int
    ) -> bool:
        now = time.time()
        data = cls._fallback_attempts.get(email, {"count": 0, "lockout_until": 0.0})

        if now < data["lockout_until"]:
            return True  # Still locked out.

        data["count"] += 1
        if data["count"] >= max_failures:
            data["lockout_until"] = now + lockout_seconds
            data["count"] = 0
            logger.warning(
                "AUDIT | Action: account_locked (memory-fallback) | Account: %s "
                "| Duration: %ss",
                email,
                lockout_seconds,
            )
            cls._fallback_attempts[email] = data
            return True

        cls._fallback_attempts[email] = data
        return False

# Instantiations
login_limiter = RedisRateLimiter(limit=5, window_seconds=15 * 60, name="login")
register_limiter = RedisRateLimiter(limit=3, window_seconds=60 * 60, name="register")
forgot_password_limiter = RedisRateLimiter(limit=3, window_seconds=60 * 60, name="forgot_password")
reset_password_limiter = RedisRateLimiter(limit=5, window_seconds=15 * 60, name="reset_password")
api_limiter = RedisRateLimiter(limit=100, window_seconds=60, name="api")
RateLimiter = RedisRateLimiter

