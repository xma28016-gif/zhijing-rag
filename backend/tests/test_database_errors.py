from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError

from app.core.config import Environment, Settings
from app.main import create_app


@pytest.mark.parametrize(
    ("error_class", "sqlstate", "constraint", "http_status", "code"),
    [
        (IntegrityError, "23505", "uq_model_configs_provider_kind_name", 409, "model_name_exists"),
        (IntegrityError, "23505", "uq_model_configs_provider_kind_model", 409, "model_config_exists"),
        (IntegrityError, "23514", "check_config", 422, "invalid_data"),
        (OperationalError, "08006", None, 503, "database_unavailable"),
        (ProgrammingError, "42P01", None, 500, "database_operation_failed"),
    ],
)
def test_database_errors_identify_conflicts_without_exposing_parameters(
    error_class, sqlstate, constraint, http_status, code
):
    app = create_app(Settings(environment=Environment.TEST, _env_file=None))
    original = Exception("raw database values must not reach the client")
    original.sqlstate = sqlstate
    original.diag = SimpleNamespace(constraint_name=constraint)

    @app.get("/database-error-regression")
    async def fail():
        raise error_class("SQL including private details", {"api_key": "private-value"}, original)

    with TestClient(app) as client:
        response = client.get("/database-error-regression")
    assert response.status_code == http_status
    assert response.json()["detail"]["code"] == code
    assert "private" not in response.text and "raw database" not in response.text
    if error_class is IntegrityError:
        assert "启动脚本" not in response.text
