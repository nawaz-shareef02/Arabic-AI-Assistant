"""
ChatRateLimitService — Enterprise Distributed Rate Limiting & Concurrency Control (P1-2).

Provides dedicated, atomic, Redis-backed sliding-window rate limiting and
active stream concurrency lease management for expensive AI endpoints (POST /chat and POST /chat/stream).

Architectural Invariants:
1. Multi-tenant isolation: Keys incorporate authenticated {org_id} and {user_id}.
2. Atomicity: Multi-step check-and-increment operations execute via Redis Lua scripts.
3. Stream Concurrency Leases: Active streams acquire a temporary lease with a TTL (dead-man switch)
   and are guaranteed to release via try...finally blocks across all lifecycle completion paths.
4. Safe Fallback: Explicit, configurable degraded behavior when Redis is unavailable.
5. Zero Sensitive Data Logging: No prompts, tokens, or JWTs are recorded in audit logs.
"""

import time
import uuid
import json
import logging
import threading
from typing import Dict, Optional, Tuple, Any
from dataclasses import dataclass

from app.core.config import settings
from app.core.security_metrics import security_metrics
from app.core.rate_limit import redis_client

logger = logging.getLogger("app.services.chat_rate_limit_service")


# ──────────────────────────────────────────────────────────────────────────────
# Redis Lua Scripts (Atomic Execution Across Distributed Workers)
# ──────────────────────────────────────────────────────────────────────────────

# 1. Atomic Sliding-Window Rate Limiter
# KEYS[1] = user_rate_key (zset), KEYS[2] = org_rate_key (zset)
# ARGV[1] = now_timestamp, ARGV[2] = window_seconds, ARGV[3] = user_limit, ARGV[4] = org_limit, ARGV[5] = unique_id
SLIDING_WINDOW_LUA = """
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local user_limit = tonumber(ARGV[3])
local org_limit = tonumber(ARGV[4])
local member = ARGV[5]
local clear_before = now - window

-- 1. Prune expired entries for user
redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, clear_before)
local user_count = redis.call('ZCARD', KEYS[1])

-- 2. Prune expired entries for org
redis.call('ZREMRANGEBYSCORE', KEYS[2], 0, clear_before)
local org_count = redis.call('ZCARD', KEYS[2])

-- 3. Check User Limit
if user_count >= user_limit then
    local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
    local reset_after = window
    if oldest and #oldest >= 2 then
        reset_after = math.max(1, math.ceil(tonumber(oldest[2]) + window - now))
    end
    return {0, 'user_rate_limit_exceeded', user_count, user_limit, reset_after}
end

-- 4. Check Organization Limit (Aggregate Ceiling)
if org_count >= org_limit then
    local oldest = redis.call('ZRANGE', KEYS[2], 0, 0, 'WITHSCORES')
    local reset_after = window
    if oldest and #oldest >= 2 then
        reset_after = math.max(1, math.ceil(tonumber(oldest[2]) + window - now))
    end
    return {0, 'org_rate_limit_exceeded', org_count, org_limit, reset_after}
end

-- 5. Record request in both sorted sets
redis.call('ZADD', KEYS[1], now, member)
redis.call('EXPIRE', KEYS[1], window + 15)

redis.call('ZADD', KEYS[2], now, member)
redis.call('EXPIRE', KEYS[2], window + 15)

local remaining = math.max(0, user_limit - (user_count + 1))
return {1, 'allowed', user_count + 1, user_limit, remaining}
"""

