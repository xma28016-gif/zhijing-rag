"""Anonymous browser sessions, history, and grounded SSE chat."""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ExperienceRoleDep
from app.core.roles import ExperienceRole
from app.db.session import AsyncSessionFactory, get_db_session
from app.models.assistant import Assistant
from app.models.chat import BrowserSession, ChatConversation, ChatMessage
from app.models.enums import (
    AssistantStatus,
    ChatRole,
    RunChannel,
    RunStatus,
    RunStepKind,
    UsageAccuracy,
)
from app.models.enums import (
    ExperienceRole as DbExperienceRole,
)
from app.models.run import RunRecord, RunStep
from app.schemas.chat import (
    BrowserSessionRead,
    ChatRequest,
    ConversationRead,
    MessageRead,
)
from app.services import call_trace
from app.services.chat_pipeline import PreparedChat, prepare_chat
from app.services.langchain_runtime import generate_answer
from app.services.model_runtime import NormalizedUsage, ProviderCallError
from app.services.system_settings import get_system_settings

router = APIRouter(prefix="/chat", tags=["chat"])
DbSession = Annotated[AsyncSession, Depends(get_db_session)]


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _browser_session(
    session: AsyncSession, token: str | None, role: ExperienceRole
) -> tuple[BrowserSession, str | None]:
    now = datetime.now(UTC)
    if token:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        record = await session.scalar(
            select(BrowserSession).where(
                BrowserSession.token_hash == token_hash, BrowserSession.expires_at > now
            )
        )
        if record:
            record.last_seen_at = now
            record.selected_role = DbExperienceRole(role.value)
            return record, None
    raw = secrets.token_urlsafe(32)
    system_settings = await get_system_settings(session)
    record = BrowserSession(
        token_hash=hashlib.sha256(raw.encode()).hexdigest(),
        selected_role=DbExperienceRole(role.value),
        expires_at=now + timedelta(days=system_settings.browser_session_days),
    )
    session.add(record)
    await session.flush()
    return record, raw


@router.post("/browser-sessions", response_model=BrowserSessionRead)
async def create_browser_session(role: ExperienceRoleDep, session: DbSession) -> BrowserSessionRead:
    record, token = await _browser_session(session, None, role)
    await session.commit()
    return BrowserSessionRead(id=record.id, token=token or "", expires_at=record.expires_at)


async def _finalize_run(
    *,
    run_id: uuid.UUID,
    answer: str,
    status: RunStatus,
    prepared: PreparedChat | None,
    usage: NormalizedUsage | None,
    generation_ms: int,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    async with AsyncSessionFactory() as session:
        run = await session.get(RunRecord, run_id)
        if not run:
            return
        rewrite_prompt = int((prepared.rewrite_usage if prepared else {}).get("prompt_tokens", 0))
        rewrite_completion = int((prepared.rewrite_usage if prepared else {}).get("completion_tokens", 0))
        prompt = rewrite_prompt + (usage.prompt_tokens if usage else 0)
        completion = rewrite_completion + (usage.completion_tokens if usage else 0)
        exact = bool(
            (usage is None or usage.exact)
            and (not prepared or not prepared.rewrite_usage or prepared.rewrite_usage.get("exact"))
        )
        traced = call_trace.calls()
        if traced:
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
        run.error_code = error_code
        run.error_message = error_message
        run.finished_at = datetime.now(UTC)
        run.duration_ms = max(0, round((run.finished_at - run.started_at).total_seconds() * 1000))
        current_max = await session.scalar(
            select(func.max(ChatMessage.sequence)).where(ChatMessage.conversation_id == run.conversation_id)
        )
        next_sequence = int(current_max) + 1 if current_max is not None else 0
        session.add(
            ChatMessage(
                conversation_id=run.conversation_id,
                run_id=run.id,
                role=ChatRole.ASSISTANT,
                sequence=next_sequence,
                content=answer,
                citations=run.citations,
                usage={
                    "prompt_tokens": prompt,
                    "completion_tokens": completion,
                    "total_tokens": prompt + completion,
                    "exact": exact,
                },
            )
        )
        steps: list[tuple[RunStepKind, int]] = []
        if prepared:
            mapping = {
                "query_rewrite": RunStepKind.QUERY_REWRITE,
                "embedding": RunStepKind.EMBEDDING,
                "retrieval": RunStepKind.SEMANTIC_RETRIEVAL,
                "rerank": RunStepKind.RERANK,
            }
            steps.extend((mapping[key], value) for key, value in prepared.durations_ms.items())
        if generation_ms:
            steps.append((RunStepKind.GENERATION, generation_ms))
        for sequence, call in enumerate(traced):
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
                        "usage_accuracy": "exact"
                        if call.usage and call.usage.exact
                        else "unavailable"
                        if not call.usage
                        else "estimated"
                    },
                )
            )
        for sequence, (kind, duration) in enumerate(steps, start=len(traced)):
            if traced and kind in {
                RunStepKind.GENERATION,
                RunStepKind.QUERY_REWRITE,
                RunStepKind.EMBEDDING,
                RunStepKind.RERANK,
            }:
                continue
            session.add(
                RunStep(
                    run_id=run.id,
                    kind=kind,
                    sequence=sequence,
                    status=RunStatus.SUCCEEDED if status is not RunStatus.FAILED else RunStatus.FAILED,
                    duration_ms=duration,
                    started_at=run.started_at,
                    finished_at=run.finished_at,
                )
            )
        await session.commit()


