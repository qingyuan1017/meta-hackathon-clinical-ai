from __future__ import annotations

import base64
import difflib
import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from .artifacts import sha256_file
from .schemas import SDTMPlan
from .schemas.sdtm_workbench import (
    ExecutionAttempt,
    ExecutionCheck,
    ExecutionOutput,
    RepairChange,
    RepairProposal,
    RawDatasetInventory,
)
from .sdtm_workbench import read_state, write_state


PROHIBITED_R = re.compile(
    r"(?i)(?:system2?\s*\(|shell\s*\(|download\.file\s*\(|install\.packages\s*\(|"
    r"socketConnection\s*\(|url\s*\(|curl::|httr2?::|processx::|parallel::|\.\.\/|/etc/|/proc/)"
)
SECRET = re.compile(r"(?i)(api[_-]?key|authorization|bearer)\s*[:=]\s*\S+")


@dataclass
class ProviderResult:
    status: str
    exit_code: int | None
    stdout: str
    stderr: str
    runtime: dict[str, str] = field(default_factory=dict)
    outputs: dict[str, bytes] = field(default_factory=dict)


class RExecutionProvider(ABC):
    @abstractmethod
    def execute(self, program: Path, inputs: list[tuple[str, Path]], timeout_seconds: int) -> ProviderResult:
        raise NotImplementedError


class UnavailableRExecutionProvider(RExecutionProvider):
    def execute(self, program: Path, inputs: list[tuple[str, Path]], timeout_seconds: int) -> ProviderResult:
        return ProviderResult(
            status="unavailable",
            exit_code=None,
            stdout="",
            stderr="The isolated SDTM runner is not configured.",
            runtime={},
        )


class RemoteRExecutionProvider(RExecutionProvider):
    def __init__(self, url: str) -> None:
        self.url = url.rstrip("/")

    def execute(self, program: Path, inputs: list[tuple[str, Path]], timeout_seconds: int) -> ProviderResult:
        files: list[tuple[str, tuple[str, bytes, str]]] = [
            ("program", (program.name, program.read_bytes(), "text/x-r-source"))
        ]
        for logical_name, path in inputs:
            files.append(("raw_files", (f"{logical_name}{path.suffix.lower()}", path.read_bytes(), "application/octet-stream")))
        try:
            response = httpx.post(
                f"{self.url}/execute",
                files=files,
                data={"timeout_seconds": str(timeout_seconds)},
                timeout=timeout_seconds + 15,
            )
        except httpx.TimeoutException:
            return ProviderResult(status="timed_out", exit_code=None, stdout="", stderr="Runner request timed out.")
        except httpx.HTTPError:
            return ProviderResult(status="unavailable", exit_code=None, stdout="", stderr="The isolated runner is unavailable.")
        if response.status_code != 200:
            return ProviderResult(status="failed", exit_code=None, stdout="", stderr=f"Runner rejected the request ({response.status_code}).")
        payload = response.json()
        outputs = {
            str(item["name"]): base64.b64decode(str(item["content_base64"]), validate=True)
            for item in payload.get("outputs", [])
        }
        return ProviderResult(
            status=str(payload.get("status", "failed")),
            exit_code=payload.get("exit_code"),
            stdout=str(payload.get("stdout", "")),
            stderr=str(payload.get("stderr", "")),
            runtime={str(k): str(v) for k, v in payload.get("runtime", {}).items()},
            outputs=outputs,
        )


