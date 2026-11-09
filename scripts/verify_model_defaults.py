"""Quick API/database check for model defaults; all database changes roll back.

Run from the project root: PYTHONPATH=backend backend/.venv/bin/python
scripts/verify_model_defaults.py. This does not call any cloud provider.
"""

import asyncio
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Environment, Settings
from app.db.session import engine, get_db_session
from app.main import create_app
from app.models.enums import ModelKind, ValidationStatus
from app.models.provider import ModelConfig, ModelProvider


async def snapshot(connection):
    return set((await connection.execute(select(
        ModelConfig.id, ModelConfig.is_default, ModelConfig.validation_status, ModelConfig.validated_at
    ))).all())


async def main():
    checks = []
    async with engine.connect() as connection:
        transaction = await connection.begin()
        before = await snapshot(connection)
        async with AsyncSession(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        ) as session:
            try:
                uid = uuid.uuid4().hex
                provider = ModelProvider(
                    key=f"defaults-check-{uid}", name="默认模型临时验证",
                    base_url="https://provider.invalid/v1", enabled=True,
                )
                session.add(provider)
                await session.flush()
                validated = datetime.now(UTC)
                records = [ModelConfig(
                    provider_id=provider.id, name=f"defaults-check-{kind.value}-{index}",
                    model_id=f"fixture-{kind.value}-{index}", kind=kind, enabled=True,
                    validation_status=ValidationStatus.UNTESTED if kind is ModelKind.RERANK else ValidationStatus.VALID,
                    validated_at=validated, validation_latency_ms=12, supports_streaming=kind is ModelKind.LLM,
                    embedding_dimension=3 if kind is ModelKind.EMBEDDING else None,
                ) for index, kind in enumerate((ModelKind.LLM, ModelKind.LLM, ModelKind.EMBEDDING, ModelKind.RERANK))]
                session.add_all(records)
                await session.flush()
                llm_a, llm_b, embedding, untested = [record.id for record in records]
                await session.commit()
                app = create_app(Settings(environment=Environment.TEST, _env_file=None))

                async def test_session():
                    try:
                        yield session
                    except Exception:
                        await session.rollback()
                        raise

                app.dependency_overrides[get_db_session] = test_session
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
                    async def patch(model_id, payload, expected=200, role="admin"):
                        response = await client.patch(
                            f"/api/v1/model-services/models/{model_id}", json=payload,
                            headers={"X-Experience-Role": role},
                        )
                        assert response.status_code == expected, response.text
                        return response.json()

                    result = await patch(llm_a, {"is_default": True})
                    assert result["is_default"] and result["validation_status"] == "valid"
                    assert result["validation_latency_ms"] == 12 and result["supports_streaming"]
                    assert result["validated_at"] is not None
                    checks.append("设置默认模型保存成功，验证状态、耗时和流式能力保留")
                    await patch(llm_b, {"is_default": True})
                    await patch(embedding, {"is_default": True})
                    defaults = set(await session.scalars(select(ModelConfig.id).where(ModelConfig.is_default)))
                    assert llm_b in defaults and llm_a not in defaults and embedding in defaults
                    checks.append("同类型默认模型唯一，不同类型互不覆盖")
                    headers = {"X-Experience-Role": "manager"}
                    embedding_options = await client.get("/api/v1/knowledge-bases/embedding-model-options", headers=headers)
                    assert any(item["id"] == str(embedding) and item["is_default"] for item in embedding_options.json())
                    assistant_options = await client.get("/api/v1/assistants/model-options", headers=headers)
                    assert any(item["id"] == str(llm_b) and item["is_default"] for item in assistant_options.json())
                    checks.append("知识库与助手模型选项返回已保存的默认项")
                    cleared = await patch(llm_b, {"is_default": False})
                    assert not cleared["is_default"] and cleared["validation_status"] == "valid"
                    await patch(llm_b, {"is_default": True})
                    renamed = await patch(embedding, {"name": "默认模型重命名验证"})
                    assert renamed["validation_status"] == "valid"
                    checks.append("清除默认及修改显示名称不触发重新验证")
                    changed = await patch(llm_a, {"model_id": "fixture-model-changed"})
                    assert changed["validation_status"] == "untested" and changed["validated_at"] is None
                    rejected = await patch(untested, {"is_default": True}, expected=422)
                    assert rejected["detail"]["code"] == "default_model_not_available"
                    assert await session.scalar(select(ModelConfig.is_default).where(ModelConfig.id == llm_b))
                    checks.append("连接参数变更后待验证，未验证模型不能设为默认")
                    await patch(llm_b, {"is_default": False}, expected=403, role="manager")
                    checks.append("默认模型配置仅管理员可修改")
            finally:
                await session.close()
                await transaction.rollback()
        assert await snapshot(connection) == before
        checks.append("测试事务回滚，现有模型及默认配置保持不变")
    report = {"status": "passed", "checks": checks, "cloud_requests": 0}
    Path("artifacts/model-settings-check.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
