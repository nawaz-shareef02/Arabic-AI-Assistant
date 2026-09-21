"""
StorageService — P0-7 Hardened File Upload Validation.

P0-7 Security Changes (audit 2026-08-20)
-----------------------------------------
1. Magic-byte (file signature) validation replaces client-trust of MIME type.
   The file's actual binary content is inspected, not just the Content-Type header.
2. Cross-validates: extension ↔ declared MIME ↔ detected MIME signatures.
3. Fixed the over-broad double-extension check that rejected valid filenames
   like report.2026.pdf or my.document.docx.
   Only genuinely dangerous polyglot extension patterns are now rejected.
4. python-magic-bin is NOT required: signatures are validated using a
   built-in byte-pattern dictionary to avoid a C-library dependency on Windows.
"""

import os
import re
import uuid as py_uuid
from pathlib import Path
from fastapi import UploadFile, HTTPException, status
from app.core.config import settings

import logging

logger = logging.getLogger("app.services.storage_service")

# ---------------------------------------------------------------------------
# Magic-byte signatures for each allowed file type.
# Format: {extension: [list of (byte_offset, magic_bytes_hex_prefix)]}
# A file must match AT LEAST ONE entry for its extension to pass.
# ---------------------------------------------------------------------------
MAGIC_SIGNATURES: dict[str, list[tuple[int, bytes]]] = {
    ".pdf": [
        (0, b"%PDF"),                   # Standard PDF header
    ],
    ".docx": [
        (0, b"PK\x03\x04"),            # ZIP container (OOXML base format)
    ],
    ".txt": [
        (0, b""),                       # Any content (text files have no magic bytes)
    ],
    ".md": [
        (0, b""),                       # Any content
    ],
    ".markdown": [
        (0, b""),                       # Any content
    ],
}

# Dangerous secondary extensions that indicate polyglot/double-extension attacks.
# e.g. malware.pdf.exe, invoice.docx.js — the LAST two extensions matter.
DANGEROUS_SECONDARY_EXTENSIONS: frozenset[str] = frozenset({
    ".exe", ".sh", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".php",
    ".py", ".rb", ".pl", ".jar", ".war", ".dll", ".so", ".dylib",
    ".scr", ".com", ".pif", ".application", ".gadget", ".msi",
    ".htaccess", ".asp", ".aspx", ".jsp", ".cgi",
})

# Maximum bytes to read for magic-byte inspection (first 16 bytes is sufficient).
_MAGIC_READ_BYTES = 16


