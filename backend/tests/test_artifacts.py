import json
import zipfile

import pytest
import pymupdf as fitz
from docx import Document
from lxml import etree
from openpyxl import load_workbook
from reportlab.pdfgen import canvas

from app.artifacts import add_manifest_and_bundle, diagnose_define, render_clinical_document, render_edc, render_protocol, render_sdtm, render_tlf
from app.core_conformance import CoreConformanceError, CoreConformanceResult
from app.schemas import ClinicalDocument, DocumentSection, EDCDesign, EDCField, EDCForm, EDCVisit, Objective, SDTMDataset, SDTMDomainMapping, SDTMPlan, SDTMRuleAugmentation, SDTMUnmappedDataset, SDTMValueLevelMetadata, SDTMVariable, StudySummary, TLFColumn, TLFFigureSpec, TLFPlan, TLFProgramSpec, TLFRow, TLFSourceVariable, TLFSpec
from tests.sdtm_helpers import read_plan, source
from app.usdm import USDM_VERSION, validate_usdm


def test_protocol_and_bundle(tmp_path) -> None:
    result = StudySummary(
        study_title="Synthetic study",
        protocol_number="SYN-101",
        sponsor="Synthetic Sponsor",
        objectives=[Objective(objective="Assess efficacy")],
        inclusion_criteria=["Adults aged 18 years or older"],
        exclusion_criteria=["Prior prohibited therapy"],
    )
    def conformant_core(usdm_path, output_dir):
        report = output_dir / "core-report.json"
        decision = output_dir / "core-conformance.json"
        report.write_text('{"Rules_Report": []}', encoding="utf-8")
        decision.write_text('{"conformant": true}', encoding="utf-8")
        return CoreConformanceResult(
            conformant=True,
            report_path=report,
            decision_path=decision,
            status_counts={"SUCCESS": 207},
            blocking_rules=(),
            allowed_skipped_rules=(),
            reported_rule_count=207,
        )

    paths = add_manifest_and_bundle(
        render_protocol(result, tmp_path, conformance_validator=conformant_core),
        tmp_path,
        "protocol-extraction",
    )
    usdm_payload = json.loads((tmp_path / "usdm.json").read_text(encoding="utf-8"))
    usdm = validate_usdm(usdm_payload)
    assert usdm.usdmVersion == USDM_VERSION
    assert usdm.study.versions[0].titles[0].text == "Synthetic study"
    assert len(usdm.study.versions[0].eligibilityCriterionItems) == 2
    assert usdm.study.versions[0].studyIdentifiers[0].text == "SYN-101"
    assert usdm.study.versions[0].roles[0].code.code == "C70793"
    assert usdm.study.versions[0].organizations[0].name == "Synthetic Sponsor"
    bundle = next(path for path in paths if path.suffix == ".zip")
    with zipfile.ZipFile(bundle) as archive:
        assert "protocol-extraction.json" in archive.namelist()
        assert "usdm.json" in archive.namelist()
        assert "core-report.json" in archive.namelist()
        assert "core-conformance.json" in archive.namelist()
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["workflow"] == "protocol-extraction"


def test_protocol_core_failure_exposes_diagnostics_without_claiming_conformance(tmp_path) -> None:
    def failing_core(usdm_path, output_dir):
        report = output_dir / "core-report.json"
        decision = output_dir / "core-conformance.json"
        report.write_text('{"Rules_Report": [{"status": "ISSUE REPORTED"}]}', encoding="utf-8")
        decision.write_text('{"conformant": false}', encoding="utf-8")
        return CoreConformanceResult(
            conformant=False,
            report_path=report,
            decision_path=decision,
            status_counts={"ISSUE REPORTED": 1, "SUCCESS": 206},
            blocking_rules=({"core_id": "CORE-000001", "status": "ISSUE REPORTED", "reason": "test"},),
            allowed_skipped_rules=(),
            reported_rule_count=207,
        )

    with pytest.raises(CoreConformanceError) as captured:
        render_protocol(
            StudySummary(study_title="Nonconformant synthetic study"),
            tmp_path,
            conformance_validator=failing_core,
        )

    assert {path.name for path in captured.value.artifact_paths} == {
        "protocol-extraction.json",
        "protocol-extraction.md",
        "usdm.json",
        "core-report.json",
        "core-conformance.json",
    }
    assert "did not pass" in (tmp_path / "protocol-extraction.md").read_text(encoding="utf-8")


