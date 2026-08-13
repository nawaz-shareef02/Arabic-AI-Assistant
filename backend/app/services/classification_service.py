"""
ClassificationService — Strategy-Based Knowledge Document Classification.

Architecture
------------
- BaseClassificationStrategy (Abstract Base)
- RuleEngineStrategy (Current Implementation: Rule & Keyword Matching)
- MLClassificationStrategy / LLMClassificationStrategy (Pluggable Future Interfaces)
- ClassificationService (Facade)

Supported Categories
--------------------
- Policies
- Contracts
- HR
- Engineering
- Finance
- Legal
- Research
- Manuals
- Technical Documentation
"""

import logging
from abc import ABC, abstractmethod
from typing import List, Dict

logger = logging.getLogger(__name__)

VALID_CLASSIFICATIONS = [
    "Policies",
    "Contracts",
    "HR",
    "Engineering",
    "Finance",
    "Legal",
    "Research",
    "Manuals",
    "Technical Documentation",
]


class BaseClassificationStrategy(ABC):
    """Abstract interface for classification strategies."""

    @abstractmethod
    def classify(self, text: str, filename: str = "") -> str:
        """Classify document content and filename into a domain category."""
        ...


class RuleEngineStrategy(BaseClassificationStrategy):
    """Rule & Keyword-based classification strategy."""

    def __init__(self):
        self.rules: Dict[str, List[str]] = {
            "Policies": [
                "policy", "policies", "procedure", "guideline", "governance",
                "سياسة", "سياسات", "إجراءات", "حوكمة", "ضوابط"
            ],
            "Contracts": [
                "contract", "agreement", "lease", "vendor", "nda", "terms of service",
                "عقد", "اتفاقية", "شروط", "التزام", "مورد"
            ],
            "HR": [
                "hr", "human resources", "employee", "onboarding", "payroll", "benefits", "vacation",
                "الموارد البشرية", "موظف", "رواتب", "إجازات", "مزايا"
            ],
            "Engineering": [
                "architecture", "software", "api", "database", "infrastructure", "backend", "code", "devops",
                "هندسة", "برمجيات", "قواعد بيانات", "تطوير", "شفرة"
            ],
            "Finance": [
                "invoice", "budget", "financial", "revenue", "expense", "tax", "audit",
                "مالية", "ميزانية", "فاتورة", "إيرادات", "مصروفات", "ضرائب"
            ],
            "Legal": [
                "compliance", "regulation", "statute", "legal", "liability", "dispute",
                "قانون", "قانوني", "امتثال", "تشريعات", "نزاع"
            ],
            "Research": [
                "paper", "experiment", "study", "analysis", "methodology", "dataset",
                "بحث", "دراسة", "تحليل", "تجربة", "منهجية"
            ],
            "Manuals": [
                "manual", "user guide", "handbook", "instruction", "how-to",
                "دليل", "إرشادات", "كتيب", "تعليمات"
            ],
            "Technical Documentation": [
                "specification", "doc", "documentation", "system", "readme", "config",
                "مواصفات", "توثيق", "نظام", "إعدادات"
            ]
        }

    def classify(self, text: str, filename: str = "") -> str:
        content_lower = f"{filename} {text[:3000]}".lower()

        scores: Dict[str, int] = {cat: 0 for cat in VALID_CLASSIFICATIONS}
        for category, keywords in self.rules.items():
            for kw in keywords:
                if kw in content_lower:
                    scores[category] += 1

        best_category = max(scores, key=lambda k: scores[k])
        if scores[best_category] > 0:
            return best_category

        return "Technical Documentation"


class ClassificationService:
    """Facade for Document Knowledge Classification."""

    def __init__(self, strategy: BaseClassificationStrategy | None = None):
        self.strategy = strategy or RuleEngineStrategy()

    def classify_document(self, text: str, filename: str = "") -> str:
        """Classify parsed document text into a standardized category."""
        category = self.strategy.classify(text, filename)
        logger.debug(f"ClassificationService: '{filename}' → {category}")
        return category
