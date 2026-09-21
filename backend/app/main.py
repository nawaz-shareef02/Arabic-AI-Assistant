import sys
import time
import uuid
import logging
from fastapi import FastAPI, Depends, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from app.api.v1.auth import router as auth_router
from app.api.v1.users import router as users_router
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.chat import router as chat_router
from app.api.v1.conversations import router as conversations_router
from app.api.v1.documents import router as documents_router
from app.api.v1.upload import router as upload_router
from app.api.v1.knowledge_base import router as kb_router
from app.api.v1.analytics import router as analytics_router
from app.api.v1.models import router as models_router
from app.api.v1.health import router as health_router
from app.api.v1.roles import router as roles_router
from app.api.v1.organizations import router as organizations_router
from app.api.v1.workspaces import router as workspaces_router
from app.api.v1.audit import router as audit_router
from app.middleware.audit_middleware import AuditMiddleware
from app.core.config_validator import validate_startup_configuration

from app.core.config import settings
from app.core.json_logger import setup_structured_logging

# Activate structured JSON logging as early as possible so all subsequent
# log records (including startup) use the structured formatter.
# safe to call multiple times — replaces root handler once.
setup_structured_logging()

logger = logging.getLogger("app.main")


app = FastAPI(
    title="ArabIQ API Server",
    description="Enterprise Arabic-English AI Knowledge Platform API Services",
    version="1.0.0"
)

# 1. Startup configuration validation & Graceful Shutdown
@app.on_event("startup")
def startup_validation():
    logger.info("Starting ArabIQ API Server configuration validation...")

    # Bypass validation if running in pytest test session
    if "pytest" in sys.modules:
        logger.info("Test environment detected (pytest). Skipping strict startup configuration validation.")
        return

    validate_startup_configuration()

    # Check SECRET_KEY
    if not settings.SECRET_KEY or settings.SECRET_KEY == "CHANGE_TO_A_RANDOM_SECRET" or len(settings.SECRET_KEY) < 32:
        logger.error("CRITICAL CONFIGURATION ERROR: SECRET_KEY is missing, default, or too weak (under 32 chars)!")
        sys.exit(1)

    # Check required config variables
    required_configs = ["DATABASE_URL", "OLLAMA_URL", "REDIS_URL"]
    for config_var in required_configs:
        if not getattr(settings, config_var, None):
            logger.error(f"CRITICAL CONFIGURATION ERROR: Required configuration variable {config_var} is missing!")
            sys.exit(1)

    # Check database connectivity
    try:
        from app.database.session import SessionLocal
        from sqlalchemy import text
        from app.core.rbac_seeder import seed_rbac
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        seed_rbac(db)
        db.close()
        logger.info("Database connectivity check & RBAC seeding passed.")
    except Exception as e:
        logger.critical(f"CRITICAL DATABASE ERROR: Could not connect to the database or seed RBAC: {str(e)}")
        sys.exit(1)

    # Check Redis connectivity
    try:
        from app.core.rate_limit import redis_client
        if redis_client:
            redis_client.ping()
            logger.info("Redis connectivity check passed.")
        else:
            logger.warning("Redis is not available; falling back to in-memory rate limiting.")
    except Exception as e:
        logger.warning(f"Redis connectivity check failed: {str(e)}. Using in-memory fallback.")

    logger.info("Startup configuration validation completed. Beginning heavyweight service pre-warming...")

    # ──────────────────────────────────────────────────────────────────────────
    # PRE-WARM ALL HEAVYWEIGHT SERVICES
    # This ensures no cold-start latency hits real user requests.
    # All services use the singleton pattern — these calls create the shared
    # instances once and verify they are healthy before accepting traffic.
    # ──────────────────────────────────────────────────────────────────────────

    # 1. EmbeddingService + SentenceTransformer (BAAI/bge-m3)
    t0 = time.perf_counter()
    try:
        from app.services.embedding_service import EmbeddingService
        emb = EmbeddingService()
        emb.warmup()  # Runs one dummy inference to heat JIT & tokenizer.
        assert emb.is_loaded(), "STARTUP ASSERTION FAILED: EmbeddingService model is NOT loaded!"
        logger.info(f"✓ EmbeddingService pre-warmed in {(time.perf_counter()-t0)*1000:.0f} ms")
    except Exception as e:
        logger.critical(f"STARTUP FAILURE: EmbeddingService pre-warm failed: {e}")
        sys.exit(1)

    # 2. QdrantService (singleton QdrantClient)
    t1 = time.perf_counter()
    try:
        from app.services.qdrant_service import QdrantService
        qs = QdrantService()
        assert qs.client is not None, "STARTUP ASSERTION FAILED: QdrantService client is None!"
        logger.info(f"✓ QdrantService pre-warmed in {(time.perf_counter()-t1)*1000:.0f} ms")
    except Exception as e:
        logger.critical(f"STARTUP FAILURE: QdrantService pre-warm failed: {e}")
        sys.exit(1)

    # 3. OllamaProvider (singleton + persistent HTTP session + model pre-load)
    t2 = time.perf_counter()
    try:
        from app.services.llm.ollama_provider import OllamaProvider
        ollama = OllamaProvider.get_instance()
        ollama.warmup()  # Sends a 1-token request to load LLM weights into RAM.
        assert ollama._session is not None, "STARTUP ASSERTION FAILED: OllamaProvider HTTP session is None!"
        logger.info(f"✓ OllamaProvider pre-warmed in {(time.perf_counter()-t2)*1000:.0f} ms")
    except Exception as e:
        logger.warning(
            f"OllamaProvider pre-warm failed: {e}. "
            "First user request may experience model-load latency."
        )

    # 4. LLMFactory — verify it returns the cached singleton (init count must stay at 1).
    from app.services.llm import LLMFactory
    LLMFactory.get_provider()  # Ensures provider is cached.

    # ── Final assertions ────────────────────────────────────────────────────
    from app.services.embedding_service import EmbeddingService as _ES
    assert _ES._model is not None, "STARTUP ASSERTION FAILED: SentenceTransformer not loaded!"

    logger.info(
        "\n"
        "┌──────────────────────────────────────────────────┐\n"
        "│       ArabIQ API Server — STARTUP COMPLETE       │\n"
        "├──────────────────────────────────────────────────┤\n"
        "│  ✓ EmbeddingService   — singleton ready          │\n"
        "│  ✓ SentenceTransformer — model loaded            │\n"
        "│  ✓ QdrantService      — singleton ready          │\n"
        "│  ✓ OllamaProvider     — model pre-loaded         │\n"
        "│  ✓ LLMFactory         — provider cached          │\n"
        "│  All startup assertions passed.                  │\n"
        "│  Server is ready to accept traffic. 🚀           │\n"
        "└──────────────────────────────────────────────────┘"
    )

