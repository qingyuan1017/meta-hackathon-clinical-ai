from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone

import pandas as pd
import pyreadstat
from lxml import etree
from reportlab.pdfgen import canvas

from app.artifacts import render_sdtm, sha256_file
from app.csdrg import render_csdrg
from app.schemas import SDTMDataset, SDTMDomainMapping, SDTMPlan, SDTMRuleAugmentation, SDTMVariable
from app.schemas.sdtm_workbench import ExecutionAttempt, ExecutionOutput
from app.sdtm_submission import PACKAGE_FOLDERS, refresh_submission_package
from app.sdtm_workbench import initialize_state, inventory_raw_dataset, read_state, write_state
from tests.sdtm_helpers import read_plan, source


def _plan() -> SDTMPlan:
    return SDTMPlan(
        study_name="SYN-PACKAGE",
        domain_mappings=[SDTMDomainMapping(source_dataset="RAW_DM", target_domain="DM", rationale="Synthetic")],
        datasets=[
            SDTMDataset(
                domain="DM",
                description="Demographics",
                record_plan=read_plan("DM", "RAW_DM"),
                variables=[SDTMVariable(name="USUBJID", label="Subject", sources=[source("RAW_DM", "USUBJID")], crf_source_label="Subject")],
            )
        ],
        rule_augmentations=[
            SDTMRuleAugmentation(
                rule_id="DM-USUBJID",
                target_domain="DM",
                target_variable="USUBJID",
                description="Direct",
                logic="Direct",
                r_expression='.data[["USUBJID"]]',
                sas_expression="USUBJID",
            )
        ],
    )


def test_submission_package_has_requested_layout_and_internal_define_links(tmp_path) -> None:
    job_dir = tmp_path / "job"
    input_dir = job_dir / "input"
    output_dir = job_dir / "output"
    execution_dir = job_dir / "sdtm" / "executions" / "attempt-0123456789ab"
    input_dir.mkdir(parents=True)
    output_dir.mkdir()
    execution_dir.mkdir(parents=True)

    raw = input_dir / "02-raw_dm.csv"
    raw.write_text("USUBJID\nSYN-001\n", encoding="utf-8")
    inventory = inventory_raw_dataset(raw, "raw_dm.csv")
    initialize_state(job_dir, metadata_files=["01-edc.json"], blank_crf="03-blank.pdf", raw_datasets=[inventory], validation_report=None)

    crf = input_dir / "03-blank.pdf"
    pdf = canvas.Canvas(str(crf))
    pdf.drawString(72, 720, "Subject")
    pdf.save()
    plan = _plan()
    render_sdtm(plan, crf, output_dir, ["r", "sas"])
    render_csdrg(job_dir, plan, output_dir)
    (output_dir / "edc-source-specification.json").write_text('{"study_name":"SYN-PACKAGE"}', encoding="utf-8")

    xpt_dir = execution_dir / "output"
    xpt_dir.mkdir()
    xpt = xpt_dir / "dm.xpt"
    pyreadstat.write_xport(pd.DataFrame({"USUBJID": ["SYN-001"]}), xpt, table_name="DM", file_format_version=5)
    attempt = ExecutionAttempt(
        attempt_id="attempt-0123456789ab",
        status="passed",
        created_at=datetime.now(timezone.utc),
        program_hash="a" * 64,
        program_artifact="sdtm/executions/attempt-0123456789ab/program.R",
        outputs=[ExecutionOutput(name="dm.xpt", sha256=sha256_file(xpt), size_bytes=xpt.stat().st_size)],
    )
    (execution_dir / "attempt.json").write_text(attempt.model_dump_json(indent=2), encoding="utf-8")
    state = read_state(job_dir)
    state.lifecycle.execution = "passed"
    write_state(job_dir, state)

    package = refresh_submission_package(job_dir, plan)
    first_bytes = package.read_bytes()
    assert refresh_submission_package(job_dir, plan).read_bytes() == first_bytes
    with zipfile.ZipFile(package) as archive:
        names = set(archive.namelist())
        assert {f"{folder}/" for folder in PACKAGE_FOLDERS} <= names
        assert {
            "data/dm.xpt",
            "define/define.xml",
            "define/define.xsl",
            "define/csdrg.pdf",
            "define/acrf.pdf",
            "raw/raw_dm.csv",
            "spec/sdtm-mapping.xlsx",
            "spec/sdtm-mapping.json",
            "spec/edc-source-specification.json",
            "program/build-dm.R",
            "program/build-dm.sas",
            "package-manifest.json",
        } <= names
        packaged_define = etree.fromstring(archive.read("define/define.xml"))
        hrefs = packaged_define.xpath("//*[local-name()='leaf']/@*[local-name()='href']")
        assert "../data/dm.xpt" in hrefs
        assert "acrf.pdf" in hrefs
        manifest = json.loads(archive.read("package-manifest.json"))
        assert manifest["claims"]["generation_implies_conformance"] is False
        assert not any(item["folder"] in {"data", "raw"} for item in manifest["omissions"])


def test_submission_package_keeps_empty_optional_folders_and_documents_omissions(tmp_path) -> None:
    job_dir = tmp_path / "job"
    output_dir = job_dir / "output"
    output_dir.mkdir(parents=True)
    initialize_state(job_dir, metadata_files=["edc.json"], blank_crf=None, raw_datasets=[], validation_report=None)
    plan = _plan()
    render_sdtm(plan, None, output_dir, ["r"])
    render_csdrg(job_dir, plan, output_dir)

    package = refresh_submission_package(job_dir, plan)
    with zipfile.ZipFile(package) as archive:
        names = set(archive.namelist())
        assert {f"{folder}/" for folder in PACKAGE_FOLDERS} <= names
        assert not any(name.startswith("data/") and name != "data/" for name in names)
        assert not any(name.startswith("raw/") and name != "raw/" for name in names)
        manifest = json.loads(archive.read("package-manifest.json"))
    omitted = {item["folder"] for item in manifest["omissions"]}
    assert {"data", "raw", "program", "define"} <= omitted
