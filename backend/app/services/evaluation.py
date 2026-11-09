"""Pure helpers shared by offline RAG quality and capacity checks."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


def percentile(values: list[float], percentile_value: float) -> float:
    """Return a linearly interpolated percentile for a non-empty sample."""

    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * percentile_value / 100
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)


def normalize_text(value: str) -> str:
    return "".join(value.casefold().split())


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    case_id: str
    question: str
    expected_documents: tuple[str, ...]
    required_answer_terms: tuple[str, ...]
    expect_answerable: bool

    @classmethod
    def from_dict(cls, value: dict[str, Any], *, line_number: int) -> EvaluationCase:
        case_id = str(value.get("id") or f"line-{line_number}").strip()
        question = str(value.get("question") or "").strip()
        expected = tuple(
            str(item).strip() for item in value.get("expected_documents", []) if str(item).strip()
        )
        terms = tuple(
            str(item).strip() for item in value.get("required_answer_terms", []) if str(item).strip()
        )
        answerable = bool(value.get("expect_answerable", True))
        if not question:
            raise ValueError(f"第 {line_number} 行缺少 question")
        if answerable and not expected:
            raise ValueError(f"第 {line_number} 行为可回答问题，但 expected_documents 为空")
        return cls(case_id, question, expected, terms, answerable)


def evaluate_chat_response(case: EvaluationCase, response: dict[str, Any], *, top_k: int) -> dict[str, Any]:
    choices = response.get("choices") or []
    message = choices[0].get("message", {}) if choices else {}
    answer = str(message.get("content") or "")
    rag = response.get("x_rag") or {}
    evidence_sufficient = bool(rag.get("evidence_sufficient"))
    citations = rag.get("citations") if isinstance(rag.get("citations"), list) else []
    cited_documents = [
        str(item.get("document_name") or "")
        for item in citations[:top_k]
        if isinstance(item, dict) and item.get("document_name")
    ]
    expected = {normalize_text(item) for item in case.expected_documents}
    cited = [normalize_text(item) for item in cited_documents]
    source_hit = bool(expected.intersection(cited)) if case.expect_answerable else None
    citation_precision = (
        sum(item in expected for item in cited) / len(cited)
        if case.expect_answerable and cited
        else (0.0 if case.expect_answerable else None)
    )
    normalized_answer = normalize_text(answer)
    term_coverage = (
        sum(normalize_text(term) in normalized_answer for term in case.required_answer_terms)
        / len(case.required_answer_terms)
        if case.required_answer_terms
        else None
    )
    refusal_correct = (not evidence_sufficient) if not case.expect_answerable else None
    answerability_correct = evidence_sufficient == case.expect_answerable
    return {
        "id": case.case_id,
        "question": case.question,
        "expect_answerable": case.expect_answerable,
        "evidence_sufficient": evidence_sufficient,
        "answerability_correct": answerability_correct,
        "source_hit_at_k": source_hit,
        "citation_precision": citation_precision,
        "required_term_coverage": term_coverage,
        "refusal_correct": refusal_correct,
        "cited_documents": cited_documents,
        "answer": answer,
    }


def average_present(rows: list[dict[str, Any]], field: str) -> float | None:
    values = [float(row[field]) for row in rows if row.get(field) is not None]
    return sum(values) / len(values) if values else None