class SDTMExecutionService:
    def __init__(self, provider: RExecutionProvider, timeout_seconds: int = 180) -> None:
        self.provider = provider
        self.timeout_seconds = timeout_seconds

    def execute(self, job_dir: Path, plan: SDTMPlan, parent_attempt_id: str | None = None) -> ExecutionAttempt:
        state = read_state(job_dir)
        if not state.inputs.raw_datasets:
            raise ValueError("Raw CSV/XPT datasets are required before R execution can start.")
        program = job_dir / "output" / "build-sdtm.R"
        if not program.is_file():
            raise ValueError("The reviewed R program artifact is unavailable.")
        program_text = program.read_text(encoding="utf-8")
        if PROHIBITED_R.search(program_text):
            raise ValueError("The generated R program contains prohibited shell, network, installation, or external-read behavior.")

        attempt_id = f"attempt-{uuid4().hex[:12]}"
        attempt_dir = job_dir / "sdtm" / "executions" / attempt_id
        attempt_dir.mkdir(parents=True, exist_ok=False)
        immutable_program = attempt_dir / "program.R"
        immutable_program.write_text(program_text, encoding="utf-8")
        created_at = datetime.now(timezone.utc)
        attempt = ExecutionAttempt(
            attempt_id=attempt_id,
            parent_attempt_id=parent_attempt_id,
            status="running",
            created_at=created_at,
            started_at=created_at,
            program_hash=sha256_file(immutable_program),
            input_manifest=state.inputs.raw_datasets,
            program_artifact=immutable_program.relative_to(job_dir).as_posix(),
        )
        _write_attempt(attempt_dir, attempt)
        state.lifecycle.execution = "running"
        state.lifecycle.submission_readiness = "blocked"
        write_state(job_dir, state)

        inputs = [
            (item.logical_name, job_dir / "input" / item.stored_name)
            for item in state.inputs.raw_datasets
        ]
        result = self.provider.execute(immutable_program, inputs, self.timeout_seconds)
        output_dir = attempt_dir / "output"
        output_dir.mkdir()
        for name, content in result.outputs.items():
            safe_name = Path(name).name
            if safe_name != name or Path(safe_name).suffix.lower() != ".xpt":
                continue
            (output_dir / safe_name).write_bytes(content)

        checks, outputs = inspect_outputs(output_dir, plan)
        provider_passed = result.status == "passed" and result.exit_code == 0
        checks_passed = bool(checks) and not any(item.status in {"failed", "not_run"} for item in checks)
        final_status = "passed" if provider_passed and checks_passed else result.status
        if final_status == "passed" and not checks_passed:
            final_status = "failed"
        if final_status not in {"passed", "failed", "timed_out", "unavailable"}:
            final_status = "failed"
        attempt.status = final_status  # type: ignore[assignment]
        attempt.completed_at = datetime.now(timezone.utc)
        attempt.exit_code = result.exit_code
        attempt.stdout = sanitize_log(result.stdout)
        attempt.stderr = sanitize_log(result.stderr)
        attempt.runtime = result.runtime
        attempt.outputs = outputs
        attempt.checks = checks
        if final_status != "passed":
            attempt.failure_classification = classify_failure(attempt)
            attempt.repair_proposal = propose_repair(attempt, plan, state.inputs.raw_datasets)
        _write_attempt(attempt_dir, attempt)

        state = read_state(job_dir)
        state.lifecycle.execution = "passed" if final_status == "passed" else ("not_run" if final_status == "unavailable" else "failed")
        state.lifecycle.submission_readiness = "review_required" if final_status == "passed" else "blocked"
        write_state(job_dir, state)
        return attempt


