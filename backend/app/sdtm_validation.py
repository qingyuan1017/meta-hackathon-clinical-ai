from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from openpyxl import load_workbook

from .schemas.validation import (
    ValidationFinding,
    ValidationImportDiagnostics,
    ValidationRecord,
)
from .sdtm_execution import list_attempts
from .sdtm_workbench import read_state, write_state


ALIASES = {
    "rule_id": {"rule id", "rule", "check id", "issue id", "ruleid"},
    "severity": {"severity", "level", "priority"},
    "dataset": {"dataset", "domain", "table"},
    "variable": {"variable", "column"},
    "record_keys": {"record keys", "record key", "keys", "record"},
    "message": {"message", "description", "issue", "details"},
    "provider_version": {"pinnacle 21 version", "p21 version", "provider version", "version"},
    "standard_version": {"standard version", "sdtmig version", "standard"},
    "controlled_terminology_version": {"ct version", "controlled terminology version", "terminology version"},
}


class ValidationProvider(ABC):
    name: str

    @abstractmethod
    def run(self, job_dir: Path) -> ValidationRecord:
        raise NotImplementedError


class InternalChecksProvider(ValidationProvider):
    name = "Workbench internal structural checks"

    def run(self, job_dir: Path) -> ValidationRecord:
        attempts = list_attempts(job_dir)
        latest = attempts[-1] if attempts else None
        findings: list[ValidationFinding] = []
        if latest is None:
            return ValidationRecord(validation_id=_id("internal"), provider=self.name, provider_version="0.1.0", status="unavailable", created_at=_now(), message="No execution attempt exists; internal output checks were not run.")
        for index, check in enumerate(latest.checks):
            if check.status not in {"failed", "warning"}:
                continue
            findings.append(ValidationFinding(finding_id=f"internal-{latest.attempt_id}-{index}", provider=self.name, provider_version="0.1.0", rule_id=check.check_id, severity="Error" if check.status == "failed" else "Warning", dataset=check.domain, message=check.message))
        status = "completed_with_findings" if findings else "passed" if latest.status == "passed" else "failed"
        return ValidationRecord(validation_id=_id("internal"), provider=self.name, provider_version="0.1.0", status=status, created_at=_now(), findings=findings, message="These are execution/structural diagnostics, not Pinnacle 21 or standards validation.")


class Pinnacle21CLIProvider(ValidationProvider):
    name = "Pinnacle 21 Community CLI"

    def __init__(self, cli_path: Path | None, java_path: Path | None, timeout_seconds: int = 600) -> None:
        self.cli_path = cli_path
        self.java_path = java_path
        self.timeout_seconds = timeout_seconds

    def run(self, job_dir: Path) -> ValidationRecord:
        missing = []
        if self.cli_path is None or not self.cli_path.is_file():
            missing.append("Pinnacle 21 CLI")
        if self.java_path is None or not self.java_path.is_file():
            missing.append("Java runtime")
        if missing:
            return ValidationRecord(validation_id=_id("p21cli"), provider=self.name, status="unavailable", created_at=_now(), message=f"Local prerequisites unavailable: {', '.join(missing)}. No validation was run.")
        attempts = [item for item in list_attempts(job_dir) if item.status == "passed"]
        if not attempts:
            return ValidationRecord(validation_id=_id("p21cli"), provider=self.name, status="failed", created_at=_now(), message="No passed execution output is available for validation.")
        source_dir = job_dir / "sdtm" / "executions" / attempts[-1].attempt_id / "output"
        run_dir = job_dir / "sdtm" / "validation" / _id("p21cli")
        run_dir.mkdir(parents=True, exist_ok=False)
        report = run_dir / "pinnacle21-report.xlsx"
        command = [str(self.java_path), "-jar", str(self.cli_path), "--input", str(source_dir), "--output", str(report)]
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=self.timeout_seconds, check=False)
        except subprocess.TimeoutExpired:
            return ValidationRecord(validation_id=run_dir.name, provider=self.name, status="failed", created_at=_now(), message="The configured local validator timed out; no successful validation is recorded.")
        if completed.returncode != 0 or not report.is_file():
            return ValidationRecord(validation_id=run_dir.name, provider=self.name, status="failed", created_at=_now(), message="The configured local validator did not produce a supported report; no successful validation is recorded.")
        record = import_pinnacle21_report(job_dir, report, preserve_original=False)
        record.provider = self.name
        if not record.findings and record.diagnostics and not record.diagnostics.warnings:
            record.status = "passed"
            record.message = "The configured local CLI completed and produced a supported report with no normalized findings."
        return record