# 2. Atomic Stream Concurrency Acquisition
# KEYS[1] = user_stream_key (string counter), KEYS[2] = org_stream_key (string counter), KEYS[3] = lease_key (string)
# ARGV[1] = max_user_streams, ARGV[2] = max_org_streams, ARGV[3] = lease_ttl_seconds, ARGV[4] = lease_data (json)
ACQUIRE_STREAM_CONCURRENCY_LUA = """
local max_user = tonumber(ARGV[1])
local max_org = tonumber(ARGV[2])
local ttl = tonumber(ARGV[3])
local lease_data = ARGV[4]

local user_active = tonumber(redis.call('GET', KEYS[1]) or '0')
local org_active = tonumber(redis.call('GET', KEYS[2]) or '0')

if user_active >= max_user then
    return {0, 'user_stream_concurrency_exceeded', user_active, max_user}
end

if org_active >= max_org then
    return {0, 'org_stream_concurrency_exceeded', org_active, max_org}
end

redis.call('INCR', KEYS[1])
redis.call('EXPIRE', KEYS[1], ttl)

redis.call('INCR', KEYS[2])
redis.call('EXPIRE', KEYS[2], ttl)

redis.call('SETEX', KEYS[3], ttl, lease_data)

return {1, 'acquired', user_active + 1, max_user}
"""

# 3. Atomic Stream Concurrency Release
# KEYS[1] = user_stream_key, KEYS[2] = org_stream_key, KEYS[3] = lease_key
RELEASE_STREAM_CONCURRENCY_LUA = """
local lease_exists = redis.call('EXISTS', KEYS[3])
if lease_exists == 1 then
    redis.call('DEL', KEYS[3])

    local user_active = tonumber(redis.call('GET', KEYS[1]) or '0')
    if user_active > 0 then
        redis.call('DECR', KEYS[1])
    end

    local org_active = tonumber(redis.call('GET', KEYS[2]) or '0')
    if org_active > 0 then
        redis.call('DECR', KEYS[2])
    end
    return 1
end
return 0
"""


@dataclass
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int
    reset_time: int
    lease_id: Optional[str] = None
    reason: Optional[str] = None
    detail: Optional[str] = None

    @property
    def headers(self) -> Dict[str, str]:
        hdrs = {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(max(0, self.remaining)),
            "X-RateLimit-Reset": str(self.reset_time),
        }
        if not self.allowed and self.retry_after > 0:
            hdrs["Retry-After"] = str(self.retry_after)
        return hdrs