def inspect_outputs(output_dir: Path, plan: SDTMPlan) -> tuple[list[ExecutionCheck], list[ExecutionOutput]]:
    checks: list[ExecutionCheck] = []
    outputs: list[ExecutionOutput] = []
    try:
        import pyreadstat
    except ImportError:
        return [ExecutionCheck(check_id="xpt-reader", status="failed", message="XPT reader dependency is unavailable.")], []
    expected = {dataset.domain.upper(): dataset for dataset in plan.datasets}
    found = {path.stem.upper(): path for path in output_dir.glob("*.xpt")}
    for domain, dataset in expected.items():
        path = found.get(domain)
        if path is None:
            checks.append(ExecutionCheck(check_id="expected-domain", domain=domain, status="failed", message=f"Expected {domain}.xpt was not produced."))
            continue
        try:
            frame, _metadata = pyreadstat.read_xport(str(path))
        except Exception:
            checks.append(ExecutionCheck(check_id="xpt-readable", domain=domain, status="failed", message=f"{path.name} is not a readable XPT dataset."))
            continue
        columns = [str(item).upper() for item in frame.columns]
        outputs.append(ExecutionOutput(name=path.name, sha256=sha256_file(path), size_bytes=path.stat().st_size, row_count=len(frame.index), columns=columns))
        checks.append(ExecutionCheck(check_id="xpt-readable", domain=domain, status="passed", message=f"{path.name} is readable with {len(frame.index)} rows."))
        missing = [variable.name for variable in dataset.variables if variable.name.upper() not in columns]
        checks.append(ExecutionCheck(check_id="expected-variables", domain=domain, status="failed" if missing else "passed", message=f"Missing expected variables: {', '.join(missing)}." if missing else "All expected variables are present."))
        actual_columns = {str(name).upper(): str(name) for name in frame.columns}
        identifiers = [name for name in dataset.key_variables if name.upper() in actual_columns]
        wholly_missing = [name for name in identifiers if frame[actual_columns[name.upper()]].isna().all()]
        checks.append(ExecutionCheck(check_id="required-identifiers", domain=domain, status="failed" if wholly_missing else "passed", message=f"Identifiers wholly missing: {', '.join(wholly_missing)}." if wholly_missing else "Available required identifiers are not wholly missing."))
        checks.append(ExecutionCheck(check_id="output-name", domain=domain, status="passed" if path.stem.upper() == domain else "failed", message=f"Output name {path.name} is consistent with domain {domain}."))
    extras = sorted(set(found) - set(expected))
    if extras:
        checks.append(ExecutionCheck(check_id="unexpected-domains", status="warning", message=f"Unexpected XPT outputs: {', '.join(extras)}."))
    return checks, outputs