@router.post("/assistants/{assistant_id}/completions")
async def chat_completion(
    assistant_id: uuid.UUID,
    payload: ChatRequest,
    role: ExperienceRoleDep,
    session: DbSession,
    browser_token: Annotated[str | None, Header(alias="X-Browser-Session")] = None,
) -> StreamingResponse:
    assistant = await session.get(Assistant, assistant_id)
    if (
        assistant is None
        or assistant.extra_config.get("deleted_at")
        or (role is ExperienceRole.USER and assistant.status is not AssistantStatus.ACTIVE)
    ):
        raise HTTPException(
            status_code=404, detail={"code": "assistant_not_found", "message": "助手不存在或尚未发布。"}
        )
    browser, new_token = await _browser_session(session, browser_token, role)
    if payload.conversation_id:
        conversation = await session.scalar(
            select(ChatConversation).where(
                ChatConversation.id == payload.conversation_id,
                ChatConversation.browser_session_id == browser.id,
                ChatConversation.assistant_id == assistant.id,
            )
        )
        if conversation is None:
            raise HTTPException(
                status_code=404, detail={"code": "conversation_not_found", "message": "会话不存在。"}
            )
    else:
        conversation = ChatConversation(
            browser_session_id=browser.id,
            assistant_id=assistant.id,
            title=payload.query[:80],
        )
        session.add(conversation)
        await session.flush()
    history = list(
        (
            await session.scalars(
                select(ChatMessage)
                .where(ChatMessage.conversation_id == conversation.id)
                .order_by(ChatMessage.sequence.desc())
                .limit(10)
            )
        ).all()
    )[::-1]
    current_max = await session.scalar(
        select(func.max(ChatMessage.sequence)).where(ChatMessage.conversation_id == conversation.id)
    )
    sequence = int(current_max) + 1 if current_max is not None else 0
    run_id = uuid.uuid4()
    session.add(
        RunRecord(
            id=run_id,
            request_id=str(uuid.uuid4()),
            conversation_id=conversation.id,
            assistant_id=assistant.id,
            llm_model_config_id=assistant.llm_model_config_id,
            rerank_model_config_id=assistant.rerank_model_config_id,
            channel=RunChannel.BROWSER,
            status=RunStatus.RUNNING,
            query_text=payload.query,
        )
    )
    session.add(
        ChatMessage(
            conversation_id=conversation.id,
            run_id=run_id,
            role=ChatRole.USER,
            sequence=sequence,
            content=payload.query,
        )
    )
    await session.commit()

    async def generate() -> AsyncIterator[str]:
        trace_token = call_trace.start_trace()
        prepared: PreparedChat | None = None
        generation_started = 0.0
        answer_parts: list[str] = []
        usage: NormalizedUsage | None = None
        try:
            async with AsyncSessionFactory() as pipeline_session:
                prepared = await prepare_chat(
                    pipeline_session,
                    assistant_id=assistant_id,
                    query=payload.query,
                    history=history,
                    require_active=role is ExperienceRole.USER,
                )
            yield _sse(
                "metadata",
                {
                    "run_id": str(run_id),
                    "conversation_id": str(conversation.id),
                    "citations": [item.model_dump(mode="json") for item in prepared.citations],
                    "rewritten_query": prepared.rewritten_query,
                    "evidence_sufficient": prepared.evidence_sufficient,
                },
            )
            if not prepared.evidence_sufficient:
                answer = prepared.assistant.insufficient_evidence_message
                yield _sse("delta", {"content": answer})
                await _finalize_run(
                    run_id=run_id,
                    answer=answer,
                    status=RunStatus.INSUFFICIENT_EVIDENCE,
                    prepared=prepared,
                    usage=None,
                    generation_ms=0,
                )
                yield _sse("done", {"status": "insufficient_evidence"})
                return
            generation_started = time.perf_counter()
            async for event in generate_answer(prepared):
                if event.delta:
                    answer_parts.append(event.delta)
                    yield _sse("delta", {"content": event.delta})
                if event.usage:
                    usage = event.usage
            generation_ms = round((time.perf_counter() - generation_started) * 1000)
            answer = "".join(answer_parts)
            await _finalize_run(
                run_id=run_id,
                answer=answer,
                status=RunStatus.SUCCEEDED,
                prepared=prepared,
                usage=usage,
                generation_ms=generation_ms,
            )
            prompt, completion, exact = call_trace.totals()
            yield _sse(
                "done",
                {
                    "status": "succeeded",
                    "usage": {
                        "prompt_tokens": prompt,
                        "completion_tokens": completion,
                        "total_tokens": prompt + completion,
                        "exact": exact,
                    },
                },
            )
        except asyncio.CancelledError:
            await asyncio.shield(
                _finalize_run(
                    run_id=run_id,
                    answer="".join(answer_parts),
                    status=RunStatus.CANCELLED,
                    prepared=prepared,
                    usage=usage,
                    generation_ms=(
                        round((time.perf_counter() - generation_started) * 1000) if generation_started else 0
                    ),
                    error_code="stream_cancelled",
                    error_message="客户端停止了回答。",
                )
            )
            raise
        except (ProviderCallError, ValueError) as exc:
            code = exc.code if isinstance(exc, ProviderCallError) else str(exc)
            message = (
                exc.safe_message if isinstance(exc, ProviderCallError) else "对话准备失败，请检查助手配置。"
            )
            await _finalize_run(
                run_id=run_id,
                answer="",
                status=RunStatus.FAILED,
                prepared=prepared,
                usage=usage,
                generation_ms=0,
                error_code=code,
                error_message=message,
            )
            yield _sse("error", {"code": code, "message": message})
        except Exception:
            message = "对话运行异常，已记录错误，请稍后重试。"
            await _finalize_run(
                run_id=run_id,
                answer="",
                status=RunStatus.FAILED,
                prepared=prepared,
                usage=usage,
                generation_ms=0,
                error_code="chat_internal_error",
                error_message=message,
            )
            yield _sse("error", {"code": "chat_internal_error", "message": message})
        finally:
            call_trace.finish_trace(trace_token)

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    if new_token:
        headers["X-Browser-Session"] = new_token
    return StreamingResponse(generate(), media_type="text/event-stream", headers=headers)


