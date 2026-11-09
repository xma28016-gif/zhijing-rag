#!/usr/bin/env python3
"""Project-owned native services. No Docker, Homebrew or system launch agents."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shlex
import signal
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / ".data"
LOGS = DATA / "logs"
PG = ROOT / ".runtime/postgres/bin"
REDIS = ROOT / ".runtime/redis-7.4.5/src"
PYTHON = ROOT / "backend/.venv/bin/python"
BACKEND_SERVICES = ("api", "beat", "worker")


def run(command, **kwargs):
    return subprocess.run([str(arg) for arg in command], check=True, **kwargs)


def environment():
    from dotenv import dotenv_values

    env_file = ROOT / ".env"
    if not env_file.exists():
        database_password = secrets.token_hex(24)
        queue_password = secrets.token_hex(24)
        values = {
            "RAG_ENVIRONMENT": "development",
            "RAG_MASTER_KEY": "base64:" + secrets.token_urlsafe(32),
            "RAG_DATABASE_URL": f"postgresql+psycopg://zhijing:{database_password}@127.0.0.1:15432/zhijing",
            "RAG_REDIS_URL": f"redis://:{queue_password}@127.0.0.1:16379/0",
            "RAG_CELERY_BROKER_URL": f"redis://:{queue_password}@127.0.0.1:16379/1",
            "RAG_CELERY_RESULT_BACKEND": f"redis://:{queue_password}@127.0.0.1:16379/2",
            "RAG_STORAGE_BACKEND": "local",
            "RAG_LOCAL_STORAGE_PATH": str(DATA / "documents"),
            "POSTGRES_USER": "zhijing",
            "POSTGRES_DB": "zhijing",
            "POSTGRES_PASSWORD": database_password,
            "MINIO_ROOT_USER": "zhijing-minio",
            "MINIO_ROOT_PASSWORD": secrets.token_hex(24),
            "HTTP_PORT": "8080",
        }
        env_file.write_text(
            "\n".join(
                f"{key}={json.dumps(value, ensure_ascii=False)}"
                for key, value in values.items()
            )
            + "\n"
        )
        env_file.chmod(0o600)
    return {
        **os.environ,
        **{
            key: value
            for key, value in dotenv_values(env_file).items()
            if value is not None
        },
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
    }


def require_runtime():
    missing = [
        str(item)
        for item in (PG / "pg_ctl", REDIS / "redis-server", PYTHON)
        if not item.exists()
    ]
    if missing:
        raise RuntimeError(
            "缺少本机运行依赖，请先执行 scripts/setup-native.sh。\n"
            + "\n".join(missing)
        )


def alive(name):
    pid_file = DATA / f"{name}.pid"
    if not pid_file.exists():
        return False
    try:
        pid = int(pid_file.read_text())
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True
        )
        if str(ROOT) in result.stdout:
            return True
        # Redis/Celery can replace their process titles; verify ownership by cwd.
        check = subprocess.run(
            ["/usr/sbin/lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
            capture_output=True,
            text=True,
        )
        return any(
            line.startswith("n" + str(ROOT)) for line in check.stdout.splitlines()
        )
    except (OSError, ValueError):
        return False


def spawn(name, command, env, cwd):
    if alive(name):
        return
    with (LOGS / f"{name}.log").open("ab") as output:
        process = subprocess.Popen(
            [str(arg) for arg in command],
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    (DATA / f"{name}.pid").write_text(str(process.pid))


def backend_revision():
    """Identify the source/config loaded by API, worker and scheduler together."""
    files = [ROOT / ".env", ROOT / "scripts/local.py", ROOT / "backend/pyproject.toml"]
    for directory in (ROOT / "backend/app", ROOT / "backend/alembic"):
        files.extend(directory.rglob("*.py"))
    digest = hashlib.sha256()
    for path in sorted(files):
        if path.is_file():
            digest.update(str(path.relative_to(ROOT)).encode())
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()


def refresh_backend_if_needed(revision):
    running = [name for name in BACKEND_SERVICES if alive(name)]
    if not running:
        return
    try:
        saved = json.loads((DATA / "backend-processes.json").read_text())
        current_pids = {name: (DATA / f"{name}.pid").read_text() for name in running}
        if (
            saved.get("revision") == revision
            and saved.get("pids") == current_pids
            and len(running) == len(BACKEND_SERVICES)
        ):
            return
    except (OSError, ValueError, AttributeError):
        pass
    print("后端代码或配置已更新，正在等待现有请求和任务结束并刷新服务。", flush=True)
    for name in running:
        pid_file = DATA / f"{name}.pid"
        try:
            os.killpg(int(pid_file.read_text()), signal.SIGTERM)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + 60
        while alive(name):
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"{name} 仍在结束当前请求或任务，未强制终止。请稍后再次启动。"
                )
            time.sleep(0.2)
        pid_file.unlink(missing_ok=True)


def record_backend_revision(revision):
    (DATA / "backend-processes.json").write_text(json.dumps({
        "revision": revision,
        "pids": {name: (DATA / f"{name}.pid").read_text() for name in BACKEND_SERVICES},
    }))


def start():
    from urllib.parse import urlsplit

    require_runtime()
    DATA.mkdir(exist_ok=True, mode=0o700)
    LOGS.mkdir(exist_ok=True)
    env = environment()
    database = DATA / "postgres"
    if not (database / "PG_VERSION").exists():
        password_file = DATA / "init-password"
        password_file.write_text(env["POSTGRES_PASSWORD"])
        password_file.chmod(0o600)
        try:
            run(
                [
                    PG / "initdb",
                    "-D",
                    database,
                    "-U",
                    "zhijing",
                    "--encoding=UTF8",
                    "--locale=C",
                    "--auth-host=scram-sha-256",
                    "--auth-local=trust",
                    "--pwfile",
                    password_file,
                ],
                stdout=subprocess.DEVNULL,
            )
        finally:
            password_file.unlink(missing_ok=True)
    status = subprocess.run(
        [str(PG / "pg_ctl"), "-D", str(database), "status"], capture_output=True
    )
    if status.returncode:
        socket_dir = DATA / "socket"
        socket_dir.mkdir(exist_ok=True)
        options = shlex.join(["-h", "127.0.0.1", "-p", "15432", "-k", str(socket_dir)])
        run(
            [
                PG / "pg_ctl",
                "-D",
                database,
                "-l",
                LOGS / "postgres.log",
                "-o",
                options,
                "-w",
                "start",
            ]
        )
    import psycopg

    dsn = env["RAG_DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(
        dsn.rsplit("/", 1)[0] + "/postgres", autocommit=True
    ) as connection:
        if not connection.execute(
            "SELECT 1 FROM pg_database WHERE datname='zhijing'"
        ).fetchone():
            connection.execute('CREATE DATABASE "zhijing"')
    redis_dir = DATA / "redis"
    redis_dir.mkdir(exist_ok=True)
    redis_config = DATA / "redis.conf"
    redis_password = urlsplit(env["RAG_REDIS_URL"]).password or ""
    redis_config.write_text(
        f"bind 127.0.0.1\nport 16379\nprotected-mode yes\n"
        f'dir "{redis_dir}"\nappendonly yes\nrequirepass "{redis_password}"\n'
    )
    redis_config.chmod(0o600)
    spawn("redis", [REDIS / "redis-server", redis_config], env, ROOT)
    from redis import Redis

    queue = Redis.from_url(
        env["RAG_REDIS_URL"], socket_connect_timeout=2, socket_timeout=2
    )
    for _ in range(30):
        try:
            if queue.ping():
                break
        except Exception:
            time.sleep(0.2)
    else:
        raise RuntimeError("Redis 未启动，请查看 .data/logs/redis.log")
    run([PYTHON, "-m", "alembic", "upgrade", "head"], cwd=ROOT / "backend", env=env)
    run(
        [
            PYTHON,
            "-c",
            "from app.services.object_storage import ensure_bucket; ensure_bucket()",
        ],
        cwd=ROOT / "backend",
        env=env,
    )
    revision = backend_revision()
    refresh_backend_if_needed(revision)
    spawn(
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
        ],
        env,
        ROOT / "backend",
    )
    spawn(
        "beat",
        [
            PYTHON,
            "-m",
            "celery",
            "-A",
            "app.worker:celery_app",
            "beat",
            "--schedule",
            DATA / "celerybeat-schedule",
            "--loglevel=INFO",
        ],
        env,
        ROOT / "backend",
    )
    spawn(
        "api",
        [
            PYTHON,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
        ],
        env,
        ROOT / "backend",
    )
    record_backend_revision(revision)
    spawn(
        "web",
        [
            "node",
            ROOT / "node_modules/next/dist/bin/next",
            "dev",
            "--webpack",
            "--hostname",
            "127.0.0.1",
            "--port",
            "3000",
        ],
        env,
        ROOT,
    )
    for _ in range(60):
        try:
            with urllib.request.urlopen(
                "http://127.0.0.1:8000/api/v1/health/ready", timeout=5
            ) as response:
                if response.status == 200:
                    print(
                        "中台已启动：http://localhost:3000\n无需登录，左下角可切换角色。"
                    )
                    print(
                        "先配置模型服务；图片及扫描 PDF 的 DocMind 凭据在系统设置填写。"
                    )
                    return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("服务尚未全部就绪，请查看 .data/logs 或执行 local.py status。")


def stop():
    for name in ("web", "api", "beat", "worker", "redis"):
        if alive(name):
            os.killpg(int((DATA / f"{name}.pid").read_text()), signal.SIGTERM)
        (DATA / f"{name}.pid").unlink(missing_ok=True)
    if (DATA / "postgres/PG_VERSION").exists() and (PG / "pg_ctl").exists():
        subprocess.run(
            [str(PG / "pg_ctl"), "-D", str(DATA / "postgres"), "stop", "-m", "fast"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    print("本项目服务已停止，数据已保留。")


def status():
    running = (
        subprocess.run(
            [str(PG / "pg_ctl"), "-D", str(DATA / "postgres"), "status"],
            capture_output=True,
        )
        if (PG / "pg_ctl").exists()
        else None
    )
    print(f"postgres: {'运行中' if running and running.returncode == 0 else '未运行'}")
    for name in ("redis", "worker", "beat", "api", "web"):
        print(f"{name}: {'运行中' if alive(name) else '未运行'}")
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:8000/api/v1/health/ready", timeout=6
        ) as response:
            print(response.read().decode())
    except Exception:
        print("后端未就绪，检查 .data/logs。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="本机无 Docker 启停")
    parser.add_argument("command", choices=["start", "stop", "status"])
    args = parser.parse_args()
    try:
        {"start": start, "stop": stop, "status": status}[args.command]()
    except Exception as exc:
        print(f"操作未完成：{exc}", file=sys.stderr)
        sys.exit(1)