def list_attempts(job_dir: Path) -> list[ExecutionAttempt]:
    root = job_dir / "sdtm" / "executions"
    if not root.is_dir():
        return []
    attempts = []
    for path in root.glob("*/attempt.json"):
        try:
            attempts.append(ExecutionAttempt.model_validate_json(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return sorted(attempts, key=lambda item: item.created_at)


def load_attempt(job_dir: Path, attempt_id: str) -> ExecutionAttempt:
    if not re.fullmatch(r"attempt-[a-f0-9]{12}", attempt_id):
        raise ValueError("Invalid execution attempt identifier.")
    path = job_dir / "sdtm" / "executions" / attempt_id / "attempt.json"
    if not path.is_file():
        raise ValueError("Execution attempt was not found.")
    return ExecutionAttempt.model_validate_json(path.read_text(encoding="utf-8"))


def save_attempt(job_dir: Path, attempt: ExecutionAttempt) -> None:
    _write_attempt(job_dir / "sdtm" / "executions" / attempt.attempt_id, attempt)


def repair_depth(job_dir: Path, attempt: ExecutionAttempt) -> int:
    by_id = {item.attempt_id: item for item in list_attempts(job_dir)}
    depth = 0
    current = attempt
    seen: set[str] = set()
    while current.parent_attempt_id:
        if current.attempt_id in seen:
            raise ValueError("Execution attempt history contains a cycle.")
        seen.add(current.attempt_id)
        depth += 1
        current = by_id.get(current.parent_attempt_id)  # type: ignore[assignment]
        if current is None:
            break
    return depth


def ensure_repair_allowed(job_dir: Path, attempt: ExecutionAttempt, maximum: int = 3) -> None:
    if repair_depth(job_dir, attempt) >= maximum:
        raise ValueError(f"The maximum of {maximum} approved repair attempts has been reached.")


def propose_repair(attempt: ExecutionAttempt, plan: SDTMPlan, inventory: list[RawDatasetInventory]) -> RepairProposal | None:
    if attempt.failure_classification != "missing_source_column":
        return None
    text = f"{attempt.stderr}\n{attempt.stdout}"
    patterns = [r"(?i)(?:object|column)\s+['`\"]([^'`\"]+)['`\"]\s+(?:not found|does not exist|doesn't exist)", r"(?i)unknown columns?:?\s*([^\s,]+)"]
    unknown = next((match.group(1) for pattern in patterns if (match := re.search(pattern, text))), None)
    if not unknown:
        return None
    for dataset in plan.datasets:
        for variable in dataset.variables:
            if not variable.source_dataset or not variable.source_field:
                continue
            if variable.source_field.casefold() != unknown.casefold() and unknown.casefold() not in next((rule.r_expression.casefold() for rule in plan.rule_augmentations if rule.target_domain == dataset.domain and rule.target_variable == variable.name), ""):
                continue
            source_inventory = next((item for item in inventory if item.logical_name == variable.source_dataset.upper()), None)
            if source_inventory is None:
                continue
            available = [column.name for column in source_inventory.columns]
            matches = difflib.get_close_matches(unknown, available, n=1, cutoff=0.55)
            if not matches:
                continue
            replacement = matches[0]
            change = RepairChange(domain=dataset.domain, target_variable=variable.name, from_source_field=variable.source_field, to_source_field=replacement)
            return RepairProposal(
                proposal_id=f"repair-{uuid4().hex[:12]}",
                rationale=f"The runner reported missing source column {unknown!r}; {replacement!r} is the closest reviewed column in {source_inventory.logical_name}.",
                diff=f"{dataset.domain}.{variable.name}: source_field {variable.source_field!r} -> {replacement!r}",
                change=change,
            )
    return None


def apply_typed_repair(plan: SDTMPlan, proposal: RepairProposal) -> SDTMPlan:
    repaired = plan.model_copy(deep=True)
    change = proposal.change
    dataset = next((item for item in repaired.datasets if item.domain == change.domain), None)
    variable = next((item for item in dataset.variables if item.name == change.target_variable), None) if dataset else None
    if variable is None or variable.source_field != change.from_source_field:
        raise ValueError("The reviewed plan changed after this proposal.")
    variable.source_field = change.to_source_field
    variable.mapping_expression = f"Direct from {change.to_source_field} (approved repair)"
    rule = next((item for item in repaired.rule_augmentations if item.target_domain == change.domain and item.target_variable == change.target_variable), None)
    if rule is None:
        raise ValueError("The typed variable rule for this proposal is unavailable.")
    rule.source_dependencies = [f"{variable.source_dataset}.{change.to_source_field}"]
    rule.r_expression = f'.data[["{change.to_source_field}"]]'
    reviewer = proposal.reviewer or "reviewer"
    rule.review_notes = [*rule.review_notes, f"Repair {proposal.proposal_id} approved by {reviewer}."]
    return repaired


def _write_attempt(attempt_dir: Path, attempt: ExecutionAttempt) -> None:
    path = attempt_dir / "attempt.json"
    temp = path.with_suffix(".tmp")
    temp.write_text(attempt.model_dump_json(indent=2), encoding="utf-8")
    temp.replace(path)


def sanitize_log(value: str) -> str:
    sanitized = SECRET.sub(r"\1=[REDACTED]", value.replace("\x00", ""))
    return sanitized[-20_000:]


def classify_failure(attempt: ExecutionAttempt) -> str:
    text = f"{attempt.stderr}\n{attempt.stdout}".lower()
    if attempt.status == "timed_out":
        return "timeout"
    if attempt.status == "unavailable":
        return "runner_unavailable"
    if (("object" in text or "column" in text) and "not found" in text) or "unknown columns" in text or ("column" in text and "doesn't exist" in text):
        return "missing_source_column"
    if any(item.check_id == "expected-variables" and item.status == "failed" for item in attempt.checks):
        return "missing_output_variable"
    if any(item.check_id == "xpt-readable" and item.status == "failed" for item in attempt.checks):
        return "malformed_output"
    return "runtime_error"

