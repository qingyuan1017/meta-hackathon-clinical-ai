from __future__ import annotations

import json
import zipfile
from pathlib import Path

from .artifacts import sha256_file
from .sdtm_execution import list_attempts
from .sdtm_validation import list_validations
from .sdtm_workbench import read_state


def refresh_evidence_manifest(job_dir: Path) -> Path:
    state = read_state(job_dir)
    attempts = list_attempts(job_dir)
    validations = list_validations(job_dir)
    artifacts = []
    for root in (job_dir / "output", job_dir / "sdtm"):
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.name not in {"sdtm-artifacts.zip", "evidence-manifest.json"} and path.suffix != ".tmp":
                artifacts.append({"name": path.name, "relative_path": path.relative_to(job_dir).as_posix(), "size_bytes": path.stat().st_size, "sha256": sha256_file(path)})
    manifest = {
        "schema_version": "1.0",
        "lifecycle": state.lifecycle.model_dump(mode="json"),
        "inputs": state.inputs.model_dump(mode="json"),
        "program_and_execution_attempts": [item.model_dump(mode="json") for item in attempts],
        "validation_records": [item.model_dump(mode="json") for item in validations],
        "artifacts": artifacts,
        "limitations": state.limitations,
        "claims": {
            "execution_checks_are_standards_validation": False,
            "generation_implies_conformance": False,
            "generation_implies_submission_readiness": False,
        },
    }
    path = job_dir / "sdtm" / "evidence-manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    temporary.replace(path)
    return path


def refresh_evidence_bundle(job_dir: Path) -> Path:
    bundle = job_dir / "output" / "sdtm-artifacts.zip"
    candidates: list[Path] = []
    for root in (job_dir / "output", job_dir / "sdtm"):
        if not root.is_dir():
            continue
        candidates.extend(path for path in root.rglob("*") if path.is_file() and path != bundle and path.suffix != ".tmp")
    temporary = bundle.with_suffix(".tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(candidates):
            archive.write(path, arcname=path.relative_to(job_dir).as_posix())
    temporary.replace(bundle)
    return bundle

