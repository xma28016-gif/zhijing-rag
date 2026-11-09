"""Import all mapped classes so Alembic and SQLAlchemy see complete metadata."""

from app.db.base import Base
from app.models.api_key import ApiKey, ApiKeyAssistant
from app.models.assistant import Assistant, AssistantKnowledgeBase
from app.models.chat import BrowserSession, ChatConversation, ChatMessage
from app.models.dataset import EvaluationDataset, EvaluationSample
from app.models.knowledge import BuildTask, Document, DocumentVersion, KnowledgeBase, KnowledgeChunk
from app.models.metrics import DailyMetric
from app.models.provider import ModelConfig, ModelProvider
from app.models.run import RunRecord, RunStep
from app.models.system import SystemSetting

__all__ = [
    "ApiKey",
    "ApiKeyAssistant",
    "Assistant",
    "AssistantKnowledgeBase",
    "Base",
    "BrowserSession",
    "BuildTask",
    "ChatConversation",
    "ChatMessage",
    "DailyMetric",
    "Document",
    "DocumentVersion",
    "EvaluationDataset",
    "EvaluationSample",
    "KnowledgeBase",
    "KnowledgeChunk",
    "ModelConfig",
    "ModelProvider",
    "RunRecord",
    "RunStep",
    "SystemSetting",
]
