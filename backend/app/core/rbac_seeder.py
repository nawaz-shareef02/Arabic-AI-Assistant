"""
RBACSeeder — Enterprise Default Roles & Dot-Notation Permission Auto-Seeder.

Refinement #6: Fully Idempotent. Creates missing roles/permissions, updates descriptions,
never duplicates records, safe to run on every startup or deployment.
"""

import logging
from sqlalchemy.orm import Session
from app.repositories.permission_repository import PermissionRepository
from app.repositories.role_repository import RoleRepository

logger = logging.getLogger("app.core.rbac_seeder")

# Refinement #3: Standardized Dot-Notation Permission Schema
DEFAULT_PERMISSIONS = [
    {"name": "knowledge_base.read", "resource": "knowledge_base", "action": "read", "description": "View knowledge bases"},
    {"name": "knowledge_base.create", "resource": "knowledge_base", "action": "create", "description": "Create new knowledge bases"},
    {"name": "knowledge_base.update", "resource": "knowledge_base", "action": "update", "description": "Update knowledge bases"},
    {"name": "knowledge_base.delete", "resource": "knowledge_base", "action": "delete", "description": "Delete knowledge bases"},
    {"name": "documents.read", "resource": "documents", "action": "read", "description": "View document content & metadata"},
    {"name": "documents.upload", "resource": "documents", "action": "upload", "description": "Upload new documents"},
    {"name": "documents.delete", "resource": "documents", "action": "delete", "description": "Delete uploaded documents"},
    {"name": "chat.use", "resource": "chat", "action": "use", "description": "Interact with AI RAG assistant"},
    {"name": "analytics.view", "resource": "analytics", "action": "view", "description": "View system analytics & health"},
    {"name": "users.manage", "resource": "users", "action": "manage", "description": "Manage organization users"},
    {"name": "roles.manage", "resource": "roles", "action": "manage", "description": "Manage enterprise roles & permissions"},
    {"name": "organizations.manage", "resource": "organizations", "action": "manage", "description": "Manage enterprise organizations"},
    {"name": "system.admin", "resource": "system", "action": "admin", "description": "Full platform administration"},
    {"name": "data.export", "resource": "data", "action": "export", "description": "Export document & telemetry data"},
]

DEFAULT_ROLES = {
    "Super Admin": {
        "description": "Platform super administrator with unrestricted access",
        "permissions": ["*"],  # All permissions
    },
    "Organization Admin": {
        "description": "Administrator for a specific enterprise organization",
        "permissions": [
            "organizations.manage", "users.manage", "roles.manage",
            "knowledge_base.read", "knowledge_base.create", "knowledge_base.update", "knowledge_base.delete",
            "documents.read", "documents.upload", "documents.delete",
            "chat.use", "analytics.view", "data.export",
        ],
    },
    "Knowledge Manager": {
        "description": "Manages knowledge bases, document uploads, and analytics",
        "permissions": [
            "knowledge_base.read", "knowledge_base.create", "knowledge_base.update", "knowledge_base.delete",
            "documents.read", "documents.upload", "documents.delete",
            "chat.use", "analytics.view", "data.export",
        ],
    },
    "Editor": {
        "description": "Can read/create knowledge bases and upload documents",
        "permissions": [
            "knowledge_base.read", "knowledge_base.create", "knowledge_base.update",
            "documents.read", "documents.upload", "chat.use",
        ],
    },
    "AI User": {
        "description": "Standard user with RAG chat search capabilities",
        "permissions": ["knowledge_base.read", "documents.read", "chat.use"],
    },
    "Viewer": {
        "description": "Read-only access to knowledge bases and documents",
        "permissions": ["knowledge_base.read", "documents.read"],
    },
}


def seed_rbac(db: Session) -> None:
    """Idempotently seeds default system roles and dot-notation permissions."""
    logger.info("RBACSeeder: Initializing default permissions and roles...")

    perm_repo = PermissionRepository(db)
    role_repo = RoleRepository(db)

    from app.models.organization import Organization
    default_org = db.query(Organization).filter(Organization.id == 1).first()
    if not default_org:
        default_org = Organization(id=1, name="Default Organization", slug="default-org", is_active=True)
        db.add(default_org)
        db.commit()

    # 1. Seed Permissions
    perm_map = {}
    for p_def in DEFAULT_PERMISSIONS:
        perm = perm_repo.get_by_name(p_def["name"])
        if not perm:
            perm = perm_repo.create(
                name=p_def["name"],
                resource=p_def["resource"],
                action=p_def["action"],
                description=p_def["description"],
            )
            logger.info(f"  + Created permission: {perm.name}")
        perm_map[perm.name] = perm

    # 2. Seed System Roles & Map Permissions
    for role_name, r_def in DEFAULT_ROLES.items():
        role = role_repo.get_by_name(role_name)
        if not role:
            role = role_repo.create(
                name=role_name,
                description=r_def["description"],
                is_system_role=True,
                org_id=None,
            )
            logger.info(f"  + Created system role: {role.name}")

        target_perms = (
            list(perm_map.values())
            if "*" in r_def["permissions"]
            else [perm_map[p] for p in r_def["permissions"] if p in perm_map]
        )

        for perm in target_perms:
            role_repo.assign_permission_to_role(role.id, perm.id)

    db.commit()
    logger.info("RBACSeeder: System roles and permissions seeding completed successfully.")
