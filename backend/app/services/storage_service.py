import os
import re
import uuid as py_uuid
from pathlib import Path
from fastapi import UploadFile, HTTPException, status
from app.core.config import settings

class StorageService:
    ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".markdown"}
    
    ALLOWED_MIME_TYPES = {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain",
        "text/markdown",
        "text/x-markdown",
        "application/octet-stream"  # Fallback for some clients sending md files as binary streams
    }
    
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB in bytes

    @staticmethod
    def secure_filename(filename: str) -> str:
        import unicodedata
        # Normalize Unicode filenames to decompose characters (NFKD)
        name = unicodedata.normalize('NFKD', filename)
        # Strip directory traversal paths
        name = Path(name).name
        # Keep only alphanumeric, dots, underscores, dashes
        name = re.sub(r'[^a-zA-Z0-9._-]', '_', name)
        # Avoid hidden/dot files
        name = name.lstrip('.')
        
        # Enforce filename length limit
        if len(name) > 255:
            stem = Path(name).stem
            suffix = Path(name).suffix
            name = stem[:255 - len(suffix)] + suffix
            
        if not name:
            name = "unnamed_file"
        return name

    async def validate_file(self, file: UploadFile) -> int:
        filename = file.filename or ""
        
        # Reject hidden files
        if filename.startswith('.'):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Hidden files are not allowed."
            )
            
        # Reject double extensions (prevent execution hijack)
        if filename.count('.') > 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Multiple file extensions are not allowed."
            )
            
        ext = Path(filename).suffix.lower()
        
        # 1. Validate Extension
        if ext not in self.ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported file extension '{ext}'."
            )

        # 2. Validate MIME type
        mime = file.content_type
        # Allow application/octet-stream fallback for text files like Markdown (.md)
        if mime not in self.ALLOWED_MIME_TYPES and not (mime == "application/octet-stream" and ext in {".md", ".markdown"}):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported file type '{mime}'."
            )

        if file.size is not None:
            size = file.size
        else:
            file.file.seek(0, 2)
            size = file.file.tell()
            file.file.seek(0)
        
        if size > self.MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"File exceeds maximum upload size of {self.MAX_FILE_SIZE // (1024*1024)} MB."
            )
        if size == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Empty file uploaded."
            )
            
        return size

    async def store_file(
        self,
        file: UploadFile,
        kb_uuid: py_uuid.UUID,
        doc_uuid: py_uuid.UUID
    ) -> str:
        safe_name = self.secure_filename(file.filename or "file")
        unique_name = f"{doc_uuid}_{safe_name}"
        
        # Create storage directory structure reading root folder from settings config
        target_dir = os.path.abspath(os.path.join(settings.UPLOAD_DIR, "knowledge_bases", str(kb_uuid)))
        # Verify it stays within the upload dir root
        upload_root = os.path.abspath(settings.UPLOAD_DIR)
        if not target_dir.startswith(upload_root):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Path traversal detected."
            )
            
        os.makedirs(target_dir, exist_ok=True)
        target_path = os.path.join(target_dir, unique_name)
        
        # Write chunks to disk
        with open(target_path, "wb") as f:
            while chunk := await file.read(8192):
                f.write(chunk)
                
        return target_path.replace("\\", "/")
