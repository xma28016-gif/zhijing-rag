from fastapi.testclient import TestClient

from app.core.config import Environment, Settings
from app.main import create_app


def test_provider_templates_are_admin_only_and_secret_free() -> None:
    app = create_app(Settings(environment=Environment.TEST, _env_file=None))
    with TestClient(app) as client:
        denied = client.get("/api/v1/model-services/templates")
        allowed = client.get("/api/v1/model-services/templates", headers={"X-Experience-Role": "admin"})
    assert denied.status_code == 403
    assert allowed.status_code == 200
    assert {item["key"] for item in allowed.json()} == {"openrouter", "aihubmix", "tongyi"}
    assert "api_key" not in allowed.text


def test_openapi_exposes_internal_and_external_contracts() -> None:
    app = create_app(Settings(environment=Environment.TEST, _env_file=None))
    schema = app.openapi()
    assert "/api/v1/knowledge-bases/{knowledge_base_id}/imports" in schema["paths"]
    assert "/api/v1/knowledge-bases/{knowledge_base_id}/retrieval-test" in schema["paths"]
    assert "/api/v1/assistants/model-options" in schema["paths"]
    assert "/api/v1/system-settings" in schema["paths"]
    assert "/v1/chat/completions" in schema["paths"]
    assert "/v1/models" in schema["paths"]
