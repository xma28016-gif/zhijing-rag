import pytest
from fastapi import HTTPException

from app.api.external import _history
from app.schemas.openai_compat import ChatCompletionsRequest, OpenAIMessage


def test_history_uses_last_user_message_as_query() -> None:
    payload = ChatCompletionsRequest(
        model="hr-assistant",
        messages=[
            OpenAIMessage(role="user", content="年假是什么？"),
            OpenAIMessage(role="assistant", content="年假是带薪休假。"),
            OpenAIMessage(role="user", content="最多几天？"),
        ],
    )
    query, history = _history(payload)
    assert query == "最多几天？"
    assert [item.content for item in history] == ["年假是什么？", "年假是带薪休假。"]


def test_history_requires_a_user_message() -> None:
    payload = ChatCompletionsRequest(
        model="hr-assistant",
        messages=[OpenAIMessage(role="system", content="hello")],
    )
    with pytest.raises(HTTPException):
        _history(payload)