@router.get("/conversations", response_model=list[ConversationRead])
async def list_conversations(
    _: ExperienceRoleDep,
    session: DbSession,
    browser_token: Annotated[str | None, Header(alias="X-Browser-Session")] = None,
) -> list[ConversationRead]:
    if not browser_token:
        return []
    token_hash = hashlib.sha256(browser_token.encode()).hexdigest()
    browser = await session.scalar(
        select(BrowserSession).where(
            BrowserSession.token_hash == token_hash, BrowserSession.expires_at > datetime.now(UTC)
        )
    )
    if not browser:
        return []
    records = (
        await session.scalars(
            select(ChatConversation)
            .where(
                ChatConversation.browser_session_id == browser.id,
                ChatConversation.archived.is_(False),
            )
            .order_by(ChatConversation.updated_at.desc())
        )
    ).all()
    return [
        ConversationRead(
            id=item.id,
            assistant_id=item.assistant_id,
            title=item.title,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )
        for item in records
    ]


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageRead])
async def list_messages(
    conversation_id: uuid.UUID,
    _: ExperienceRoleDep,
    session: DbSession,
    browser_token: Annotated[str | None, Header(alias="X-Browser-Session")] = None,
) -> list[MessageRead]:
    if not browser_token:
        raise HTTPException(status_code=404, detail={"code": "conversation_not_found"})
    token_hash = hashlib.sha256(browser_token.encode()).hexdigest()
    conversation = await session.scalar(
        select(ChatConversation)
        .join(BrowserSession)
        .where(
            ChatConversation.id == conversation_id,
            BrowserSession.token_hash == token_hash,
            BrowserSession.expires_at > datetime.now(UTC),
        )
    )
    if not conversation:
        raise HTTPException(status_code=404, detail={"code": "conversation_not_found"})
    messages = (
        await session.scalars(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == conversation.id)
            .order_by(ChatMessage.sequence)
        )
    ).all()
    return [
        MessageRead(
            id=item.id,
            role=item.role.value,
            sequence=item.sequence,
            content=item.content,
            citations=item.citations,
            usage=item.usage,
            created_at=item.created_at,
        )
        for item in messages
    ]
