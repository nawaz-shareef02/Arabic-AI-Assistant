"""
JSONLogger — Refinement #11: Enterprise Structured JSON Log Formatter.

Formats log events into structured JSON including timestamp, level, service, module,
request_id, correlation_id, org_id, workspace_id, user_id, duration_ms, and status_code.
"""

import json
import logging
import datetime
from typing import Dict, Any


class StructuredJSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_data: Dict[str, Any] = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "level": record.levelname,
            "service": "arabiq-backend",
            "module": record.module,
            "function": record.funcName,
            "message": record.getMessage(),
        }

        # Extra attributes attached via Logger.info(..., extra={...})
        for key in ["request_id", "correlation_id", "org_id", "workspace_id", "user_id", "session_id", "duration_ms", "status_code"]:
            if hasattr(record, key):
                log_data[key] = getattr(record, key)

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data)


def setup_structured_logging():
    handler = logging.StreamHandler()
    handler.setFormatter(StructuredJSONFormatter())
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    # Avoid duplicate handlers
    root_logger.handlers = [handler]