def test_document_and_edc_files_are_readable(tmp_path) -> None:
    document = ClinicalDocument(document_type="SAP", title="Synthetic SAP", executive_summary="Summary", sections=[DocumentSection(heading="Methods", body="Draft methods")])
    document_paths = render_clinical_document(document, tmp_path)
    assert Document(next(path for path in document_paths if path.suffix == ".docx")).paragraphs[0].text == "Synthetic SAP"

    edc = EDCDesign(study_name="SYN-101", visits=[EDCVisit(name="Baseline")], forms=[EDCForm(form_id="DM", name="Demographics", fields=[EDCField(field_id="AGE", label="Age", data_type="integer")])])
    edc_paths = render_edc(edc, tmp_path)
    workbook = load_workbook(next(path for path in edc_paths if path.suffix == ".xlsx"))
    assert "Forms and Fields" in workbook.sheetnames


def test_sdtm_and_tlf_artifacts(tmp_path) -> None:
    crf = tmp_path / "blank.pdf"
    pdf = canvas.Canvas(str(crf))
    pdf.drawString(50, 750, "Age")
    pdf.save()
    sdtm = SDTMPlan(
        study_name="SYN-101",
        domain_mappings=[SDTMDomainMapping(source_dataset="RAW_DM", target_domain="DM", rationale="Demographics source")],
        unmapped_datasets=[SDTMUnmappedDataset(source_dataset="AUDIT_LOG", rationale="Operational metadata")],
        datasets=[SDTMDataset(domain="DM", description="Demographics", record_plan=read_plan("DM", "RAW_DM"), variables=[SDTMVariable(name="AGE", label="Age", data_type="Num", sources=[source("RAW_DM", "AGE")], crf_source_label="Age", value_level_metadata=[SDTMValueLevelMetadata(where_clause="AGEU = 'YEARS'", label="Age in years", data_type="Num", mapping_expression="Direct", sources=[source("RAW_DM", "AGE")])])])],
        rule_augmentations=[SDTMRuleAugmentation(rule_id="DM-AGE", target_domain="DM", target_variable="AGE", description="Copy collected age", logic="Direct assignment", r_expression='.data[["AGE"]]', sas_expression="AGE")],
    )
    sdtm.datasets[0].variables.append(
        SDTMVariable(
            name="STUDYID",
            label="Study Identifier",
            mapping_type="assigned",
            origin="Assigned",
            mapping_expression="Assign the approved study identifier SYN-101.",
        )
    )
    sdtm.rule_augmentations.append(
        SDTMRuleAugmentation(
            rule_id="DM-STUDYID",
            target_domain="DM",
            target_variable="STUDYID",
            description="Assign study identifier",
            logic="Assign the approved constant SYN-101",
            r_expression='"SYN-101"',
            sas_expression='"SYN-101"',
        )
    )
    sdtm_paths = render_sdtm(sdtm, crf, tmp_path, ["r", "sas"])
    define_path = next(path for path in sdtm_paths if path.name == "define.xml")
    tree = etree.parse(str(define_path))
    assert tree.getroot().tag.endswith("ODM")
    assert (tmp_path / "annotated-crf.pdf").stat().st_size > 0
    workbook = load_workbook(tmp_path / "sdtm-mapping.xlsx")
    assert {"Domain Mappings", "Unmapped Sources", "Variable Mappings", "Value Level Metadata", "Record Construction", "Variable Rule Augmentation"} <= set(workbook.sheetnames)
    assert workbook["Unmapped Sources"]["A2"].value == "AUDIT_LOG"
    assert "dm <- dm_source %>%" in (tmp_path / "build-dm.R").read_text(encoding="utf-8")
    assert '.data[["AGE"]]' in (tmp_path / "build-dm.R").read_text(encoding="utf-8")
    assert "AGE = AGE;" in (tmp_path / "build-dm.sas").read_text(encoding="utf-8")

    code_only_dir = tmp_path / "code-only"
    code_only_dir.mkdir()
    code_only_paths = render_sdtm(sdtm, None, code_only_dir, ["r", "sas"])
    assert "annotated-crf.pdf" not in {path.name for path in code_only_paths}
    assert {"define.xml", "build-dm.R", "build-dm.sas"} <= {path.name for path in code_only_paths}
    assert "build-sdtm.R" not in {path.name for path in code_only_paths}
    assert "build-sdtm.sas" not in {path.name for path in code_only_paths}

    tlf = TLFPlan(
        study_name="SYN-101",
        outputs=[
            TLFSpec(output_id="T-01", output_type="table", title="Disposition", analysis_datasets=["ADSL"], source_variables=[TLFSourceVariable(dataset="ADSL", variable="TRT01P")], columns=[TLFColumn(column_id="TRT", heading="Treatment")], rows=[TLFRow(row_id="R1", label="Randomized")]),
            TLFSpec(output_id="L-01", output_type="listing", title="Adverse events", basis="conventional_proposal", columns=[TLFColumn(column_id="TERM", heading="Preferred term", source="ADAE.AEDECOD")]),
            TLFSpec(output_id="TLF-SETUP", output_type="figure", title="Mean change", figure=TLFFigureSpec(geometry="line", x_axis="AVISIT", y_axis="CHG")),
        ],
        programs=[
            TLFProgramSpec(output_id="T-01", input_datasets=["ADSL"], adam_sources=[TLFSourceVariable(dataset="ADSL", variable="TRT01P")], r_code="table(adsl$TRT01P)", sas_code="proc freq data=adsl; run;"),
            TLFProgramSpec(output_id="L-01", input_datasets=["ADAE"]),
            TLFProgramSpec(output_id="TLF-SETUP", input_datasets=["ADEFF"]),
        ],
    )
    tlf_paths = render_tlf(tlf, tmp_path, ["r", "sas"])
    assert Document(next(path for path in tlf_paths if path.name == "tlf-shells.docx")).tables
    workbook = load_workbook(tmp_path / "tlf-specifications.xlsx")
    assert {"Output Inventory", "Populations", "Source Mapping", "Display Elements", "Programming", "Assumptions and Blockers"} <= set(workbook.sheetnames)
    assert workbook["Output Inventory"]["D1"].value == "Basis"
    assert workbook["Output Inventory"]["D3"].value == "conventional_proposal"
    assert (tmp_path / "tlf-setup.R").is_file()
    assert (tmp_path / "tlf-setup.sas").is_file()
    assert "table(adsl$TRT01P)" in (tmp_path / "t-01.R").read_text(encoding="utf-8")
    assert "ADaM schema: ADSL.TRT01P" in (tmp_path / "t-01.R").read_text(encoding="utf-8")
    assert workbook["Programming"]["C2"].value.startswith("ADSL.TRT01P")
    assert (tmp_path / "l-01.sas").is_file()
    assert (tmp_path / "tlf-setup-2.R").is_file()


