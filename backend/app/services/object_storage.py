"""MinIO client and idempotent bucket bootstrap."""

from __future__ import annotations

import os
import shutil
import tempfile
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from minio import Minio

from app.core.config import Settings, get_settings


def _local_path(object_key: str, settings: Settings) -> Path:
    root = settings.local_storage_path.resolve()
    target = (root / object_key).resolve()
    if target == root or not target.is_relative_to(root):
        raise ValueError("invalid object key")
    return target


@lru_cache(maxsize=1)
def get_minio_client() -> Minio:
    settings = get_settings()
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key.get_secret_value(),
        secret_key=settings.minio_secret_key.get_secret_value(),
        secure=settings.minio_secure,
    )


def ensure_bucket(settings: Settings | None = None) -> None:
    resolved = settings or get_settings()
    if resolved.storage_backend == "local":
        resolved.local_storage_path.mkdir(parents=True, exist_ok=True)
        return
    client = get_minio_client()
    if not client.bucket_exists(resolved.minio_bucket):
        client.make_bucket(resolved.minio_bucket)


def storage_ready(settings: Settings | None = None) -> bool:
    resolved = settings or get_settings()
    if resolved.storage_backend == "local":
        return resolved.local_storage_path.is_dir() and os.access(resolved.local_storage_path, os.W_OK)
    return get_minio_client().bucket_exists(resolved.minio_bucket)


def put_bytes(
    object_key: str,
    content: bytes,
    *,
    content_type: str = "application/octet-stream",
    settings: Settings | None = None,
) -> None:
    resolved = settings or get_settings()
    if resolved.storage_backend == "local":
        destination = _local_path(object_key, resolved)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as handle:
            temporary = Path(handle.name)
            try:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
        return
    get_minio_client().put_object(
        resolved.minio_bucket, object_key, BytesIO(content), len(content), content_type=content_type
    )


def get_bytes(object_key: str, *, settings: Settings | None = None) -> bytes:
    resolved = settings or get_settings()
    if resolved.storage_backend == "local":
        return _local_path(object_key, resolved).read_bytes()
    response = get_minio_client().get_object(resolved.minio_bucket, object_key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def download_file(object_key: str, destination: Path, *, settings: Settings | None = None) -> None:
    resolved = settings or get_settings()
    if resolved.storage_backend == "local":
        shutil.copyfile(_local_path(object_key, resolved), destination)
        return
    get_minio_client().fget_object(resolved.minio_bucket, object_key, str(destination))


def remove_object(object_key: str, *, settings: Settings | None = None) -> None:
    resolved = settings or get_settings()
    if resolved.storage_backend == "local":
        _local_path(object_key, resolved).unlink(missing_ok=True)
        return
    get_minio_client().remove_object(resolved.minio_bucket, object_key)