@app.on_event("shutdown")
def shutdown_logging():
    logger.info("Shutting down ArabIQ API Server gracefully.")

# 2. Add Request ID / Correlation ID Middleware
@app.middleware("http")
async def add_request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


# 2b. HTTP Telemetry Middleware — records request count and latency.
# Route template extraction: FastAPI populates request.scope["route"] after
# routing resolves inside call_next. We read it post-call to get the template
# (e.g. "/api/v1/chat/{kb_id}") rather than the raw URL path.
# Labels used: method (bounded), endpoint (route template — bounded by route count),
# status (HTTP status code — bounded set). Never uses user/org/conversation IDs.
@app.middleware("http")
async def http_telemetry_middleware(request: Request, call_next):
    t0 = time.perf_counter()
    response = await call_next(request)
    try:
        from app.core.prometheus_exporter import metrics_registry
        duration = time.perf_counter() - t0
        method = request.method
        status = str(response.status_code)
        # Extract route template to avoid high-cardinality raw URLs.
        route = request.scope.get("route")
        endpoint = getattr(route, "path", None)
        if not endpoint:
            # Fallback: use path prefix (max 50 chars) for unrouted requests.
            raw = request.url.path
            endpoint = raw[:50] if raw else "unknown"
        metrics_registry.http_requests_total.labels(
            method=method, endpoint=endpoint, status=status
        ).inc()
        metrics_registry.http_request_duration_seconds.labels(
            method=method, endpoint=endpoint
        ).observe(duration)
    except Exception:
        # Telemetry failures must NEVER affect the response.
        pass
    return response


# 3. Payload size limiter middleware
@app.middleware("http")
async def limit_request_size_middleware(request: Request, call_next):
    # Set limit: 50MB for upload endpoints, 2MB for other standard JSON APIs
    max_size = 50 * 1024 * 1024 if "upload" in request.url.path else 2 * 1024 * 1024
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_size:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "Request payload too large. Limits: 2MB for standard API, 50MB for uploads."}
                )
        except ValueError:
            pass
    return await call_next(request)

# 4. Enterprise Security Headers Middleware
@app.middleware("http")
async def add_security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path

    # Allow Swagger/ReDoc/OpenAPI to load external resources
    if (
        path.startswith("/docs")
        or path.startswith("/redoc")
        or path.startswith("/openapi.json")
    ):
        return response

    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    # Build CSP connect-src dynamically from configured allowed origins.
    # This ensures no localhost URLs leak into production headers.
    connect_origins = " ".join(settings.ALLOWED_ORIGINS)
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        f"connect-src 'self' {connect_origins};"
    )
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["X-DNS-Prefetch-Control"] = "off"

    # Cache-Control for authenticated pages
    is_public_api = "/auth/login" in path or "/auth/register" in path or "/auth/forgot-password" in path or "/auth/reset-password" in path or "/health" in path or path == "/"
    if not is_public_api and path.startswith("/api/v1/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"

    return response

from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from app.services.llm.ollama_provider import OllamaOverloadedException

@app.exception_handler(OllamaOverloadedException)
async def ollama_overloaded_exception_handler(request: Request, exc: OllamaOverloadedException):
    req_id = getattr(request.state, "request_id", "unknown")
    logger.warning(f"Ollama inference capacity reached [Req ID: {req_id}]: {str(exc)}")
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        headers={"Retry-After": "5"},
        content={
            "detail": "The AI inference engine is currently at peak capacity. Please retry shortly.",
            "request_id": req_id,
        },
    )

