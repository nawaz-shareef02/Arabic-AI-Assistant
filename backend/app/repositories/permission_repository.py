"""
PermissionRepository — Data Access for Granular Permissions & RolePermission Associations.
"""

from typing import List, Optional
from sqlalchemy.orm import Session
from app.models.permission import Permission
from app.models.role import RolePermission, Role, UserRole


class PermissionRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_name(self, name: str) -> Optional[Permission]:
        return self.db.query(Permission).filter(Permission.name == name).first()

    def get_all(self) -> List[Permission]:
        return self.db.query(Permission).order_by(Permission.name.asc()).all()

    def create(self, name: str, resource: str, action: str, description: str = "") -> Permission:
        perm = Permission(
            name=name,
            resource=resource,
            action=action,
            description=description,
        )
        self.db.add(perm)
        self.db.commit()
        self.db.refresh(perm)
        return perm

    def get_permissions_for_role_ids(self, role_ids: List[int]) -> List[Permission]:
        if not role_ids:
            return []
        return (
            self.db.query(Permission)
            .join(RolePermission, Permission.id == RolePermission.permission_id)
            .filter(RolePermission.role_id.in_(role_ids))
            .distinct()
            .all()
        )

    def get_permissions_for_user(self, user_id: int) -> List[Permission]:
        return (
            self.db.query(Permission)
            .join(RolePermission, Permission.id == RolePermission.permission_id)
            .join(UserRole, RolePermission.role_id == UserRole.role_id)
            .filter(UserRole.user_id == user_id)
            .distinct()
            .all()
        )
