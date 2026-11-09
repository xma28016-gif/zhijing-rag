from __future__ import annotations

from fastapi import Depends
from fastapi.testclient import TestClient

from app.api.deps import ExperienceRoleDep, require_roles
from app.core.config import Environment, Settings
from app.core.roles import ExperienceRole
from app.main import create_app


def build_role_client() -> TestClient:
    application = create_app(Settings(environment=Environment.TEST, _env_file=None))
    admin_only = require_roles(ExperienceRole.ADMIN)

    @application.get("/whoami")
    async def whoami(role: ExperienceRoleDep) -> dict[str, str]:
        return {"role": role.value}

    @application.get("/admin-only")
    async def admin_route(
        role: ExperienceRole = Depends(admin_only),
    ) -> dict[str, str]:
        return {"role": role.value}

    return TestClient(application)


def test_missing_role_defaults_to_user() -> None:
    with build_role_client() as client:
        response = client.get("/whoami")

    assert response.status_code == 200
    assert response.json() == {"role": "user"}


def test_knowledge_manager_alias_is_normalized() -> None:
    with build_role_client() as client:
        response = client.get(
            "/whoami",
            headers={"X-Experience-Role": "knowledge_manager"},
        )

    assert response.status_code == 200
    assert response.json() == {"role": "manager"}


def test_require_roles_allows_admin_and_rejects_user() -> None:
    with build_role_client() as client:
        denied = client.get("/admin-only")
        allowed = client.get("/admin-only", headers={"X-Experience-Role": "admin"})

    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "insufficient_experience_role"
    assert allowed.status_code == 200
    assert allowed.json() == {"role": "admin"}


def test_invalid_role_returns_actionable_400() -> None:
    with build_role_client() as client:
        response = client.get("/whoami", headers={"X-Experience-Role": "owner"})

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_experience_role"
