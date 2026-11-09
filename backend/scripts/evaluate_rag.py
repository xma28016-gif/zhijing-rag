#!/usr/bin/env python3
"""Evaluate a published assistant against a versioned JSONL question set."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from app.services.evaluation import (
    EvaluationCase,
    average_present,
    evaluate_chat_response,
    percentile,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True, help="UTF-8 JSONL 标准问答集")
    parser.add_argument("--assistant", required=True, help="已发布助手的 ID 或别名")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--api-key-env", default="RAG_EVAL_API_KEY")
    parser.add_argument("--output", type=Path, default=Path("rag-quality-report.json"))
    parser.add_argument("--top-k", type=int, default=6)
    parser.add_argument("--min-cases", type=int, default=30)
    parser.add_argument("--timeout", type=float, default=120)
    return parser.parse_args()


def load_cases(path: Path, minimum: int) -> tuple[list[EvaluationCase], str]:
    content = path.read_bytes()
    cases: list[EvaluationCase] = []
    for line_number, raw_line in enumerate(content.decode("utf-8-sig").splitlines(), start=1):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        value = json.loads(raw_line)
        if not isinstance(value, dict):
            raise ValueError(f"第 {line_number} 行必须是 JSON 对象")
        cases.append(EvaluationCase.from_dict(value, line_number=line_number))
    if len(cases) < minimum:
        raise ValueError(f"质量基线至少需要 {minimum} 条用例，当前仅 {len(cases)} 条")
    return cases, hashlib.sha256(content).hexdigest()


async def run_case(
    client: httpx.AsyncClient,
    case: EvaluationCase,
    assistant: str,
    top_k: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    response = await client.post(
        "/v1/chat/completions",
        json={
            "model": assistant,
            "messages": [{"role": "user", "content": case.question}],
            "stream": False,
            "user": f"quality-eval:{case.case_id}",
        },
    )
    latency_ms = round((time.perf_counter() - started) * 1000)
    response.raise_for_status()
    result = evaluate_chat_response(case, response.json(), top_k=top_k)
    result["latency_ms"] = latency_ms
    return result


async def async_main(args: argparse.Namespace) -> int:
    if args.top_k < 1 or args.min_cases < 1 or args.timeout <= 0:
        raise ValueError("top-k/min-cases 必须大于 0，timeout 必须大于 0")
    api_key = os.getenv(args.api_key_env)
    if not api_key:
        raise ValueError(f"请通过环境变量 {args.api_key_env} 传入 API Key，避免密钥出现在命令行。")
    cases, dataset_sha256 = load_cases(args.dataset, args.min_cases)
    headers = {"Authorization": f"Bearer {api_key}"}
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    async with httpx.AsyncClient(
        base_url=args.base_url.rstrip("/"), headers=headers, timeout=args.timeout
    ) as client:
        for case in cases:
            try:
                results.append(await run_case(client, case, args.assistant, args.top_k))
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                errors.append({"id": case.case_id, "error": str(exc)[:500]})

    answerable = [row for row in results if row["expect_answerable"]]
    unanswerable = [row for row in results if not row["expect_answerable"]]
    latencies = [float(row["latency_ms"]) for row in results]
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": str(args.dataset),
        "dataset_sha256": dataset_sha256,
        "assistant": args.assistant,
        "top_k": args.top_k,
        "case_count": len(cases),
        "completed_count": len(results),
        "error_count": len(errors),
        "metrics": {
            "source_recall_at_k": average_present(answerable, "source_hit_at_k"),
            "citation_precision": average_present(answerable, "citation_precision"),
            "required_term_coverage": average_present(answerable, "required_term_coverage"),
            "answerability_accuracy": average_present(results, "answerability_correct"),
            "no_answer_refusal_rate": average_present(unanswerable, "refusal_correct"),
            "latency_p50_ms": round(percentile(latencies, 50), 2),
            "latency_p95_ms": round(percentile(latencies, 95), 2),
        },
        "errors": errors,
        "cases": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["metrics"], ensure_ascii=False, indent=2))
    print(f"报告已写入 {args.output}")
    return 1 if errors else 0


def main() -> None:
    try:
        raise SystemExit(asyncio.run(async_main(parse_args())))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"评测配置错误：{exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
