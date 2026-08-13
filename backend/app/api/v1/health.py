"""
Health API Router — Refinement #8: Three-State Kubernetes Probes (/health, /ready, /live).

Health States:
- Healthy: All dependencies online
- Degraded: Auxiliary services (Redis / Ollama) offline but core DB online
- Unhealthy: Core Database offline
"""

import httpx
from fastapi import APIRouter, Response, status
from app.core.config import settings

router = APIRouter(prefix="", tags=["HEALTH"])


@router.get("/health", summary="Aggregated Three-State Health Check")
async def health_check():
    postgres_status = _check_postgres()
    redis_status = _check_redis()
    qdrant_status = _check_qdrant()
    ollama_status = _check_ollama()

    # Three-state evaluation logic (Refinement #8)
    if postgres_status == "online" and redis_status == "online" and qdrant_status == "online" and ollama_status == "online":
        health_state = "Healthy"
    elif postgres_status == "online":
        health_state = "Degraded"
    else:
        health_state = "Unhealthy"

    return {
        "status": health_state,
        "apiServer": "online",
        "postgres": postgres_status,
        "redis": redis_status,
        "qdrant": qdrant_status,
        "ollama": ollama_status,
    }


@router.get("/ready", summary="Kubernetes Readiness Probe")
async def readiness_probe(response: Response):
    """Kubernetes readiness probe. Returns HTTP 200 for Healthy/Degraded, HTTP 503 for Unhealthy."""
    postgres_status = _check_postgres()
    redis_status = _check_redis()
    qdrant_status = _check_qdrant()

    if postgres_status != "online":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"ready": False, "reason": "PostgreSQL database offline", "status": "Unhealthy"}

    is_degraded = redis_status != "online" or qdrant_status != "online"
    return {
        "ready": True,
        "status": "Degraded" if is_degraded else "Healthy",
        "postgres": postgres_status,
        "redis": redis_status,
        "qdrant": qdrant_status,
    }


@router.get("/live", summary="Kubernetes Liveness Probe")
async def liveness_probe():
    """Kubernetes liveness probe. Indicates process is running."""
    return {"alive": True, "status": "Healthy"}


def _check_postgres() -> str:
    try:
        from app.database.session import SessionLocal
        from sqlalchemy import text
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        return "online"
    except Exception:
        return "offline"


def _check_redis() -> str:
    try:
        from app.core.rate_limit import redis_client
        if redis_client:
            redis_client.ping()
            return "online"
        return "offline"
    except Exception:
        return "offline"


def _check_qdrant() -> str:
    try:
        from qdrant_client import QdrantClient
        client = QdrantClient(
            host=settings.QDRANT_HOST,
            port=settings.QDRANT_PORT,
            check_compatibility=False,
        )
        client.get_collections()
        return "online"
    except Exception:
        return "offline"


def _check_ollama() -> str:
    try:
        with httpx.Client(timeout=1.0) as client:
            res = client.get(settings.OLLAMA_URL)
            if res.status_code in [200, 404]:
                return "online"
            return "offline"
    except Exception:
        return "offline"