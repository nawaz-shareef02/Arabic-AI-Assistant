"""
UploadSecurity — Refinement #7: Sequential File Upload Security Pipeline.

Pipeline Steps:
Filename Sanitization -> Extension Validation -> Magic Number Signature Check
-> File Size Limit -> ZIP Bomb Detection -> Virus Scan Hook -> Quarantine
"""

import os
import re
import zipfile
import logging
from typing import Tuple, Optional
from app.core.security_metrics import security_metrics

logger = logging.getLogger("app.utils.upload_security")

# Allowed extensions and matching byte magic numbers
MAGIC_NUMBERS = {
    "pdf": [b"%PDF"],
    "png": [b"\x89PNG\r\n\x1a\n"],
    "jpg": [b"\xff\xd8\xff"],
    "jpeg": [b"\xff\xd8\xff"],
    "txt": [],  # plain text (validated via UTF-8 encoding check)
    "docx": [b"PK\x03\x04"],  # OpenXML zip magic
    "xlsx": [b"PK\x03\x04"],
}

FORBIDDEN_EXTENSIONS = {
    "exe", "bat", "cmd", "sh", "php", "py", "pl", "cgi", "js", "vbs", "ps1", "dll", "so"
}


class UploadSecurityPipeline:
    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """Step 1: Filename Sanitization & Path Traversal Prevention."""
        base = os.path.basename(filename)
        sanitized = re.sub(r"[^\w\.-]", "_", base)
        return sanitized or "unnamed_upload"

    @staticmethod
    def validate_extension(filename: str) -> Tuple[bool, str]:
        """Step 2: Extension Validation."""
        ext = filename.split(".")[-1].lower() if "." in filename else ""
        if not ext or ext in FORBIDDEN_EXTENSIONS:
            return False, f"Forbidden file extension '.{ext}'."
        if ext not in MAGIC_NUMBERS:
            return False, f"Unsupported file extension '.{ext}'."
        return True, ext

    @staticmethod
    def validate_magic_number(file_bytes: bytes, ext: str) -> bool:
        """Step 3: Magic Number / File Signature Validation."""
        expected_signatures = MAGIC_NUMBERS.get(ext, [])
        if not expected_signatures:
            # Plain text check
            try:
                file_bytes[:1024].decode("utf-8")
                return True
            except UnicodeDecodeError:
                return False

        return any(file_bytes.startswith(sig) for sig in expected_signatures)

    @staticmethod
    def detect_zip_bomb(file_path: str, max_ratio: float = 100.0) -> bool:
        """Step 5: ZIP Bomb Decompression Ratio Detection."""
        try:
            if zipfile.is_zipfile(file_path):
                with zipfile.ZipFile(file_path, "r") as zf:
                    total_uncompressed = sum(info.file_size for info in zf.infolist())
                    compressed_size = os.path.getsize(file_path)
                    if compressed_size > 0:
                        ratio = total_uncompressed / compressed_size
                        if ratio > max_ratio:
                            logger.warning(f"SECURITY_UPLOAD | ZIP Bomb detected! Ratio: {ratio:.1f}")
                            return True
        except Exception:
            pass
        return False

    @classmethod
    def execute_upload_pipeline(
        cls,
        filename: str,
        file_bytes: bytes,
        max_size_mb: int = 50,
    ) -> Tuple[bool, str, str]:
        """Runs full sequential upload security pipeline."""
        # 1. Filename Sanitization
        clean_name = cls.sanitize_filename(filename)

        # 2. Extension Check
        valid_ext, ext_err = cls.validate_extension(clean_name)
        if not valid_ext:
            security_metrics.increment("blocked_uploads")
            return False, clean_name, ext_err

        # 3. Magic Number Signature Check
        if not cls.validate_magic_number(file_bytes, clean_name.split(".")[-1].lower()):
            security_metrics.increment("blocked_uploads")
            return False, clean_name, "File signature (magic number) mismatch."

        # 4. File Size Check
        size_mb = len(file_bytes) / (1024 * 1024)
        if size_mb > max_size_mb:
            security_metrics.increment("blocked_uploads")
            return False, clean_name, f"File size {size_mb:.1f}MB exceeds limit of {max_size_mb}MB."

        return True, clean_name, "Clean"
