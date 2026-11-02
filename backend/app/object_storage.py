from __future__ import annotations

from functools import lru_cache
import hashlib
import mimetypes
from pathlib import Path
import time
from typing import Any

from minio import Minio

from .config import Settings, get_settings


class ObjectStorageError(RuntimeError):
    """Raised when durable object storage cannot preserve or restore a job input."""


class ObjectStorage:
    def __init__(self, settings: Settings, *, client: Any | None = None) -> None:
        self.enabled = settings.object_storage_enabled
        self.bucket = settings.object_storage_bucket
        self.region = settings.object_storage_region
        self.startup_attempts = max(1, settings.object_storage_startup_attempts)
        self.startup_delay_seconds = max(0.0, settings.object_storage_startup_delay_seconds)
        if not self.enabled:
            self.client = None
            return
        if not settings.object_storage_access_key.strip() or not settings.object_storage_secret_key.strip():
            raise ObjectStorageError("Object storage credentials are required when object storage is enabled.")
        self.client = client or Minio(
            settings.object_storage_endpoint,
            access_key=settings.object_storage_access_key,
            secret_key=settings.object_storage_secret_key,
            secure=settings.object_storage_secure,
            region=settings.object_storage_region,
        )

    def ensure_ready(self) -> None:
        if not self.enabled:
            return
        assert self.client is not None
        last_error: Exception | None = None
        for attempt in range(self.startup_attempts):
            try:
                if not self.client.bucket_exists(self.bucket):
                    self.client.make_bucket(self.bucket, location=self.region)
                return
            except Exception as exc:  # MinIO surfaces several transport and S3 exception types.
                last_error = exc
                if attempt + 1 < self.startup_attempts:
                    time.sleep(self.startup_delay_seconds)
        raise ObjectStorageError("Object storage is unavailable or the input bucket cannot be initialized.") from last_error

    def health(self) -> str:
        if not self.enabled:
            return "disabled"
        assert self.client is not None
        try:
            return "ok" if self.client.bucket_exists(self.bucket) else "error"
        except Exception:
            return "error"

    def upload_job_inputs(self, job_id: str, input_dir: Path, filenames: list[str]) -> None:
        if not self.enabled:
            return
        assert self.client is not None
        try:
            for filename in filenames:
                path = self._safe_input_path(input_dir, filename, require_exists=True)
                content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                self.client.fput_object(
                    self.bucket,
                    self.input_key(job_id, filename),
                    str(path),
                    content_type=content_type,
                    metadata={"sha256": _sha256(path)},
                )
        except Exception as exc:
            try:
                self.delete_job_inputs(job_id)
            except Exception:
                pass
            raise ObjectStorageError("Validated job inputs could not be persisted to object storage.") from exc

    def restore_job_inputs(self, job_id: str, input_dir: Path, filenames: list[str]) -> None:
        if not self.enabled:
            return
        assert self.client is not None
        input_dir.mkdir(parents=True, exist_ok=True)
        for filename in filenames:
            path = self._safe_input_path(input_dir, filename, require_exists=False)
            if path.is_file():
                continue
            temporary = path.with_suffix(f"{path.suffix}.object-storage-download")
            try:
                stat = self.client.stat_object(self.bucket, self.input_key(job_id, filename))
                self.client.fget_object(self.bucket, self.input_key(job_id, filename), str(temporary))
                expected = _metadata_value(getattr(stat, "metadata", {}), "x-amz-meta-sha256")
                if expected and _sha256(temporary) != expected:
                    raise ObjectStorageError(f"Object storage checksum mismatch for {filename}.")
                temporary.replace(path)
            except Exception as exc:
                temporary.unlink(missing_ok=True)
                if isinstance(exc, ObjectStorageError):
                    raise
                raise ObjectStorageError(f"Job input {filename} could not be restored from object storage.") from exc

    def delete_job_inputs(self, job_id: str) -> None:
        if not self.enabled:
            return
        assert self.client is not None
        prefix = f"jobs/{job_id}/inputs/"
        try:
            for item in self.client.list_objects(self.bucket, prefix=prefix, recursive=True):
                self.client.remove_object(self.bucket, item.object_name)
        except Exception as exc:
            raise ObjectStorageError("Job inputs could not be deleted from object storage.") from exc

    @staticmethod
    def input_key(job_id: str, filename: str) -> str:
        if not job_id or "/" in job_id or "\\" in job_id or job_id in {".", ".."}:
            raise ObjectStorageError("Invalid job identifier for object storage.")
        if Path(filename).name != filename or filename in {"", ".", ".."}:
            raise ObjectStorageError("Invalid input filename for object storage.")
        return f"jobs/{job_id}/inputs/{filename}"

    @staticmethod
    def _safe_input_path(input_dir: Path, filename: str, *, require_exists: bool) -> Path:
        if Path(filename).name != filename or filename in {"", ".", ".."}:
            raise ObjectStorageError("Invalid input filename for object storage.")
        root = input_dir.resolve()
        path = (root / filename).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ObjectStorageError("Input path escapes the job workspace.") from exc
        if require_exists and not path.is_file():
            raise ObjectStorageError(f"Job input is unavailable: {filename}")
        return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _metadata_value(metadata: Any, key: str) -> str | None:
    if not isinstance(metadata, dict):
        return None
    lowered = {str(name).lower(): str(value) for name, value in metadata.items()}
    return lowered.get(key.lower()) or lowered.get("sha256")


@lru_cache
def get_object_storage() -> ObjectStorage:
    return ObjectStorage(get_settings())
