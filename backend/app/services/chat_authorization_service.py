"""
Chat Authorization Service — P0-1 & P0-2 Security Hardening.

Enforces server-side ownership and organization isolation for chat endpoints:
  POST /api/v1/chat/
  POST /api/v1/chat/stream

The secure request flow is:

  Request
    ↓  authenticate (get_current_user dependency)
  Current User & Organization Context
    ↓  authorize_knowledge_base_access()
  Verified KnowledgeBase (belongs to user's Organization)
    ↓  authorize_conversation_access()  (only when conversation_id provided)
  Verified Conversation (belongs to user's Organization AND to the authorized KB)
    ↓  RAG / LLM
  Response

Rules enforced
--------------
- User MUST belong to at least one Organization. Unaffiliated users → 403.
  There is NO silent fallback to Organization ID 1.
- KB must exist, be active, and belong to the user's Organization → 403.
  There is NO legacy owner_id fallback path.
- Conversation (when supplied) must belong to the user's Organization → 403.
- Conversation (when supplied) must reference the same KB as the request → 403.
- None of the above expose internal DB errors or stack traces.

P0 Changes (audit 2026-08-20)
------------------------------
- Removed: `_get_user_org_id() → return 1`  (org=1 fallback)
- Removed: `authorize_knowledge_base_access()` owner_id fallback path
- Removed: `authorize_conversation_access()` org-less fallback call
- All authorization paths now raise 403 rather than silently downgrading
  to a weaker check.
"""

import logging
from typing import Optional
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.knowledge_base import KnowledgeBase
from app.models.conversation import Conversation, ConversationStatus
from app.crud.knowledge_base import get_kb_by_id_and_org
from app.crud.conversation import ConversationRepository
from app.models.organization import OrganizationMember

logger = logging.getLogger(__name__)


def _get_user_org_id(db: Session, user_id: int) -> int:
    """
    Returns the organization ID for the given user.

    P0-2 Security: NEVER falls back to organization 1.
    If the user has no organization membership, raises HTTP 403.

    Raises
    ------
    HTTPException 403
        When the user is not a member of any organization.
    """
    member = db.query(OrganizationMember).filter(
        OrganizationMember.user_id == user_id
    ).first()

    if member is None:
        logger.warning(
            "AUDIT_CHAT | Action: org_lookup_failed | User ID: %s "
            "| Reason: no_organization_membership",
            user_id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: user is not a member of any organization.",
        )

    return member.organization_id


def authorize_knowledge_base_access(
    db: Session,
    *,
    knowledge_base_id: int,
    current_user: User,
) -> KnowledgeBase:
    """
    Verify that ``current_user``'s Organization owns and may access the requested KB.

    P0-2 Security: Only the organization-based check is performed.
    There is no owner_id fallback. If the org-based lookup fails, the request
    is denied unconditionally.

    Raises
    ------
    HTTPException 403
        When the user has no org membership, the KB does not exist,
        belongs to a different organization, or has been soft-deleted.
    """
    # Raises 403 if user has no org membership (no silent fallback).
    org_id = _get_user_org_id(db, current_user.id)

    # Authoritative org-scoped check only — no owner_id fallback.
    kb = get_kb_by_id_and_org(db, kb_id=knowledge_base_id, organization_id=org_id)

    if kb is None:
        logger.warning(
            "AUDIT_CHAT | Action: kb_access_denied "
            "| User: %s | Org ID: %s | KB ID: %s | Reason: not_found_or_unauthorized",
            current_user.email,
            org_id,
            knowledge_base_id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to the requested knowledge base.",
        )

    logger.info(
        "AUDIT_CHAT | Action: kb_access_granted | User: %s | Org ID: %s | KB ID: %s",
        current_user.email,
        org_id,
        knowledge_base_id,
    )
    return kb


def authorize_conversation_access(
    db: Session,
    *,
    conversation_id: int,
    current_user: User,
    authorized_kb: KnowledgeBase,
) -> Conversation:
    """
    Verify that ``current_user``'s Organization owns the conversation and that it
    belongs to the already-authorized knowledge base.

    P0-2 Security: Always enforces organization_id. No org-less fallback path.

    Raises
    ------
    HTTPException 403
        When the conversation does not exist, belongs to another user/org,
        or does not reference the authorized KB.
    """
    # Raises 403 if user has no org membership (no silent fallback).
    org_id = _get_user_org_id(db, current_user.id)
    repo = ConversationRepository(db)

    # Enforce org + user ownership in a single authoritative lookup.
    conv = repo.get_by_id_and_user(
        conversation_id=conversation_id,
        user_id=current_user.id,
        organization_id=org_id,
    )

    if conv is None:
        logger.warning(
            "AUDIT_CHAT | Action: conversation_access_denied "
            "| User: %s | Org: %s | Conv ID: %s | Reason: not_found_or_unauthorized",
            current_user.email,
            org_id,
            conversation_id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to the requested conversation.",
        )

    if conv.knowledge_base_id != authorized_kb.id:
        logger.warning(
            "AUDIT_CHAT | Action: conversation_kb_mismatch "
            "| User: %s | Conv ID: %s | Conv KB: %s | Request KB: %s",
            current_user.email,
            conversation_id,
            conv.knowledge_base_id,
            authorized_kb.id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Conversation does not belong to the requested knowledge base.",
        )

    logger.info(
        "AUDIT_CHAT | Action: conversation_access_granted "
        "| User: %s | Conv ID: %s | KB ID: %s",
        current_user.email,
        conversation_id,
        authorized_kb.id,
    )
    return conv