class ChatRateLimitService:
    """
    Dedicated rate limiting and concurrency management service for AI chat & streaming.
    """
    _mem_lock = threading.Lock()
    _mem_user_history: Dict[str, list] = {}
    _mem_org_history: Dict[str, list] = {}
    _mem_user_streams: Dict[str, int] = {}
    _mem_org_streams: Dict[str, int] = {}
    _mem_leases: Dict[str, dict] = {}

    def __init__(
        self,
        user_req_limit: Optional[int] = None,
        org_req_limit: Optional[int] = None,
        user_max_streams: Optional[int] = None,
        org_max_streams: Optional[int] = None,
        window_seconds: int = 60,
        lease_ttl_seconds: Optional[int] = None,
        fail_closed: Optional[bool] = None,
        client: Optional[Any] = None,
    ):
        self.user_req_limit = user_req_limit or settings.CHAT_RATE_LIMIT_USER_REQ_PER_MINUTE
        self.org_req_limit = org_req_limit or settings.CHAT_RATE_LIMIT_ORG_REQ_PER_MINUTE
        self.user_max_streams = user_max_streams or settings.CHAT_RATE_LIMIT_USER_MAX_CONCURRENT_STREAMS
        self.org_max_streams = org_max_streams or settings.CHAT_RATE_LIMIT_ORG_MAX_CONCURRENT_STREAMS
        self.window_seconds = window_seconds
        self.lease_ttl = lease_ttl_seconds or settings.CHAT_STREAM_CONCURRENCY_LEASE_SECONDS
        self.fail_closed = fail_closed if fail_closed is not None else settings.CHAT_RATE_LIMIT_FAIL_CLOSED
        self._redis = client if client is not None else redis_client

    def _get_client(self):
        # Allow dynamic patching of redis_client or instance client
        return self._redis if self._redis is not None else redis_client

    # ──────────────────────────────────────────────────────────────────────────
    # Request Rate Limiting (POST /chat and POST /chat/stream)
    # ──────────────────────────────────────────────────────────────────────────

    def check_chat_rate_limit(self, user_id: int, org_id: int) -> RateLimitResult:
        """
        Evaluates sliding-window request limits for a user and their organization.
        Returns a RateLimitResult containing standard rate-limit headers.
        """
        now = time.time()
        now_ts = int(now)
        unique_member = f"{now}:{uuid.uuid4().hex[:8]}"
        user_key = f"ratelimit:chat:user:{org_id}:{user_id}"
        org_key = f"ratelimit:chat:org:{org_id}"

        client = self._get_client()
        if client is not None:
            try:
                # Execute atomic Lua script
                res = client.eval(
                    SLIDING_WINDOW_LUA,
                    2,
                    user_key,
                    org_key,
                    str(now),
                    str(self.window_seconds),
                    str(self.user_req_limit),
                    str(self.org_req_limit),
                    unique_member,
                )
                allowed_flag = int(res[0])
                raw_reason = res[1]
                reason = raw_reason.decode("utf-8") if isinstance(raw_reason, bytes) else str(raw_reason)

                if allowed_flag == 1:
                    remaining = int(res[4])
                    return RateLimitResult(
                        allowed=True,
                        limit=self.user_req_limit,
                        remaining=remaining,
                        retry_after=0,
                        reset_time=now_ts + self.window_seconds,
                    )
                else:
                    retry_after = int(res[4])
                    security_metrics.increment("rate_limit_hits")
                    logger.warning(
                        "AUDIT_CHAT | Action: chat_rate_limit_exceeded | UserID: %s | OrgID: %s "
                        "| Reason: %s | Limit: %s | RetryAfter: %ss | Status: blocked",
                        user_id,
                        org_id,
                        reason,
                        self.user_req_limit if "user" in reason else self.org_req_limit,
                        retry_after,
                    )
                    return RateLimitResult(
                        allowed=False,
                        limit=self.user_req_limit,
                        remaining=0,
                        retry_after=retry_after,
                        reset_time=now_ts + retry_after,
                        reason=reason,
                        detail="Too many AI requests. Please retry later.",
                    )

            except Exception as exc:
                logger.error(
                    "AUDIT_CHAT | Action: rate_limit_redis_error | Detail: %s | Falling back.",
                    exc,
                )
                if self.fail_closed:
                    return RateLimitResult(
                        allowed=False,
                        limit=self.user_req_limit,
                        remaining=0,
                        retry_after=self.window_seconds,
                        reset_time=now_ts + self.window_seconds,
                        reason="redis_unavailable_fail_closed",
                        detail="AI services are temporarily rate-limited due to system maintenance.",
                    )

        # In-memory fallback (per-worker degraded mode)
        return self._memory_check_rate_limit(user_id, org_id, now)

    # ──────────────────────────────────────────────────────────────────────────
    # Active Stream Concurrency Management (POST /chat/stream)
    # ──────────────────────────────────────────────────────────────────────────

    def check_and_acquire_stream_slot(self, user_id: int, org_id: int) -> RateLimitResult:
        """
        Atomically checks sliding-window request limit AND acquires a concurrent streaming lease.
        Both user concurrency and organization concurrency limits are enforced.
        """
        # Step 1: Enforce request rate limit first
        rate_res = self.check_chat_rate_limit(user_id, org_id)
        if not rate_res.allowed:
            return rate_res

        now = time.time()
        now_ts = int(now)
        lease_id = str(uuid.uuid4())
        user_stream_key = f"ratelimit:chat:streams:user:{org_id}:{user_id}"
        org_stream_key = f"ratelimit:chat:streams:org:{org_id}"
        lease_key = f"ratelimit:chat:lease:{lease_id}"

        lease_payload = json.dumps({
            "user_id": user_id,
            "org_id": org_id,
            "acquired_at": now,
        })

        client = self._get_client()
        if client is not None:
            try:
                res = client.eval(
                    ACQUIRE_STREAM_CONCURRENCY_LUA,
                    3,
                    user_stream_key,
                    org_stream_key,
                    lease_key,
                    str(self.user_max_streams),
                    str(self.org_max_streams),
                    str(self.lease_ttl),
                    lease_payload,
                )
                acquired_flag = int(res[0])
                raw_reason = res[1]
                reason = raw_reason.decode("utf-8") if isinstance(raw_reason, bytes) else str(raw_reason)

                if acquired_flag == 1:
                    rate_res.lease_id = lease_id
                    return rate_res
                else:
                    security_metrics.increment("rate_limit_hits")
                    logger.warning(
                        "AUDIT_CHAT | Action: stream_concurrency_exceeded | UserID: %s | OrgID: %s "
                        "| Reason: %s | Max: %s | Status: blocked",
                        user_id,
                        org_id,
                        reason,
                        self.user_max_streams if "user" in reason else self.org_max_streams,
                    )
                    return RateLimitResult(
                        allowed=False,
                        limit=self.user_max_streams,
                        remaining=0,
                        retry_after=5,
                        reset_time=now_ts + 5,
                        reason=reason,
                        detail="Active AI streaming limit reached. Please wait for previous stream to complete.",
                    )
            except Exception as exc:
                logger.error(
                    "AUDIT_CHAT | Action: stream_concurrency_redis_error | Detail: %s",
                    exc,
                )
                if self.fail_closed:
                    return RateLimitResult(
                        allowed=False,
                        limit=self.user_max_streams,
                        remaining=0,
                        retry_after=10,
                        reset_time=now_ts + 10,
                        reason="redis_unavailable_fail_closed",
                        detail="AI streaming is temporarily unavailable.",
                    )

        # In-memory fallback
        return self._memory_acquire_stream_slot(user_id, org_id, rate_res, lease_id, now)

    def release_stream_slot(self, lease_id: Optional[str], user_id: int, org_id: int) -> bool:
        """
        Releases an active streaming lease, atomically decrementing concurrency counters.
        Safe to call multiple times (idempotent).
        """
        if not lease_id:
            return False

        user_stream_key = f"ratelimit:chat:streams:user:{org_id}:{user_id}"
        org_stream_key = f"ratelimit:chat:streams:org:{org_id}"
        lease_key = f"ratelimit:chat:lease:{lease_id}"

        client = self._get_client()
        if client is not None:
            try:
                res = client.eval(
                    RELEASE_STREAM_CONCURRENCY_LUA,
                    3,
                    user_stream_key,
                    org_stream_key,
                    lease_key,
                )
                return int(res) == 1
            except Exception as exc:
                logger.error("AUDIT_CHAT | Action: stream_release_redis_error | Detail: %s", exc)

        # In-memory fallback release
        with self._mem_lock:
            if lease_id in self._mem_leases:
                del self._mem_leases[lease_id]
                u_key = f"{org_id}:{user_id}"
                o_key = str(org_id)
                self._mem_user_streams[u_key] = max(0, self._mem_user_streams.get(u_key, 0) - 1)
                self._mem_org_streams[o_key] = max(0, self._mem_org_streams.get(o_key, 0) - 1)
                return True
        return False

    # ──────────────────────────────────────────────────────────────────────────
    # In-Memory Degraded Fallback Logic (Thread-Safe)
    # ──────────────────────────────────────────────────────────────────────────

    def _memory_check_rate_limit(self, user_id: int, org_id: int, now: float) -> RateLimitResult:
        now_ts = int(now)
        u_key = f"{org_id}:{user_id}"
        o_key = str(org_id)
        clear_before = now - self.window_seconds

        with self._mem_lock:
            # User check
            u_history = self._mem_user_history.setdefault(u_key, [])
            self._mem_user_history[u_key] = [t for t in u_history if t > clear_before]
            if len(self._mem_user_history[u_key]) >= self.user_req_limit:
                security_metrics.increment("rate_limit_hits")
                oldest = self._mem_user_history[u_key][0]
                retry_after = max(1, int(oldest + self.window_seconds - now))
                return RateLimitResult(
                    allowed=False,
                    limit=self.user_req_limit,
                    remaining=0,
                    retry_after=retry_after,
                    reset_time=now_ts + retry_after,
                    reason="user_rate_limit_exceeded (memory)",
                    detail="Too many AI requests. Please retry later.",
                )

            # Org check
            o_history = self._mem_org_history.setdefault(o_key, [])
            self._mem_org_history[o_key] = [t for t in o_history if t > clear_before]
            if len(self._mem_org_history[o_key]) >= self.org_req_limit:
                security_metrics.increment("rate_limit_hits")
                oldest = self._mem_org_history[o_key][0]
                retry_after = max(1, int(oldest + self.window_seconds - now))
                return RateLimitResult(
                    allowed=False,
                    limit=self.user_req_limit,
                    remaining=0,
                    retry_after=retry_after,
                    reset_time=now_ts + retry_after,
                    reason="org_rate_limit_exceeded (memory)",
                    detail="Too many AI requests. Please retry later.",
                )

            # Record
            self._mem_user_history[u_key].append(now)
            self._mem_org_history[o_key].append(now)
            remaining = max(0, self.user_req_limit - len(self._mem_user_history[u_key]))

            return RateLimitResult(
                allowed=True,
                limit=self.user_req_limit,
                remaining=remaining,
                retry_after=0,
                reset_time=now_ts + self.window_seconds,
            )

    def _memory_acquire_stream_slot(
        self, user_id: int, org_id: int, rate_res: RateLimitResult, lease_id: str, now: float
    ) -> RateLimitResult:
        now_ts = int(now)
        u_key = f"{org_id}:{user_id}"
        o_key = str(org_id)

        with self._mem_lock:
            # Clean expired memory leases
            expired_leases = [
                lid for lid, meta in self._mem_leases.items()
                if now - meta["acquired_at"] > self.lease_ttl
            ]
            for lid in expired_leases:
                meta = self._mem_leases.pop(lid, None)
                if meta:
                    uk = f"{meta['org_id']}:{meta['user_id']}"
                    ok = str(meta['org_id'])
                    self._mem_user_streams[uk] = max(0, self._mem_user_streams.get(uk, 0) - 1)
                    self._mem_org_streams[ok] = max(0, self._mem_org_streams.get(ok, 0) - 1)

            u_active = self._mem_user_streams.get(u_key, 0)
            if u_active >= self.user_max_streams:
                security_metrics.increment("rate_limit_hits")
                return RateLimitResult(
                    allowed=False,
                    limit=self.user_max_streams,
                    remaining=0,
                    retry_after=5,
                    reset_time=now_ts + 5,
                    reason="user_stream_concurrency_exceeded (memory)",
                    detail="Active AI streaming limit reached. Please wait for previous stream to complete.",
                )

            o_active = self._mem_org_streams.get(o_key, 0)
            if o_active >= self.org_max_streams:
                security_metrics.increment("rate_limit_hits")
                return RateLimitResult(
                    allowed=False,
                    limit=self.user_max_streams,
                    remaining=0,
                    retry_after=5,
                    reset_time=now_ts + 5,
                    reason="org_stream_concurrency_exceeded (memory)",
                    detail="Active AI streaming limit reached. Please wait for previous stream to complete.",
                )

            self._mem_user_streams[u_key] = u_active + 1
            self._mem_org_streams[o_key] = o_active + 1
            self._mem_leases[lease_id] = {
                "user_id": user_id,
                "org_id": org_id,
                "acquired_at": now,
            }
            rate_res.lease_id = lease_id
            return rate_res

    @classmethod
    def reset_memory_state(cls):
        """Utility for test suites to reset in-memory state cleanly."""
        with cls._mem_lock:
            cls._mem_user_history.clear()
            cls._mem_org_history.clear()
            cls._mem_user_streams.clear()
            cls._mem_org_streams.clear()
            cls._mem_leases.clear()

    @classmethod
    def reset_all_state(cls):
        """Utility for test suites to reset both Redis and in-memory rate limiting state."""
        cls.reset_memory_state()
        if redis_client is not None:
            try:
                keys = redis_client.keys("ratelimit:chat:*")
                if keys:
                    redis_client.delete(*keys)
            except Exception:
                pass
