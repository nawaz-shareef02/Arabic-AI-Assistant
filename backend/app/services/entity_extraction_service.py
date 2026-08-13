"""
EntityExtractionService — Modular Bilingual Entity Extraction.

Architecture
------------
- BaseEntityExtractor (Abstract Base Interface)
- RegexExtractor (Emails, Phones, Dates, URLs, Technical Frameworks)
- ArabicRulesExtractor (Arabic Companies, Locations, Organizations, Names)
- SpacyExtractor (spaCy NER fallback / heuristic capitalized NER)
- EntityExtractionService (Pipeline Orchestrator)
"""

import re
import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Set

logger = logging.getLogger(__name__)


class BaseEntityExtractor(ABC):
    """Abstract interface for modular entity extractors."""

    @abstractmethod
    def extract(self, text: str) -> List[Dict[str, Any]]:
        """Extract entities from input text."""
        ...


class RegexExtractor(BaseEntityExtractor):
    """Regex-based extractor for Emails, Phone Numbers, Dates, URLs, and Frameworks."""

    def __init__(self):
        self.patterns = {
            "EMAIL": (r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", "EN"),
            "PHONE": (r"\+?\d{1,4}?[-.\s]?\(?\d{1,3}?\)?[-.\s]?\d{1,4}[-.\s]?\d{1,4}[-.\s]?\d{1,9}", "EN"),
            "DATE": (r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b|\b\d{1,2}[-/]\d{1,2}[-/]\d{4}\b", "EN"),
            "TECHNOLOGY": (r"\b(FastAPI|PostgreSQL|Qdrant|Redis|Python|Docker|Next\.js|TypeScript|React|Tailwind|Ollama|Qwen|PyTorch|TensorFlow|BERT)\b", "EN"),
        }

    def extract(self, text: str) -> List[Dict[str, Any]]:
        entities = []
        for entity_type, (pattern, lang) in self.patterns.items():
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                matched_text = match.group(0).strip()
                if len(matched_text) >= 3:
                    entities.append({
                        "text": matched_text,
                        "type": entity_type,
                        "language": lang,
                        "confidence": 0.95
                    })
        return entities


class ArabicRulesExtractor(BaseEntityExtractor):
    """Rule-based extractor for Arabic Person names, Companies, Locations, and Organizations."""

    def __init__(self):
        self.org_prefixes = ["شركة", "مؤسسة", "جامعة", "وزارة", "هيئة", "منظمة", "مركز", "معهد"]
        self.loc_prefixes = ["مدينة", "دولة", "مملكة", "إمارة", "محافظة", "رياض", "دبي", "القاهرة", "جدة", "أبوظبي"]

    def extract(self, text: str) -> List[Dict[str, Any]]:
        entities = []
        words = text.split()
        
        for i, word in enumerate(words):
            clean_word = word.strip(".,!?:;\"'")
            if clean_word in self.org_prefixes and i + 1 < len(words):
                org_name = f"{clean_word} {words[i+1]}".strip(".,!?:;\"'")
                if i + 2 < len(words) and words[i+2][0].isupper() or len(words[i+2]) > 2:
                    org_name += f" {words[i+2]}".strip(".,!?:;\"'")
                entities.append({
                    "text": org_name,
                    "type": "ORGANIZATION",
                    "language": "AR",
                    "confidence": 0.85
                })
            elif clean_word in self.loc_prefixes:
                loc_name = clean_word
                if i + 1 < len(words) and len(words[i+1]) > 2:
                    loc_name += f" {words[i+1]}".strip(".,!?:;\"'")
                entities.append({
                    "text": loc_name,
                    "type": "LOCATION",
                    "language": "AR",
                    "confidence": 0.85
                })

        return entities


class SpacyExtractor(BaseEntityExtractor):
    """Heuristic Capitalized / Title NER Extractor for English People, Companies, and Products."""

    def extract(self, text: str) -> List[Dict[str, Any]]:
        entities = []
        # Capitalized multi-word sequences
        cap_matches = re.finditer(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b", text)
        for match in cap_matches:
            matched_text = match.group(0).strip()
            if matched_text not in ["ArabIQ Platform", "Document Ingestion"]:
                entities.append({
                    "text": matched_text,
                    "type": "ORGANIZATION" if any(w in matched_text for w in ["Corp", "Inc", "Ltd", "Group", "AI", "Lab", "Platform"]) else "PERSON",
                    "language": "EN",
                    "confidence": 0.80
                })
        return entities


class EntityExtractionService:
    """Pipeline orchestrator running modular extractors."""

    def __init__(self, extractors: List[BaseEntityExtractor] | None = None):
        self.extractors = extractors or [
            RegexExtractor(),
            ArabicRulesExtractor(),
            SpacyExtractor()
        ]

    def extract_entities(self, text: str) -> List[Dict[str, Any]]:
        raw_entities: List[Dict[str, Any]] = []
        for extractor in self.extractors:
            try:
                extracted = extractor.extract(text)
                raw_entities.extend(extracted)
            except Exception as e:
                logger.warning(f"Extractor {extractor.__class__.__name__} failed: {e}")

        # Deduplicate entities by (lowercase text, entity_type)
        seen: Set[str] = set()
        deduped: List[Dict[str, Any]] = []
        for item in raw_entities:
            key = f"{item['text'].lower()}:{item['type']}"
            if key not in seen:
                seen.add(key)
                deduped.append(item)

        return deduped
