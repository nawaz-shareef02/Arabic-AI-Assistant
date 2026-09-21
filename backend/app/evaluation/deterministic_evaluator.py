"""
Deterministic Evaluator for AI-1.

Implements genuinely deterministic, rule-based verification:
1. Entity, date, and number presence (with Arabic normalization)
2. Forbidden term absence
3. Language verification (Arabic vs Latin character distribution)
4. Refusal detection (distinguishing appropriate refusal vs exact production wording)
5. Citation existence, syntax matching, and source context membership
"""

import re
import unicodedata
from typing import List, Tuple

from app.evaluation.schemas import EvalCase, DeterministicResult


def normalize_arabic(text: str) -> str:
    """Normalize common Arabic orthographic variations for robust string matching."""
    # Normalize unicode composition
    text = unicodedata.normalize("NFKD", text)
    # Remove tashkeel (diacritics)
    text = re.sub(r"[\u064B-\u065F\u0670]", "", text)
    # Normalize alef variants to bare alef
    text = re.sub(r"[إأآا]", "ا", text)
    # Normalize taa marbuta to haa
    text = re.sub(r"ة", "ه", text)
    # Normalize alif maqsura to yaa
    text = re.sub(r"ى", "ي", text)
    return text


class DeterministicEvaluator:
    """Automated deterministic evaluator for controlled generation outputs."""

    # Regex for standard citation patterns: [Source: file.pdf] or [المصدر: file.pdf]
    CITATION_PATTERNS = [
        re.compile(r"\[(?:Source|المصدر):\s*([^\]]+)\]", re.IGNORECASE),
        re.compile(r"\((?:Source|المصدر):\s*([^\)]+)\)", re.IGNORECASE),
    ]

    # Exact production refusal defined in PromptBuilder.SYSTEM_PROMPT
    EXACT_PRODUCTION_REFUSAL = "I couldn't find enough information in the uploaded documents."

    # Semantic refusal phrases recognized in Arabic and English
    REFUSAL_PHRASES = [
        "couldn't find enough information",
        "could not find enough information",
        "does not contain enough information",
        "not enough information in the uploaded documents",
        "insufficient information",
        "information is not provided",
        "no information provided",
        "لم أتمكن من العثور على معلومات كافية",
        "لا توجد معلومات كافية",
        "لا يحتوي المستند على",
        "لم يرد في المستند",
        "لا تتوفر معلومات كافية",
        "لم يذكر المستند",
        "لم تذكر الوثيقة",
        "المعلومات غير متوفرة",
    ]

    @classmethod
    def detect_language(cls, text: str) -> str:
        """Determines dominant script: 'ar' (Arabic), 'en' (English), or 'mixed'."""
        arabic_chars = len(re.findall(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]", text))
        latin_chars = len(re.findall(r"[a-zA-Z]", text))
        total = arabic_chars + latin_chars

        if total == 0:
            return "unknown"
        if arabic_chars / total >= 0.55:
            return "ar"
        if latin_chars / total >= 0.55:
            return "en"
        return "mixed"

    @classmethod
    def extract_citations(cls, text: str) -> List[str]:
        """Extracts cited source names/IDs from text using citation regex patterns."""
        citations = []
        for pattern in cls.CITATION_PATTERNS:
            matches = pattern.findall(text)
            for m in matches:
                clean = m.strip()
                if clean and clean not in citations:
                    citations.append(clean)
        return citations

    # Narrow, justified deterministic semantic equivalences (currencies, unit variations, obvious domain synonyms)
    ENTITY_EQUIVALENCES: dict[str, List[str]] = {
        "sar": ["saudi riyals", "saudi riyal", "ريال سعودي", "ريال", "ر.س"],
        "saudi riyals": ["sar", "ريال سعودي", "ريال"],
        "usd": ["$", "dollars", "دولار"],
        "$": ["usd", "dollars", "دولار"],
        "gbp": ["£", "pounds", "جنيه إسترليني"],
        "£": ["gbp", "pounds"],
        "10 أسابيع": ["70 يوما", "70 يوم", "عشرة أسابيع", "عشرة اسابيع"],
        "عشرة أسابيع": ["70 يوما", "70 يوم", "10 أسابيع", "10 اسابيع"],
        "أربعة أشهر وعشرة أيام": ["130 يوما", "130 يوم"],
        "الموافقة": ["موافقة", "موافقه"],
        "الثلاثين": ["30", "ثلاثين"],
        "ستين": ["60"],
        "general assembly": ["annual general meeting", "agm"],
    }

    @classmethod
    def check_entities(cls, text: str, required_entities: List[str]) -> Tuple[bool, List[str], List[str]]:
        """Verifies presence of required entity strings with multilingual normalization and narrow semantic equivalence."""
        if not required_entities:
            return True, [], []

        found = []
        missing = []
        norm_text = normalize_arabic(text.lower())

        for ent in required_entities:
            norm_ent = normalize_arabic(ent.lower().strip())
            # 1. Direct normalized match
            if norm_ent in norm_text:
                found.append(ent)
                continue

            # 2. Check narrow deterministic equivalences/aliases
            matched_alias = False
            for k, v in cls.ENTITY_EQUIVALENCES.items():
                if normalize_arabic(k.lower().strip()) == norm_ent:
                    if any(normalize_arabic(alias.lower().strip()) in norm_text for alias in v):
                        matched_alias = True
                        break
            if matched_alias:
                found.append(ent)
            else:
                missing.append(ent)

        return len(missing) == 0, found, missing



    @classmethod
    def check_forbidden_terms(cls, text: str, forbidden_terms: List[str]) -> Tuple[bool, List[str]]:
        """Verifies absence of forbidden strings (hallucinations, leaks, injection keywords)."""
        if not forbidden_terms:
            return True, []

        found = []
        norm_text = normalize_arabic(text.lower())
        for term in forbidden_terms:
            norm_term = normalize_arabic(term.lower())
            if norm_term in norm_text:
                found.append(term)

        return len(found) == 0, found

    @classmethod
    def check_refusal(cls, text: str) -> Tuple[bool, bool]:
        """
        Distinguishes:
        - refusal_detected: whether the answer appropriately communicates inability to answer due to missing context.
        - exact_refusal_wording: whether the exact production system instruction was matched.
        """
        exact_wording = cls.EXACT_PRODUCTION_REFUSAL.lower() in text.lower()

        detected = exact_wording
        if not detected:
            norm_text = normalize_arabic(text.lower())
            for phrase in cls.REFUSAL_PHRASES:
                if normalize_arabic(phrase.lower()) in norm_text:
                    detected = True
                    break

        return detected, exact_wording

    @classmethod
    def check_citations(
        cls,
        extracted_citations: List[str],
        valid_source_ids: List[str],
        min_citations: int,
    ) -> Tuple[bool, List[str]]:
        """
        Validates:
        1. At least min_citations extracted.
        2. All extracted citations match one of valid_source_ids.
        """
        reasons = []
        if len(extracted_citations) < min_citations:
            reasons.append(f"Extracted {len(extracted_citations)} citations, expected at least {min_citations}.")

        # Check source membership
        norm_valid = [v.lower().strip() for v in valid_source_ids]
        for cit in extracted_citations:
            cit_lower = cit.lower().strip()
            # Match either exact or basename substring
            matched = any(cit_lower == v or cit_lower in v or v in cit_lower for v in norm_valid)
            if not matched and valid_source_ids:
                reasons.append(f"Cited source '{cit}' not found in valid evaluation context documents.")

        return len(reasons) == 0, reasons

    @classmethod
    def evaluate(cls, case: EvalCase, generated_answer: str) -> DeterministicResult:
        """Runs the complete suite of deterministic checks on the generated answer."""
        spec = case.deterministic_checks
        checks: dict[str, bool] = {}
        failure_reasons: List[str] = []

        # 1. Refusal check
        refusal_detected, exact_refusal = cls.check_refusal(generated_answer)
        if spec.expected_refusal:
            checks["refusal_appropriate"] = refusal_detected
            checks["exact_refusal_wording"] = exact_refusal
            if not refusal_detected:
                failure_reasons.append("Expected unanswerable refusal, but model attempted to answer.")
        else:
            checks["refusal_appropriate"] = True
            checks["exact_refusal_wording"] = exact_refusal
            # If answer was expected to be answerable but model refused (exempt adversarial cases where refusal is acceptable)
            if refusal_detected and case.category != "adversarial":
                checks["spurious_refusal"] = False
                failure_reasons.append("Model refused unexpectedly on an answerable query.")
            else:
                checks["spurious_refusal"] = True

        # 2. Entity presence check
        if spec.required_entities and not spec.expected_refusal:
            ent_passed, found_ents, missing_ents = cls.check_entities(generated_answer, spec.required_entities)
            checks["required_entities"] = ent_passed
            if not ent_passed:
                failure_reasons.append(f"Missing required entities: {missing_ents}")
        else:
            found_ents, missing_ents = [], []
            checks["required_entities"] = True

        # 3. Forbidden terms check
        forb_passed, found_forb = cls.check_forbidden_terms(generated_answer, spec.forbidden_terms)
        checks["forbidden_terms"] = forb_passed
        if not forb_passed:
            failure_reasons.append(f"Found forbidden terms/hallucinations: {found_forb}")

        # 4. Language detection check
        lang_detected = cls.detect_language(generated_answer)
        if spec.expected_language:
            # If an exact production refusal wording was emitted (which is defined in English),
            # do not penalize it as a language mismatch.
            if spec.expected_refusal and exact_refusal:
                lang_match = True
            else:
                lang_match = (lang_detected == spec.expected_language) or (spec.expected_language == "mixed")
            checks["expected_language"] = lang_match
            if not lang_match:
                failure_reasons.append(f"Expected language '{spec.expected_language}', detected '{lang_detected}'.")
        else:
            checks["expected_language"] = True

        # 5. Citation validation
        extracted_cits = cls.extract_citations(generated_answer)
        if spec.min_citations > 0:
            cit_passed, cit_reasons = cls.check_citations(extracted_cits, spec.valid_source_ids, spec.min_citations)
            checks["citations_valid"] = cit_passed
            if not cit_passed:
                failure_reasons.extend(cit_reasons)
        else:
            checks["citations_valid"] = True

        all_passed = len(failure_reasons) == 0

        return DeterministicResult(
            passed=all_passed,
            checks=checks,
            failure_reasons=failure_reasons,
            citations_extracted=extracted_cits,
            refusal_detected=refusal_detected,
            exact_refusal_wording=exact_refusal,
            language_detected=lang_detected,
            entities_found=found_ents,
            entities_missing=missing_ents,
            forbidden_terms_found=found_forb,
        )
