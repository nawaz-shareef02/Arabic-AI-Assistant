"""
ConfigValidator — Refinement #8: Pre-flight Startup Configuration & Profile Validator.

Validates environment profiles (Development, Testing, Staging, Production)
and checks secret entropy rules without logging credential values.
"""

import os
import logging
from app.core.config import settings

logger = logging.getLogger("app.core.config_validator")


class SecurityProfile:
    DEVELOPMENT = "Development"
    TESTING = "Testing"
    STAGING = "Staging"
    PRODUCTION = "Production"


def validate_startup_configuration() -> str:
    env_name = os.getenv("APP_ENV", "Development").capitalize()
    if env_name not in [SecurityProfile.DEVELOPMENT, SecurityProfile.TESTING, SecurityProfile.STAGING, SecurityProfile.PRODUCTION]:
        env_name = SecurityProfile.DEVELOPMENT

    logger.info(f"SECURITY_CONFIG | Profile: {env_name} | Initializing startup validation...")

    secret_key = settings.SECRET_KEY
    if not secret_key or len(secret_key) < 16:
        msg = f"SECURITY_WARNING | SECRET_KEY is too short or insecure ({len(secret_key) if secret_key else 0} chars)."
        if env_name in [SecurityProfile.STAGING, SecurityProfile.PRODUCTION]:
            raise ValueError(msg)
        logger.warning(msg)

    if env_name in [SecurityProfile.STAGING, SecurityProfile.PRODUCTION]:
        if "secret" in secret_key.lower() or "change" in secret_key.lower():
            raise ValueError("SECURITY_ERROR | Weak or default SECRET_KEY detected in production profile!")

    logger.info(f"SECURITY_CONFIG | Profile: {env_name} | Startup validation PASSED.")
    return env_name
