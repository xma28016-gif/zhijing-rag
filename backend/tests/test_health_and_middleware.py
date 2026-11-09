from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient

from app.core.config import Environment, Settings
from app.main import create_app


def make_client() -> TestClient:
    configured = Settings(
        environment=Environment.TEST,
        cors_origins=["http://localhost:3000"],
        _env_file=None,
    )
    return TestClient(create_app(configured))


def test_root_and_versioned_health_routes_are_available() -> None:
    with make_client() as client:
        root_response = client.get("/health/live")
        versioned_response = client.get("/api/v1/health/ready")

    assert root_response.status_code == 200
    assert root_response.json()["status"] == "ok"
    assert versioned_response.status_code == 200
    assert versioned_response.json() == {
        "status": "ready",
        "checks": {"application": "ok"},
    }


def test_readiness_returns_503_when_a_registered_check_fails() -> None:
    configured = Settings(environment=Environment.TEST, _env_file=None)
    application = create_app(configured)
    application.state.readiness_checks["database"] = lambda: False

    with TestClient(application) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"application": "ok", "database": "failed"},
    }


def test_request_id_is_preserved_or_generated() -> None:
    with make_client() as client:
        supplied = client.get("/health/live", headers={"X-Request-ID": "caller-123"})
        generated = client.get("/health/live", headers={"X-Request-ID": "invalid id with spaces"})

    assert supplied.headers["X-Request-ID"] == "caller-123"
    UUID(generated.headers["X-Request-ID"])


def test_cors_preflight_allows_configured_frontend() -> None:
    with make_client() as client:
        response = client.options(
            "/api/v1/health/live",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "X-Experience-Role",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert response.headers["access-control-allow-credentials"] == "true"
    assert "x-experience-role" in response.headers["access-control-allow-headers"].lower()