def test_acrf_coverage_and_define_review_diagnostics(tmp_path) -> None:
    crf = tmp_path / "blank.pdf"
    pdf = canvas.Canvas(str(crf))
    pdf.drawString(50, 750, "Age")
    pdf.drawString(50, 700, "Age")
    pdf.drawString(50, 650, "RACE")
    pdf.save()
    plan = SDTMPlan(
        study_name="SYN-ACRF",
        domain_mappings=[SDTMDomainMapping(source_dataset="RAW_DM", target_domain="DM", rationale="Synthetic")],
        datasets=[SDTMDataset(domain="DM", description="Demographics", record_plan=read_plan("DM", "RAW_DM"), variables=[SDTMVariable(name="AGE", label="Age", data_type="Num", sources=[source("RAW_DM", "AGE")], crf_source_label="Age", value_level_metadata=[SDTMValueLevelMetadata(where_clause="AGEU = 'YEARS'", label="Age in years", data_type="Num", mapping_expression="Direct", sources=[source("RAW_DM", "AGE")])]), SDTMVariable(name="SEX", label="Sex", sources=[source("RAW_DM", "SEX")], crf_source_label="Sex"), SDTMVariable(name="RACE", label="Race", sources=[source("RAW_DM", "RACE")])])],
        rule_augmentations=[SDTMRuleAugmentation(rule_id="DM-AGE", target_domain="DM", target_variable="AGE", description="Direct", logic="Direct", r_expression='.data[["AGE"]]', sas_expression="AGE"), SDTMRuleAugmentation(rule_id="DM-SEX", target_domain="DM", target_variable="SEX", description="Direct", logic="Direct", r_expression='.data[["SEX"]]', sas_expression="SEX"), SDTMRuleAugmentation(rule_id="DM-RACE", target_domain="DM", target_variable="RACE", description="Direct", logic="Direct", r_expression='.data[["RACE"]]', sas_expression="RACE")],
    )
    paths = render_sdtm(plan, crf, tmp_path, ["r"])
    assert {"define.xml", "define.xsl", "define.html", "define-diagnostics.json", "annotated-crf.pdf", "acrf-annotations.json"} <= {path.name for path in paths}
    coverage = json.loads((tmp_path / "acrf-annotations.json").read_text(encoding="utf-8"))
    assert coverage["summary"] == {"matched": 0, "ambiguous": 1, "unmatched": 2}
    age_annotation = next(item for item in coverage["annotations"] if item["variable"] == "AGE")
    race_annotation = next(item for item in coverage["annotations"] if item["variable"] == "RACE")
    assert age_annotation["rendering"] == "textbox"
    assert len(age_annotation["textbox"]) == 4
    assert race_annotation["label"] == ""
    assert race_annotation["rendering"] is None
    with fitz.open(tmp_path / "annotated-crf.pdf") as annotated_crf:
        first_page = annotated_crf[0]
        assert first_page.search_for("DM.AGE")
        assert not first_page.search_for("DM.RACE")
        assert list(first_page.annots() or []) == []
        assert first_page.get_drawings()
        appendix_text = annotated_crf[-1].get_text("text")
        assert "DRAFT - HACKATHON DEMONSTRATION ONLY" in appendix_text
        assert "AMBIGUOUS: DM.AGE <- Age" in appendix_text
    diagnostics = json.loads((tmp_path / "define-diagnostics.json").read_text(encoding="utf-8"))
    assert diagnostics["well_formed"] is True
    assert diagnostics["internal_references_valid"] is True
    assert diagnostics["xsd_validation"] == "not_run"
    tree = etree.parse(str(tmp_path / "define.xml"))
    assert tree.xpath("//*[local-name()='ValueListDef'][@OID='VL.DM.AGE']")
    assert tree.xpath("//*[local-name()='WhereClauseDef'][@OID='WC.DM.AGE.1']")
    assert tree.xpath("//*[local-name()='leaf'][@ID='LF.ACRF'][@*[local-name()='href']='annotated-crf.pdf']")
    assert tree.xpath("//*[local-name()='DocumentRef'][@leafID='LF.ACRF']/*[local-name()='PDFPageRef'][@PageRefs='1']")
    item_ref = tree.xpath("//*[local-name()='ItemRef']")[0]
    item_ref.set("ItemOID", "IT.MISSING")
    broken = tmp_path / "define-broken.xml"
    tree.write(str(broken), encoding="UTF-8", xml_declaration=True)
    assert diagnose_define(broken)["missing_references"] == ["IT.MISSING"]