@app.exception_handler(SQLAlchemyTimeoutError)
async def pool_timeout_exception_handler(request: Request, exc: SQLAlchemyTimeoutError):
    req_id = getattr(request.state, "request_id", "unknown")
    logger.error(f"Database connection pool exhausted [Req ID: {req_id}]: {str(exc)}")
    try:
        from app.database.session import pool_metrics
        pool_metrics.record_timeout()
    except Exception:
        pass
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        headers={"Retry-After": "5"},
        content={
            "detail": "Database connection pool capacity reached. Please retry in a few seconds.",
            "request_id": req_id,
        },
    )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    req_id = getattr(request.state, "request_id", "unknown")
    logger.exception(f"Unhandled server error [Req ID: {req_id}]: {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={"detail": f"An internal server error occurred. Please contact support. Request ID: {req_id}"}
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    req_id = getattr(request.state, "request_id", "unknown")
    logger.warning(f"Validation error [Req ID: {req_id}]: {exc.errors()}")
    errors = []
    for err in exc.errors():
        loc = " -> ".join(str(x) for x in err.get("loc", []))
        errors.append(f"{loc}: {err.get('msg', 'Invalid value')}")
    return JSONResponse(
        status_code=422,
        content={"detail": f"Validation failed: {'; '.join(errors)}"}
    )

# 6. GZip Compression Middleware
app.add_middleware(GZipMiddleware, minimum_size=1000)

# 7. Trusted Host Middleware — configured from settings, not hardcoded.
# In production set ALLOWED_HOSTS=["your-domain.com"] in environment.
# Do NOT use ["*"] in production.
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=settings.ALLOWED_HOSTS,
)

# 8. CORS Setup (explicit allow-list from settings & enterprise header policy)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-CSRF-Token",
        "Accept",
        "Origin",
        "X-Requested-With",
        "X-Request-ID",
    ],
)

app.add_middleware(AuditMiddleware)

# Include v1 Routers
from app.api.v1.ai_performance import router as ai_performance_router
from app.api.v1.backups import router as backups_router

app.include_router(auth_router, prefix="/api/v1")
app.include_router(users_router, prefix="/api/v1")
app.include_router(dashboard_router, prefix="/api/v1")
app.include_router(chat_router, prefix="/api/v1")
app.include_router(conversations_router, prefix="/api/v1")
app.include_router(documents_router, prefix="/api/v1")
app.include_router(upload_router, prefix="/api/v1")
app.include_router(kb_router, prefix="/api/v1")
app.include_router(analytics_router, prefix="/api/v1")
app.include_router(models_router, prefix="/api/v1")
app.include_router(health_router)
app.include_router(roles_router, prefix="/api/v1")
app.include_router(organizations_router, prefix="/api/v1")
app.include_router(workspaces_router, prefix="/api/v1")
app.include_router(audit_router, prefix="/api/v1")
app.include_router(ai_performance_router, prefix="/api/v1")
app.include_router(backups_router, prefix="/api/v1")

from app.core.prometheus_exporter import get_prometheus_metrics_text, CONTENT_TYPE_LATEST
from fastapi import Response
import hmac

@app.get("/metrics", summary="Prometheus Metrics Endpoint", include_in_schema=False)
def metrics(request: Request):
    """
    Prometheus metrics endpoint.

    Security:
    - When METRICS_TOKEN is set in config, the request must include the header
      X-Metrics-Token: <token>. Comparison uses hmac.compare_digest (constant-time).
    - When METRICS_TOKEN is unset (default), the endpoint is open.
      Deploy behind a network firewall or VPC rule restricting scraper access.
    - The token is never echoed in error responses or logs.
    """
    token = settings.METRICS_TOKEN
    if token:
        provided = request.headers.get("X-Metrics-Token", "")
        # constant-time comparison prevents timing-based token enumeration.
        if not hmac.compare_digest(provided.encode(), token.encode()):
            return Response(
                content="Unauthorized",
                status_code=401,
                media_type="text/plain",
            )
    return Response(content=get_prometheus_metrics_text(), media_type=CONTENT_TYPE_LATEST)


@app.get("/")
def root():
    return {
        "message": "ArabIQ Enterprise AI Assistant Backend Running 🚀"
    }