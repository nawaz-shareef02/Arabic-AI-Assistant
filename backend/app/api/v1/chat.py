"""
Chat API Router — Production-Hardened for P0-1 Security Sprint.

Authentication & Authorization
-------------------------------
Both endpoints now require a valid JWT (via ``get_current_user``).
Authorization is enforced **before** any RAG or LLM call:

  Request
    ↓  get_current_user   → 401 if unauthenticated
  Current User
    ↓  authorize_knowledge_base_access()  → 403 if unauthorized
  Verified KnowledgeBase
    ↓  authorize_conversation_access()    → 403 if unauthorized
       (only when conversation_id is supplied)
  Verified Conversation
    ↓  RAG / LLM
  Response

The streaming endpoint enforces all authorization checks synchronously
before the StreamingResponse generator is created, so no Qdrant retrieval
or LLM tokens are ever produced for an unauthorized request.

Endpoints
---------
POST /chat/        — Non-streaming RAG (stateless + conversational)
POST /chat/stream  — Streaming RAG (stateless + conversational)
"""

import logging
import traceback

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_current_user
from app.database.session import SessionLocal
from app.models.user import User
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.rag_service import RAGService
from app.services.conversation_service import ConversationService
from app.services.title_service import TitleService
from app.services.chat_authorization_service import (
    authorize_knowledge_base_access,
    authorize_conversation_access,
)
from app.crud.conversation import ConversationRepository

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/chat",
    tags=["CHAT"],
)


# ──────────────────────────────────────────────────────────────────────────────
# Non-streaming RAG endpoint
# ──────────────────────────────────────────────────────────────────────────────

@router.post(
    "/",
    response_model=ChatResponse,
    summary="Non-streaming RAG chat (authenticated)",
)
def chat(
    request: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),  # ← P0-1: authentication
):
    """
    Non-streaming RAG chat.

    **Authentication**: Bearer token required (HTTP 401 if missing/invalid).
    **Authorization**: The authenticated user must own the requested knowledge
    base (HTTP 403 otherwise).  When ``conversation_id`` is provided, the
    conversation must also belong to the same user and the same KB (HTTP 403).

    Stateless mode   — ``conversation_id`` absent  → original behavior preserved.
    Conversational   — ``conversation_id`` present → history-aware RAG with DB
                       persistence.
    """
    try:
        # ── Step 1: Authorize KB access ──────────────────────────────────────
        authorized_kb = authorize_knowledge_base_access(
            db,
            knowledge_base_id=request.knowledge_base_id,
            current_user=current_user,
        )

        rag = RAGService(db)

        if request.conversation_id is not None:
            # ── Step 2: Authorize conversation access ────────────────────────
            authorize_conversation_access(
                db,
                conversation_id=request.conversation_id,
                current_user=current_user,
                authorized_kb=authorized_kb,
            )

            # ── Step 3: Run conversational RAG ───────────────────────────────
            result = rag.ask_with_history(
                question=request.question,
                knowledge_base_id=authorized_kb.id,
                conversation_id=request.conversation_id,
                user_id=current_user.id,
                organization_id=authorized_kb.organization_id,
            )

            _post_message_tasks(
                db=db,
                conversation_id=request.conversation_id,
                first_question=request.question,
            )

            return result

        # ── Step 3 (stateless): Run stateless RAG ────────────────────────────
        return rag.ask(
            question=request.question,
            knowledge_base_id=authorized_kb.id,
            organization_id=authorized_kb.organization_id,
        )

    except HTTPException:
        raise
    except Exception:
        logger.exception("Chat endpoint failed unexpectedly")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred. Please try again later.",
        )


# ──────────────────────────────────────────────────────────────────────────────
# Streaming RAG endpoint
# ──────────────────────────────────────────────────────────────────────────────

@router.post(
    "/stream",
    summary="Streaming RAG chat (authenticated)",
)
def stream_chat(
    request: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),  # ← P0-1: authentication
):
    """
    Streaming RAG chat.

    **Authentication**: Bearer token required (HTTP 401 if missing/invalid).
    **Authorization**: Enforced *synchronously* before the StreamingResponse
    generator is created — no Qdrant retrieval or LLM tokens are produced for
    an unauthorized request.

    Stateless mode   — ``conversation_id`` absent  → original streaming behavior.
    Conversational   — ``conversation_id`` present → history-aware streaming
                       with DB persistence (message saved ONLY on success).
    """
    try:
        # ── Step 1: Authorize KB access (before generator) ───────────────────
        authorized_kb = authorize_knowledge_base_access(
            db,
            knowledge_base_id=request.knowledge_base_id,
            current_user=current_user,
        )

        rag = RAGService(db)

        if request.conversation_id is not None:
            # ── Step 2: Authorize conversation access (before generator) ─────
            authorize_conversation_access(
                db,
                conversation_id=request.conversation_id,
                current_user=current_user,
                authorized_kb=authorized_kb,
            )

            # Authorization passed — now safe to build the streaming generator.
            kb_id = authorized_kb.id
            conversation_id = request.conversation_id
            user_id = current_user.id
            question = request.question
            org_id = authorized_kb.organization_id

            def stream_and_post_process():
                """Wrap the generator so post-processing runs after stream ends."""
                yield from rag.stream_ask_with_history(
                    question=question,
                    knowledge_base_id=kb_id,
                    conversation_id=conversation_id,
                    user_id=user_id,
                    organization_id=org_id,
                )
                # After stream completes: update last_message_at + generate title.
                # Use a fresh DB session — the streaming session may be closed.
                _post_message_tasks_new_session(
                    conversation_id=conversation_id,
                    first_question=question,
                )

            return StreamingResponse(
                stream_and_post_process(),
                media_type="text/plain",
            )

        # ── Stateless streaming (backward compatible) ─────────────────────────
        return StreamingResponse(
            rag.stream_ask(
                question=request.question,
                knowledge_base_id=authorized_kb.id,
                organization_id=authorized_kb.organization_id,
            ),
            media_type="text/plain",
        )

    except HTTPException:
        raise
    except Exception:
        logger.exception("Streaming chat endpoint failed unexpectedly")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred. Please try again later.",
        )


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────

def _post_message_tasks(
    db: Session,
    conversation_id: int,
    first_question: str,
) -> None:
    """
    Run post-message tasks in the same session:
    1. Touch last_message_at
    2. Generate title (if not yet set — idempotent)
    """
    try:
        svc = ConversationService(db)
        svc.touch_last_message_at(conversation_id)

        conv = ConversationRepository(db).get_by_id(conversation_id)
        if conv and not conv.title:
            title = TitleService().generate(first_question)
            svc.set_title_if_empty(conversation_id, title)
    except Exception as exc:
        # Never let metadata failures propagate to the caller.
        logger.warning("Post-message tasks failed (non-fatal): %s", exc)


def _post_message_tasks_new_session(
    conversation_id: int,
    first_question: str,
) -> None:
    """
    Same as _post_message_tasks but opens a fresh session.
    Used after streaming where the original session may be closed.
    """
    db = SessionLocal()
    try:
        _post_message_tasks(db, conversation_id, first_question)
    except Exception as exc:
        logger.warning("Post-message tasks (new session) failed (non-fatal): %s", exc)
    finally:
        db.close()