def test_sdtm_program_artifacts_are_isolated_by_domain(tmp_path) -> None:
    plan = SDTMPlan(
        study_name="SYN-DOMAIN-FILES",
        domain_mappings=[
            SDTMDomainMapping(source_dataset="RAW_DM", target_domain="DM", rationale="Synthetic"),
            SDTMDomainMapping(source_dataset="RAW_AE", target_domain="AE", rationale="Synthetic"),
        ],
        datasets=[
            SDTMDataset(
                domain="DM",
                description="Demographics",
                record_plan=read_plan("DM", "RAW_DM"),
                variables=[SDTMVariable(name="USUBJID", label="Unique subject", sources=[source("RAW_DM", "USUBJID")])],
            ),
            SDTMDataset(
                domain="AE",
                description="Adverse events",
                record_plan=read_plan("AE", "RAW_AE"),
                variables=[SDTMVariable(name="AETERM", label="Reported term", sources=[source("RAW_AE", "AETERM")])],
            ),
        ],
        rule_augmentations=[
            SDTMRuleAugmentation(rule_id="DM-USUBJID", target_domain="DM", target_variable="USUBJID", description="Direct", logic="Direct", r_expression='.data[["USUBJID"]]', sas_expression="USUBJID"),
            SDTMRuleAugmentation(rule_id="AE-AETERM", target_domain="AE", target_variable="AETERM", description="Direct", logic="Direct", r_expression='.data[["AETERM"]]', sas_expression="AETERM"),
        ],
    )

    paths = render_sdtm(plan, None, tmp_path, ["r", "sas"])
    names = {path.name for path in paths}
    assert {"build-dm.R", "build-dm.sas", "build-ae.R", "build-ae.sas"} <= names
    assert {"build-sdtm.R", "build-sdtm.sas"}.isdisjoint(names)
    dm_r = (tmp_path / "build-dm.R").read_text(encoding="utf-8")
    ae_r = (tmp_path / "build-ae.R").read_text(encoding="utf-8")
    dm_sas = (tmp_path / "build-dm.sas").read_text(encoding="utf-8")
    ae_sas = (tmp_path / "build-ae.sas").read_text(encoding="utf-8")
    assert "# DM: Demographics" in dm_r and "# AE:" not in dm_r
    assert "# AE: Adverse events" in ae_r and "# DM:" not in ae_r
    assert "data sdtm.dm;" in dm_sas and "data sdtm.ae;" not in dm_sas
    assert "data sdtm.ae;" in ae_sas and "data sdtm.dm;" not in ae_sas


