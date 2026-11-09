"""OpenAI-compatible assistant API protected by hashed API keys."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import ORJSONResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionFactory, get_db_session
from app.models.api_key import ApiKey
from app.models.assistant import Assistant
from app.models.enums import AssistantStatus, ChatRole, RunChannel, RunStatus, RunStepKind, UsageAccuracy
from app.models.run import RunRecord, RunStep
from app.schemas.openai_compat import ChatCompletionsRequest
from app.services import call_trace
from app.services.api_keys import (
    api_key_can_use_assistant,
    authenticate_api_key,
    enforce_rate_limit,
)
from app.services.chat_pipeline import PreparedChat, prepare_chat
from app.services.langchain_runtime import complete_answer, generate_answer
from app.services.model_runtime import (
    LLMResult,
    NormalizedUsage,
    ProviderCallError,
)

router = APIRouter(prefix="/v1", tags=["openai-compatible"])
DbSession = Annotated[AsyncSession, Depends(get_db_session)]


@dataclass(slots=True)
class HistoryItem:
    role: ChatRole
    content: str


async def external_api_key(
    session: DbSession,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> ApiKey:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail={
                "error": {
                    "type": "invalid_request_error",
                    "code": "invalid_api_key",
                    "message": "Missing Bearer API key.",
                }
            },
            headers={"WWW-Authenticate": "Bearer"},
        )
    record = await authenticate_api_key(session, authorization.removeprefix("Bearer ").strip())
    await enforce_rate_limit(record)
    return record


ApiKeyDep = Annotated[ApiKey, Depends(external_api_key)]


async def _allowed_assistants(session: AsyncSession, api_key: ApiKey) -> list[Assistant]:
    records = list(
        (
            await session.scalars(
                select(Assistant).where(Assistant.status == AssistantStatus.ACTIVE).order_by(Assistant.name)
            )
        ).all()
    )
    return [record for record in records if await api_key_can_use_assistant(session, api_key, record.id)]


@router.get("/models")
async def models(api_key: ApiKeyDep, session: DbSession) -> dict[str, Any]:
    records = await _allowed_assistants(session, api_key)
    return {
        "object": "list",
        "data": [
            {
                "id": item.alias,
                "object": "model",
                "created": int(item.created_at.timestamp()),
                "owned_by": "enterprise-knowledge-hub",
                "x_assistant_id": str(item.id),
            }
            for item in records
        ],
    }


async def _resolve_assistant(session: AsyncSession, api_key: ApiKey, identifier: str) -> Assistant:
    try:
        assistant_id = uuid.UUID(identifier)
    except ValueError:
        assistant_id = None
    statement = select(Assistant).where(Assistant.status == AssistantStatus.ACTIVE)
    statement = statement.where(
        Assistant.id == assistant_id if assistant_id else Assistant.alias == identifier
    )
    assistant = await session.scalar(statement)
    if not assistant or not await api_key_can_use_assistant(session, api_key, assistant.id):
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "type": "invalid_request_error",
                    "code": "model_not_found",
                    "message": "The requested assistant model is not available.",
                }
            },
        )
    return assistant


def _history(payload: ChatCompletionsRequest) -> tuple[str, list[HistoryItem]]:
    user_indexes = [index for index, item in enumerate(payload.messages) if item.role == "user"]
    if not user_indexes:
        raise HTTPException(
            status_code=422,
            detail={
                "error": {
                    "type": "invalid_request_error",
                    "code": "user_message_required",
                    "message": "At least one user message is required.",
                }
            },
        )
    latest = user_indexes[-1]
    history = [
        HistoryItem(role=ChatRole(item.role), content=item.content)
        for item in payload.messages[:latest]
        if item.role in {"user", "assistant"}
    ]
    return payload.messages[latest].content, history


async def _persist_external(
    *,
    run_id: uuid.UUID,
    prepared: PreparedChat | None,
    answer: str,
    status: RunStatus,
    usage: NormalizedUsage | None,
    started: float,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    async with AsyncSessionFactory() as session:
        run = await session.get(RunRecord, run_id)
        if not run:
            return
        rewrite = prepared.rewrite_usage if prepared else {}
        prompt = int(rewrite.get("prompt_tokens", 0)) + (usage.prompt_tokens if usage else 0)
        completion = int(rewrite.get("completion_tokens", 0)) + (usage.completion_tokens if usage else 0)
        exact = bool((usage is None or usage.exact) and (not rewrite or rewrite.get("exact")))
        if call_trace.calls():
            prompt, completion, exact = call_trace.totals()
        run.status = status
        run.answer_text = answer
        run.rewritten_query = prepared.rewritten_query if prepared else None
        run.evidence_sufficient = prepared.evidence_sufficient if prepared else None
        run.retrieved_chunk_count = len(prepared.retrieval_results) if prepared else 0
        run.citations = [item.model_dump(mode="json") for item in prepared.citations] if prepared else []
        run.retrieval_results = prepared.retrieval_results if prepared else []
        run.prompt_tokens = prompt
        run.completion_tokens = completion
        run.total_tokens = prompt + completion
        run.usage_accuracy = UsageAccuracy.EXACT if exact else UsageAccuracy.ESTIMATED
        run.duration_ms = max(0, round((time.perf_counter() - started) * 1000))
        run.error_code = error_code
        run.error_message = error_message
        run.finished_at = datetime.now(UTC)
        for sequence, call in enumerate(call_trace.calls()):
            kind = {
                "embedding": RunStepKind.EMBEDDING,
                "rerank": RunStepKind.RERANK,
                "llm": RunStepKind.GENERATION,
            }[call.kind]
            if call.kind == "llm" and prepared and prepared.rewrite_usage and sequence == 0:
                kind = RunStepKind.QUERY_REWRITE
            session.add(
                RunStep(
                    run_id=run.id,
                    kind=kind,
                    sequence=sequence,
                    status=RunStatus(call.status),
                    started_at=call.started_at,
                    finished_at=call.finished_at,
                    duration_ms=call.duration_ms,
                    error_code=call.error_code,
                    input_tokens=call.usage.prompt_tokens if call.usage else 0,
                    output_tokens=call.usage.completion_tokens if call.usage else 0,
                    input_summary={"model": call.model_name},
                    output_summary={
                        "usage_accuracy": "exact" if call.usage and call.usage.exact else "estimated"
                    },
                )
            )
        await session.commit()


def _usage_dict(prepared: PreparedChat, usage: NormalizedUsage | None) -> tuple[dict, str]:
    rewrite = prepared.rewrite_usage
    prompt = int(rewrite.get("prompt_tokens", 0)) + (usage.prompt_tokens if usage else 0)
    completion = int(rewrite.get("completion_tokens", 0)) + (usage.completion_tokens if usage else 0)
    exact = bool((usage is None or usage.exact) and (not rewrite or rewrite.get("exact")))
    if call_trace.calls():
        prompt, completion, exact = call_trace.totals()
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
    }, "exact" if exact else "local_estimate"


@router.post("/chat/completions")
async def chat_completions(payload: ChatCompletionsRequest, api_key: ApiKeyDep, session: DbSession):
    token = call_trace.start_trace()
    try:
        response = await _execute_completion(payload, api_key, session)
        if isinstance(response, StreamingResponse):
            rows = call_trace.calls()
            iterator = response.body_iterator

            async def traced_iterator():
                with call_trace.use_trace(rows):
                    async for item in iterator:
                        yield item

            response.body_iterator = traced_iterator()
        return response
    finally:
        call_trace.finish_trace(token)


async def _execute_completion(payload, api_key, session):
    assistant = await _resolve_assistant(session, api_key, payload.model)
    query, history = _history(payload)
    run_id = uuid.uuid4()
    started = time.perf_counter()
    session.add(
        RunRecord(
            id=run_id,
            request_id=f"chatcmpl-{uuid.uuid4().hex}",
            assistant_id=assistant.id,
            api_key_id=api_key.id,
            llm_model_config_id=assistant.llm_model_config_id,
            rerank_model_config_id=assistant.rerank_model_config_id,
            channel=RunChannel.API,
            status=RunStatus.RUNNING,
            query_text=query,
            config_snapshot={"requested_model": payload.model, "external_user": payload.user},
        )
    )
    await session.commit()
    try:
        async with AsyncSessionFactory() as pipeline_session:
            prepared = await prepare_chat(
                pipeline_session,
                assistant_id=assistant.id,
                query=query,
                history=history,
                require_active=True,
            )
    except asyncio.CancelledError:
        await asyncio.shield(
            _persist_external(
                run_id=run_id,
                prepared=None,
                answer="",
                status=RunStatus.CANCELLED,
                usage=None,
                started=started,
                error_code="request_cancelled",
                error_message="客户端已断开。",
            )
        )
        raise
    except Exception as exc:
        code = exc.code if isinstance(exc, ProviderCallError) else "pipeline_error"
        message = (
            exc.safe_message if isinstance(exc, ProviderCallError) else "Assistant configuration failed."
        )
        await _persist_external(
            run_id=run_id,
            prepared=None,
            answer="",
            status=RunStatus.FAILED,
            usage=None,
            started=started,
            error_code=code,
            error_message=message,
        )
        raise HTTPException(
            status_code=502, detail={"error": {"type": "server_error", "code": code, "message": message}}
        ) from exc
    completion_id = f"chatcmpl-{run_id.hex}"
    created = int(time.time())
    citations = [item.model_dump(mode="json") for item in prepared.citations]
    if not prepared.evidence_sufficient:
        answer = prepared.assistant.insufficient_evidence_message
        usage_dict, accuracy = _usage_dict(prepared, None)
        await _persist_external(
            run_id=run_id,
            prepared=prepared,
            answer=answer,
            status=RunStatus.INSUFFICIENT_EVIDENCE,
            usage=None,
            started=started,
        )
        response = {
            "id": completion_id,
            "object": "chat.completion",
            "created": created,
            "model": prepared.assistant.alias,
            "choices": [
                {"index": 0, "message": {"role": "assistant", "content": answer}, "finish_reason": "stop"}
            ],
            "usage": usage_dict,
            "x_rag": {"citations": [], "evidence_sufficient": False, "usage_accuracy": accuracy},
        }
        if not payload.stream:
            return ORJSONResponse(response)

        async def refusal_stream():
            chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": prepared.assistant.alias,
                "choices": [
                    {"index": 0, "delta": {"role": "assistant", "content": answer}, "finish_reason": None}
                ],
            }
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            final = {
                **chunk,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                "usage": usage_dict,
                "x_rag": {"citations": [], "evidence_sufficient": False, "usage_accuracy": accuracy},
            }
            yield f"data: {json.dumps(final, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(refusal_stream(), media_type="text/event-stream")

    if not payload.stream:
        try:
            result: LLMResult = await complete_answer(prepared)
        except asyncio.CancelledError:
            await asyncio.shield(
                _persist_external(
                    run_id=run_id,
                    prepared=prepared,
                    answer="",
                    status=RunStatus.CANCELLED,
                    usage=None,
                    started=started,
                    error_code="request_cancelled",
                    error_message="客户端已断开。",
                )
            )
            raise
        except Exception as exc:
            code = exc.code if isinstance(exc, ProviderCallError) else "generation_error"
            message = exc.safe_message if isinstance(exc, ProviderCallError) else "回答生成失败，请稍后重试。"
            await _persist_external(
                run_id=run_id,
                prepared=prepared,
                answer="",
                status=RunStatus.FAILED,
                usage=None,
                started=started,
                error_code=code,
                error_message=message,
            )
            raise HTTPException(
                status_code=502,
                detail={"error": {"type": "server_error", "code": code, "message": message}},
            ) from exc
        usage_dict, accuracy = _usage_dict(prepared, result.usage)
        await _persist_external(
            run_id=run_id,
            prepared=prepared,
            answer=result.text,
            status=RunStatus.SUCCEEDED,
            usage=result.usage,
            started=started,
        )
        return ORJSONResponse(
            {
                "id": completion_id,
                "object": "chat.completion",
                "created": created,
                "model": prepared.assistant.alias,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": result.text},
                        "finish_reason": "stop",
                    }
                ],
                "usage": usage_dict,
                "x_rag": {"citations": citations, "evidence_sufficient": True, "usage_accuracy": accuracy},
            }
        )

    async def completion_stream():
        answer_parts: list[str] = []
        usage: NormalizedUsage | None = None
        try:
            async for event in generate_answer(prepared):
                if event.delta:
                    answer_parts.append(event.delta)
                    chunk = {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": prepared.assistant.alias,
                        "choices": [{"index": 0, "delta": {"content": event.delta}, "finish_reason": None}],
                    }
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                if event.usage:
                    usage = event.usage
            usage_dict, accuracy = _usage_dict(prepared, usage)
            await _persist_external(
                run_id=run_id,
                prepared=prepared,
                answer="".join(answer_parts),
                status=RunStatus.SUCCEEDED,
                usage=usage,
                started=started,
            )
            final = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": prepared.assistant.alias,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                "usage": usage_dict,
                "x_rag": {"citations": citations, "evidence_sufficient": True, "usage_accuracy": accuracy},
            }
            yield f"data: {json.dumps(final, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except asyncio.CancelledError:
            await asyncio.shield(
                _persist_external(
                    run_id=run_id,
                    prepared=prepared,
                    answer="".join(answer_parts),
                    status=RunStatus.CANCELLED,
                    usage=usage,
                    started=started,
                    error_code="stream_cancelled",
                    error_message="客户端停止了回答。",
                )
            )
            raise
        except Exception as exc:
            code = exc.code if isinstance(exc, ProviderCallError) else "generation_error"
            message = exc.safe_message if isinstance(exc, ProviderCallError) else "回答生成失败，请稍后重试。"
            await _persist_external(
                run_id=run_id,
                prepared=prepared,
                answer="".join(answer_parts),
                status=RunStatus.FAILED,
                usage=usage,
                started=started,
                error_code=code,
                error_message=message,
            )
            error = {"error": {"type": "server_error", "code": code, "message": message}}
            yield f"data: {json.dumps(error, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        completion_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
