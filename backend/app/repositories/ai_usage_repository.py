"""
AIUsageRepository — Append-Only Data Access & Accounting for the AI Usage Ledger.

Durable PostgreSQL AI Usage Ledger (AI-8 Phase C.1):
- Enforces frozen accounting policy:
  * Quota-bearing: RAG_ASK, RAG_STREAM, RAG_CONV_ASK, RAG_CONV_STREAM
  * Non-quota: QUERY_REWRITE, QUERY_EXPANSION, TITLE_GENERATION, EVALUATION, WARMUP
- Enforces token contract: EXACT (exact prompt, completion, total tokens) vs UNAVAILABLE (NULL tokens)
- Enforces uniqueness / idempotency: duplicate settlement prevention via unique idempotency_key
- Enforces tenant attribution: quota-bearing events require organization_id
"""

import datetime
import uuid as py_uuid
from typing import Any, Dict, List, Optional, Tuple, Union
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.models.ai_usage_event import (
    AIUsageEvent,
    AIUsageEventType,
    AIUsageStatus,
    QUOTA_BEARING_EVENT_TYPES,
)


class DuplicateUsageEventError(Exception):
    """Raised when an AI usage event with an already existing idempotency_key is attempted."""

    def __init__(self, idempotency_key: str, message: Optional[str] = None):
        self.idempotency_key = idempotency_key
        super().__init__(
            message
            or f"AI usage event with idempotency_key '{idempotency_key}' already exists in ledger."
        )


