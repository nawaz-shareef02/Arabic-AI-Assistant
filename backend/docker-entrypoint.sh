#!/bin/sh
set -e

# ==============================================================================
# ArabIQ Backend Production Container Entrypoint
# ==============================================================================

# If RUN_MIGRATIONS is set to "true", run Alembic migrations before starting server
if [ "$RUN_MIGRATIONS" = "true" ]; then
    echo "[Entrypoint] Running database migrations (alembic upgrade head)..."
    alembic upgrade head
    echo "[Entrypoint] Migrations completed successfully."
fi

# Execute passed command (e.g. gunicorn or celery)
exec "$@"
