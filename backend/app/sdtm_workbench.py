from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .schemas.sdtm_workbench import (
    RawDatasetInventory,
    SDTMInputManifest,
    SDTMLifecycle,
    SDTMWorkbenchState,
    SourceColumnProfile,
)


LOGICAL_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,7}$")


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def logical_dataset_name(filename: str) -> str:
    name = Path(filename).stem.upper().replace("-", "_")
    name = re.sub(r"[^A-Z0-9_]", "_", name).strip("_")
    if not LOGICAL_NAME.fullmatch(name):
        raise ValueError(
            f"Raw dataset {filename!r} does not yield a valid SAS dataset name (1-8 letters, digits, or underscores)."
        )
    return name


def inventory_raw_dataset(path: Path, original_name: str) -> RawDatasetInventory:
    suffix = path.suffix.lower()
    if suffix not in {".csv", ".xpt"}:
        raise ValueError(f"Unsupported raw dataset format: {suffix or 'unknown'}")
    inventory = RawDatasetInventory(
        stored_name=path.name,
        original_name=original_name,
        logical_name=logical_dataset_name(original_name),
        format=suffix[1:],
        size_bytes=path.stat().st_size,
        sha256=sha256_path(path),
    )
    if suffix == ".csv":
        _profile_csv(path, inventory)
    else:
        _profile_xpt(path, inventory)
    return inventory


def _profile_csv(path: Path, inventory: RawDatasetInventory) -> None:
    with path.open("r", encoding="utf-8-sig", errors="strict", newline="") as handle:
        reader = csv.reader(handle)
        try:
            headers = next(reader)
        except StopIteration:
            inventory.diagnostics.append("CSV file is empty.")
            return
        normalized = [header.strip() for header in headers]
        if not all(normalized) or len(set(name.casefold() for name in normalized)) != len(normalized):
            raise ValueError(f"CSV {inventory.original_name!r} has blank or duplicate column names.")
        inferred = ["unknown"] * len(normalized)
        row_count = 0
        for row in reader:
            row_count += 1
            for index, value in enumerate(row[: len(inferred)]):
                if not value.strip():
                    continue
                candidate = "numeric" if _is_number(value) else "character"
                inferred[index] = candidate if inferred[index] in {"unknown", candidate} else "mixed"
        inventory.row_count = row_count
        inventory.columns = [
            SourceColumnProfile(name=name, data_type=data_type)
            for name, data_type in zip(normalized, inferred, strict=True)
        ]


def _profile_xpt(path: Path, inventory: RawDatasetInventory) -> None:
    try:
        import pyreadstat

        frame, _metadata = pyreadstat.read_xport(str(path))
    except Exception as exc:
        raise ValueError(f"XPT {inventory.original_name!r} is not readable.") from exc
    inventory.row_count = len(frame.index)
    inventory.columns = [
        SourceColumnProfile(
            name=str(name),
            data_type="numeric" if getattr(dtype, "kind", "") in {"i", "u", "f", "c"} else "character",
        )
        for name, dtype in frame.dtypes.items()
    ]


def _is_number(value: str) -> bool:
    try:
        float(value)
        return True
    except ValueError:
        return False


def state_path(job_dir: Path) -> Path:
    return job_dir / "sdtm" / "workbench.json"


def read_state(job_dir: Path) -> SDTMWorkbenchState:
    path = state_path(job_dir)
    if not path.is_file():
        return SDTMWorkbenchState()
    return SDTMWorkbenchState.model_validate_json(path.read_text(encoding="utf-8"))


def write_state(job_dir: Path, state: SDTMWorkbenchState) -> Path:
    path = state_path(job_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    state.updated_at = datetime.now(timezone.utc)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(state.model_dump_json(indent=2), encoding="utf-8")
    temporary.replace(path)
    return path


def initialize_state(
    job_dir: Path,
    *,
    metadata_files: list[str],
    blank_crf: str | None,
    raw_datasets: list[RawDatasetInventory],
    validation_report: str | None,
    study_metadata: dict[str, str] | None = None,
) -> SDTMWorkbenchState:
    has_raw = bool(raw_datasets)
    state = SDTMWorkbenchState(
        lifecycle=SDTMLifecycle(
            program_generation="not_started",
            execution="not_run",
            validation="not_run",
            submission_readiness="blocked",
        ),
        inputs=SDTMInputManifest(
            metadata_files=metadata_files,
            blank_crf=blank_crf,
            raw_datasets=raw_datasets,
            validation_report=validation_report,
            study_metadata=study_metadata or {},
        ),
        limitations=[
            "No raw datasets were supplied; generated programs will not be executed."
        ] if not has_raw else [],
    )
    write_state(job_dir, state)
    return state


def public_state(job_dir: Path) -> dict:
    return read_state(job_dir).model_dump(mode="json")

