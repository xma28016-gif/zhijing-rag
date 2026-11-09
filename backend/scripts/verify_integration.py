"""Real PostgreSQL/pgvector + Redis/Celery + storage + HTTP RAG verification.

Only the billable model service is a local protocol fixture. The application has
no fixture-mode code and the user's knowledge database is never modified.
"""

from __future__ import annotations

import io
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
import psycopg
from dotenv import dotenv_values
from psycopg import sql

ROOT = Path(__file__).resolve().parents[2]
PYTHON = ROOT / "backend/.venv/bin/python"
ARTIFACTS = ROOT / "artifacts"


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main():
    ARTIFACTS.mkdir(exist_ok=True)
    env = {**os.environ, **dotenv_values(ROOT / ".env"), "PYTHONDONTWRITEBYTECODE": "1"}
    source = env["RAG_DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
    admin_dsn = source.rsplit("/", 1)[0] + "/postgres"
    database = "zhijing_verify_" + uuid.uuid4().hex[:8]
    run_dir = ARTIFACTS / database
    run_dir.mkdir()
    api_port, provider_port = port(), port()
    env.update(
        {
            "RAG_DATABASE_URL": source.rsplit("/", 1)[0].replace("postgresql://", "postgresql+psycopg://")
            + "/"
            + database,
            "RAG_LOCAL_STORAGE_PATH": str(run_dir / "documents"),
            "RAG_STORAGE_BACKEND": "local",
            "RAG_MASTER_KEY": "base64:" + secrets.token_urlsafe(32),
            "RAG_CELERY_BROKER_URL": env["RAG_REDIS_URL"].rsplit("/", 1)[0] + "/6",
            "RAG_CELERY_RESULT_BACKEND": env["RAG_REDIS_URL"].rsplit("/", 1)[0] + "/7",
        }
    )
    processes = []
    restore_database = database + "_restore"
    evidence = []
    report = {
        "database": database,
        "provider": "local protocol fixture; no real cloud calls",
        "checks": evidence,
        "passed": False,
    }

    def start(name, command):
        output = (run_dir / f"{name}.log").open("wb")
        process = subprocess.Popen(  # noqa: S603 - executable and arguments are project-owned
            [str(item) for item in command],
            cwd=ROOT if name == "web" else ROOT / "backend",
            env=env,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        processes.append((process, output))

    def wait_http(url):
        for _ in range(100):
            try:
                if httpx.get(url, timeout=5).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        raise AssertionError(f"Service not ready: {url}")

    try:
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        migration = subprocess.run(  # noqa: S603 - project migration command
            [str(PYTHON), "-m", "alembic", "upgrade", "head"],
            cwd=ROOT / "backend",
            env=env,
            capture_output=True,
            text=True,
        )
        (run_dir / "migration.log").write_text(migration.stdout + migration.stderr)
        assert migration.returncode == 0, "Migration failed; see migration.log"
        evidence.append("fresh database migrations")
        start(
            "provider",
            [
                PYTHON,
                "-m",
                "uvicorn",
                "provider_stub:app",
                "--app-dir",
                "tests",
                "--host",
                "127.0.0.1",
                "--port",
                provider_port,
            ],
        )
        start(
            "worker",
            [
                PYTHON,
                "-m",
                "celery",
                "-A",
                "app.worker:celery_app",
                "worker",
                "--pool=threads",
                "--concurrency=4",
                "--loglevel=INFO",
                "--hostname",
                f"verify-{database}@%h",
            ],
        )
        start("api", [PYTHON, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", api_port])
        wait_http(f"http://127.0.0.1:{provider_port}/health")
        wait_http(f"http://127.0.0.1:{api_port}/health/live")
        base = f"http://127.0.0.1:{api_port}"
        with httpx.Client(base_url=base, headers={"X-Experience-Role": "admin"}, timeout=30) as client:

            def api(method, path, **kwargs):
                response = client.request(method, "/api/v1" + path, **kwargs)
                assert response.is_success, f"{method} {path}: {response.status_code} {response.text[:500]}"
                return response.json() if response.status_code != 204 else None

            providers = api("GET", "/model-services/providers")
            provider = next(item for item in providers if item["key"] == "openrouter")
            api(
                "PATCH",
                "/model-services/providers/" + provider["id"],
                json={
                    "base_url": f"http://127.0.0.1:{provider_port}/v1",
                    "api_key": "integration-fixture-only",
                },
            )
            models = {}
            for kind in ("embedding", "rerank", "llm"):
                models[kind] = api(
                    "POST",
                    "/model-services/models",
                    json={
                        "provider_id": provider["id"],
                        "kind": kind,
                        "model_id": "verify-" + kind,
                        "name": "Mx",
                        "max_context_tokens": 4096,
                    },
                )
                assert models[kind]["validation_status"] == "valid"
            assert models["llm"]["supports_streaming"]
            duplicate = client.post(
                "/api/v1/model-services/models",
                json={
                    "provider_id": provider["id"],
                    "kind": "embedding",
                    "model_id": "verify-other-embedding",
                    "name": "Mx",
                },
            )
            assert duplicate.status_code == 409 and duplicate.json()["detail"]["code"] == "model_name_exists"
            duplicate_id = client.post(
                "/api/v1/model-services/models",
                json={
                    "provider_id": provider["id"],
                    "kind": "embedding",
                    "model_id": "verify-embedding",
                    "name": "Other name",
                },
            )
            assert (
                duplicate_id.status_code == 409
                and duplicate_id.json()["detail"]["code"] == "model_config_exists"
            )
            evidence.append("same display name across LLM/Embedding/Rerank; same-type duplicates report 409")
            evidence.append("provider save and real HTTP probes for embedding/rerank/streaming LLM")
            kb = api(
                "POST",
                "/knowledge-bases",
                json={
                    "name": "Integration knowledge",
                    "embedding_model_config_id": models["embedding"]["id"],
                },
            )
            name = "/knowledge-bases/" + kb["id"]

            def wait_task(task_id, expected):
                for _ in range(150):
                    task = api("GET", "/knowledge-bases/build-tasks/" + task_id)
                    if task["status"] == expected:
                        return task
                    assert task["status"] != "failed", task
                    time.sleep(0.2)
                raise AssertionError(f"Task did not reach {expected}: {task}")

            def upload(filename, data):
                item = api(
                    "POST", name + "/imports", files={"files": (filename, data)}, data={"enhanced": "false"}
                )["items"][0]
                assert item["accepted"], item
                wait_task(item["build_task_id"], "preview_ready")
                return item["build_task_id"]

            task_id = upload("policy.md", "# 员工年假\n员工年假为10天。\n报销需要发票和审批单。".encode())
            preview = api("GET", "/knowledge-bases/build-tasks/" + task_id + "/preview")
            assert preview["chunks"] and "10" in preview["chunks"][0]["content"]
            # Resume from persisted tasks, independent of the import wizard's memory.
            listed = api("GET", name + "/build-tasks")
            assert listed[0]["id"] == task_id
            api(
                "POST",
                "/knowledge-bases/build-tasks/" + task_id + "/build",
                json={"target_tokens": 800, "overlap_tokens": 120},
            )
            wait_task(task_id, "ready")
            assert api("GET", name + "/chunks")["total"] > 0
            evidence.append(
                "multipart upload, Celery parse, persisted preview/resume, embedding and pgvector activation"
            )
            assistant = api(
                "POST",
                "/assistants",
                json={
                    "name": "Integration assistant",
                    "alias": "integration-assistant",
                    "status": "active",
                    "llm_model_config_id": models["llm"]["id"],
                    "rerank_model_config_id": models["rerank"]["id"],
                    "knowledge_bases": [{"knowledge_base_id": kb["id"]}],
                },
            )
            browser = api("POST", "/chat/browser-sessions")
            client.headers["X-Browser-Session"] = browser["token"]
            client.headers["X-Experience-Role"] = "user"

            def chat(query, conversation=None):
                result = client.post(
                    "/api/v1/chat/assistants/" + assistant["id"] + "/completions",
                    json={"query": query, "conversation_id": conversation},
                )
                assert result.is_success, result.text
                events = []
                for frame in result.text.split("\n\n"):
                    lines = frame.splitlines()
                    event = next((line[6:].strip() for line in lines if line.startswith("event:")), None)
                    data = next((line[5:].strip() for line in lines if line.startswith("data:")), None)
                    if event and data:
                        events.append((event, json.loads(data)))
                assert not any(event == "error" for event, _ in events), events
                assert events[-1][0] == "done", events
                return dict(events), "".join(data["content"] for event, data in events if event == "delta")

            events, answer = chat("员工年假有多少天")
            assert "10" in answer and events["metadata"]["citations"]
            conversation = events["metadata"]["conversation_id"]
            assert events["done"]["usage"]["total_tokens"] == 40  # embedding 5 + rerank 7 + LLM 28
            _, followup = chat("具体多少天？", conversation)
            assert "10" in followup
            refused, _ = chat("明天会下雨吗")
            assert refused["done"]["status"] == "insufficient_evidence"
            assert client.get("/api/v1/model-services/providers").status_code == 403
            evidence.append(
                "user role, SSE answer, citations, multi-turn rewrite, refusal and all-model token accounting"
            )
            client.headers["X-Experience-Role"] = "admin"
            incremental = upload("additional.md", "# 补充制度\n员工年假制度补充说明。".encode())
            assert "10" in chat("员工年假有多少天")[1]
            api("POST", "/knowledge-bases/build-tasks/" + incremental + "/cancel")
            evidence.append("old knowledge remains queryable while incremental import waits for preview")
            from docx import Document
            from openpyxl import Workbook

            doc = Document()
            doc.add_paragraph("员工年假制度 Word 附件")
            buffer = io.BytesIO()
            doc.save(buffer)
            word_task = upload("word.docx", buffer.getvalue())
            workbook = Workbook()
            workbook.active.append(["制度", "天数"])
            workbook.active.append(["员工年假", 10])
            buffer = io.BytesIO()
            workbook.save(buffer)
            sheet_task = upload("table.xlsx", buffer.getvalue())
            for task in (word_task, sheet_task):
                api(
                    "POST",
                    "/knowledge-bases/build-tasks/" + task + "/build",
                    json={"target_tokens": 800, "overlap_tokens": 120},
                )
                wait_task(task, "ready")
            evidence.append("DOCX and XLSX through real worker and index")

            # Removal affects every version/index, preserves restore, and fences late worker writes.
            before = next(item for item in api("GET", "/knowledge-bases") if item["id"] == kb["id"])
            delete_content = "# 删除与恢复验收\n员工年假删除测试文件。".encode()
            delete_task = upload("delete-ready.md", delete_content)
            api(
                "POST",
                "/knowledge-bases/build-tasks/" + delete_task + "/build",
                json={"target_tokens": 800, "overlap_tokens": 120},
            )
            wait_task(delete_task, "ready")
            document = next(
                item for item in api("GET", name + "/documents") if item["name"] == "delete-ready.md"
            )
            path = name + "/documents/" + document["id"]
            client.headers["X-Experience-Role"] = "user"
            assert client.delete("/api/v1" + path).status_code == 403
            client.headers["X-Experience-Role"] = "manager"
            api("DELETE", path)
            assert not any(item["id"] == document["id"] for item in api("GET", name + "/documents"))
            assert any(item["id"] == document["id"] for item in api("GET", name + "/documents?deleted=true"))
            assert not any(
                item["document_name"] == "delete-ready.md" for item in api("GET", name + "/chunks")["items"]
            )
            hits = api("POST", name + "/retrieval-test", json={"query": "员工年假"})["results"]
            assert not any(item["document_name"] == "delete-ready.md" for item in hits)
            after = next(item for item in api("GET", "/knowledge-bases") if item["id"] == kb["id"])
            assert (
                after["chunk_count"] == before["chunk_count"]
                and after["document_count"] == before["document_count"]
            )
            api("POST", path + "/restore")
            assert any(
                item["document_name"] == "delete-ready.md" for item in api("GET", name + "/chunks")["items"]
            )
            api("DELETE", path)
            reimport = upload("delete-ready.md", delete_content)
            conflict = client.post("/api/v1" + path + "/restore")
            assert (
                conflict.status_code == 409
                and conflict.json()["detail"]["code"] == "document_restore_conflict"
            )
            reimport_doc = next(
                item for item in api("GET", name + "/documents") if item["name"] == "delete-ready.md"
            )
            api("DELETE", name + "/documents/" + reimport_doc["id"])
            rejected = client.post("/api/v1/knowledge-bases/build-tasks/" + reimport + "/retry")
            assert rejected.status_code == 409 and rejected.json()["detail"]["code"] == "document_deleted"
            api("POST", path + "/restore")
            api("DELETE", path)
            slow_task = upload("delete-building.md", "员工年假旧版本慢构建，删除验收。".encode())
            api(
                "POST",
                "/knowledge-bases/build-tasks/" + slow_task + "/build",
                json={"target_tokens": 800, "overlap_tokens": 120},
            )
            for _ in range(100):
                events = httpx.get(f"http://127.0.0.1:{provider_port}/embedding-events").json()
                if any("删除验收" in event["input"] and event["status"] == "started" for event in events):
                    break
                time.sleep(0.1)
            else:
                raise AssertionError("The in-flight embedding request never started")
            slow_doc = next(
                item for item in api("GET", name + "/documents") if item["name"] == "delete-building.md"
            )
            api("DELETE", name + "/documents/" + slow_doc["id"])
            for _ in range(100):
                events = httpx.get(f"http://127.0.0.1:{provider_port}/embedding-events").json()
                if any("删除验收" in event["input"] and event["status"] == "completed" for event in events):
                    break
                time.sleep(0.1)
            assert api("GET", "/knowledge-bases/build-tasks/" + slow_task)["status"] == "cancelled"
            assert not any(
                item["document_name"] == "delete-building.md"
                for item in api("GET", name + "/chunks")["items"]
            )
            client.headers["X-Experience-Role"] = "admin"
            evidence.append(
                "document delete/restore, role checks, count/retrieval removal, "
                "reimport and late-worker fencing"
            )
            runs = api("GET", "/logs/runs")
            succeeded = next(run for run in runs if run["status"] == "succeeded")
            detail = api("GET", "/logs/runs/" + succeeded["id"])
            assert detail["total_tokens"] > 0 and detail["duration_ms"] >= 0 and detail["steps"]
            evidence.append("persisted query/answer, usage, timings and per-model steps")
            api_key = api("POST", "/api-keys", json={"name": "verify", "allow_all_assistants": True})
            external = client.post(
                "/v1/chat/completions",
                headers={"Authorization": "Bearer " + api_key["key"]},
                json={"model": assistant["alias"], "messages": [{"role": "user", "content": "年假多少天"}]},
            )
            assert external.is_success, external.text
            assert "10" in external.json()["choices"][0]["message"]["content"]
            streamed = client.post(
                "/v1/chat/completions",
                headers={"Authorization": "Bearer " + api_key["key"]},
                json={
                    "model": assistant["alias"],
                    "stream": True,
                    "messages": [{"role": "user", "content": "年假多少天"}],
                },
            )
            assert streamed.is_success and "data: [DONE]" in streamed.text
            api_runs = [item for item in api("GET", "/logs/runs") if item["channel"] == "api"]
            assert len(api_runs) == 2
            assert all(api("GET", "/logs/runs/" + item["id"])["steps"] for item in api_runs)
            evidence.append("OpenAI-compatible API uses the same grounded LangChain pipeline")

            slow = upload("versioned.md", "员工年假旧版本慢构建。".encode())
            latest = upload("versioned.md", "员工年假新版本。".encode())
            for task in (slow, latest):
                api(
                    "POST",
                    "/knowledge-bases/build-tasks/" + task + "/build",
                    json={"target_tokens": 800, "overlap_tokens": 120},
                )
            wait_task(latest, "ready")
            assert wait_task(slow, "cancelled")["current_step"] == "superseded"
            evidence.append("out-of-order concurrent version builds cannot replace a newer active version")

            for dimension in (2048, 4096):
                high = api(
                    "POST",
                    "/model-services/models",
                    json={
                        "provider_id": provider["id"],
                        "kind": "embedding",
                        "model_id": "verify-embedding-" + str(dimension),
                        "name": str(dimension),
                    },
                )
                assert high["validation_status"] == "valid" and high["embedding_dimension"] == dimension
                high_kb = api(
                    "POST",
                    "/knowledge-bases",
                    json={
                        "name": "Dimension " + str(dimension),
                        "embedding_model_config_id": high["id"],
                    },
                )
                original_name = name
                name = "/knowledge-bases/" + high_kb["id"]
                high_task = upload("high.md", "员工年假高维文档。".encode())
                api(
                    "POST",
                    "/knowledge-bases/build-tasks/" + high_task + "/build",
                    json={"target_tokens": 800, "overlap_tokens": 120},
                )
                wait_task(high_task, "ready")
                recalled = api("POST", name + "/retrieval-test", json={"query": "员工年假"})
                assert recalled["results"] and recalled["results"][0]["semantic_score"] > 0.99
                with psycopg.connect(env["RAG_DATABASE_URL"].replace("+psycopg", "")) as connection:
                    indexes = connection.execute(
                        "SELECT indexdef FROM pg_indexes WHERE tablename='knowledge_chunks' "
                        "AND indexname LIKE %s",
                        ("%" + high["id"].replace("-", "") + "%",),
                    ).fetchall()
                    if dimension == 2048:
                        assert indexes and "halfvec(2048)" in indexes[0][0]
                        connection.execute("SET enable_seqscan=off")
                        plan = connection.execute(
                            "EXPLAIN SELECT id FROM knowledge_chunks WHERE embedding_model_config_id=%s "
                            "AND embedding IS NOT NULL AND is_active IS TRUE AND is_enabled IS TRUE "
                            "ORDER BY embedding::halfvec(2048) <=> %s::halfvec(2048) LIMIT 5",
                            (high["id"], "[1," + ",".join(["0"] * 2047) + "]"),
                        ).fetchall()
                        assert "hnsw_v2" in str(plan), plan
                    else:
                        assert not indexes
                name = original_name
            evidence.append("2048-dimension halfvec HNSW query plan and 4096-dimension exact retrieval")

            saved = api(
                "PATCH",
                "/system-settings",
                json={
                    "docmind_access_key_id": "verify-only-access-key",
                    "docmind_access_key_secret": "verify-only-secret",
                    "detailed_log_retention_days": 7,
                },
            )
            assert saved["docmind_configured"] and "verify-only-secret" not in json.dumps(saved)
            dsn = env["RAG_DATABASE_URL"].replace("+psycopg", "")
            with psycopg.connect(dsn) as connection:
                encrypted = connection.execute(
                    "SELECT docmind_access_key_secret_encrypted FROM system_settings WHERE id=1"
                ).fetchone()[0]
                assert encrypted != "verify-only-secret"
                connection.execute(
                    "INSERT INTO daily_metrics(id,metric_date,scope,request_count) "
                    "VALUES (%s,CURRENT_DATE-30,'system',99)",
                    (uuid.uuid4(),),
                )
                connection.execute(
                    "UPDATE build_tasks SET status='queued',current_step=NULL,"
                    "updated_at=now()-interval '10 minutes' WHERE id=%s",
                    (incremental,),
                )
            jobs = subprocess.run(  # noqa: S603 - fixed local maintenance commands
                [
                    str(PYTHON),
                    "-c",
                    "from app.services.log_retention import run_aggregation; "
                    "from app.services.build_recovery import run_stale_build_recovery; "
                    "run_aggregation(); run_stale_build_recovery()",
                ],
                cwd=ROOT / "backend",
                env=env,
                capture_output=True,
                text=True,
            )
            assert jobs.returncode == 0, jobs.stderr[-1000:]
            assert api("GET", "/knowledge-bases/build-tasks/" + incremental)["status"] == "failed"
            assert (
                next(item for item in api("GET", "/knowledge-bases") if item["id"] == kb["id"])["status"]
                == "ready"
            )
            with psycopg.connect(dsn) as connection:
                assert (
                    connection.execute(
                        "SELECT request_count FROM daily_metrics WHERE metric_date=CURRENT_DATE-30"
                    ).fetchone()[0]
                    == 99
                )
            evidence.append(
                "OCR keys encrypted/masked; shorter raw retention preserves historical aggregates; "
                "abandoned queue converges"
            )

            # Restart the actual API process: configuration and active chunks survive.
            process, output = processes.pop()
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=10)
            output.close()
            start(
                "api-restarted",
                [PYTHON, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", api_port],
            )
            wait_http(base + "/health/live")
            assert api("GET", "/system-settings")["docmind_configured"]
            assert "10" in chat("员工年假有多少天")[1]
            evidence.append("API restart retains model/OCR configuration, active knowledge and grounded chat")

            sys.path.insert(0, str(ROOT / "scripts"))
            from native_backup import create_backup, restore_backup

            isolated_config = run_dir / "isolated.env"
            isolated_config.write_text("RAG_MASTER_KEY=" + json.dumps(env["RAG_MASTER_KEY"]) + "\n")
            isolated_config.chmod(0o600)
            backup = create_backup(run_dir / "backup", env, isolated_config)
            restore_env = {
                **env,
                "RAG_DATABASE_URL": env["RAG_DATABASE_URL"].rsplit("/", 1)[0] + "/" + restore_database,
                "RAG_LOCAL_STORAGE_PATH": str(run_dir / "restored-documents"),
            }
            with psycopg.connect(admin_dsn, autocommit=True) as connection:
                connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(restore_database)))
            # pgvector type must exist before pg_restore restores application tables.
            restore_backup(backup, restore_env, isolated_config)
            with psycopg.connect(restore_env["RAG_DATABASE_URL"].replace("+psycopg", "")) as restored:
                assert (
                    restored.execute("SELECT count(*) FROM knowledge_chunks WHERE is_active").fetchone()[0]
                    > 0
                )
                assert (
                    restored.execute("SELECT count(*) FROM run_records WHERE status='succeeded'").fetchone()[
                        0
                    ]
                    > 0
                )
            originals = list((run_dir / "documents").rglob("*"))
            assert originals and all(
                (run_dir / "restored-documents" / file.relative_to(run_dir / "documents")).read_bytes()
                == file.read_bytes()
                for file in originals
                if file.is_file()
            )
            evidence.append(
                "native PostgreSQL dump and document archive restored into a separate database "
                "with file equality"
            )
            client_check = subprocess.run(  # noqa: S603 - project-owned client verification script
                [
                    shutil.which("node") or "/usr/local/bin/node",
                    str(ROOT / "scripts/verify-upload-client.mjs"),
                    base,
                    kb["id"],
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
            )
            assert client_check.returncode == 0, client_check.stderr[-1000:]
            evidence.append("actual TypeScript client uploads each file separately and retains both task IDs")
            if ui_port := os.environ.get("RAG_VERIFY_UI_PORT"):
                env.update({"NEXT_DIST_DIR": ".next-verify", "BACKEND_ORIGIN": base})
                start(
                    "web",
                    [
                        "node",
                        ROOT / "node_modules/next/dist/bin/next",
                        "dev",
                        ROOT,
                        "--webpack",
                        "--hostname",
                        "127.0.0.1",
                        "--port",
                        ui_port,
                    ],
                )
                wait_http(f"http://127.0.0.1:{ui_port}")
                (run_dir / "browser-policy.md").write_text("# 浏览器验收\n员工年假为10天。")
                (ARTIFACTS / "ui-session.json").write_text(
                    json.dumps(
                        {
                            "url": f"http://127.0.0.1:{ui_port}",
                            "run_dir": str(run_dir),
                            "stop_file": str(run_dir / "ui-complete"),
                            "knowledge_base": kb["name"],
                        }
                    )
                )
                print("Browser verification ready", flush=True)
                for _ in range(1800):
                    if (run_dir / "ui-complete").exists():
                        break
                    time.sleep(1)
        report["passed"] = True
    except Exception as exc:
        report["error"] = str(exc)
        raise
    finally:
        for process, output in reversed(processes):
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
            output.close()
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(restore_database))
            )
            connection.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(database))
            )
        (ARTIFACTS / "integration-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
