from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.object_storage import ObjectStorage, ObjectStorageError


class FakeMinio:
    def __init__(self) -> None:
        self.bucket_created = False
        self.objects: dict[str, bytes] = {}
        self.metadata: dict[str, dict[str, str]] = {}

    def bucket_exists(self, _bucket: str) -> bool:
        return self.bucket_created

    def make_bucket(self, _bucket: str, *, location: str) -> None:
        assert location == "us-east-1"
        self.bucket_created = True

    def fput_object(
        self,
        _bucket: str,
        key: str,
        path: str,
        *,
        content_type: str,
        metadata: dict[str, str],
    ) -> None:
        assert content_type
        self.objects[key] = Path(path).read_bytes()
        self.metadata[key] = {"X-Amz-Meta-Sha256": metadata["sha256"]}

    def stat_object(self, _bucket: str, key: str) -> SimpleNamespace:
        if key not in self.objects:
            raise KeyError(key)
        return SimpleNamespace(metadata=self.metadata[key])

    def fget_object(self, _bucket: str, key: str, path: str) -> None:
        Path(path).write_bytes(self.objects[key])

    def list_objects(self, _bucket: str, *, prefix: str, recursive: bool):
        assert recursive is True
        return [SimpleNamespace(object_name=key) for key in self.objects if key.startswith(prefix)]

    def remove_object(self, _bucket: str, key: str) -> None:
        self.objects.pop(key, None)
        self.metadata.pop(key, None)


def _storage(client: FakeMinio) -> ObjectStorage:
    settings = Settings(
        _env_file=None,
        object_storage_enabled=True,
        object_storage_endpoint="minio:9000",
        object_storage_access_key="test-access",
        object_storage_secret_key="test-secret",
        object_storage_bucket="test-inputs",
        object_storage_startup_attempts=1,
    )
    return ObjectStorage(settings, client=client)


def test_job_inputs_round_trip_through_object_storage(tmp_path: Path) -> None:
    client = FakeMinio()
    storage = _storage(client)
    storage.ensure_ready()
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    source = input_dir / "01-edc.json"
    source.write_text('{"study":"SYN-101"}', encoding="utf-8")

    storage.upload_job_inputs("job-123", input_dir, [source.name])
    key = "jobs/job-123/inputs/01-edc.json"
    assert client.objects[key] == source.read_bytes()
    source.unlink()

    storage.restore_job_inputs("job-123", input_dir, [source.name])
    assert source.read_text(encoding="utf-8") == '{"study":"SYN-101"}'

    storage.delete_job_inputs("job-123")
    assert client.objects == {}


def test_object_storage_rejects_unsafe_keys() -> None:
    with pytest.raises(ObjectStorageError, match="Invalid input filename"):
        ObjectStorage.input_key("job-123", "../secret.txt")


def test_object_storage_wraps_delete_failures() -> None:
    class FailingDeleteMinio(FakeMinio):
        def list_objects(self, _bucket: str, *, prefix: str, recursive: bool):
            raise RuntimeError("storage unavailable")

    with pytest.raises(ObjectStorageError, match="could not be deleted"):
        _storage(FailingDeleteMinio()).delete_job_inputs("job-123")
