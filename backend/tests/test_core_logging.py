from __future__ import annotations

import json
import logging

from app.core.logging import JsonFormatter, bind_request_id, reset_request_id


def test_json_formatter_emits_context_and_structured_fields() -> None:
    formatter = JsonFormatter()
    token = bind_request_id("req-test-123")
    try:
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname=__file__,
            lineno=17,
            msg="completed",
            args=(),
            exc_info=None,
        )
        record.event = "unit_test"
        record.duration_ms = 12.5
        payload = json.loads(formatter.format(record))
    finally:
        reset_request_id(token)

    assert payload["level"] == "info"
    assert payload["message"] == "completed"
    assert payload["request_id"] == "req-test-123"
    assert payload["event"] == "unit_test"
    assert payload["duration_ms"] == 12.5
