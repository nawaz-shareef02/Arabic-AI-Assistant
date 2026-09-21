# pyrefly: ignore [missing-import]

from typing import Optional
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    # --------------------------------------------------
    # Project Configuration
    # --------------------------------------------------

    PROJECT_NAME: str = "ArabIQ"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "development"  # "development" | "staging" | "production" | "test"

    # --------------------------------------------------
    # Database Configuration
    # --------------------------------------------------

    # SECURITY: No default credential is provided.
    # DATABASE_URL MUST be injected via environment variable or .env file.
    # Format: postgresql://USER:PASSWORD@HOST:PORT/DBNAME
    DATABASE_URL: str

    # P2-2 Enterprise Database Connection Pool & Concurrency Configuration
    # Initial bounded defaults (to be tuned via production environment variables)
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 5
    DB_POOL_TIMEOUT: int = 10        # Seconds to wait for pool connection before raising TimeoutError
    DB_POOL_RECYCLE: int = 1800      # Recycle connections after 30 mins to avoid stale TCP drops
    DB_POOL_PRE_PING: bool = True    # Validate socket liveness on checkout via SELECT 1
    # Declarative application connection budget target across all worker processes.
    # NOTE: SQLAlchemy QueuePool is process-local; this setting is a capacity planning budget,
    # not a distributed cross-process hard cap. E.g., 6 workers * 10 conns (pool 5 + overflow 5) = 60 conns.
    # Against a default PostgreSQL max_connections=100, the 40-connection difference provides
    # intentional operational headroom / application budget protection for DBA sessions, migrations,
    # autovacuum, backups, and replication (not a PostgreSQL-internal reservation).
    DB_APP_CONNECTION_BUDGET: int = 60

    # --------------------------------------------------
    # Authentication & Transport Security (P2-1)
    # --------------------------------------------------

    # SECURITY: SECRET_KEY must be set in environment. No default.
    # Generate with: python -c "import secrets; print(secrets.token_hex(32))"
    SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60

    # Cookie transport security settings
    AUTH_COOKIE_NAME: str = "auth_token"
    CSRF_COOKIE_NAME: str = "csrf_token"
    AUTH_COOKIE_SECURE: bool = False
    AUTH_COOKIE_SAMESITE: str = "lax"
    AUTH_COOKIE_DOMAIN: Optional[str] = None

    @model_validator(mode="after")
    def validate_cookie_security(self) -> "Settings":
        if self.ENVIRONMENT.lower() == "production" and not self.AUTH_COOKIE_SECURE:
            raise ValueError(
                "CRITICAL SECURITY CONFIGURATION ERROR: AUTH_COOKIE_SECURE must be True when ENVIRONMENT is 'production'."
            )
        if self.AUTH_COOKIE_SAMESITE.lower() == "none" and not self.AUTH_COOKIE_SECURE:
            raise ValueError(
                "CRITICAL SECURITY CONFIGURATION ERROR: SameSite='None' cookies must have AUTH_COOKIE_SECURE=True."
            )
        return self

    # --------------------------------------------------
    # Ollama Configuration
    # --------------------------------------------------

    OLLAMA_URL: str

    # --------------------------------------------------
    # LLM Configuration
    # --------------------------------------------------

    LLM_PROVIDER: str = "ollama"
    # Production baseline model: Qwen3-8B (bilingual Arabic/English reasoning)
    LLM_MODEL: str = "qwen3:8b"
    # Timeout for 8B model inference on CPU/GPU
    LLM_TIMEOUT: int = 180
    # Low temperature for factual grounded RAG answers.
    LLM_TEMPERATURE: float = 0.1
    # 400 tokens is sufficient for concise RAG answers; fewer = faster generation.
    LLM_MAX_TOKENS: int = 400

    # Ollama performance tuning
    # "24h" keeps the model pinned in RAM between requests,
    # eliminating the cold-load penalty on every inference.
    OLLAMA_KEEP_ALIVE: str = "24h"
    # 2048 comfortably fits system prompt + 3 RAG chunks + question.
    OLLAMA_NUM_CTX: int = 2048
    # 0 = let Ollama auto-detect physical core count (optimal for CPU inference).
    OLLAMA_NUM_THREAD: int = 0
    # P2-4 Bounded Inference Concurrency & Admission Control
    # Default is 1 for local CPU inference (Ryzen 7 laptop).
    # NOTE: Aggregate Ollama concurrency across workers = OLLAMA_MAX_CONCURRENCY * number_of_processes.
    OLLAMA_MAX_CONCURRENCY: int = 1
    # Max seconds to wait for an inference slot before backpressure rejection.
    # 0.0 = immediate admission control (fail-fast, prevents worker thread exhaustion).
    OLLAMA_ACQUIRE_TIMEOUT: float = 0.0

    # --------------------------------------------------
    # Redis
    # --------------------------------------------------

    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # --------------------------------------------------
    # Qdrant Configuration
    # --------------------------------------------------

    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333
    QDRANT_COLLECTION: str = "arabiq_documents"

    # --------------------------------------------------
    # Embedding Configuration
    # --------------------------------------------------

    EMBEDDING_MODEL: str = "BAAI/bge-m3"
    EMBEDDING_DEVICE: str = "cpu"
    EMBEDDING_BATCH_SIZE: int = 32

    # --------------------------------------------------
    # Retrieval Configuration
    # --------------------------------------------------

    # 3 retrieved chunks is sufficient for RAG; keeps prompt under num_ctx budget.
    TOP_K_RESULTS: int = 3
    # AI-3 Hard upper bound on retrieved chunks to prevent resource exhaustion (Fix #4).
    RETRIEVAL_MAX_TOP_K: int = 50
    # AI-3 Maximum character length for search queries to prevent tokenizer/PyTorch pressure (Fix #5).
    RETRIEVAL_MAX_QUERY_LENGTH: int = 2000

    # --------------------------------------------------
    # Conversation Configuration (Sprint 11)
    # --------------------------------------------------

    # Maximum estimated tokens from conversation history injected into the prompt.
    # Budget is consumed newest-first; oldest messages are dropped when exceeded.
    # Tune lower for faster prefill; higher for deeper context.
    CONV_HISTORY_TOKEN_BUDGET: int = 800

    # Maximum words in a generated conversation title.
    CONV_TITLE_MAX_WORDS: int = 5

    # --------------------------------------------------
    # Sprint 12 — Hybrid Retrieval Configuration
    # --------------------------------------------------

    # Toggle query expansion (adds synonyms/translations to retrieval query).
    ENABLE_QUERY_EXPANSION: bool = True
    # Toggle retrieval debug logging (chunk-level scores, ranks, metadata).
    ENABLE_RETRIEVAL_DEBUG: bool = False
    # Toggle metadata filtering (language, document type, etc.) during retrieval.
    ENABLE_METADATA_FILTERING: bool = True
    # Toggle re-ranker (NoOp by default; enable when a real reranker is configured).
    ENABLE_RERANKER: bool = False

    # Maximum results from hybrid search (before re-ranking).
    HYBRID_MAX_RESULTS: int = 10
    # Maximum results after re-ranking (fed to the prompt builder).
    RERANK_MAX_RESULTS: int = 5
    # Redis TTL (seconds) for cached query expansions.
    QUERY_EXPANSION_CACHE_TTL: int = 3600
    # Reciprocal Rank Fusion constant (standard default is 60).
    RRF_K: int = 60

    # --------------------------------------------------
    # Upload Configuration
    # --------------------------------------------------

    UPLOAD_DIR: str = "uploads"

    # --------------------------------------------------
    # SMTP / Email & Password Reset Configuration
    # --------------------------------------------------

    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = "noreply@arabiq.sa"
    SMTP_FROM_NAME: str = "ArabIQ Security"
    SMTP_USE_TLS: bool = True

    FRONTEND_URL: str = "http://localhost:3000"
    INVITATION_BASE_URL: Optional[str] = None
    INVITATION_TOKEN_EXPIRE_HOURS: int = 168  # 7 days
    EMAIL_PROVIDER: str = "console"  # "console" | "smtp" | "auto"
    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES: int = 60

    @property
    def resolved_invitation_base_url(self) -> str:
        """Returns configured invitation base URL or fallback to frontend URL."""
        url = self.INVITATION_BASE_URL or self.FRONTEND_URL
        return url.rstrip("/")

    # --------------------------------------------------
    # P1-2 Chat & Streaming Rate Limiting Configuration
    # --------------------------------------------------
    CHAT_RATE_LIMIT_USER_REQ_PER_MINUTE: int = 20
    CHAT_RATE_LIMIT_USER_BURST: int = 5
    CHAT_RATE_LIMIT_ORG_REQ_PER_MINUTE: int = 200
    CHAT_RATE_LIMIT_USER_MAX_CONCURRENT_STREAMS: int = 2
    CHAT_RATE_LIMIT_ORG_MAX_CONCURRENT_STREAMS: int = 20
    CHAT_STREAM_CONCURRENCY_LEASE_SECONDS: int = 120
    CHAT_RATE_LIMIT_FAIL_CLOSED: bool = False

    # --------------------------------------------------
    # P2-3 Observability Configuration
    # --------------------------------------------------
    # Optional token to protect the /metrics Prometheus endpoint.
    # When set, GET /metrics requires: X-Metrics-Token: <value>
    # Comparison is constant-time to prevent timing attacks.
    # If None, /metrics is open — appropriate when protected by network policy
    # (e.g., VPC/firewall restricting scraper access) or in development.
    # SECURITY: Never log this value. Never include it in error responses.
    # Generate with: python -c "import secrets; print(secrets.token_hex(32))"
    METRICS_TOKEN: Optional[str] = None

    # --------------------------------------------------
    # CORS
    # --------------------------------------------------

    ALLOWED_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    # --------------------------------------------------
    # P0-4 Trusted Host Configuration
    # --------------------------------------------------
    # SECURITY: In production, set ALLOWED_HOSTS to your actual domain(s).
    # Example: ALLOWED_HOSTS=["arabiq.example.com"]
    # Development default includes localhost and testserver (pytest).
    # Do NOT use ["*"] in production.
    ALLOWED_HOSTS: list[str] = ["localhost", "127.0.0.1", "testserver"]


settings = Settings()