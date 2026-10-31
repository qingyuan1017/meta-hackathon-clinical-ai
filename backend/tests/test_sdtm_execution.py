from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyreadstat
import pytest

from app.schemas import (
    SDTMDataset,
    SDTMDomainMapping,
    SDTMDomainRuleAugmentation,
    SDTMPlan,
    SDTMRuleAugmentation,
    SDTMVariable,
)
from app.sdtm_execution import ProviderResult, RExecutionProvider, SDTMExecutionService, apply_typed_repair, ensure_repair_allowed, inspect_outputs, repair_depth
from app.sdtm_workbench import initialize_state, inventory_raw_dataset


class FakeProvider(RExecutionProvider):
    def __init__(self, result: ProviderResult) -> None:
        self.result = result
        self.calls = []

    def execute(self, program: Path, inputs: list[tuple[str, Path]], timeout_seconds: int) -> ProviderResult:
        self.calls.append((program, inputs, timeout_seconds))
        return self.result


def _plan() -> SDTMPlan:
    return SDTMPlan(
        study_name="SYN-101",
        domain_mappings=[SDTMDomainMapping(source_dataset="RAW_DM", target_domain="DM", rationale="Synthetic source")],
        datasets=[SDTMDataset(domain="DM", description="Demographics", key_variables=["USUBJID"], variables=[SDTMVariable(name="USUBJID", label="Unique subject", source_dataset="RAW_DM", source_field="USUBJID"), SDTMVariable(name="AGE", label="Age", data_type="Num", source_dataset="RAW_DM", source_field="AGE")])],
        domain_rule_augmentations=[SDTMDomainRuleAugmentation(rule_id="DM-SOURCE", target_domain="DM", source_datasets=["RAW_DM"], description="Read DM", logic="Direct", r_input_expression="raw_dm", sas_input_statement="set raw.raw_dm;")],
        rule_augmentations=[SDTMRuleAugmentation(rule_id="DM-USUBJID", target_domain="DM", target_variable="USUBJID", description="Direct", logic="Direct", r_expression='.data[["USUBJID"]]', sas_expression="USUBJID"), SDTMRuleAugmentation(rule_id="DM-AGE", target_domain="DM", target_variable="AGE", description="Direct", logic="Direct", r_expression='.data[["AGE"]]', sas_expression="AGE")],
    )


def _job_dir(tmp_path: Path, program: str = "x <- 1\n") -> Path:
    job_dir = tmp_path / "job"
    input_dir = job_dir / "input"
    output_dir = job_dir / "output"
    input_dir.mkdir(parents=True)
    output_dir.mkdir()
    raw = input_dir / "raw_dm.csv"
    raw.write_text("USUBJID,AGE\nSYN-001,42\n", encoding="utf-8")
    inventory = inventory_raw_dataset(raw, "raw_dm.csv")
    initialize_state(job_dir, metadata_files=["edc.json"], blank_crf=None, raw_datasets=[inventory], validation_report=None)
    (output_dir / "build-dm.R").write_text(program, encoding="utf-8")
    return job_dir


def _xpt_bytes(tmp_path: Path, columns: dict[str, list[object]] | None = None) -> bytes:
    path = tmp_path / "fixture.xpt"
    pyreadstat.write_xport(pd.DataFrame(columns or {"USUBJID": ["SYN-001"], "AGE": [42.0]}), path, table_name="DM", file_format_version=5)
    return path.read_bytes()


def test_execution_preserves_hashes_runtime_outputs_and_checks(tmp_path) -> None:
    provider = FakeProvider(ProviderResult(status="passed", exit_code=0, stdout="done", stderr="", runtime={"r": "4.4", "haven": "2.5"}, outputs={"dm.xpt": _xpt_bytes(tmp_path)}))
    attempt = SDTMExecutionService(provider, 30).execute(_job_dir(tmp_path), _plan())
    assert attempt.status == "passed"
    assert len(attempt.program_hash) == 64
    assert attempt.runtime["r"] == "4.4"
    assert attempt.outputs[0].name == "dm.xpt"
    assert all(check.status == "passed" for check in attempt.checks)
    assert provider.calls[0][1][0][0] == "RAW_DM"


@pytest.mark.parametrize("provider_status,classification", [("timed_out", "timeout"), ("unavailable", "runner_unavailable")])
def test_timeout_and_unavailable_are_truthful(tmp_path, provider_status: str, classification: str) -> None:
    provider = FakeProvider(ProviderResult(status=provider_status, exit_code=None, stdout="", stderr="not executed"))
    attempt = SDTMExecutionService(provider).execute(_job_dir(tmp_path), _plan())
    assert attempt.status == provider_status
    assert attempt.failure_classification == classification


def test_prohibited_program_is_rejected_before_provider_call(tmp_path) -> None:
    provider = FakeProvider(ProviderResult(status="passed", exit_code=0, stdout="", stderr=""))
    with pytest.raises(ValueError, match="prohibited"):
        SDTMExecutionService(provider).execute(_job_dir(tmp_path, "system('id')\n"), _plan())
    assert provider.calls == []


def test_malformed_xpt_and_missing_columns_fail_post_run_checks(tmp_path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    (output / "dm.xpt").write_bytes(b"not-an-xpt")
    checks, _ = inspect_outputs(output, _plan())
    assert any(check.check_id == "xpt-readable" and check.status == "failed" for check in checks)
    (output / "dm.xpt").write_bytes(_xpt_bytes(tmp_path, {"USUBJID": ["SYN-001"]}))
    checks, _ = inspect_outputs(output, _plan())
    assert any(check.check_id == "expected-variables" and check.status == "failed" for check in checks)


def test_missing_column_proposes_typed_repair_and_preserves_parent_history(tmp_path) -> None:
    plan = _plan()
    age = next(item for item in plan.datasets[0].variables if item.name == "AGE")
    age.source_field = "AGEE"
    age_rule = next(item for item in plan.rule_augmentations if item.target_variable == "AGE")
    age_rule.r_expression = '.data[["AGEE"]]'
    provider = FakeProvider(ProviderResult(status="failed", exit_code=1, stdout="", stderr="Caused by error in `.data[[\"AGEE\"]]`: Column `AGEE` not found in `.data`."))
    job_dir = _job_dir(tmp_path)
    first = SDTMExecutionService(provider).execute(job_dir, plan)
    assert first.status == "failed"
    assert first.failure_classification == "missing_source_column"
    assert first.repair_proposal is not None
    assert "AGEE" in first.repair_proposal.diff and "AGE" in first.repair_proposal.diff
    first.repair_proposal.status = "approved"
    first.repair_proposal.reviewer = "Jane Reviewer"
    repaired = apply_typed_repair(plan, first.repair_proposal)
    assert next(item for item in repaired.datasets[0].variables if item.name == "AGE").source_field == "AGE"
    assert next(item for item in repaired.rule_augmentations if item.target_variable == "AGE").r_expression == '.data[["AGE"]]'

    second = SDTMExecutionService(provider).execute(job_dir, plan, parent_attempt_id=first.attempt_id)
    third = SDTMExecutionService(provider).execute(job_dir, plan, parent_attempt_id=second.attempt_id)
    fourth = SDTMExecutionService(provider).execute(job_dir, plan, parent_attempt_id=third.attempt_id)
    assert repair_depth(job_dir, first) == 0
    assert repair_depth(job_dir, fourth) == 3
    assert (job_dir / "sdtm" / "executions" / first.attempt_id / "attempt.json").is_file()
    with pytest.raises(ValueError, match="maximum of 3"):
        ensure_repair_allowed(job_dir, fourth)

