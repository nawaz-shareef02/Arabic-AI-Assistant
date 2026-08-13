"""
SecurityContext — Request-Scoped Enterprise Context Object (Refinement #5).

Encapsulates CurrentUser, CurrentOrganization, CurrentWorkspace, assigned Roles,
and resolved Permissions for clean, thread-safe request authorization.
"""

from dataclasses import dataclass, field
from typing import Optional, Set, List
from app.models.user import User


@dataclass
class SecurityContext:
    user: User
    org_id: Optional[int] = None
    workspace_id: Optional[int] = None
    role_ids: List[int] = field(default_factory=list)
    permissions: Set[str] = field(default_factory=set)

    @property
    def is_super_admin(self) -> bool:
        return "system.admin" in self.permissions

    def has_permission(self, perm: str) -> bool:
        return self.is_super_admin or (perm in self.permissions)