class AIUsageRepository:
    def __init__(self, db: Session):
        self.db = db

    def create_event(
        self,
        event_type: Union[AIUsageEventType, str],
        idempotency_key: str,
        organization_id: Optional[int] = None,
        user_id: Optional[int] = None,
        request_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        status: Union[AIUsageStatus, str] = AIUsageStatus.EXACT,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
        total_tokens: Optional[int] = None,
        is_quota_bearing: Optional[bool] = None,
        commit: bool = True,
    ) -> AIUsageEvent:
        """
        Records an authoritative usage event to the durable PostgreSQL ledger.

        Enforces:
        - Quota-bearing categorization rule
        - Tenant attribution invariant (quota-bearing requires organization_id)
        - Token accounting contract (EXACT vs UNAVAILABLE)
        - Idempotency uniqueness boundary (raises DuplicateUsageEventError on duplicate)
        """
        # Normalize enums to string values
        str_event_type = event_type.value if isinstance(event_type, AIUsageEventType) else str(event_type)
        str_status = status.value if isinstance(status, AIUsageStatus) else str(status)

        # 1. Determine is_quota_bearing if not explicitly supplied
        expected_quota = str_event_type in QUOTA_BEARING_EVENT_TYPES
        if is_quota_bearing is None:
            is_quota_bearing = expected_quota

        # 2. Enforce bidirectional quota policy
        if is_quota_bearing != expected_quota:
            if expected_quota:
                raise ValueError(
                    f"RAG event type '{str_event_type}' must be quota-bearing (is_quota_bearing=True)."
                )
            else:
                raise ValueError(
                    f"Internal event type '{str_event_type}' cannot be marked quota-bearing (is_quota_bearing=False required)."
                )

        # 3. Enforce tenant attribution invariant
        if is_quota_bearing and organization_id is None:
            raise ValueError("Quota-bearing AI usage events require an organization_id.")

        # 4. Enforce Token Contract per Status
        if str_status == AIUsageStatus.EXACT.value:
            if prompt_tokens is None or completion_tokens is None:
                raise ValueError("EXACT usage events require non-null prompt_tokens and completion_tokens.")
            if prompt_tokens < 0 or completion_tokens < 0:
                raise ValueError("Token counts must be non-negative integers.")
            calculated_total = prompt_tokens + completion_tokens
            if total_tokens is not None and total_tokens != calculated_total:
                raise ValueError(
                    f"Inconsistent total_tokens: provided {total_tokens}, but prompt ({prompt_tokens}) "
                    f"+ completion ({completion_tokens}) = {calculated_total}."
                )
            final_total_tokens = calculated_total
            is_exact = True

        elif str_status == AIUsageStatus.UNAVAILABLE.value:
            if prompt_tokens is not None or completion_tokens is not None or total_tokens is not None:
                raise ValueError(
                    "UNAVAILABLE usage events must not record token counts (tokens must be NULL, never zero)."
                )
            final_total_tokens = None
            is_exact = False
        else:
            raise ValueError(f"Invalid AIUsageStatus '{str_status}'. Must be EXACT or UNAVAILABLE.")

        # 5. Construct and persist event
        event = AIUsageEvent(
            idempotency_key=idempotency_key,
            organization_id=organization_id,
            user_id=user_id,
            request_id=request_id,
            correlation_id=correlation_id,
            event_type=str_event_type,
            is_quota_bearing=is_quota_bearing,
            status=str_status,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=final_total_tokens,
            is_exact=is_exact,
        )

        try:
            self.db.add(event)
            if commit:
                self.db.commit()
                self.db.refresh(event)
            else:
                self.db.flush()
            return event
        except IntegrityError as exc:
            self.db.rollback()
            # Check if failure is due to idempotency_key collision
            if "idempotency_key" in str(exc).lower() or "unique" in str(exc).lower():
                raise DuplicateUsageEventError(idempotency_key) from exc
            raise

    def get_by_id(self, event_id: int) -> Optional[AIUsageEvent]:
        """Look up event by internal serial primary key."""
        return self.db.query(AIUsageEvent).filter(AIUsageEvent.id == event_id).first()

    def get_by_uuid(self, event_uuid: Union[py_uuid.UUID, str]) -> Optional[AIUsageEvent]:
        """Look up event by public UUID."""
        if isinstance(event_uuid, str):
            try:
                event_uuid = py_uuid.UUID(event_uuid)
            except (ValueError, TypeError):
                return None
        return self.db.query(AIUsageEvent).filter(AIUsageEvent.uuid == event_uuid).first()

    def get_by_idempotency_key(self, idempotency_key: str) -> Optional[AIUsageEvent]:
        """Look up event by authoritative idempotency key."""
        return self.db.query(AIUsageEvent).filter(AIUsageEvent.idempotency_key == idempotency_key).first()

    def get_monthly_usage_sum(
        self,
        organization_id: int,
        start_date: datetime.datetime,
        end_date: datetime.datetime,
    ) -> int:
        """
        Calculates authoritative total consumed tokens for an organization within a date window.
        Only counts exact, quota-bearing usage events.
        """
        total = (
            self.db.query(func.coalesce(func.sum(AIUsageEvent.total_tokens), 0))
            .filter(
                AIUsageEvent.organization_id == organization_id,
                AIUsageEvent.is_quota_bearing.is_(True),
                AIUsageEvent.status == AIUsageStatus.EXACT.value,
                AIUsageEvent.created_at >= start_date,
                AIUsageEvent.created_at < end_date,
            )
            .scalar()
        )
        return int(total or 0)

    def get_organization_usage_summary(
        self,
        organization_id: int,
        start_date: datetime.datetime,
        end_date: datetime.datetime,
    ) -> Dict[str, Any]:
        """
        Summarizes authoritative quota and observability metrics for an organization over a date window.
        """
        row = (
            self.db.query(
                func.coalesce(func.sum(AIUsageEvent.total_tokens), 0).label("total_tokens"),
                func.coalesce(func.sum(AIUsageEvent.prompt_tokens), 0).label("prompt_tokens"),
                func.coalesce(func.sum(AIUsageEvent.completion_tokens), 0).label("completion_tokens"),
                func.count(AIUsageEvent.id).label("event_count"),
            )
            .filter(
                AIUsageEvent.organization_id == organization_id,
                AIUsageEvent.is_quota_bearing.is_(True),
                AIUsageEvent.status == AIUsageStatus.EXACT.value,
                AIUsageEvent.created_at >= start_date,
                AIUsageEvent.created_at < end_date,
            )
            .first()
        )

        unavailable_count = (
            self.db.query(func.count(AIUsageEvent.id))
            .filter(
                AIUsageEvent.organization_id == organization_id,
                AIUsageEvent.status == AIUsageStatus.UNAVAILABLE.value,
                AIUsageEvent.created_at >= start_date,
                AIUsageEvent.created_at < end_date,
            )
            .scalar()
        )

        return {
            "organization_id": organization_id,
            "start_date": start_date,
            "end_date": end_date,
            "total_tokens": int(row.total_tokens if row else 0),
            "prompt_tokens": int(row.prompt_tokens if row else 0),
            "completion_tokens": int(row.completion_tokens if row else 0),
            "exact_events_count": int(row.event_count if row else 0),
            "unavailable_events_count": int(unavailable_count or 0),
        }

    def list_events(
        self,
        organization_id: Optional[int] = None,
        event_type: Optional[str] = None,
        is_quota_bearing: Optional[bool] = None,
        status: Optional[str] = None,
        start_date: Optional[datetime.datetime] = None,
        end_date: Optional[datetime.datetime] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Tuple[List[AIUsageEvent], int]:
        """Paginated search for AI usage ledger events."""
        query = self.db.query(AIUsageEvent)

        if organization_id is not None:
            query = query.filter(AIUsageEvent.organization_id == organization_id)
        if event_type is not None:
            query = query.filter(AIUsageEvent.event_type == event_type)
        if is_quota_bearing is not None:
            query = query.filter(AIUsageEvent.is_quota_bearing == is_quota_bearing)
        if status is not None:
            query = query.filter(AIUsageEvent.status == status)
        if start_date is not None:
            query = query.filter(AIUsageEvent.created_at >= start_date)
        if end_date is not None:
            query = query.filter(AIUsageEvent.created_at <= end_date)

        total = query.count()
        results = (
            query.order_by(AIUsageEvent.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return results, total
