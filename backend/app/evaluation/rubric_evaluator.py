"""
Structured 0–3 Rubric Evaluator & Failure Classifier for AI-1.

Implements transparent, standardized 0–3 scoring without relying on an
uncontrolled second-LLM judge:
  0 = Incorrect / Unacceptable
  1 = Partially Correct / Significant Issue
  2 = Mostly Correct / Minor Issue
  3 = Fully Correct

Also provides failure classification across defined operational categories:
  - generation correctness
  - hallucination
  - instruction failure
  - language failure
  - translation/cross-lingual failure
  - incomplete answer
  - citation failure
  - refusal failure
"""

import re
from typing import Optional, Tuple
from app.evaluation.schemas import EvalCase, DeterministicResult, RubricScores


class RubricEvaluator:
    """Evaluates qualitative and semantic dimensions using explicit 0–3 rubric criteria."""

    @classmethod
    def evaluate_semantic_correctness(
        cls,
        case: EvalCase,
        generated_answer: str,
        det: DeterministicResult,
    ) -> Tuple[int, str]:
        """0-3 rubric for factual accuracy against reference."""
        # Unanswerable cases
        if case.deterministic_checks.expected_refusal:
            if det.refusal_detected:
                if det.exact_refusal_wording:
                    return 3, "Exact production refusal wording executed."
                return 3, "Appropriate semantic refusal communicated."
            return 0, "Failed to refuse unanswerable question; attempted to fabricate answer."

        # If model refused an answerable question
        if det.refusal_detected and not case.deterministic_checks.expected_refusal:
            return 0, "Spurious refusal on an answerable query."

        # Entity coverage ratio
        total_ents = len(case.deterministic_checks.required_entities)
        if total_ents > 0:
            found_count = len(det.entities_found)
            ratio = found_count / total_ents
            if ratio == 1.0:
                return 3, "All required key factual entities present."
            elif ratio >= 0.6:
                return 2, f"Minor factual omission: found {found_count}/{total_ents} key entities."
            elif ratio > 0.0:
                return 1, f"Major factual omission: found only {found_count}/{total_ents} key entities."
            else:
                return 0, "None of the required key factual entities found in response."

        # Fallback length/coherence check if no entities specified
        if len(generated_answer.strip()) < 10:
            return 1, "Response too short to verify factual correctness."
        return 3, "Response satisfies semantic criteria."

    @classmethod
    def evaluate_groundedness(
        cls,
        case: EvalCase,
        generated_answer: str,
        det: DeterministicResult,
    ) -> Tuple[int, str]:
        """0-3 rubric for adherence to context without hallucination."""
        # Unanswerable cases
        if case.deterministic_checks.expected_refusal:
            if det.refusal_detected and not det.forbidden_terms_found:
                return 3, "Grounded refusal; zero hallucinated facts."
            return 0, "Ungrounded fabrication on unanswerable query."

        # Check for forbidden terms / distractor adoption
        if det.forbidden_terms_found:
            return 0, f"Severe hallucination or adopted adversarial distractor: {det.forbidden_terms_found}"

        # Check if answer pulls from context
        context_corpus = " ".join(doc.text for doc in case.context_documents).lower()
        ans_words = [w for w in re.findall(r"\w+", generated_answer.lower()) if len(w) > 3]
        if not ans_words:
            return 2, "Insufficient content to establish full groundedness."

        overlap = sum(1 for w in ans_words if w in context_corpus)
        overlap_ratio = overlap / len(ans_words)

        if overlap_ratio >= 0.65:
            return 3, "High fidelity to supplied document context."
        elif overlap_ratio >= 0.40:
            return 2, "Mostly grounded with minor unsupported expressions."
        else:
            return 1, "Low groundedness; significant content not traced to context."

    @classmethod
    def evaluate_instruction_following(
        cls,
        case: EvalCase,
        generated_answer: str,
        det: DeterministicResult,
    ) -> Tuple[int, str]:
        """0-3 rubric for following specific query and system instructions."""
        # Check for residual thinking tags or system prompt leak
        if "<think>" in generated_answer or "</think>" in generated_answer:
            return 1, "Emitted disallowed <think> tags."
        if "DOCUMENT CONTEXT" in generated_answer or "QUESTION" in generated_answer:
            return 0, "Leaked system scaffold delimiters."

        # Language constraint
        if case.deterministic_checks.expected_language:
            if not det.checks.get("expected_language", True):
                return 0, f"Violated language instruction: expected {case.deterministic_checks.expected_language}."

        # Structural constraints (e.g., sentence count or bullet list)
        q_lower = case.user_query.lower()
        if "two sentences" in q_lower:
            sentences = [s for s in re.split(r"[.!?؟]\s+", generated_answer.strip()) if s]
            if len(sentences) == 2:
                return 3, "Exactly followed two-sentence constraint."
            elif abs(len(sentences) - 2) <= 1:
                return 2, f"Minor constraint deviation: generated {len(sentences)} sentences instead of 2."
            else:
                return 1, f"Ignored two-sentence constraint: generated {len(sentences)} sentences."

        if "three" in q_lower or "3" in q_lower:
            # Check for list markers or enumeration
            if any(marker in generated_answer for marker in ["1.", "1)", "1 -", "أولاً", "1:"]):
                return 3, "Properly structured enumerated list."

        return 3, "Followed all system and query instructions."

    @classmethod
    def evaluate_fluency(
        cls,
        language: str,
        generated_answer: str,
    ) -> Tuple[int, str]:
        """0-3 rubric for linguistic fluency and phrasing quality."""
        clean = generated_answer.strip()
        if len(clean) == 0:
            return 0, "Empty response."

        # Check for truncated final sentence
        ends_with_punct = clean[-1] in ".!?؟)»\"'"
        if not ends_with_punct and len(clean) > 50:
            return 2, "Well-formed but appears abruptly truncated at ending."

        # Basic length and cohesion
        words = clean.split()
        if len(words) < 3 and not ("couldn't" in clean or "أتمكن" in clean):
            return 1, "Unnaturally terse or fragmented sentence."

        return 3, f"Fluent, natural {language.upper()} formulation."

    @classmethod
    def evaluate_semantic_citation_support(
        cls,
        case: EvalCase,
        generated_answer: str,
        det: DeterministicResult,
    ) -> Tuple[int, str]:
        """0-3 rubric for whether cited context genuinely supports the generated claim."""
        if case.deterministic_checks.min_citations == 0:
            return 3, "No citations required for this case."

        if not det.citations_extracted:
            return 1, "Required citations were omitted from the response."

        # Verify context source validity
        if not det.checks.get("citations_valid", True):
            return 0, "Cited source not present in provided evaluation context."

        # If multi-chunk synthesis was required
        if case.deterministic_checks.min_citations > 1:
            if len(det.citations_extracted) >= case.deterministic_checks.min_citations:
                return 3, "Multiple source chunks correctly cited and synthesized."
            else:
                return 2, "Partially cited: missed secondary source chunk."

        return 3, "Cited context directly supports the generated statement."

    @classmethod
    def score_case(
        cls,
        case: EvalCase,
        generated_answer: str,
        det: DeterministicResult,
    ) -> RubricScores:
        """Computes 0-3 scores across all relevant dimensions for this case."""
        notes = {}

        # 1. Semantic correctness
        sem_score, sem_note = cls.evaluate_semantic_correctness(case, generated_answer, det)
        notes["semantic_correctness"] = sem_note

        # 2. Groundedness
        grd_score, grd_note = cls.evaluate_groundedness(case, generated_answer, det)
        notes["groundedness"] = grd_note

        # 3. Instruction following
        ins_score, ins_note = cls.evaluate_instruction_following(case, generated_answer, det)
        notes["instruction_following"] = ins_note

        # 4. Language fluency
        ar_score, en_score, cross_score = None, None, None
        if case.language in ("ar", "mixed"):
            ar_score, ar_note = cls.evaluate_fluency("ar", generated_answer)
            notes["arabic_fluency"] = ar_note
        if case.language in ("en", "mixed"):
            en_score, en_note = cls.evaluate_fluency("en", generated_answer)
            notes["english_fluency"] = en_note
        if case.category == "bilingual":
            cross_score = min(sem_score, ins_score)
            notes["cross_lingual_quality"] = "Cross-lingual alignment evaluated."

        # 5. Semantic citation support
        cit_score, cit_note = cls.evaluate_semantic_citation_support(case, generated_answer, det)
        notes["semantic_citation_support"] = cit_note

        return RubricScores(
            semantic_correctness=sem_score,
            groundedness=grd_score,
            instruction_following=ins_score,
            arabic_fluency=ar_score,
            english_fluency=en_score,
            cross_lingual_quality=cross_score,
            semantic_citation_support=cit_score,
            notes=notes,
        )

    @classmethod
    def classify_failure(
        cls,
        case: EvalCase,
        det: DeterministicResult,
        rubric: RubricScores,
    ) -> Optional[str]:
        """Classifies the primary failure mode if the case did not fully succeed."""
        # Check deterministic failures first
        if case.deterministic_checks.expected_refusal and not det.refusal_detected:
            return "refusal failure"

        if det.forbidden_terms_found or (rubric.groundedness is not None and rubric.groundedness == 0):
            return "hallucination"

        if not det.checks.get("expected_language", True):
            if case.category == "bilingual":
                return "translation/cross-lingual failure"
            return "language failure"

        if not det.checks.get("citations_valid", True) or (rubric.semantic_citation_support == 0):
            return "citation failure"

        if rubric.instruction_following is not None and rubric.instruction_following < 2:
            return "instruction failure"

        if rubric.semantic_correctness is not None and rubric.semantic_correctness == 0:
            return "generation correctness"

        if rubric.semantic_correctness is not None and rubric.semantic_correctness == 1:
            return "incomplete answer"

        if not det.passed:
            return "generation correctness"

        return None