def import_pinnacle21_report(job_dir: Path, source: Path, *, preserve_original: bool = True) -> ValidationRecord:
    validation_id = _id("p21import")
    target_dir = job_dir / "sdtm" / "validation" / validation_id
    target_dir.mkdir(parents=True, exist_ok=False)
    original = target_dir / f"original-{source.name}"
    if preserve_original:
        shutil.copy2(source, original)
    else:
        original = source
    headers, rows = _read_rows(source)
    mapped, unknown = _map_headers(headers)
    diagnostics = ValidationImportDiagnostics(source_name=source.name, format=source.suffix.lower().lstrip("."), rows_read=len(rows), recognized_columns={key: headers[index] for key, index in mapped.items()}, unknown_columns=unknown)
    required = {"rule_id", "severity", "message"}
    missing = sorted(required - set(mapped))
    findings: list[ValidationFinding] = []
    if missing:
        diagnostics.warnings.append(f"Required columns not recognized: {', '.join(missing)}.")
    else:
        for row_number, row in enumerate(rows, start=2):
            values = {key: _cell(row, index) for key, index in mapped.items()}
            if not any(values.values()):
                continue
            fingerprint = json.dumps([source.name, row_number, values], sort_keys=True).encode("utf-8")
            findings.append(ValidationFinding(
                finding_id=f"p21-{hashlib.sha256(fingerprint).hexdigest()[:16]}",
                provider="Pinnacle 21 report import",
                provider_version=values.get("provider_version") or "not reported",
                standard_version=values.get("standard_version") or None,
                controlled_terminology_version=values.get("controlled_terminology_version") or None,
                rule_id=values.get("rule_id") or f"unidentified-row-{row_number}",
                severity=values.get("severity") or "Unknown",
                dataset=values.get("dataset") or None,
                variable=values.get("variable") or None,
                record_keys=values.get("record_keys") or None,
                message=values.get("message") or "No message supplied",
            ))
    diagnostics.findings_imported = len(findings)
    version = next((item.provider_version for item in findings if item.provider_version != "not reported"), "not reported")
    status = "completed_with_findings" if findings else "review_required"
    record = ValidationRecord(validation_id=validation_id, provider="Pinnacle 21 report import", provider_version=version, status=status, created_at=_now(), source_artifact=original.relative_to(job_dir).as_posix(), diagnostics=diagnostics, findings=findings, message="Imported report findings require human review; import alone is not a validation pass.")
    save_validation(job_dir, record)
    state = read_state(job_dir)
    state.lifecycle.validation = "completed_with_findings" if findings else "review_required"
    state.lifecycle.submission_readiness = "review_required" if findings else "blocked"
    write_state(job_dir, state)
    return record


def save_validation(job_dir: Path, record: ValidationRecord) -> Path:
    root = job_dir / "sdtm" / "validation"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{record.validation_id}.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(record.model_dump_json(indent=2), encoding="utf-8")
    temporary.replace(path)
    return path


def list_validations(job_dir: Path) -> list[ValidationRecord]:
    root = job_dir / "sdtm" / "validation"
    if not root.is_dir():
        return []
    records = []
    for path in root.glob("*.json"):
        try:
            records.append(ValidationRecord.model_validate_json(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return sorted(records, key=lambda item: item.created_at)


def find_finding(job_dir: Path, finding_id: str) -> tuple[ValidationRecord, ValidationFinding]:
    for record in list_validations(job_dir):
        finding = next((item for item in record.findings if item.finding_id == finding_id), None)
        if finding:
            return record, finding
    raise ValueError("Validation finding was not found.")


def update_readiness(job_dir: Path) -> None:
    state = read_state(job_dir)
    validations = list_validations(job_dir)
    findings = [finding for record in validations for finding in record.findings]
    unresolved = [item for item in findings if item.finding_status == "open" or (item.finding_status in {"accepted", "not_applicable", "explained"} and item.approved_at is None)]
    external_pass = any(record.provider != InternalChecksProvider.name and record.status == "passed" for record in validations)
    if state.lifecycle.execution != "passed":
        state.lifecycle.submission_readiness = "blocked"
    elif unresolved or not external_pass:
        state.lifecycle.submission_readiness = "review_required"
    else:
        state.lifecycle.submission_readiness = "ready"
    write_state(job_dir, state)


def _read_rows(path: Path) -> tuple[list[str], list[list[object]]]:
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            rows = list(csv.reader(handle))
        return ([str(item) for item in rows[0]] if rows else []), rows[1:]
    if path.suffix.lower() == ".xlsx":
        workbook = load_workbook(path, read_only=True, data_only=True)
        sheet = workbook.active
        rows = [list(row) for row in sheet.iter_rows(values_only=True)]
        workbook.close()
        return ([str(item or "") for item in rows[0]] if rows else []), rows[1:]
    raise ValueError("Pinnacle 21 report import supports CSV and XLSX files only.")


def _map_headers(headers: list[str]) -> tuple[dict[str, int], list[str]]:
    mapped: dict[str, int] = {}
    unknown = []
    for index, header in enumerate(headers):
        normalized = " ".join(header.strip().lower().replace("_", " ").split())
        field = next((key for key, aliases in ALIASES.items() if normalized in aliases), None)
        if field and field not in mapped:
            mapped[field] = index
        elif header.strip():
            unknown.append(header)
    return mapped, unknown


def _cell(row: list[object], index: int) -> str:
    return str(row[index]).strip() if index < len(row) and row[index] is not None else ""


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


def _now() -> datetime:
    return datetime.now(timezone.utc)

