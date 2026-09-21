"""
RoleRepository — Data Access for Roles, System Roles & User Role Assignments.
"""

from typing import List, Optional
from sqlalchemy.orm import Session
from app.models.role import Role, RolePermission, UserRole
from app.models.permission import Permission


class RoleRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, role_id: int) -> Optional[Role]:
        return self.db.query(Role).filter(Role.id == role_id).first()

    def get_by_name(self, name: str, org_id: Optional[int] = None) -> Optional[Role]:
        query = self.db.query(Role).filter(Role.name == name)
        if org_id is not None:
            query = query.filter((Role.organization_id == org_id) | (Role.is_system_role == True))
        return query.first()

    def get_all(self, org_id: Optional[int] = None) -> List[Role]:
        query = self.db.query(Role)
        if org_id is not None:
            query = query.filter((Role.organization_id == org_id) | (Role.is_system_role == True))
        return query.order_by(Role.name.asc()).all()

    def create(self, name: str, description: str = "", is_system_role: bool = False, org_id: Optional[int] = None) -> Role:
        role = Role(
            name=name,
            description=description,
            is_system_role=is_system_role,
            organization_id=org_id,
        )
        self.db.add(role)
        self.db.commit()
        self.db.refresh(role)
        return role

    def assign_permission_to_role(self, role_id: int, permission_id: int) -> RolePermission:
        existing = (
            self.db.query(RolePermission)
            .filter(RolePermission.role_id == role_id, RolePermission.permission_id == permission_id)
            .first()
        )
        if existing:
            return existing

        rp = RolePermission(role_id=role_id, permission_id=permission_id)
        self.db.add(rp)
        self.db.commit()
        self.db.refresh(rp)
        return rp

    def assign_role_to_user(self, user_id: int, role_id: int, org_id: Optional[int] = None) -> UserRole:
        existing = (
            self.db.query(UserRole)
            .filter(UserRole.user_id == user_id, UserRole.role_id == role_id)
            .first()
        )
        if existing:
            return existing

        ur = UserRole(user_id=user_id, role_id=role_id, organization_id=org_id)
        self.db.add(ur)
        self.db.commit()
        self.db.refresh(ur)
        return ur

    def get_user_roles(self, user_id: int) -> List[Role]:
        return (
            self.db.query(Role)
            .join(UserRole, Role.id == UserRole.role_id)
            .filter(UserRole.user_id == user_id)
            .all()
        )

    def get_users_roles_batch(self, user_ids: List[int]) -> dict:
        """Return a mapping of user_id -> List[Role] in a single query."""
        if not user_ids:
            return {}

        rows = (
            self.db.query(UserRole.user_id, Role)
            .join(Role, Role.id == UserRole.role_id)
            .filter(UserRole.user_id.in_(user_ids))
            .all()
        )
        res = {uid: [] for uid in user_ids}
        for uid, role in rows:
            res[uid].append(role)
        return res
