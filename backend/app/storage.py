from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterator, Optional

from app.config import get_settings

CHUNK_SIZE = 1024 * 1024


class ObjectNotFoundError(FileNotFoundError):
    pass


@dataclass(frozen=True)
class StoredObject:
    etag: Optional[str]
    version_id: Optional[str]


class ObjectStorage:
    backend_name: str

    def put_file(
        self,
        object_key: str,
        source_path: Path,
        media_type: str,
        metadata: Dict[str, str],
    ) -> StoredObject:
        raise NotImplementedError

    def iter_bytes(self, object_key: str) -> Iterator[bytes]:
        raise NotImplementedError


class LocalObjectStorage(ObjectStorage):
    backend_name = "local"

    def __init__(self, root: str):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, object_key: str) -> Path:
        target = (self.root / object_key).resolve()
        if os.path.commonpath([str(self.root), str(target)]) != str(self.root):
            raise ValueError("Unsafe object key")
        return target

    def put_file(
        self,
        object_key: str,
        source_path: Path,
        media_type: str,
        metadata: Dict[str, str],
    ) -> StoredObject:
        del media_type
        target = self._resolve(object_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, target)
        return StoredObject(etag=metadata.get("sha256"), version_id=None)

    def iter_bytes(self, object_key: str) -> Iterator[bytes]:
        target = self._resolve(object_key)
        if not target.is_file():
            raise ObjectNotFoundError(object_key)
        with target.open("rb") as handle:
            while True:
                chunk = handle.read(CHUNK_SIZE)
                if not chunk:
                    break
                yield chunk


class MinioObjectStorage(ObjectStorage):
    backend_name = "minio"

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        secure: bool,
    ):
        from minio import Minio

        self.bucket = bucket
        self.client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )

    def _ensure_bucket(self) -> None:
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)

    def put_file(
        self,
        object_key: str,
        source_path: Path,
        media_type: str,
        metadata: Dict[str, str],
    ) -> StoredObject:
        self._ensure_bucket()
        result = self.client.fput_object(
            self.bucket,
            object_key,
            str(source_path),
            content_type=media_type,
            metadata=metadata,
        )
        return StoredObject(etag=result.etag, version_id=result.version_id)

    def iter_bytes(self, object_key: str) -> Iterator[bytes]:
        from minio.error import S3Error

        try:
            response = self.client.get_object(self.bucket, object_key)
        except S3Error as exc:
            raise ObjectNotFoundError(object_key) from exc
        try:
            while True:
                chunk = response.read(CHUNK_SIZE)
                if not chunk:
                    break
                yield chunk
        finally:
            response.close()
            response.release_conn()


@lru_cache
def get_object_storage() -> ObjectStorage:
    settings = get_settings()
    if settings.object_storage_backend == "minio":
        return MinioObjectStorage(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            bucket=settings.minio_bucket,
            secure=settings.minio_secure,
        )
    return LocalObjectStorage(settings.local_object_root)