def test_sdtm_record_plan_compiles_stack_join_and_transpose_for_r_and_sas(tmp_path) -> None:
    dataset = SDTMDataset.model_validate(
        {
            "domain": "AE",
            "description": "Adverse events from two collection streams with subject lookup data",
            "record_plan": {
                "steps": [
                    {"step_id": "read_ae", "operation": "read", "description": "Read AE", "output": "ae_raw", "source_dataset": "RAW_AE"},
                    {"step_id": "read_sae", "operation": "read", "description": "Read SAE", "output": "sae_raw", "source_dataset": "RAW_SAE"},
                    {"step_id": "read_dm", "operation": "read", "description": "Read subject lookup", "output": "dm_raw", "source_dataset": "RAW_DM"},
                    {
                        "step_id": "stack_events",
                        "operation": "stack",
                        "description": "Align and stack event streams",
                        "output": "events_stacked",
                        "inputs": ["read_ae", "read_sae"],
                        "column_alignment": [
                            {"target": "SUBJID", "sources": [{"input": "read_ae", "variable": "SUBJID"}, {"input": "read_sae", "variable": "SUBJECT"}]},
                            {"target": "AETERM", "sources": [{"input": "read_ae", "variable": "AETERM"}, {"input": "read_sae", "variable": "TERM"}]},
                            {"target": "AEDECOD", "sources": [{"input": "read_ae", "variable": "AEDECOD"}, {"input": "read_sae", "variable": "PT"}]},
                        ],
                    },
                    {
                        "step_id": "join_subject",
                        "operation": "join",
                        "description": "Join unique subject identifier",
                        "output": "events_with_subject",
                        "left": "stack_events",
                        "right": "read_dm",
                        "join_type": "left",
                        "join_keys": [{"left": "SUBJID", "right": "SUBJID"}],
                        "cardinality": "many_to_one",
                    },
                    {
                        "step_id": "transpose_terms",
                        "operation": "transpose",
                        "description": "Create reviewed value-level term rows",
                        "output": "event_terms",
                        "inputs": ["join_subject"],
                        "id_variables": ["USUBJID"],
                        "value_variables": ["AETERM", "AEDECOD"],
                        "name_variable": "TERM_ROLE",
                        "value_variable": "TERM_VALUE",
                        "transpose_values": [
                            {"source_variable": "AETERM", "name_value": "REPORTED"},
                            {"source_variable": "AEDECOD", "name_value": "CODED"},
                        ],
                    },
                ],
                "output_step": "transpose_terms",
            },
            "variables": [
                {
                    "name": "USUBJID",
                    "label": "Unique Subject Identifier",
                    "mapping_type": "lookup",
                    "sources": [
                        {"dataset": "RAW_AE", "variable": "SUBJID", "role": "join_key"},
                        {"dataset": "RAW_SAE", "variable": "SUBJECT", "role": "join_key"},
                        {"dataset": "RAW_DM", "variable": "USUBJID", "role": "lookup"},
                    ],
                    "mapping_expression": "Look up USUBJID after stacking AE and SAE.",
                },
                {
                    "name": "AETERM",
                    "label": "Reported Term",
                    "mapping_type": "transpose",
                    "sources": [
                        {"dataset": "RAW_AE", "variable": "AETERM"},
                        {"dataset": "RAW_SAE", "variable": "TERM"},
                    ],
                    "mapping_expression": "Stack reported terms and transpose reviewed term roles.",
                },
            ],
        }
    )
    plan = SDTMPlan(
        study_name="SYN-LINEAGE",
        domain_mappings=[
            SDTMDomainMapping(source_dataset="RAW_AE", target_domain="AE", rationale="Collected AE"),
            SDTMDomainMapping(source_dataset="RAW_SAE", target_domain="AE", rationale="Collected SAE"),
            SDTMDomainMapping(source_dataset="RAW_DM", target_domain="AE", rationale="Subject lookup"),
        ],
        datasets=[dataset],
        rule_augmentations=[
            SDTMRuleAugmentation(rule_id="AE-USUBJID", target_domain="AE", target_variable="USUBJID", description="Use subject lookup", logic="Lookup after stack", r_expression='.data[["USUBJID"]]', sas_expression="USUBJID"),
            SDTMRuleAugmentation(rule_id="AE-AETERM", target_domain="AE", target_variable="AETERM", description="Use transposed value", logic="Reviewed value-level transpose", r_expression='.data[["TERM_VALUE"]]', sas_expression="TERM_VALUE"),
        ],
    )

    render_sdtm(plan, None, tmp_path, ["r", "sas"])
    r_program = (tmp_path / "build-ae.R").read_text(encoding="utf-8")
    sas_program = (tmp_path / "build-ae.sas").read_text(encoding="utf-8")
    assert "dplyr::bind_rows(" in r_program
    assert "dplyr::left_join(" in r_program
    assert "tidyr::pivot_longer(" in r_program
    assert '"AETERM" = "REPORTED"' in r_program
    assert "events_stacked_aligned_1" in sas_program
    assert "left join work.dm_raw" in sas_program
    assert "proc transpose" in sas_program
    assert 'when ("AETERM") TERM_ROLE = "REPORTED";' in sas_program


def test_non_searchable_crf_reports_ocr_limitation(tmp_path) -> None:
    crf = tmp_path / "scan.pdf"
    pdf = canvas.Canvas(str(crf))
    pdf.showPage()
    pdf.save()
    plan = SDTMPlan(
        study_name="SYN-SCAN",
        domain_mappings=[SDTMDomainMapping(source_dataset="RAW_DM", target_domain="DM", rationale="Synthetic")],
        datasets=[SDTMDataset(domain="DM", description="Demographics", record_plan=read_plan("DM", "RAW_DM"), variables=[SDTMVariable(name="AGE", label="Age", sources=[source("RAW_DM", "AGE")])])],
        rule_augmentations=[SDTMRuleAugmentation(rule_id="DM-AGE", target_domain="DM", target_variable="AGE", description="Direct", logic="Direct", r_expression='.data[["AGE"]]', sas_expression="AGE")],
    )
    paths = render_sdtm(plan, crf, tmp_path, ["r"])
    assert "annotated-crf.pdf" not in {path.name for path in paths}
    coverage = json.loads((tmp_path / "acrf-annotations.json").read_text(encoding="utf-8"))
    assert coverage["status"] == "ocr_required"
    assert "not supported" in coverage["message"]
