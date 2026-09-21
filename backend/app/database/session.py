# Database session configuration
import time
import threading
import logging
from typing import Dict, Any, Generator
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool

from app.core.config import settings

logger = logging.getLogger("app.database.session")

# ---------------------------------------------------------------------------
# Engine Initialization with Bounded Enterprise Connection Pool
# ---------------------------------------------------------------------------
_engine_kwargs: Dict[str, Any] = {
    "echo": False,
    "future": True,
}

if settings.DATABASE_URL.startswith("sqlite"):
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    _engine_kwargs.update({
        "pool_size": settings.DB_POOL_SIZE,
        "max_overflow": settings.DB_MAX_OVERFLOW,
        "pool_timeout": settings.DB_POOL_TIMEOUT,
        "pool_recycle": settings.DB_POOL_RECYCLE,
        "pool_pre_ping": settings.DB_POOL_PRE_PING,
    })

engine = create_engine(settings.DATABASE_URL, **_engine_kwargs)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)


# ---------------------------------------------------------------------------
# P2-2 / P2-3 Database Connection Pool Instrumentation & Metric Hooks
# ---------------------------------------------------------------------------
class PoolMetricsTracker:
    """Thread-safe collector for connection pool lifecycle metrics."""

    def __init__(self):
        self._lock = threading.Lock()
        self.checkouts_total: int = 0
        self.checkins_total: int = 0
        self.timeouts_total: int = 0
        self.connections_created: int = 0
        self.connections_closed: int = 0
        self.total_checkout_duration_ms: float = 0.0

    def record_checkout(self):
        with self._lock:
            self.checkouts_total += 1

    def record_checkin(self, duration_ms: float = 0.0):
        with self._lock:
            self.checkins_total += 1
            self.total_checkout_duration_ms += duration_ms

    def record_timeout(self):
        with self._lock:
            self.timeouts_total += 1

    def record_connect(self):
        with self._lock:
            self.connections_created += 1

    def record_close(self):
        with self._lock:
            self.connections_closed += 1


pool_metrics = PoolMetricsTracker()


@event.listens_for(engine, "connect")
def _on_engine_connect(dbapi_connection, connection_record):
    pool_metrics.record_connect()


@event.listens_for(engine, "close")
def _on_engine_close(dbapi_connection, connection_record):
    pool_metrics.record_close()


@event.listens_for(engine, "checkout")
def _on_engine_checkout(dbapi_connection, connection_record, connection_proxy):
    connection_record.info["checkout_start"] = time.perf_counter()
    pool_metrics.record_checkout()
    try:
        from app.core.prometheus_exporter import metrics_registry
        metrics_registry.db_checkouts_total.inc()
    except Exception:
        pass


@event.listens_for(engine, "checkin")
def _on_engine_checkin(dbapi_connection, connection_record):
    start = connection_record.info.get("checkout_start")
    duration_ms = (time.perf_counter() - start) * 1000 if start else 0.0
    pool_metrics.record_checkin(duration_ms)
    try:
        from app.core.prometheus_exporter import metrics_registry
        metrics_registry.db_checkins_total.inc()
    except Exception:
        pass


def get_pool_status() -> Dict[str, Any]:
    """Returns a snapshot of the database connection pool state for monitoring & diagnostics."""
    pool = getattr(engine, "pool", None)
    checkedin = pool.checkedin() if pool and hasattr(pool, "checkedin") else 0
    checkedout = pool.checkedout() if pool and hasattr(pool, "checkedout") else 0
    overflow = pool.overflow() if pool and hasattr(pool, "overflow") else 0
    size = pool.size() if pool and hasattr(pool, "size") else 0

    return {
        "pool_size": size,
        "checkedin": checkedin,
        "checkedout": checkedout,
        "overflow": overflow,
        "active_connections": checkedin + checkedout,
        "checkouts_total": pool_metrics.checkouts_total,
        "checkins_total": pool_metrics.checkins_total,
        "timeouts_total": pool_metrics.timeouts_total,
        "connections_created": pool_metrics.connections_created,
        "connections_closed": pool_metrics.connections_closed,
    }


def reset_engine_pool():
    """Disposes engine pool connection sockets to guarantee process/fork safety."""
    engine.dispose(close=False)


# ---------------------------------------------------------------------------
# Session Generator with Guaranteed Exception Rollback & Cleanup
# ---------------------------------------------------------------------------
def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding an isolated, transaction-safe database session."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        try:
            db.rollback()
        except Exception as rb_exc:
            logger.warning(f"Error rolling back session on exception: {rb_exc}")
        raise
    finally:
        db.close()