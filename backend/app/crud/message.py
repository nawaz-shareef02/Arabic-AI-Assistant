"""
Message Repository — Repository Pattern.

All database interaction for the messages table lives here.
No business logic, no AI calls, no external service calls.
"""

from typing import Any, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.message import Message


class MessageRepository:
    """
    Data access layer for Message entities.

    Designed for efficient retrieval of conversation history
    using a token-budget approach (newest messages first).
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    # ──────────────────────────────────────────────────────────────────────
    # Write operations
    # ──────────────────────────────────────────────────────────────────────

    def create(
        self,
        *,
        conversation_id: int,
        role: str,
        content: str,
        citations: Optional[Any] = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
    ) -> Message:
        """Persist a new message and return the saved instance."""
        msg = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            citations=citations,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
        self.db.add(msg)
        self.db.commit()
        self.db.refresh(msg)
        return msg

    # ──────────────────────────────────────────────────────────────────────
    # Read operations
    # ──────────────────────────────────────────────────────────────────────

    def get_history(
        self,
        conversation_id: int,
        *,
        token_budget: int = 2000,
    ) -> List[Message]:
        """
        Retrieve conversation history within a token budget.

        Strategy
        --------
        1. Fetch the N most recent messages (newest first).
        2. Accumulate from newest until the token budget is exhausted.
        3. Return in chronological order (oldest first) for the prompt.

        Token estimation: len(content.split()) * 1.4
        This is intentionally conservative (actual Arabic tokens are denser).

        Parameters
        ----------
        conversation_id : int
            The conversation to retrieve history for.
        token_budget : int
            Maximum estimated tokens to include. Configured via
            settings.CONV_HISTORY_TOKEN_BUDGET.
        """
        # Fetch up to 40 recent messages — worst case we'll trim them below.
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(40)
        )
        recent: List[Message] = list(self.db.scalars(stmt).all())

        # Walk from newest → oldest, accumulating within budget.
        selected: List[Message] = []
        used_tokens = 0
        for msg in recent:
            estimated = int(len(msg.content.split()) * 1.4) + 4  # 4 for role/overhead
            if used_tokens + estimated > token_budget:
                break
            selected.append(msg)
            used_tokens += estimated

        # Reverse to chronological order for prompt construction.
        selected.reverse()
        return selected

    def get_all_for_conversation(self, conversation_id: int) -> List[Message]:
        """Return all messages ordered chronologically (for the detail view)."""
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
        )
        return list(self.db.scalars(stmt).all())
