from __future__ import annotations

import pytest

from app.services.evaluation import EvaluationCase, evaluate_chat_response, percentile


def test_percentile_interpolates_ordered_sample() -> None:
    assert percentile([40, 10, 30, 20], 50) == 25
    assert percentile([10, 20, 30, 40], 95) == pytest.approx(38.5)
    assert percentile([], 95) == 0


def test_answerable_case_scores_source_and_terms() -> None:
    case = EvaluationCase(
        case_id="qa-001",
        question="质保期多久？",
        expected_documents=("产品手册.pdf",),
        required_answer_terms=("12 个月", "发票"),
        expect_answerable=True,
    )
    result = evaluate_chat_response(
        case,
        {
            "choices": [{"message": {"content": "质保期为 12 个月，请保留发票。"}}],
            "x_rag": {
                "evidence_sufficient": True,
                "citations": [{"document_name": "产品手册.pdf"}],
            },
        },
        top_k=6,
    )
    assert result["source_hit_at_k"] is True
    assert result["citation_precision"] == 1
    assert result["required_term_coverage"] == 1
    assert result["answerability_correct"] is True


def test_unanswerable_case_scores_refusal() -> None:
    case = EvaluationCase("qa-002", "明天天气？", (), (), False)
    result = evaluate_chat_response(
        case,
        {
            "choices": [{"message": {"content": "当前知识库未找到足够依据"}}],
            "x_rag": {"evidence_sufficient": False, "citations": []},
        },
        top_k=6,
    )
    assert result["refusal_correct"] is True
    assert result["answerability_correct"] is True
