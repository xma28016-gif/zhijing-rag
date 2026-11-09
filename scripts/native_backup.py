#!/usr/bin/env python3
"""Native backup/restore, including encrypted-credential recovery material."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tarfile
import time
from datetime import UTC, datetime

from dotenv import dotenv_values, set_key

from local import DATA, PG, ROOT, alive, environment, start


def pause_writers():
    for name in ("api", "beat", "worker"):
        if alive(name):
            pid = int((DATA / f"{name}.pid").read_text())
            os.killpg(pid, signal.SIGTERM)
            for _ in range(150):
                if not alive(name):
                    break
                time.sleep(0.2)
            else:
                raise RuntimeError(f"{name} 尚未停止，未执行备份或恢复。")
        (DATA / f"{name}.pid").unlink(missing_ok=True)


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def database_env(env):
    from urllib.parse import unquote, urlsplit

    parts = urlsplit(env["RAG_DATABASE_URL"].replace("+psycopg", ""))
    return {
        **os.environ,
        "PGHOST": parts.hostname or "127.0.0.1",
        "PGPORT": str(parts.port or 5432),
        "PGUSER": unquote(parts.username or ""),
        "PGPASSWORD": unquote(parts.password or ""),
        "PGDATABASE": parts.path.lstrip("/"),
    }


def create_backup(destination, env, env_file=ROOT / ".env"):
    destination.mkdir(parents=True, mode=0o700)
    destination.chmod(0o700)
    subprocess.run(
        [
            str(PG / "pg_dump"),
            "--format=custom",
            "--compress=none",
            "--no-owner",
            "--file",
            str(destination / "postgres.dump"),
        ],
        env=database_env(env),
        check=True,
    )
    documents = Path(env["RAG_LOCAL_STORAGE_PATH"])
    documents.mkdir(parents=True, exist_ok=True)
    with tarfile.open(destination / "documents.tar", "w") as archive:
        archive.add(documents, arcname="documents")
    shutil.copy2(env_file, destination / "recovery.env")
    checksums = {}
    for name in ("postgres.dump", "documents.tar", "recovery.env"):
        path = destination / name
        path.chmod(0o600)
        checksums[name] = digest(path)
    (destination / "manifest.json").write_text(
        json.dumps(
            {
                "format": "zhijing-native-v1",
                "created_at": datetime.now(UTC).isoformat(),
                "sha256": checksums,
            },
            indent=2,
        )
    )
    return destination


def restore_backup(source, env, env_file=ROOT / ".env"):
    manifest = json.loads((source / "manifest.json").read_text())
    if manifest["format"] != "zhijing-native-v1":
        raise ValueError("不支持的备份格式。")
    for name in ("postgres.dump", "documents.tar", "recovery.env"):
        if digest(source / name) != manifest["sha256"][name]:
            raise ValueError(f"备份校验失败：{name}")
    recovery = dotenv_values(source / "recovery.env")
    if not recovery.get("RAG_MASTER_KEY"):
        raise ValueError("备份缺少密钥恢复材料。")
    stage = DATA / "restore-staging"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(mode=0o700)
    with tarfile.open(source / "documents.tar") as archive:
        archive.extractall(stage, filter="data")
    if not (stage / "documents").is_dir():
        raise ValueError("备份缺少文档目录。")
    subprocess.run(
        [
            str(PG / "pg_restore"),
            "--clean",
            "--if-exists",
            "--no-owner",
            "--exit-on-error",
            "--single-transaction",
            "--dbname",
            database_env(env)["PGDATABASE"],
            str(source / "postgres.dump"),
        ],
        env=database_env(env),
        check=True,
    )
    documents = Path(env["RAG_LOCAL_STORAGE_PATH"])
    previous = documents.with_name("documents-before-restore-" + str(time.time_ns()))
    if documents.exists():
        documents.rename(previous)
    (stage / "documents").rename(documents)
    stage.rmdir()
    # Keep this installation's DB/network credentials; restore model-key encryption.
    for key in (
        "RAG_MASTER_KEY",
        "RAG_DOCMIND_ACCESS_KEY_ID",
        "RAG_DOCMIND_ACCESS_KEY_SECRET",
        "RAG_DOCMIND_ENDPOINT",
    ):
        if recovery.get(key):
            set_key(env_file, key, recovery[key])
    env_file.chmod(0o600)


def main():
    parser = argparse.ArgumentParser(
        description="本机版备份与恢复，操作时短暂停止 API/Worker"
    )
    parser.add_argument("command", choices=["backup", "restore"])
    parser.add_argument("path", type=Path)
    parser.add_argument("--confirm-restore", action="store_true")
    args = parser.parse_args()
    if args.command == "restore" and not args.confirm_restore:
        parser.error("恢复会替换当前数据库，必须添加 --confirm-restore")
    env = environment()
    if env.get("RAG_STORAGE_BACKEND") != "local":
        raise ValueError(
            "此脚本用于本机文件存储，MinIO 部署使用 backup.sh/restore.sh。"
        )
    pause_writers()
    try:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        if args.command == "backup":
            print(create_backup(args.path.resolve() / ("zhijing-" + stamp), env))
        else:
            rollback = create_backup(
                DATA / "backups" / ("before-restore-" + stamp), env
            )
            restore_backup(args.path.resolve(), env)
            print(f"恢复完成。恢复前快照：{rollback}")
    finally:
        start()


if __name__ == "__main__":
    main()
