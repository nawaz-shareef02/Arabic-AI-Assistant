"""
PromptSecurityService — Refinements #5, #6 & #11:
Modular AI Security Pipeline with Prompt Risk Scoring & Knowledge Access Validation.
"""

import re
import logging
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session

from app.models.user import User
from app.core.security_metrics import security_metrics
from app.services.audit_event_publisher import AuditEventPublisher

logger = logging.getLogger("app.services.prompt_security_service")

# Prompt injection & instruction override regex patterns
INJECTION_PATTERNS = [
    r"ignore (all )?previous instructions",
    r"disregard (all )?above",
    r"system prompt",
    r"you are now (an?|in) (unrestricted|admin|god) mode",
    r"reveal (your|the) (hidden|system) prompt",
    r"override (system|safety) rules",
    r"\[SYSTEM INSTRUCTION\]",
    r"---BEGIN SYSTEM---",
]


class InputSanitizer:
    @staticmethod
    def sanitize(prompt: str) -> str:
        # Strip control characters & excessive whitespace
        cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", prompt)
        return cleaned.strip()


class PromptInjectionDetector:
    @staticmethod
    def evaluate(prompt: str) -> float:
        score = 0.0
        prompt_lower = prompt.lower()

        for pattern in INJECTION_PATTERNS:
            if re.search(pattern, prompt_lower):
                score += 0.40

        if len(prompt) > 4000:
            score += 0.20

        return min(1.0, score)


class KnowledgeAccessValidator:
    """Refinement #11: Validates user permissions against target Knowledge Base."""
    @staticmethod
    def validate_access(user: User, kb_id: Optional[int], db: Session) -> bool:
        if not kb_id:
            return True
        from app.repositories.permission_repository import PermissionRepository
        from app.models.knowledge_base import KnowledgeBase

        kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
        if not kb:
            return False

        # Validate multi-tenant org boundary
        user_orgs = [m.organization_id for m in user.organization_memberships]
        if kb.organization_id not in user_orgs:
            return False

        return True


class PromptSecurityService:
    def __init__(self, db: Session):
        self.db = db
        self.publisher = AuditEventPublisher(db)

    def process_prompt(
        self,
        prompt: str,
        user: User,
        kb_id: Optional[int] = None,
        org_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Runs full modular AI Prompt Security Pipeline."""
        # 1. Input Sanitization
        clean_prompt = InputSanitizer.sanitize(prompt)

        # 2. Prompt Injection Detection & Risk Scoring
        risk_score = PromptInjectionDetector.evaluate(clean_prompt)

        # 3. Knowledge Access Validation (Refinement #11)
        access_granted = KnowledgeAccessValidator.validate_access(user, kb_id, self.db)
        if not access_granted:
            security_metrics.increment("prompt_injection_detections")
            self.publisher.publish_event(
                action="Unauthorized KB Access Blocked",
                resource_type="KnowledgeBase",
                category="Security",
                user_id=user.id,
                organization_id=org_id,
                status="denied",
                metadata_json={"kb_id": kb_id, "severity": "HIGH"},
            )
            return {
                "decision": "DENIED",
                "reason": "Unauthorized knowledge base access.",
                "risk_score": 1.0,
                "sanitized_prompt": "",
                "severity": "HIGH",
            }

        # 4. Prompt Risk Scoring Threshold
        severity = "LOW"
        if risk_score >= 0.70:
            severity = "CRITICAL" if risk_score >= 0.90 else "HIGH"
            security_metrics.increment("prompt_injection_detections")
            self.publisher.publish_event(
                action="Prompt Injection Detected",
                resource_type="Prompt",
                category="Security",
                user_id=user.id,
                organization_id=org_id,
                status="blocked",
                metadata_json={"risk_score": risk_score, "severity": severity, "prompt_snippet": clean_prompt[:100]},
            )
            return {
                "decision": "BLOCKED",
                "reason": "Prompt injection / instruction override pattern detected.",
                "risk_score": risk_score,
                "sanitized_prompt": "",
                "severity": severity,
            }
        elif risk_score >= 0.40:
            severity = "MEDIUM"

        return {
            "decision": "ALLOWED",
            "reason": "Safe prompt",
            "risk_score": risk_score,
            "sanitized_prompt": clean_prompt,
            "severity": severity,
        }
