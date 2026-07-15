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
    LLM_MODEL: str = "qwen3:8b"
    LLM_TIMEOUT: int = 300
    LLM_TEMPERATURE: float = 0.2
    LLM_MAX_TOKENS: int = 2048

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

    TOP_K_RESULTS: int = 5

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