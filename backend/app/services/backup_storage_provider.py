"""
BackupStorageProvider — Refinement #7: Abstract Backup Storage Provider Interface.

Provides a pluggable interface for backup storage backends (Local Disk,
Shared Network Storage, S3-Compatible Object Storage, Azure Blob Storage).
"""

import os
import shutil
import logging
from abc import ABC, abstractmethod
from app.core.config import settings

logger = logging.getLogger("app.services.backup_storage_provider")


class BackupStorageProvider(ABC):
    @abstractmethod
    def store_file(self, source_path: str, destination_key: str) -> str:
        pass

    @abstractmethod
    def retrieve_file(self, destination_key: str, target_path: str) -> bool:
        pass

    @abstractmethod
    def delete_file(self, destination_key: str) -> bool:
        pass


class LocalDiskStorageProvider(BackupStorageProvider):
    """Default Local / Shared Network Disk Storage Provider."""
    def __init__(self, base_dir: str = None):
        self.base_dir = os.path.abspath(base_dir or os.path.join(settings.UPLOAD_DIR, "..", "backups"))
        os.makedirs(self.base_dir, exist_ok=True)

    def store_file(self, source_path: str, destination_key: str) -> str:
        dest_path = os.path.join(self.base_dir, destination_key)
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        shutil.copy2(source_path, dest_path)
        logger.info(f"STORAGE_PROVIDER | Stored backup archive: {dest_path}")
        return dest_path.replace("\\", "/")

    def retrieve_file(self, destination_key: str, target_path: str) -> bool:
        src_path = os.path.join(self.base_dir, destination_key)
        if not os.path.exists(src_path):
            logger.error(f"STORAGE_PROVIDER | Archive not found: {src_path}")
            return False
        shutil.copy2(src_path, target_path)
        return True

    def delete_file(self, destination_key: str) -> bool:
        path = os.path.join(self.base_dir, destination_key)
        if os.path.exists(path):
            os.remove(path)
            return True
        return False
