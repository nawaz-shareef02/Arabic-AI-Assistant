"""
Chat API Router — Extended for Sprint 11 Conversational Intelligence.

Backward Compatibility
----------------------
Existing stateless endpoints are fully preserved.
When conversation_id is absent → stateless RAG pipeline (original behavior).
When conversation_id is present → conversational RAG pipeline with persistence.

Endpoints
---------
POST /chat/        — Non-streaming RAG (stateless + conversational)
POST /chat/stream  — Streaming RAG (stateless + conversational)
"""

import logging
import traceback
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, require_permission
from app.database.session import SessionLocal
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.rag_service import RAGService
from app.services.conversation_service import ConversationService
from app.services.title_service import TitleService
from app.crud.conversation import ConversationRepository

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/chat",
    tags=["CHAT"],
)


def _get_user_id_from_conv(conversation_id: int, db: Session) -> Optional[int]:
    """Resolve user_id from conversation — avoids requiring auth on stateless calls."""
    conv = ConversationRepository(db).get_by_id(conversation_id)
    return conv.user_id if conv else None


# ──────────────────────────────────────────────────────────────────────────────
# Existing Chat Endpoint (non-streaming)
# ──────────────────────────────────────────────────────────────────────────────

@router.post(
    "/",
    response_model=ChatResponse,
)
def chat(
    request: ChatRequest,
    db: Session = Depends(get_db),
):
    """
    Non-streaming RAG chat.

    Stateless mode  — conversation_id absent  → original behavior preserved.
    Conversational  — conversation_id present → history-aware RAG with DB persistence.
    """
    try:
        rag = RAGService(db)

        if request.conversation_id is not None:
            # ── Conversational mode ──────────────────────────────────────
            user_id = _get_user_id_from_conv(request.conversation_id, db)
            if user_id is None:
                raise HTTPException(status_code=404, detail="Conversation not found.")

            result = rag.ask_with_history(
                question=request.question,
                knowledge_base_id=request.knowledge_base_id,
                conversation_id=request.conversation_id,
                user_id=user_id,
            )

            # Update last_message_at and generate title if not yet set.
            _post_message_tasks(
                db=db,
                conversation_id=request.conversation_id,
                first_question=request.question,
            )

            return result

        # ── Stateless mode (backward compatible) ─────────────────────────
        return rag.ask(
            question=request.question,
            knowledge_base_id=request.knowledge_base_id,
        )

    except HTTPException:
        raise
    except Exception as ex:
        logger.exception("Chat endpoint failed")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(ex))


# ──────────────────────────────────────────────────────────────────────────────
# Streaming Chat Endpoint
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/stream")
def stream_chat(
    request: ChatRequest,
    db: Session = Depends(get_db),
):
    """
    Streaming RAG chat.

    Stateless mode  — conversation_id absent  → original streaming behavior.
    Conversational  — conversation_id present → history-aware streaming with
                      DB persistence (message saved ONLY on success).
    """
    try:
        rag = RAGService(db)

        if request.conversation_id is not None:
            # ── Conversational streaming mode ────────────────────────────
            user_id = _get_user_id_from_conv(request.conversation_id, db)
            if user_id is None:
                raise HTTPException(status_code=404, detail="Conversation not found.")

            def stream_and_post_process():
                """Wrap the generator so post-processing runs after stream ends."""
                yield from rag.stream_ask_with_history(
                    question=request.question,
                    knowledge_base_id=request.knowledge_base_id,
                    conversation_id=request.conversation_id,
                    user_id=user_id,
                )
                # After stream completes: update last_message_at + generate title.
                # Use a fresh DB session — the streaming session may be closed.
                _post_message_tasks_new_session(
                    conversation_id=request.conversation_id,
                    first_question=request.question,
                )

            return StreamingResponse(
                stream_and_post_process(),
                media_type="text/plain",
            )

        # ── Stateless streaming mode (backward compatible) ────────────────
        return StreamingResponse(
            rag.stream_ask(
                question=request.question,
                knowledge_base_id=request.knowledge_base_id,
            ),
            media_type="text/plain",
        )

    except HTTPException:
        raise
    except Exception as ex:
        logger.exception("Streaming chat endpoint failed")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(ex))


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
        logger.warning(f"Post-message tasks failed (non-fatal): {exc}")


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
        logger.warning(f"Post-message tasks (new session) failed (non-fatal): {exc}")
    finally:
        db.close()