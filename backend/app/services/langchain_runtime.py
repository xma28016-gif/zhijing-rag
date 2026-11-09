"""LangChain adapters for configured providers and the persisted hybrid retriever.

Provider HTTP contracts remain in model_runtime so probes, indexing and chat
share the same protocol. LangChain owns embedding, retrieval, prompt and model
composition; no model or OCR weights are downloaded.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict, Field

from app.core.crypto import CredentialCipher
from app.schemas.knowledge import RetrievalTestResponse
from app.services import model_runtime


class ConfiguredEmbeddings(Embeddings):
    def __init__(self, model: Any, provider: Any, cipher: CredentialCipher):
        self.model, self.provider, self.cipher = model, provider, cipher

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError("Use aembed_documents with the async RAG pipeline")

    def embed_query(self, text: str) -> list[float]:
        raise NotImplementedError("Use aembed_query with the async RAG pipeline")

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return await model_runtime.embed_texts(self.model, self.provider, texts, self.cipher)

    async def aembed_query(self, text: str) -> list[float]:
        return (await self.aembed_documents([text]))[0]


def _messages(messages: list[BaseMessage]) -> list[dict[str, str]]:
    roles = {"human": "user", "ai": "assistant", "system": "system"}
    return [{"role": roles.get(item.type, "user"), "content": item.text} for item in messages]


def _usage(usage: model_runtime.NormalizedUsage) -> dict[str, int]:
    return {
        "input_tokens": usage.prompt_tokens,
        "output_tokens": usage.completion_tokens,
        "total_tokens": usage.total_tokens,
    }


class ConfiguredChatModel(BaseChatModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    provider_model: Any = Field(exclude=True)
    provider: Any = Field(exclude=True)
    cipher: Any = Field(exclude=True)
    temperature: float = 0.2
    max_tokens: int = 2048

    @property
    def _llm_type(self) -> str:
        return "configured-enterprise-provider"

    def _generate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs) -> ChatResult:
        raise NotImplementedError("Use the async LangChain model interface")

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        result = await model_runtime.complete_chat(
            self.provider_model,
            self.provider,
            _messages(messages),
            self.cipher,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content=result.text,
                        usage_metadata=_usage(result.usage),
                        response_metadata={"usage_exact": result.usage.exact, "model": result.returned_model},
                    )
                )
            ]
        )

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        if self.provider_model.supports_streaming is not True:
            result = await self._agenerate(messages)
            message = result.generations[0].message
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content=message.content,
                    usage_metadata=message.usage_metadata,
                    response_metadata=message.response_metadata,
                )
            )
            return
        async for event in model_runtime.stream_chat(
            self.provider_model,
            self.provider,
            _messages(messages),
            self.cipher,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        ):
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content=event.delta,
                    usage_metadata=_usage(event.usage) if event.usage else None,
                    response_metadata={"usage_exact": event.usage.exact} if event.usage else {},
                )
            )


class KnowledgeRetriever(BaseRetriever):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    retrieve: Callable[[str], Awaitable[RetrievalTestResponse]] = Field(exclude=True)
    last_response: Any = Field(default=None, exclude=True)

    def _get_relevant_documents(self, query, *, run_manager):
        raise NotImplementedError("Use ainvoke with the async retriever")

    async def _aget_relevant_documents(self, query, *, run_manager):
        self.last_response = await self.retrieve(query)
        return [
            Document(page_content=hit.content, metadata={"hit": hit.model_dump()})
            for hit in self.last_response.results
        ]


async def generate_answer(prepared: Any) -> AsyncIterator[model_runtime.LLMStreamEvent]:
    model = ConfiguredChatModel(
        provider_model=prepared.llm_model,
        provider=prepared.llm_provider,
        cipher=prepared.cipher,
        temperature=float(prepared.assistant.temperature),
        max_tokens=prepared.assistant.max_output_tokens,
    )
    # Build message objects first: user documents may contain literal braces.
    prompt = ChatPromptTemplate.from_messages(_to_base_messages(prepared.messages))
    chain = prompt | model
    async for chunk in chain.astream({}):
        usage = chunk.usage_metadata
        yield model_runtime.LLMStreamEvent(
            delta=chunk.text,
            usage=model_runtime.NormalizedUsage(
                usage["input_tokens"],
                usage["output_tokens"],
                usage["total_tokens"],
                bool(chunk.response_metadata.get("usage_exact", False)),
            )
            if usage
            else None,
        )


async def complete_answer(prepared: Any) -> model_runtime.LLMResult:
    model = ConfiguredChatModel(
        provider_model=prepared.llm_model,
        provider=prepared.llm_provider,
        cipher=prepared.cipher,
        temperature=float(prepared.assistant.temperature),
        max_tokens=prepared.assistant.max_output_tokens,
    )
    prompt = ChatPromptTemplate.from_messages(_to_base_messages(prepared.messages))
    message = await (prompt | model).ainvoke({})
    usage = message.usage_metadata or {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    return model_runtime.LLMResult(
        message.text,
        message.response_metadata.get("model"),
        model_runtime.NormalizedUsage(
            usage["input_tokens"],
            usage["output_tokens"],
            usage["total_tokens"],
            bool(message.response_metadata.get("usage_exact", False)),
        ),
    )


def _to_base_messages(messages: list[dict[str, str]]) -> list[BaseMessage]:
    from langchain_core.messages import HumanMessage, SystemMessage

    classes = {"system": SystemMessage, "user": HumanMessage, "assistant": AIMessage}
    return [classes.get(item["role"], HumanMessage)(content=item["content"]) for item in messages]
