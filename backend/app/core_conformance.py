from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from .config import Settings, get_settings


CORE_ENGINE_NAME = "CDISC CORE"
CORE_ENGINE_VERSION = "0.17.1"
CORE_STANDARD = "USDM"
CORE_STANDARD_VERSION = "4.0"
CORE_CLI_VERSION = "4-0"
CORE_USDM4_RULE_COUNT = 207
CORE_REPORT_FILENAME = "core-report.json"
CORE_DECISION_FILENAME = "core-conformance.json"

_KNOWN_STATUSES = {"SUCCESS", "SKIPPED", "ISSUE REPORTED", "EXECUTION ERROR"}
_NON_APPLICABLE_REASON = "Outside scope"


@dataclass(frozen=True)
class CoreConformanceResult:
    conformant: bool
    report_path: Path | None
    decision_path: Path
    status_counts: dict[str, int]
    blocking_rules: tuple[dict[str, str], ...]
    allowed_skipped_rules: tuple[str, ...]
    reported_rule_count: int


class CoreConformanceError(RuntimeError):
    """Raised when CORE cannot prove conformance for a generated USDM artifact."""

    def __init__(
        self,
        message: str,
        *,
        artifact_paths: list[Path],
        result_data: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.artifact_paths = artifact_paths
        self.result_data = result_data


def run_core_conformance(
    usdm_path: Path,
    output_dir: Path,
    *,
    settings: Settings | None = None,
) -> CoreConformanceResult:
    """Run the complete pinned CORE USDM 4.0 ruleset and make a fail-closed decision."""

    active_settings = settings or get_settings()
    report_path = output_dir / CORE_REPORT_FILENAME
    decision_path = output_dir / CORE_DECISION_FILENAME
    cli_path = active_settings.core_cli_path.resolve()

    if not cli_path.is_file():
        decision = _runtime_failure(
            f"The pinned CDISC CORE CLI was not found at {cli_path}.",
        )
        _write_decision(decision_path, decision)
        return _result_from_decision(decision, None, decision_path)

    command = _core_command(cli_path, usdm_path.resolve(), report_path.resolve(), active_settings)
    try:
        completed = subprocess.run(
            command,
            cwd=cli_path.parent,
            capture_output=True,
            text=True,
            timeout=active_settings.core_timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        decision = _runtime_failure(f"CDISC CORE could not be executed: {exc}")
        _write_decision(decision_path, decision)
        return _result_from_decision(decision, None, decision_path)

    if completed.returncode != 0 or not report_path.is_file():
        diagnostic = (completed.stderr or completed.stdout or "No diagnostic was returned.").strip()
        decision = _runtime_failure(
            f"CDISC CORE exited with code {completed.returncode}: {diagnostic[:800]}"
        )
        _write_decision(decision_path, decision)
        return _result_from_decision(
            decision,
            report_path if report_path.is_file() else None,
            decision_path,
        )

    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        decision = _runtime_failure(f"CDISC CORE produced an unreadable JSON report: {exc}")
        _write_decision(decision_path, decision)
        return _result_from_decision(decision, report_path, decision_path)

    decision = evaluate_core_report(report)
    _write_decision(decision_path, decision)
    return _result_from_decision(decision, report_path, decision_path)


def evaluate_core_report(report: dict[str, Any]) -> dict[str, Any]:
    """Evaluate an official raw JSON report using a strict, reproducible policy."""

    details = report.get("Conformance_Details")
    rules = report.get("Rules_Report")
    raw_results = report.get("results_data")
    blocking: list[dict[str, str]] = []
    allowed_skips: list[str] = []

    if not isinstance(details, dict):
        details = {}
        blocking.append(_block("REPORT", "INVALID REPORT", "Conformance_Details is missing."))
    expected_metadata = {
        "CORE_Engine_Version": CORE_ENGINE_VERSION,
        "Standard": CORE_STANDARD,
        "Version": f"V{CORE_STANDARD_VERSION}",
    }
    for key, expected in expected_metadata.items():
        actual = details.get(key)
        if actual != expected:
            blocking.append(
                _block("REPORT", "METADATA MISMATCH", f"{key} is {actual!r}; expected {expected!r}.")
            )

    if not isinstance(rules, list):
        rules = []
        blocking.append(_block("REPORT", "INVALID REPORT", "Rules_Report is missing."))
    if not isinstance(raw_results, list):
        raw_results = []
        blocking.append(_block("REPORT", "INVALID REPORT", "Raw results_data is missing."))

    rule_rows = [row for row in rules if isinstance(row, dict)]
    rule_ids = [str(row.get("core_id", "")) for row in rule_rows]
    raw_by_id = {
        str(row.get("id")): row
        for row in raw_results
        if isinstance(row, dict) and row.get("id")
    }
    if len(rule_rows) != CORE_USDM4_RULE_COUNT:
        blocking.append(
            _block(
                "RULESET",
                "INCOMPLETE RULESET",
                f"CORE reported {len(rule_rows)} rules; {CORE_USDM4_RULE_COUNT} are required.",
            )
        )
    if len(set(rule_ids)) != len(rule_ids) or set(rule_ids) != set(raw_by_id):
        blocking.append(
            _block(
                "RULESET",
                "INCONSISTENT RULESET",
                "Rules_Report and raw results_data do not contain the same unique CORE IDs.",
            )
        )

    counts = Counter(str(row.get("status", "UNKNOWN STATUS")).upper() for row in rule_rows)
    for row in rule_rows:
        core_id = str(row.get("core_id") or "UNKNOWN")
        status = str(row.get("status") or "UNKNOWN STATUS").upper()
        if status not in _KNOWN_STATUSES:
            blocking.append(_block(core_id, status, "CORE returned an unknown rule status."))
        elif status in {"ISSUE REPORTED", "EXECUTION ERROR"}:
            blocking.append(_block(core_id, status, str(row.get("message") or status)))
        elif status == "SKIPPED":
            raw = raw_by_id.get(core_id)
            if _is_non_applicable_skip(raw):
                allowed_skips.append(core_id)
            else:
                blocking.append(
                    _block(
                        core_id,
                        status,
                        _skip_reason(raw) or "The rule did not execute and was not proven out of scope.",
                    )
                )

    decision = {
        "conformant": not blocking,
        "engine": {"name": CORE_ENGINE_NAME, "version": CORE_ENGINE_VERSION},
        "standard": {"name": CORE_STANDARD, "version": CORE_STANDARD_VERSION},
        "ruleset": {
            "expected_rule_count": CORE_USDM4_RULE_COUNT,
            "reported_rule_count": len(rule_rows),
            "complete": len(rule_rows) == CORE_USDM4_RULE_COUNT,
        },
        "status_counts": dict(sorted(counts.items())),
        "allowed_non_applicable_skips": sorted(allowed_skips),
        "blocking_rules": blocking,
        "policy": (
            "All 207 rules bundled with CDISC CORE 0.17.1 must be reported. Findings, execution "
            "errors, unknown statuses, incomplete reports, and technical skips fail conformance. "
            "A skipped rule is allowed only when every raw result is explicitly Outside scope."
        ),
    }
    return decision


def _core_command(
    cli_path: Path,
    usdm_path: Path,
    report_path: Path,
    settings: Settings,
) -> list[str]:
    launcher = [str(cli_path)] if cli_path.suffix.lower() == ".exe" else [sys.executable, str(cli_path)]
    return [
        *launcher,
        "validate",
        "--standard",
        "usdm",
        "--version",
        CORE_CLI_VERSION,
        "--dataset-path",
        str(usdm_path),
        "--output",
        str(report_path),
        "--output-format",
        "JSON",
        "--raw-report",
        "--progress",
        "disabled",
        "--pool-size",
        str(settings.core_pool_size),
    ]


def _is_non_applicable_skip(raw: Any) -> bool:
    if not isinstance(raw, dict) or str(raw.get("execution_status", "")).lower() != "skipped":
        return False
    results = raw.get("results")
    if not isinstance(results, list) or not results:
        return False
    errors: list[Any] = []
    for result in results:
        if not isinstance(result, dict) or str(result.get("executionStatus", "")).lower() != "skipped":
            return False
        result_errors = result.get("errors")
        if not isinstance(result_errors, list) or not result_errors:
            return False
        errors.extend(result_errors)
    return bool(errors) and all(
        isinstance(error, dict) and error.get("error") == _NON_APPLICABLE_REASON
        for error in errors
    )


def _skip_reason(raw: Any) -> str:
    if not isinstance(raw, dict):
        return "Raw result is missing."
    reasons: list[str] = []
    for result in raw.get("results") or []:
        if not isinstance(result, dict):
            continue
        for error in result.get("errors") or []:
            if not isinstance(error, dict):
                continue
            reason = str(error.get("error") or error.get("message") or "").strip()
            if reason and reason not in reasons:
                reasons.append(reason)
    return "; ".join(reasons)


def _runtime_failure(message: str) -> dict[str, Any]:
    return {
        "conformant": False,
        "engine": {"name": CORE_ENGINE_NAME, "version": CORE_ENGINE_VERSION},
        "standard": {"name": CORE_STANDARD, "version": CORE_STANDARD_VERSION},
        "ruleset": {
            "expected_rule_count": CORE_USDM4_RULE_COUNT,
            "reported_rule_count": 0,
            "complete": False,
        },
        "status_counts": {},
        "allowed_non_applicable_skips": [],
        "blocking_rules": [_block("RUNTIME", "EXECUTION ERROR", message)],
        "policy": "Conformance fails closed when the pinned official CORE runtime cannot complete.",
    }


def _result_from_decision(
    decision: dict[str, Any],
    report_path: Path | None,
    decision_path: Path,
) -> CoreConformanceResult:
    ruleset = decision.get("ruleset") or {}
    return CoreConformanceResult(
        conformant=bool(decision.get("conformant")),
        report_path=report_path,
        decision_path=decision_path,
        status_counts={str(key): int(value) for key, value in (decision.get("status_counts") or {}).items()},
        blocking_rules=tuple(decision.get("blocking_rules") or []),
        allowed_skipped_rules=tuple(decision.get("allowed_non_applicable_skips") or []),
        reported_rule_count=int(ruleset.get("reported_rule_count") or 0),
    )


def _block(core_id: str, status: str, reason: str) -> dict[str, str]:
    return {"core_id": core_id, "status": status, "reason": reason}


def _write_decision(path: Path, decision: dict[str, Any]) -> None:
    path.write_text(json.dumps(decision, indent=2, ensure_ascii=False), encoding="utf-8")
