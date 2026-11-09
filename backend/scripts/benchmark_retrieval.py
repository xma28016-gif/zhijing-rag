#!/usr/bin/env python3
"""Measure internal hybrid-retrieval latency with controlled concurrency."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from app.services.evaluation import percentile


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--knowledge-base-id", required=True)
    parser.add_argument("--queries", type=Path, required=True, help="每行一个查询")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--warmup", type=int, default=20)
    parser.add_argument("--rerank-model-id")
    parser.add_argument("--max-retrieval-p95-ms", type=float, default=1500)
    parser.add_argument("--output", type=Path, default=Path("retrieval-benchmark.json"))
    return parser.parse_args()


def read_queries(path: Path) -> list[str]:
    queries = [line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines()]
    queries = [line for line in queries if line and not line.startswith("#")]
    if not queries:
        raise ValueError("查询文件不能为空")
    return queries


def payload(query: str, rerank_model_id: str | None) -> dict[str, Any]:
    value: dict[str, Any] = {
        "query": query,
        "semantic_top_k": 30,
        "keyword_top_k": 30,
        "fusion_top_k": 20,
        "final_top_k": 6,
    }
    if rerank_model_id:
        value["rerank_model_config_id"] = rerank_model_id
    return value


async def request_once(
    client: httpx.AsyncClient, endpoint: str, query: str, rerank_model_id: str | None
) -> dict[str, float]:
    started = time.perf_counter()
    response = await client.post(endpoint, json=payload(query, rerank_model_id))
    client_ms = (time.perf_counter() - started) * 1000
    response.raise_for_status()
    data = response.json()
    return {
        "client_ms": client_ms,
        "embedding_ms": float(data["embedding_ms"]),
        "retrieval_ms": float(data["retrieval_ms"]),
        "rerank_ms": float(data["rerank_ms"]),
    }


async def async_main(args: argparse.Namespace) -> int:
    if args.requests < 1 or args.concurrency < 1 or args.warmup < 0:
        raise ValueError("requests/concurrency 必须大于 0，warmup 不能小于 0")
    queries = read_queries(args.queries)
    endpoint = f"/api/v1/knowledge-bases/{args.knowledge_base_id}/retrieval-test"
    limits = httpx.Limits(
        max_connections=args.concurrency,
        max_keepalive_connections=args.concurrency,
    )
    samples: list[dict[str, float]] = []
    errors: list[str] = []
    semaphore = asyncio.Semaphore(args.concurrency)
    async with httpx.AsyncClient(
        base_url=args.base_url.rstrip("/"),
        headers={"X-Experience-Role": "manager"},
        timeout=120,
        limits=limits,
    ) as client:
        for index in range(args.warmup):
            await request_once(client, endpoint, queries[index % len(queries)], args.rerank_model_id)

        async def measured(index: int) -> None:
            async with semaphore:
                try:
                    sample = await request_once(
                        client, endpoint, queries[index % len(queries)], args.rerank_model_id
                    )
                    samples.append(sample)
                except (httpx.HTTPError, ValueError, KeyError) as exc:
                    errors.append(str(exc)[:500])

        started = time.perf_counter()
        await asyncio.gather(*(measured(index) for index in range(args.requests)))
        elapsed_seconds = time.perf_counter() - started

    def summary(field: str) -> dict[str, float]:
        values = [sample[field] for sample in samples]
        return {
            "p50_ms": round(percentile(values, 50), 2),
            "p95_ms": round(percentile(values, 95), 2),
            "p99_ms": round(percentile(values, 99), 2),
            "max_ms": round(max(values, default=0), 2),
        }

    retrieval = summary("retrieval_ms")
    passed = not errors and retrieval["p95_ms"] < args.max_retrieval_p95_ms
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "knowledge_base_id": args.knowledge_base_id,
        "requested": args.requests,
        "completed": len(samples),
        "errors": errors,
        "concurrency": args.concurrency,
        "throughput_rps": round(len(samples) / elapsed_seconds, 2) if elapsed_seconds else 0,
        "latency": {
            "client_total": summary("client_ms"),
            "external_embedding": summary("embedding_ms"),
            "internal_retrieval": retrieval,
            "external_rerank": summary("rerank_ms"),
        },
        "acceptance": {
            "metric": "internal_retrieval.p95_ms",
            "threshold_ms": args.max_retrieval_p95_ms,
            "passed": passed,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if passed else 1


def main() -> None:
    try:
        raise SystemExit(asyncio.run(async_main(parse_args())))
    except (OSError, UnicodeError, ValueError, httpx.HTTPError) as exc:
        print(f"压测配置错误：{exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
