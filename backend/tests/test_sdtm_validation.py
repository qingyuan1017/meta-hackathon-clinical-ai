from __future__ import annotations

import json
import zipfile

from openpyxl import Workbook

from app.csdrg import build_csdrg, render_csdrg
from app.schemas import SDTMDataset, SDTMDomainMapping, SDTMPlan, SDTMRuleAugmentation, SDTMVariable
from tests.sdtm_helpers import read_plan, source
from app.sdtm_validation import Pinnacle21CLIProvider, import_pinnacle21_report, save_validation
from app.sdtm_workbench import initialize_state
from app.sdtm_audit import refresh_evidence_bundle, refresh_evidence_manifest


def _plan() -> SDTMPlan:
    return SDTMPlan(
        study_name="SYN-VAL",
        domain_mappings=[SDTMDomainMapping(source_dataset="RAW_DM", target_domain="DM", rationale="Synthetic")],
        datasets=[SDTMDataset(domain="DM", description="Demographics", record_plan=read_plan("DM", "RAW_DM"), variables=[SDTMVariable(name="USUBJID", label="Subject", sources=[source("RAW_DM", "USUBJID")])])],
        rule_augmentations=[SDTMRuleAugmentation(rule_id="DM-USUBJID", target_domain="DM", target_variable="USUBJID", description="Direct", logic="Direct", r_expression='.data[["USUBJID"]]', sas_expression="USUBJID")],
    )


def _job_dir(tmp_path):
    job_dir = tmp_path / "job"
    initialize_state(job_dir, metadata_files=["edc.json"], blank_crf=None, raw_datasets=[], validation_report=None)
    return job_dir


def test_pinnacle21_csv_and_xlsx_import_preserve_provenance(tmp_path) -> None:
    job_dir = _job_dir(tmp_path)
    csv_path = tmp_path / "p21.csv"
    csv_path.write_text("Rule ID,Severity,Dataset,Variable,Message,P21 Version,Extra Column\nSD0001,Warning,DM,USUBJID,Example finding,3.1.2,ignored\n", encoding="utf-8")
    csv_record = import_pinnacle21_report(job_dir, csv_path)
    assert csv_record.provider == "Pinnacle 21 report import"
    assert csv_record.provider_version == "3.1.2"
    assert csv_record.findings[0].rule_id == "SD0001"
    assert csv_record.diagnostics and csv_record.diagnostics.unknown_columns == ["Extra Column"]
    assert (job_dir / csv_record.source_artifact).read_bytes() == csv_path.read_bytes()

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Rule", "Level", "Domain", "Column", "Description", "Provider Version"])
    sheet.append(["SD0002", "Error", "AE", "AETERM", "Second finding", "3.1.2"])
    xlsx_path = tmp_path / "p21.xlsx"
    workbook.save(xlsx_path)
    xlsx_record = import_pinnacle21_report(job_dir, xlsx_path)
    assert xlsx_record.findings[0].dataset == "AE"
    assert xlsx_record.findings[0].variable == "AETERM"


def test_unknown_report_shape_is_review_required_not_passed(tmp_path) -> None:
    job_dir = _job_dir(tmp_path)
    report = tmp_path / "unknown.csv"
    report.write_text("Something,Else\n1,2\n", encoding="utf-8")
    record = import_pinnacle21_report(job_dir, report)
    assert record.status == "review_required"
    assert record.findings == []
    assert record.diagnostics and "Required columns not recognized" in record.diagnostics.warnings[0]


def test_missing_cli_and_java_are_unavailable_not_passed(tmp_path) -> None:
    record = Pinnacle21CLIProvider(tmp_path / "missing.jar", tmp_path / "missing-java").run(_job_dir(tmp_path))
    assert record.status == "unavailable"
    assert "No validation was run" in record.message


def test_csdrg_includes_only_approved_explanations_and_truthful_metadata_only_todos(tmp_path) -> None:
    job_dir = _job_dir(tmp_path)
    report = tmp_path / "p21.csv"
    report.write_text("Rule ID,Severity,Dataset,Message\nSD0001,Warning,DM,Explain me\nSD0002,Warning,DM,Keep open\n", encoding="utf-8")
    record = import_pinnacle21_report(job_dir, report)
    record.findings[0].finding_status = "explained"
    record.findings[0].explanation = "Synthetic source does not collect this optional value."
    record.findings[0].reviewer = "Jane Reviewer"
    from datetime import datetime, timezone
    record.findings[0].approved_at = datetime.now(timezone.utc)
    record.findings[1].finding_status = "explained"
    record.findings[1].explanation = "Unapproved explanation must stay out."
    save_validation(job_dir, record)
    document = build_csdrg(job_dir, _plan())
    approved_section = next(section for section in document.sections if "Reviewer-approved" in section.heading)
    assert "Synthetic source" in approved_section.body
    assert "Unapproved explanation" not in approved_section.body
    assert approved_section.evidence_controlled is True
    assert approved_section.tables[0].columns == ["Dataset", "Rule", "Severity", "Diagnostic message", "Explanation", "Reviewer", "Approved"]
    assert approved_section.tables[0].rows[0][1] == "SD0001"
    dataset_section = next(section for section in document.sections if "Dataset descriptions" in section.heading)
    assert dataset_section.tables[0].rows[0][0] == "DM"
    execution_section = next(section for section in document.sections if "execution" in section.heading.lower())
    assert "were not executed" in execution_section.body
    assert execution_section.todos
    paths = render_csdrg(job_dir, _plan())
    assert {path.name for path in paths} == {"csdrg.json", "csdrg.md", "csdrg.pdf"}
    assert "were not executed" in (job_dir / "output" / "csdrg.md").read_text(encoding="utf-8")
    assert "| Dataset | Rule | Severity |" in (job_dir / "output" / "csdrg.md").read_text(encoding="utf-8")


def test_evidence_manifest_and_bundle_include_audit_records_without_raw_rows(tmp_path) -> None:
    job_dir = _job_dir(tmp_path)
    output = job_dir / "output"
    output.mkdir()
    (output / "build-dm.R").write_text("# generated; not run\n", encoding="utf-8")
    report = tmp_path / "p21.csv"
    report.write_text("Rule ID,Severity,Message\nSD0001,Warning,Example\n", encoding="utf-8")
    import_pinnacle21_report(job_dir, report)
    manifest_path = refresh_evidence_manifest(job_dir)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["claims"]["generation_implies_conformance"] is False
    assert manifest["validation_records"][0]["provider"] == "Pinnacle 21 report import"
    assert "Example" in json.dumps(manifest["validation_records"])
    assert any(item["relative_path"].endswith("original-p21.csv") and len(item["sha256"]) == 64 for item in manifest["artifacts"])
    bundle = refresh_evidence_bundle(job_dir)
    with zipfile.ZipFile(bundle) as archive:
        names = set(archive.namelist())
    assert "sdtm/evidence-manifest.json" in names
    assert "output/build-dm.R" in names
    assert not any(name.startswith("input/") for name in names)

