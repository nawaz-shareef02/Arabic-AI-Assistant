"""
Chat API Router — Production-Hardened for P0-1 Security and P1-2 Distributed Rate Limiting.

Authentication, Authorization & Abuse-Control Pipeline:
--------------------------------------------------------
Both endpoints strictly enforce the following security pipeline:

  Request
    ↓  get_current_user              → 401 Unauthorized (if missing or invalid JWT)
  Authenticated User
    ↓  authorize_knowledge_base_access() → 403 Forbidden (if unauthorized / cross-org)
  Verified KnowledgeBase
    ↓  ChatRateLimitService          → 429 Too Many Requests (if rate/concurrency limit hit)
  Rate Limit / Concurrency Acquired
    ↓  PromptSecurityService         → 400 Bad Request (if prompt injection / jailbreak)
  Safe Prompt
    ↓  authorize_conversation_access() → 403 Forbidden (if conversational & mismatched)
  Verified Conversation
    ↓  RAG / LLM Execution
  Response / Stream (Guaranteed release of concurrency leases in `finally:`)

Endpoints:
---------
POST /chat/        — Non-streaming RAG (stateless + conversational)
POST /chat/stream  — Streaming RAG with active concurrency lease management
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
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
from app.services.prompt_security_service import PromptSecurityService
from app.services.chat_rate_limit_service import ChatRateLimitService
from app.services.llm.ollama_provider import OllamaProvider, OllamaOverloadedException
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
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Non-streaming RAG chat with distributed sliding-window rate limiting.

    Pipeline:
      1. Authenticate (HTTP 401)
      2. Authorize Knowledge Base access (HTTP 403)
      3. Rate Limit evaluation (HTTP 429)
      4. Prompt Security validation (HTTP 400)
      5. Authorize Conversation access if present (HTTP 403)
      6. Run RAG retrieval and LLM inference
    """
    try:
        # ── Step 1: Authorize KB access ──────────────────────────────────────
        authorized_kb = authorize_knowledge_base_access(
            db,
            knowledge_base_id=request.knowledge_base_id,
            current_user=current_user,
        )

        # ── Step 1.2: Rate Limit Decision (P1-2) ──────────────────────────────
        rate_service = ChatRateLimitService()
        rate_res = rate_service.check_chat_rate_limit(
            user_id=current_user.id,
            org_id=authorized_kb.organization_id,
        )
        if not rate_res.allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=rate_res.detail or "Too many AI requests. Please retry later.",
                headers=rate_res.headers,
            )

        # Attach rate-limit headers to response
        for k, v in rate_res.headers.items():
            response.headers[k] = v

        # ── Step 1.5: Validate Prompt Security (P0-3) ────────────────────────
        sec = PromptSecurityService(db)
        decision = sec.process_prompt(
            prompt=request.question,
            user=current_user,
            kb_id=authorized_kb.id,
            org_id=authorized_kb.organization_id,
        )
        if decision["decision"] in ("BLOCKED", "DENIED"):
            logger.warning(
                "AUDIT_CHAT | Action: prompt_rejected | User: %s | Decision: %s "
                "| Reason: %s | Risk: %.2f",
                current_user.email,
                decision["decision"],
                decision["reason"],
                decision["risk_score"],
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Request blocked: {decision['reason']}",
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
                user=current_user,
            )

            _post_message_tasks_new_session(
                conversation_id=request.conversation_id,
                first_question=request.question,
            )

            return result

        # ── Step 3 (stateless): Run stateless RAG ────────────────────────────
        return rag.ask(
            question=request.question,
            knowledge_base_id=authorized_kb.id,
            organization_id=authorized_kb.organization_id,
            user=current_user,
        )

    except OllamaOverloadedException:
        logger.warning("Chat request rejected: Ollama inference capacity reached (503).")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The AI inference engine is currently at peak capacity. Please retry shortly.",
            headers={"Retry-After": "5"},
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
    current_user: User = Depends(get_current_user),
):
    """
    Streaming RAG chat with active stream concurrency management and lease reclamation.

    Guarantees:
      1. All authorization checks executed before stream generator instantiation.
      2. Concurrency slot reserved before streaming begins.
      3. Concurrency slot released in `finally:` block regardless of whether stream
         completes normally, encounters an error, or the client disconnects.
    """
    try:
        # ── Step 1: Authorize KB access (before generator) ───────────────────
        authorized_kb = authorize_knowledge_base_access(
            db,
            knowledge_base_id=request.knowledge_base_id,
            current_user=current_user,
        )

        # ── Step 1.2: Rate Limit & Stream Concurrency Acquisition (P1-2) ──────
        rate_service = ChatRateLimitService()
        rate_res = rate_service.check_and_acquire_stream_slot(
            user_id=current_user.id,
            org_id=authorized_kb.organization_id,
        )
        if not rate_res.allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=rate_res.detail or "Too many AI requests. Please retry later.",
                headers=rate_res.headers,
            )

        lease_id = rate_res.lease_id
        user_id = current_user.id
        org_id = authorized_kb.organization_id
        kb_id = authorized_kb.id
        question = request.question

        # ── Step 1.25: Fast Admission Check for Ollama Engine (P2-4) ──────────
        if not OllamaProvider.get_instance().has_available_slot():
            rate_service.release_stream_slot(lease_id, user_id, org_id)
            logger.warning(
                "AUDIT_CHAT | Action: stream_rejected_capacity | User: %s | Status: 503",
                current_user.email,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The AI inference engine is currently at peak capacity. Please retry shortly.",
                headers={"Retry-After": "5", **rate_res.headers},
            )

        # ── Step 1.5: Validate Prompt Security (synchronously before streaming) ──
        sec = PromptSecurityService(db)
        decision = sec.process_prompt(
            prompt=request.question,
            user=current_user,
            kb_id=authorized_kb.id,
            org_id=authorized_kb.organization_id,
        )
        if decision["decision"] in ("BLOCKED", "DENIED"):
            rate_service.release_stream_slot(lease_id, user_id, org_id)
            logger.warning(
                "AUDIT_CHAT | Action: prompt_rejected_stream | User: %s | Decision: %s "
                "| Reason: %s | Risk: %.2f",
                current_user.email,
                decision["decision"],
                decision["reason"],
                decision["risk_score"],
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Request blocked: {decision['reason']}",
            )

        rag = RAGService(db)

        if request.conversation_id is not None:
            # ── Step 2: Authorize conversation access (before generator) ─────
            try:
                authorize_conversation_access(
                    db,
                    conversation_id=request.conversation_id,
                    current_user=current_user,
                    authorized_kb=authorized_kb,
                )
            except Exception:
                rate_service.release_stream_slot(lease_id, user_id, org_id)
                raise

            conversation_id = request.conversation_id

            def stream_and_post_process():
                """Wrap the generator so post-processing and concurrency release run cleanly."""
                try:
                    yield from rag.stream_ask_with_history(
                        question=question,
                        knowledge_base_id=kb_id,
                        conversation_id=conversation_id,
                        user_id=user_id,
                        organization_id=org_id,
                        user=current_user,
                    )
                    _post_message_tasks_new_session(
                        conversation_id=conversation_id,
                        first_question=question,
                    )
                except OllamaOverloadedException:
                    logger.warning("Streaming backpressure: Ollama inference slot unavailable.")
                    yield "The AI inference engine is currently at peak capacity. Please retry shortly."
                finally:
                    rate_service.release_stream_slot(lease_id, user_id, org_id)

            return StreamingResponse(
                stream_and_post_process(),
                media_type="text/plain",
                headers=rate_res.headers,
            )

        # ── Stateless streaming ──────────────────────────────────────────────
        def stateless_stream():
            try:
                yield from rag.stream_ask(
                    question=question,
                    knowledge_base_id=kb_id,
                    organization_id=org_id,
                    user=current_user,
                )
            except OllamaOverloadedException:
                logger.warning("Streaming backpressure: Ollama inference slot unavailable.")
                yield "The AI inference engine is currently at peak capacity. Please retry shortly."
            finally:
                rate_service.release_stream_slot(lease_id, user_id, org_id)

        return StreamingResponse(
            stateless_stream(),
            media_type="text/plain",
            headers=rate_res.headers,
        )

    except OllamaOverloadedException:
        if "rate_service" in locals() and "lease_id" in locals():
            rate_service.release_stream_slot(lease_id, user_id, org_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The AI inference engine is currently at peak capacity. Please retry shortly.",
            headers={"Retry-After": "5"},
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