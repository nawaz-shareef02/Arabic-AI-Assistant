"""
PermissionService — Dynamic Permission Resolution & Invalidation Service.

Refinement #1: Does NOT store full permission lists inside JWT. Resolves permissions
dynamically from role_ids with caching.

Refinement #8: Provides explicit cache invalidation when roles, permissions,
or user assignments are mutated.
"""

import logging
from typing import List, Set, Optional
from sqlalchemy.orm import Session
from app.repositories.permission_repository import PermissionRepository

logger = logging.getLogger("app.services.permission_service")

# In-memory permission resolution cache fallback (or Redis backed)
_PERMISSION_CACHE = {}


class PermissionService:
    def __init__(self, db: Session):
        self.db = db
        self.perm_repo = PermissionRepository(db)

    def get_permissions_for_roles(self, role_ids: List[int]) -> Set[str]:
        """Resolves set of dot-notation permission strings for a given list of role IDs."""
        if not role_ids:
            return set()

        cache_key = f"roles_perms:{','.join(map(str, sorted(role_ids)))}"
        if cache_key in _PERMISSION_CACHE:
            return _PERMISSION_CACHE[cache_key]

        perms = self.perm_repo.get_permissions_for_role_ids(role_ids)
        perm_set = {p.name for p in perms}

        _PERMISSION_CACHE[cache_key] = perm_set
        return perm_set

    def get_user_permissions(self, user_id: int) -> Set[str]:
        """Resolves permissions assigned to a user across all assigned roles."""
        cache_key = f"user_perms:{user_id}"
        if cache_key in _PERMISSION_CACHE:
            return _PERMISSION_CACHE[cache_key]

        perms = self.perm_repo.get_permissions_for_user(user_id)
        perm_set = {p.name for p in perms}

        _PERMISSION_CACHE[cache_key] = perm_set
        return perm_set

    @staticmethod
    def invalidate_cache_for_user(user_id: int) -> None:
        """Refinement #8: Clears cached permission set when user roles change."""
        cache_key = f"user_perms:{user_id}"
        _PERMISSION_CACHE.pop(cache_key, None)
        logger.info(f"PermissionService: Invalidated permission cache for user {user_id}")

    @staticmethod
    def invalidate_all_cache() -> None:
        """Clears all cached permission mappings."""
        _PERMISSION_CACHE.clear()
        logger.info("PermissionService: Cleared global permission cache")
