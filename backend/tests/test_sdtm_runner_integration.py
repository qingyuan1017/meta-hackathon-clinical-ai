from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from app.artifacts import render_sdtm
from app.schemas import (
    SDTMDataset,
    SDTMDomainMapping,
    SDTMDomainRuleAugmentation,
    SDTMPlan,
    SDTMRuleAugmentation,
    SDTMVariable,
)
from app.sdtm_execution import RemoteRExecutionProvider, SDTMExecutionService, apply_typed_repair, list_attempts
from app.sdtm_workbench import initialize_state, inventory_raw_dataset


pytestmark = pytest.mark.skipif(
    os.environ.get("SDTM_RUNNER_INTEGRATION") != "1",
    reason="Set SDTM_RUNNER_INTEGRATION=1 with a reachable isolated runner to execute R.",
)


def _demo_plan() -> SDTMPlan:
    domains = {
        "DM": ["STUDYID", "USUBJID", "SUBJID", "RFICDTC", "AGE", "SEX"],
        "AE": ["STUDYID", "USUBJID", "AESEQ", "AETERM", "AESTDTC", "AEENDTC", "AESEV", "AESER"],
    }
    labels = {
        "DM": "Demographics",
        "AE": "Adverse Events",
    }
    numeric = {"AGE", "AESEQ"}
    datasets = []
    mappings = []
    domain_rules = []
    variable_rules = []
    for domain, names in domains.items():
        source = f"RAW_{domain}"
        mappings.append(SDTMDomainMapping(source_dataset=source, target_domain=domain, rationale="Synthetic direct-map demo"))
        domain_rules.append(
            SDTMDomainRuleAugmentation(
                rule_id=f"{domain}-SOURCE",
                target_domain=domain,
                source_datasets=[source],
                description=f"Read the synthetic {source} source.",
                logic="Direct source read",
                r_input_expression=source.lower(),
                sas_input_statement=f"set raw.{source.lower()};",
            )
        )
        variables = []
        for name in names:
            variables.append(
                SDTMVariable(
                    name=name,
                    label=name.replace("ID", " Identifier").title(),
                    data_type="Num" if name in numeric else "Char",
                    source_dataset=source,
                    source_field=name,
                    mapping_expression=f"Direct from {source}.{name}",
                )
            )
            variable_rules.append(
                SDTMRuleAugmentation(
                    rule_id=f"{domain}-{name}",
                    target_domain=domain,
                    target_variable=name,
                    description=f"Direct map from {source}.{name}.",
                    logic="Direct",
                    source_dependencies=[f"{source}.{name}"],
                    r_expression=f'.data[["{name}"]]',
                    sas_expression=name,
                )
            )
        datasets.append(
            SDTMDataset(
                domain=domain,
                description=labels[domain],
                key_variables=["USUBJID"] if domain == "DM" else ["USUBJID", "AESEQ"],
                variables=variables,
            )
        )
    return SDTMPlan(
        study_name="SYN-DMAE-001",
        domain_mappings=mappings,
        datasets=datasets,
        domain_rule_augmentations=domain_rules,
        rule_augmentations=variable_rules,
    )


def test_live_isolated_runner_generates_readable_dm_and_ae_xpt(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[2]
    job_dir = tmp_path / "job"
    input_dir = job_dir / "input"
    output_dir = job_dir / "output"
    input_dir.mkdir(parents=True)
    output_dir.mkdir()
    inventories = []
    for name in ("RAW_DM.csv", "RAW_AE.csv"):
        target = input_dir / name
        shutil.copy2(repository / "samples" / name, target)
        inventories.append(inventory_raw_dataset(target, name))
    initialize_state(
        job_dir,
        metadata_files=["sdtm-demo-edc.json"],
        blank_crf=None,
        raw_datasets=inventories,
        validation_report=None,
    )
    plan = _demo_plan()
    render_sdtm(plan, None, output_dir, ["r", "sas"])

    provider = RemoteRExecutionProvider(os.environ.get("SDTM_RUNNER_URL", "http://sdtm-runner:8010"))
    attempt = SDTMExecutionService(provider, timeout_seconds=120).execute(job_dir, plan)

    assert attempt.status == "passed", attempt.stderr
    assert {item.name for item in attempt.outputs} == {"dm.xpt", "ae.xpt"}
    assert {item.domain for item in attempt.checks if item.check_id == "xpt-readable" and item.status == "passed"} == {"DM", "AE"}
    assert attempt.runtime["runner"] == "clinical-ai-sdtm-runner/0.1.0"


def test_live_missing_column_repair_is_reviewed_rerun_and_retained(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[2]
    job_dir = tmp_path / "repair-job"
    input_dir = job_dir / "input"
    output_dir = job_dir / "output"
    input_dir.mkdir(parents=True)
    output_dir.mkdir()
    dm = input_dir / "RAW_DM.csv"
    ae = input_dir / "RAW_AE.csv"
    shutil.copy2(repository / "samples" / "RAW_DM.csv", dm)
    shutil.copy2(repository / "samples" / "RAW_AE-mismatch.csv", ae)
    initialize_state(
        job_dir,
        metadata_files=["sdtm-demo-edc.json"],
        blank_crf=None,
        raw_datasets=[inventory_raw_dataset(dm, dm.name), inventory_raw_dataset(ae, ae.name)],
        validation_report=None,
    )
    plan = _demo_plan()
    render_sdtm(plan, None, output_dir, ["r", "sas"])
    provider = RemoteRExecutionProvider(os.environ.get("SDTM_RUNNER_URL", "http://sdtm-runner:8010"))
    service = SDTMExecutionService(provider, timeout_seconds=120)

    failed = service.execute(job_dir, plan)
    assert failed.status == "failed"
    assert failed.failure_classification == "missing_source_column"
    assert failed.repair_proposal is not None
    assert failed.repair_proposal.change.from_source_field == "AETERM"
    assert failed.repair_proposal.change.to_source_field == "AETERM_RAW"

    failed.repair_proposal.status = "approved"
    failed.repair_proposal.reviewer = "Synthetic Demo Reviewer"
    repaired_plan = apply_typed_repair(plan, failed.repair_proposal)
    render_sdtm(repaired_plan, None, output_dir, ["r", "sas"])
    rerun = service.execute(job_dir, repaired_plan, parent_attempt_id=failed.attempt_id)

    assert rerun.status == "passed", rerun.stderr
    assert rerun.parent_attempt_id == failed.attempt_id
    attempts = list_attempts(job_dir)
    assert [item.status for item in attempts] == ["failed", "passed"]
    assert all((job_dir / "sdtm" / "executions" / item.attempt_id / "program.R").is_file() for item in attempts)
