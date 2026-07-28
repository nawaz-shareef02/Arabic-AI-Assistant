# pyrefly: ignore [missing-import]

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    # --------------------------------------------------
    # Project Configuration
    # --------------------------------------------------

    PROJECT_NAME: str = "ArabIQ"
    API_V1_STR: str = "/api/v1"

    # --------------------------------------------------
    # Database Configuration
    # --------------------------------------------------

    DATABASE_URL: str = "postgresql://postgres:nawaz@localhost:5432/arabiq_platform"

    # --------------------------------------------------
    # Authentication
    # --------------------------------------------------

    SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60

    # --------------------------------------------------
    # Ollama Configuration
    # --------------------------------------------------

    OLLAMA_URL: str

    # --------------------------------------------------
    # LLM Configuration
    # --------------------------------------------------

    LLM_PROVIDER: str = "ollama"
    # deepseek-r1:1.5b (1.1 GB) — ~5x faster than qwen3:8b on CPU.
    # For GPU deployments, switch back to qwen3:8b for higher answer quality.
    LLM_MODEL: str = "deepseek-r1:1.5b"
    # 120s is ample for a 1.5B model; was 300s for the 8B model.
    LLM_TIMEOUT: int = 120
    # Low temperature for factual grounded RAG answers.
    LLM_TEMPERATURE: float = 0.1
    # 512 tokens is sufficient for concise RAG answers; fewer = faster generation.
    LLM_MAX_TOKENS: int = 512

    # Ollama performance tuning
    # "24h" keeps the model pinned in RAM between requests,
    # eliminating the cold-load penalty on every inference.
    OLLAMA_KEEP_ALIVE: str = "24h"
    # 1536 comfortably fits 3 × 600-char chunks + system prompt.
    # Smaller num_ctx = significantly faster CPU prefill.
    OLLAMA_NUM_CTX: int = 1536
    # 0 = let Ollama auto-detect physical core count (optimal for CPU inference).
    OLLAMA_NUM_THREAD: int = 0

    # --------------------------------------------------
    # Redis
    # --------------------------------------------------

    REDIS_URL: str = "redis://localhost:6379/0"

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
    # Upload Configuration
    # --------------------------------------------------

    UPLOAD_DIR: str = "uploads"

    # --------------------------------------------------
    # CORS
    # --------------------------------------------------

    ALLOWED_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]


settings = Settings()