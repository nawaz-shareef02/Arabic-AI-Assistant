import sys
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
from app.api.v1.documents import router as documents_router
from app.api.v1.upload import router as upload_router
from app.api.v1.knowledge_base import router as kb_router
from app.api.v1.analytics import router as analytics_router
from app.api.v1.models import router as models_router
from app.api.v1.health import router as health_router

from app.core.config import settings

logger = logging.getLogger("app.main")
logging.basicConfig(level=logging.INFO)

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
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        logger.info("Database connectivity check passed.")
    except Exception as e:
        logger.critical(f"CRITICAL DATABASE ERROR: Could not connect to the database: {str(e)}")
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

    logger.info("Startup configuration validation completed successfully. API server is ready.")

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
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self' http://localhost:8000 http://localhost:3000 http://127.0.0.1:3000;"
    )
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["X-DNS-Prefetch-Control"] = "off"

    # Cache-Control for authenticated pages
    is_public_api = "/auth/login" in path or "/auth/register" in path or "/auth/forgot-password" in path or "/health" in path or path == "/"
    if not is_public_api and path.startswith("/api/v1/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"

    return response

# 5. Global Exception Handlers
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

# 7. Trusted Host Middleware
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["localhost", "127.0.0.1", "testserver"]
)

# 8. CORS Setup (using allow-list from settings)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include v1 Routers
app.include_router(auth_router, prefix="/api/v1")
app.include_router(users_router, prefix="/api/v1")
app.include_router(dashboard_router, prefix="/api/v1")
app.include_router(chat_router, prefix="/api/v1")
app.include_router(documents_router, prefix="/api/v1")
app.include_router(upload_router, prefix="/api/v1")
app.include_router(kb_router, prefix="/api/v1")
app.include_router(analytics_router, prefix="/api/v1")
app.include_router(models_router, prefix="/api/v1")
app.include_router(health_router, prefix="/api/v1")

@app.get("/")
def root():
    return {
        "message": "ArabIQ Enterprise AI Assistant Backend Running 🚀"
    }