import httpx
from fastapi import APIRouter
from app.core.config import settings

router = APIRouter(prefix="/health", tags=["HEALTH"])

@router.get("")
async def health_check():
    # 1. Postgres check
    try:
        from app.database.session import SessionLocal
        from sqlalchemy import text
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        postgres_status = "online"
    except Exception:
        postgres_status = "offline"

    # 2. Redis check
    try:
        from app.core.rate_limit import redis_client
        if redis_client:
            redis_client.ping()
            redis_status = "online"
        else:
            redis_status = "offline"
    except Exception:
        redis_status = "offline"

    # 3. Qdrant check
    try:
        from qdrant_client import QdrantClient
        client = QdrantClient(
            host=settings.QDRANT_HOST,
            port=settings.QDRANT_PORT,
            check_compatibility=False,
        )
        client.get_collections()
        qdrant_status = "online"
    except Exception:
        qdrant_status = "offline"

    # 4. Ollama check
    try:
        with httpx.Client(timeout=1.0) as client:
            res = client.get(settings.OLLAMA_URL)
            if res.status_code in [200, 404]: # Ollama returns 200 or 404 depending on the exact route check
                ollama_status = "online"
            else:
                ollama_status = "offline"
    except Exception:
        ollama_status = "offline"

    # API Server is running since this endpoint is reachable
    api_status = "online"

    # Overall status
    all_online = all(
        s == "online" 
        for s in [postgres_status, redis_status, qdrant_status, ollama_status]
    )

    return {
        "status": "healthy" if all_online else "degraded",
        "apiServer": api_status,
        "postgres": postgres_status,
        "redis": redis_status,
        "qdrant": qdrant_status,
        "ollama": ollama_status
    }