class StorageService:
    ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".markdown"}

    ALLOWED_MIME_TYPES = {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain",
        "text/markdown",
        "text/x-markdown",
        # application/octet-stream is allowed only for text-type extensions
        # after magic-byte validation passes.
        "application/octet-stream",
    }

    # Map from extension → expected declared MIME types.
    # Used for cross-validation between client-sent MIME and extension.
    _EXT_TO_EXPECTED_MIMES: dict[str, frozenset[str]] = {
        ".pdf": frozenset({"application/pdf"}),
        ".docx": frozenset({
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/octet-stream",
        }),
        ".txt": frozenset({"text/plain", "application/octet-stream"}),
        ".md": frozenset({"text/plain", "text/markdown", "text/x-markdown", "application/octet-stream"}),
        ".markdown": frozenset({"text/plain", "text/markdown", "text/x-markdown", "application/octet-stream"}),
    }

    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB in bytes

    @staticmethod
    def secure_filename(filename: str) -> str:
        import unicodedata
        # Normalize Unicode filenames to decompose characters (NFKD)
        name = unicodedata.normalize("NFKD", filename)
        # Strip directory traversal paths
        name = Path(name).name
        # Keep only alphanumeric, dots, underscores, dashes
        name = re.sub(r"[^a-zA-Z0-9._-]", "_", name)
        # Avoid hidden/dot files
        name = name.lstrip(".")

        # Enforce filename length limit
        if len(name) > 255:
            stem = Path(name).stem
            suffix = Path(name).suffix
            name = stem[: 255 - len(suffix)] + suffix

        if not name:
            name = "unnamed_file"
        return name

    @staticmethod
    def _check_dangerous_double_extension(filename: str) -> bool:
        """
        Returns True if the filename has a DANGEROUS double-extension pattern.

        Safe: report.2026.pdf, my.document.docx, chapter.1.txt
        Dangerous: invoice.pdf.exe, invoice.exe.pdf, resume.docx.js, payload.txt.ps1

        We check whether any extension component matches known dangerous executable/script extensions.
        """
        parts = Path(filename).suffixes  # e.g. ['.2026', '.pdf'] or ['.pdf', '.exe']
        if len(parts) < 2:
            return False
        return any(suffix.lower() in DANGEROUS_SECONDARY_EXTENSIONS for suffix in parts)

    @staticmethod
    def _validate_magic_bytes(header: bytes, ext: str) -> bool:
        """
        Validate that the file's leading bytes match known signatures for the extension.

        For text-based formats (.txt, .md, .markdown) any content is accepted
        since plain text has no universal magic bytes.

        Returns True if the magic bytes are consistent with the extension.
        """
        signatures = MAGIC_SIGNATURES.get(ext, [])
        if not signatures:
            # Unknown extension — already blocked upstream by extension check.
            return False

        for offset, magic in signatures:
            if magic == b"":
                # Text files — no magic bytes to check.
                return True
            if len(header) >= offset + len(magic):
                if header[offset: offset + len(magic)] == magic:
                    return True

        return False

    async def validate_file(self, file: UploadFile) -> int:
        """
        Comprehensive file validation: extension, MIME cross-check, size, and magic bytes.

        Raises HTTPException on any validation failure.
        Returns the file size in bytes on success.
        """
        filename = file.filename or ""

        # 1. Reject hidden files (dot-files).
        if filename.startswith("."):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Hidden files are not allowed.",
            )

        # 2. Reject dangerous double-extension polyglot patterns.
        #    report.2026.pdf is SAFE; invoice.pdf.exe is DANGEROUS.
        if self._check_dangerous_double_extension(filename):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Dangerous double file extension pattern detected.",
            )

        ext = Path(filename).suffix.lower()

        # 3. Validate extension is in the allow-list.
        if ext not in self.ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported file extension '{ext}'.",
            )

        # 4. Validate declared MIME type is expected for this extension.
        mime = file.content_type or ""
        expected_mimes = self._EXT_TO_EXPECTED_MIMES.get(ext, frozenset())
        if mime not in expected_mimes:
            logger.warning(
                "AUDIT | Action: upload_mime_mismatch | File: %s | Ext: %s "
                "| DeclaredMIME: %s | Expected: %s",
                filename,
                ext,
                mime,
                expected_mimes,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"MIME type '{mime}' is inconsistent with extension '{ext}'.",
            )

        # 5. Read file size.
        if file.size is not None:
            size = file.size
        else:
            file.file.seek(0, 2)
            size = file.file.tell()
            file.file.seek(0)

        if size > self.MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"File exceeds maximum upload size of {self.MAX_FILE_SIZE // (1024 * 1024)} MB.",
            )
        if size == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Empty file uploaded.",
            )

        # 6. P0-7: Magic-byte (file signature) validation.
        #    Read leading bytes and verify against known file signatures.
        #    This catches renamed executables (e.g. malware.pdf that is actually an EXE).
        header = await file.read(_MAGIC_READ_BYTES)
        await file.seek(0)  # Reset for downstream readers.

        if not self._validate_magic_bytes(header, ext):
            logger.warning(
                "AUDIT | Action: upload_magic_byte_fail | File: %s | Ext: %s "
                "| Header: %s | Status: rejected",
                filename,
                ext,
                header[:8].hex(),
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File content does not match the declared type '{ext}'. Upload rejected.",
            )

        logger.info(
            "AUDIT | Action: upload_validation_passed | File: %s | Ext: %s "
            "| MIME: %s | Size: %d bytes",
            filename,
            ext,
            mime,
            size,
        )
        return size

    async def store_file(
        self,
        file: UploadFile,
        kb_uuid: py_uuid.UUID,
        doc_uuid: py_uuid.UUID,
    ) -> str:
        safe_name = self.secure_filename(file.filename or "file")
        unique_name = f"{doc_uuid}_{safe_name}"

        # Create storage directory structure reading root folder from settings config
        target_dir = os.path.abspath(
            os.path.join(settings.UPLOAD_DIR, "knowledge_bases", str(kb_uuid))
        )
        # Verify it stays within the upload dir root
        upload_root = os.path.abspath(settings.UPLOAD_DIR)
        if not target_dir.startswith(upload_root):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Path traversal detected.",
            )

        os.makedirs(target_dir, exist_ok=True)
        target_path = os.path.join(target_dir, unique_name)

        # Write chunks to disk
        with open(target_path, "wb") as f:
            while chunk := await file.read(8192):
                f.write(chunk)

        return target_path.replace("\\", "/")

