from __future__ import annotations

from copy import copy
from datetime import datetime, timezone
import hashlib
import json
import re
import shutil
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import pymupdf as fitz
from docx import Document
from docx.shared import Inches, Pt
from lxml import etree
from openpyxl import Workbook
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

from .schemas import (
    ClinicalDocument,
    DISCLAIMER,
    EDCDesign,
    SDTMDataset,
    SDTMPlan,
    StudySummary,
    TLFPlan,
)
from .core_conformance import (
    CORE_ENGINE_VERSION,
    CORE_USDM4_RULE_COUNT,
    CoreConformanceError,
    CoreConformanceResult,
    run_core_conformance,
)
from .usdm import USDM_VERSION, build_usdm
from .sdtm_r import normalize_r_mapping_expression


MEDIA_TYPES = {
    ".json": "application/json",
    ".md": "text/markdown",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pdf": "application/pdf",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xml": "application/xml",
    ".xsl": "application/xml",
    ".html": "text/html",
    ".r": "text/x-r-source",
    ".sas": "text/x-sas",
    ".xpt": "application/x-sas-transport",
    ".zip": "application/zip",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_record(path: Path, job_dir: Path) -> dict:
    return {
        "name": path.name,
        "media_type": MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream"),
        "relative_path": path.relative_to(job_dir).as_posix(),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def render_protocol(
    result: StudySummary,
    output_dir: Path,
    *,
    conformance_validator=None,
) -> list[Path]:
    json_path = output_dir / "protocol-extraction.json"
    json_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    usdm = build_usdm(result)
    usdm_path = output_dir / "usdm.json"
    usdm_path.write_text(usdm.model_dump_json(indent=2), encoding="utf-8")
    validator = conformance_validator or run_core_conformance
    conformance: CoreConformanceResult = validator(usdm_path, output_dir)
    status = (
        f"passed all applicable rules in the complete {CORE_USDM4_RULE_COUNT}-rule USDM 4.0 "
        f"ruleset bundled with CDISC CORE {CORE_ENGINE_VERSION}"
        if conformance.conformant
        else "did not pass the strict CDISC CORE conformance gate"
    )
    markdown = [
        f"# {result.study_title}",
        "",
        f"> {DISCLAIMER}",
        "",
        f"> `usdm.json` passed structural validation against CDISC USDM {USDM_VERSION} and {status}. See `core-report.json` and `core-conformance.json`.",
        "",
    ]
    for label, value in [
        ("Protocol", result.protocol_number),
        ("Phase", result.phase),
        ("Indication", result.indication),
        ("Design", result.study_design),
        ("Population", result.population),
        ("Sample size", result.sample_size),
        ("Duration", result.duration),
    ]:
        markdown.append(f"- **{label}:** {value}")
    markdown.extend(["", "## Objectives"])
    markdown.extend(f"- **{item.category}:** {item.objective} — {item.endpoint}" for item in result.objectives)
    sections = {
        "Arms": result.arms,
        "Visits": result.visits,
        "Inclusion criteria": result.inclusion_criteria,
        "Exclusion criteria": result.exclusion_criteria,
        "Assessments": result.assessments,
        "Safety monitoring": result.safety_monitoring,
        "Unresolved ambiguities": result.ambiguities,
    }
    for heading, values in sections.items():
        markdown.extend(["", f"## {heading}"])
        markdown.extend(f"- {value}" for value in values)
    md_path = output_dir / "protocol-extraction.md"
    md_path.write_text("\n".join(markdown), encoding="utf-8")
    paths = [json_path, usdm_path, md_path, conformance.decision_path]
    if conformance.report_path is not None:
        paths.append(conformance.report_path)
    if not conformance.conformant:
        counts = ", ".join(
            f"{name.lower()}={count}" for name, count in conformance.status_counts.items()
        ) or "CORE did not produce rule counts"
        raise CoreConformanceError(
            f"USDM 4.0 CORE conformance failed ({counts}). Review core-conformance.json and core-report.json.",
            artifact_paths=paths,
            result_data=result.model_dump(mode="json"),
        )
    return paths


def _document_header(document: Document, title: str) -> None:
    document.add_heading(title, 0)
    notice = document.add_paragraph(DISCLAIMER)
    notice.style = document.styles["Intense Quote"]
    section = document.sections[0]
    section.top_margin = Inches(0.7)
    section.bottom_margin = Inches(0.7)
    styles = document.styles
    styles["Normal"].font.name = "Aptos"
    styles["Normal"].font.size = Pt(10)


def _pdf_story(title: str, sections: list[tuple[str, str]], path: Path) -> None:
    styles = getSampleStyleSheet()
    notice_style = ParagraphStyle(
        "Notice",
        parent=styles["BodyText"],
        textColor="#9f1239",
        borderColor="#fda4af",
        borderWidth=1,
        borderPadding=8,
        leading=14,
        alignment=TA_LEFT,
    )
    story = [Paragraph(escape(title), styles["Title"]), Spacer(1, 0.15 * inch), Paragraph(escape(DISCLAIMER), notice_style)]
    for heading, body in sections:
        story.extend([Spacer(1, 0.16 * inch), Paragraph(escape(heading), styles["Heading2"]), Paragraph(escape(body).replace("\n", "<br/>"), styles["BodyText"])])
    SimpleDocTemplate(str(path), pagesize=letter, rightMargin=54, leftMargin=54, topMargin=54, bottomMargin=54).build(story)


def render_clinical_document(result: ClinicalDocument, output_dir: Path) -> list[Path]:
    slug = _slug(result.document_type)
    document = Document()
    _document_header(document, result.title)
    document.add_paragraph(f"Document type: {result.document_type}\nVersion: {result.version}")
    document.add_heading("Executive summary", level=1)
    document.add_paragraph(result.executive_summary)
    for section in result.sections:
        document.add_heading(section.heading, level=1)
        document.add_paragraph(section.body)
        if section.review_notes:
            document.add_paragraph("Review notes: " + "; ".join(section.review_notes), style="Intense Quote")
    document.add_heading("Assumptions and unresolved items", level=1)
    for item in [*result.assumptions, *result.unresolved_items]:
        document.add_paragraph(item, style="List Bullet")
    docx_path = output_dir / f"{slug}.docx"
    document.save(docx_path)
    pdf_path = output_dir / f"{slug}.pdf"
    pdf_sections = [("Executive summary", result.executive_summary)] + [
        (section.heading, section.body) for section in result.sections
    ] + [("Assumptions and unresolved items", "\n".join([*result.assumptions, *result.unresolved_items]))]
    _pdf_story(result.title, pdf_sections, pdf_path)
    json_path = output_dir / f"{slug}.json"
    json_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return [docx_path, pdf_path, json_path]


def render_edc(result: EDCDesign, output_dir: Path) -> list[Path]:
    json_path = output_dir / "edc-build-specification.json"
    json_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    workbook = Workbook()
    visits_sheet = workbook.active
    visits_sheet.title = "Visits"
    visits_sheet.append(["Visit", "Timing", "Forms"])
    for visit in result.visits:
        visits_sheet.append([visit.name, visit.timing, ", ".join(visit.forms)])
    fields_sheet = workbook.create_sheet("Forms and Fields")
    fields_sheet.append(["Form ID", "Form", "Purpose", "Field ID", "Label", "Type", "Required", "Codelist", "Derivation", "Instructions"])
    for form in result.forms:
        for field in form.fields:
            fields_sheet.append([form.form_id, form.name, form.purpose, field.field_id, field.label, field.data_type, field.required, field.codelist, field.derivation, field.instructions])
    code_sheet = workbook.create_sheet("Codelists")
    code_sheet.append(["Codelist", "Value"])
    for codelist in result.codelists:
        for value in codelist.values:
            code_sheet.append([codelist.name, value])
    checks_sheet = workbook.create_sheet("Edit Checks")
    checks_sheet.append(["Check ID", "Form", "Field", "Condition", "Message", "Severity"])
    for check in result.edit_checks:
        checks_sheet.append([check.check_id, check.form, check.field, check.condition, check.message, check.severity])
    assumptions = workbook.create_sheet("Assumptions")
    assumptions.append([DISCLAIMER])
    for item in result.assumptions:
        assumptions.append([item])
    for sheet in workbook.worksheets:
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for cell in sheet[1]:
            bold_font = copy(cell.font)
            bold_font.bold = True
            cell.font = bold_font
    xlsx_path = output_dir / "edc-build-specification.xlsx"
    workbook.save(xlsx_path)
    return [json_path, xlsx_path]


def render_sdtm(result: SDTMPlan, crf_path: Path | None, output_dir: Path, languages: list[str]) -> list[Path]:
    paths: list[Path] = []
    acrf_annotations: list[dict] = []
    json_path = output_dir / "sdtm-mapping.json"
    json_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    paths.append(json_path)
    paths.append(_render_sdtm_xlsx(result, output_dir / "sdtm-mapping.xlsx"))
    if crf_path is not None:
        annotated, coverage = _annotate_crf(result, crf_path, output_dir / "annotated-crf.pdf", output_dir / "acrf-annotations.json")
        if annotated is not None:
            paths.append(annotated)
            acrf_annotations = json.loads(coverage.read_text(encoding="utf-8")).get("annotations", [])
        paths.append(coverage)
    define_path = _render_define_xml(result, output_dir / "define.xml", acrf_annotations)
    paths.append(define_path)
    stylesheet_path = _render_define_stylesheet(output_dir / "define.xsl")
    paths.append(stylesheet_path)
    paths.append(_render_define_html(define_path, stylesheet_path, output_dir / "define.html"))
    diagnostics_path = output_dir / "define-diagnostics.json"
    diagnostics_path.write_text(json.dumps(diagnose_define(define_path), indent=2), encoding="utf-8")
    paths.append(diagnostics_path)
    if "r" in languages:
        paths.extend(
            _render_r_sdtm(result, dataset, output_dir / sdtm_program_filename(dataset.domain, "r"))
            for dataset in result.datasets
        )
    if "sas" in languages:
        paths.extend(
            _render_sas_sdtm(result, dataset, output_dir / sdtm_program_filename(dataset.domain, "sas"))
            for dataset in result.datasets
        )
    return paths


def _render_sdtm_xlsx(result: SDTMPlan, path: Path) -> Path:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Domain Mappings"
    sheet.append(["Source Dataset", "Source Type", "Target Domain", "Relationship", "Rationale"])
    for mapping in result.domain_mappings:
        sheet.append(
            [
                mapping.source_dataset,
                mapping.source_type,
                mapping.target_domain,
                mapping.relationship,
                mapping.rationale,
            ]
        )

    unmapped = workbook.create_sheet("Unmapped Sources")
    unmapped.append(["Source Dataset", "Rationale"])
    for disposition in result.unmapped_datasets:
        unmapped.append([disposition.source_dataset, disposition.rationale])

    variables = workbook.create_sheet("Variable Mappings")
    variables.append(
        [
            "Domain",
            "Dataset",
            "Variable",
            "Label",
            "Type",
            "Mapping Type",
            "Sources",
            "Origin",
            "Mapping",
            "Controlled Terms",
            "aCRF Annotations",
        ]
    )
    for dataset in result.datasets:
        for variable in dataset.variables:
            variables.append(
                [
                    dataset.domain,
                    dataset.description,
                    variable.name,
                    variable.label,
                    variable.data_type,
                    variable.mapping_type,
                    _source_reference_text(variable.sources),
                    variable.origin,
                    variable.mapping_expression,
                    "; ".join(variable.controlled_terms),
                    "; ".join(f"{annotation.source_label} -> {annotation.mapping_text or f'{dataset.domain}.{variable.name}'}" for annotation in variable.acrf_annotations) or variable.crf_source_label or "",
                ]
            )

    value_level = workbook.create_sheet("Value Level Metadata")
    value_level.append(
        [
            "Domain",
            "Variable",
            "Where Clause",
            "Label",
            "Type",
            "Origin",
            "Mapping",
            "Sources",
            "Controlled Terms",
        ]
    )
    for dataset in result.datasets:
        for variable in dataset.variables:
            for metadata in variable.value_level_metadata:
                value_level.append(
                    [
                        dataset.domain,
                        variable.name,
                        metadata.where_clause,
                        metadata.label,
                        metadata.data_type,
                        metadata.origin,
                        metadata.mapping_expression,
                        _source_reference_text(metadata.sources),
                        "; ".join(metadata.controlled_terms),
                    ]
                )

    record_steps = workbook.create_sheet("Record Construction")
    record_steps.append(["Domain", "Step ID", "Operation", "Inputs", "Output", "Description", "Configuration", "Review Notes"])
    for dataset in result.datasets:
        for step in dataset.record_plan.steps:
            configuration = step.model_dump(
                mode="json",
                exclude={"step_id", "operation", "inputs", "output", "description", "review_notes"},
                exclude_none=True,
                exclude_defaults=True,
            )
            record_steps.append([
                dataset.domain,
                step.step_id,
                step.operation,
                "; ".join(step.inputs),
                step.output,
                step.description,
                json.dumps(configuration, ensure_ascii=False),
                "; ".join(step.review_notes),
            ])

    rules = workbook.create_sheet("Variable Rule Augmentation")
    rules.append(
        [
            "Rule ID",
            "Target Domain",
            "Target Variable",
            "Description",
            "Logic",
            "R Expression",
            "SAS Expression",
            "Review Notes",
        ]
    )
    for rule in result.rule_augmentations:
        rules.append(
            [
                rule.rule_id,
                rule.target_domain,
                rule.target_variable,
                rule.description,
                rule.logic,
                rule.r_expression,
                rule.sas_expression,
                "; ".join(rule.review_notes),
            ]
        )

    assumptions = workbook.create_sheet("Assumptions")
    assumptions.append([DISCLAIMER])
    for item in [*result.assumptions, *result.unresolved_mappings]:
        assumptions.append([item])
    for current in (sheet, variables, value_level, record_steps, rules):
        current.freeze_panes = "A2"
        current.auto_filter.ref = current.dimensions
    workbook.save(path)
    return path


def _render_define_xml(result: SDTMPlan, path: Path, acrf_annotations: list[dict] | None = None) -> Path:
    odm_ns = "http://www.cdisc.org/ns/odm/v1.3"
    def_ns = "http://www.cdisc.org/ns/def/v2.1"
    xlink_ns = "http://www.w3.org/1999/xlink"
    root = etree.Element(
        f"{{{odm_ns}}}ODM",
        nsmap={None: odm_ns, "def": def_ns, "xlink": xlink_ns},
        FileOID=f"WORKBENCH.DEFINE.{_define_oid_token(result.study_name)}",
        ODMVersion="1.3.2",
        FileType="Snapshot",
        CreationDateTime=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        Originator="Clinical AI Artifact Workbench",
        SourceSystem="Clinical AI Artifact Workbench",
        SourceSystemVersion="0.1.0",
    )
    root.set(f"{{{def_ns}}}Context", "Other")
    root.addprevious(etree.Comment(DISCLAIMER))
    root.addprevious(etree.ProcessingInstruction("xml-stylesheet", 'type="text/xsl" href="define.xsl"'))
    study = etree.SubElement(root, f"{{{odm_ns}}}Study", OID="STUDY.1")
    global_variables = etree.SubElement(study, f"{{{odm_ns}}}GlobalVariables")
    etree.SubElement(global_variables, f"{{{odm_ns}}}StudyName").text = result.study_name
    etree.SubElement(global_variables, f"{{{odm_ns}}}StudyDescription").text = f"Draft SDTM metadata for {result.study_name}"
    etree.SubElement(global_variables, f"{{{odm_ns}}}ProtocolName").text = result.study_name
    metadata = etree.SubElement(study, f"{{{odm_ns}}}MetaDataVersion", OID="MDV.1", Name=result.study_name, Description=DISCLAIMER)
    metadata.set(f"{{{def_ns}}}DefineVersion", result.define_standard.replace("Define-XML ", ""))
    metadata.set(f"{{{def_ns}}}StandardName", "SDTM-IG")
    metadata.set(f"{{{def_ns}}}StandardVersion", result.standard.replace("SDTMIG ", ""))
    standards = etree.SubElement(metadata, f"{{{def_ns}}}Standards")
    etree.SubElement(
        standards,
        f"{{{def_ns}}}Standard",
        OID="STD.SDTMIG",
        Name="SDTMIG",
        Type="IG",
        Version=result.standard.replace("SDTMIG ", ""),
        Status="Final",
    )
    annotations: dict[tuple[str, str], list[dict]] = {}
    for annotation in acrf_annotations or []:
        if annotation.get("annotation_type", "variable") != "variable":
            continue
        key = (str(annotation.get("domain", "")).upper(), str(annotation.get("variable", "")).upper())
        annotations.setdefault(key, []).append(annotation)
    if acrf_annotations:
        acrf_leaf = etree.SubElement(metadata, f"{{{def_ns}}}leaf", ID="LF.ACRF")
        acrf_leaf.set(f"{{{xlink_ns}}}href", "annotated-crf.pdf")
        etree.SubElement(acrf_leaf, f"{{{def_ns}}}title").text = "Annotated CRF"
    csdrg_leaf = etree.SubElement(metadata, f"{{{def_ns}}}leaf", ID="LF.CSDRG")
    csdrg_leaf.set(f"{{{xlink_ns}}}href", "csdrg.pdf")
    etree.SubElement(csdrg_leaf, f"{{{def_ns}}}title").text = "Clinical Study Data Reviewer's Guide"
    methods = {(rule.target_domain.upper(), rule.target_variable.upper()): rule for rule in result.rule_augmentations}
    comments: list[tuple[str, str]] = []
    for dataset in result.datasets:
        domain = dataset.domain.upper()
        is_reference = domain in {"TA", "TD", "TE", "TI", "TM", "TS", "TV"}
        group = etree.SubElement(
            metadata,
            f"{{{odm_ns}}}ItemGroupDef",
            OID=f"IG.{domain}",
            Name=domain,
            Domain=domain,
            Repeating="No" if is_reference else "Yes",
            IsReferenceData="Yes" if is_reference else "No",
            SASDatasetName=domain,
            Purpose=dataset.purpose,
        )
        group.set(f"{{{def_ns}}}Structure", dataset.structure)
        group.set(f"{{{def_ns}}}StandardOID", "STD.SDTMIG")
        group.set(f"{{{def_ns}}}ArchiveLocationID", f"LF.{domain}")
        etree.SubElement(group, f"{{{odm_ns}}}Description").append(_translated_text(odm_ns, dataset.description))
        key_variables = [item.upper() for item in dataset.key_variables]
        for order, variable in enumerate(dataset.variables, 1):
            variable_name = variable.name.upper()
            reference = etree.SubElement(group, f"{{{odm_ns}}}ItemRef", ItemOID=f"IT.{domain}.{variable_name}", OrderNumber=str(order), Mandatory="Yes" if variable.core == "Req" else "No")
            if variable_name in key_variables:
                reference.set("KeySequence", str(key_variables.index(variable_name) + 1))
            if variable.role:
                reference.set("Role", variable.role)
            rule = methods.get((domain, variable_name))
            if rule:
                reference.set("MethodOID", f"MT.{domain}.{variable_name}")
            item = etree.SubElement(
                metadata,
                f"{{{odm_ns}}}ItemDef",
                OID=f"IT.{domain}.{variable_name}",
                Name=variable_name,
                DataType="text" if variable.data_type == "Char" else "float",
                Length=str(variable.length or (200 if variable.data_type == "Char" else 8)),
                SASFieldName=variable_name[:8],
            )
            if variable.format:
                item.set("DisplayFormat", variable.format)
            if variable.value_level_metadata:
                item.set(f"{{{def_ns}}}ValueListOID", f"VL.{domain}.{variable_name}")
            description = etree.SubElement(item, f"{{{odm_ns}}}Description")
            description.append(_translated_text(odm_ns, variable.label))
            origin_type, origin_source = _define_origin(variable.origin)
            origin = etree.SubElement(item, f"{{{def_ns}}}Origin", Type=origin_type, Source=origin_source)
            origin_description = etree.SubElement(origin, f"{{{odm_ns}}}Description")
            origin_description.append(
                _translated_text(
                    odm_ns,
                    _source_reference_text(variable.sources) or variable.mapping_expression,
                )
            )
            variable_annotations = annotations.get((domain, variable_name), [])
            annotation_pages = sorted({int(annotation["page"]) for annotation in variable_annotations if annotation.get("page")})
            if annotation_pages:
                document_reference = etree.SubElement(origin, f"{{{def_ns}}}DocumentRef", leafID="LF.ACRF")
                etree.SubElement(
                    document_reference,
                    f"{{{def_ns}}}PDFPageRef",
                    PageRefs=" ".join(str(page) for page in annotation_pages),
                    Type="PhysicalRef",
                )
            if variable.controlled_terms:
                etree.SubElement(item, f"{{{odm_ns}}}CodeListRef", CodeListOID=f"CL.{domain}.{variable_name}")
            if variable.comment:
                comment_oid = f"COM.{domain}.{variable_name}"
                item.set(f"{{{def_ns}}}CommentOID", comment_oid)
                comments.append((comment_oid, variable.comment))
        etree.SubElement(group, f"{{{def_ns}}}Class", Name=dataset.dataset_class.upper())
        leaf = etree.SubElement(group, f"{{{def_ns}}}leaf", ID=f"LF.{domain}")
        leaf.set(f"{{{xlink_ns}}}href", f"{domain.lower()}.xpt")
        etree.SubElement(leaf, f"{{{def_ns}}}title").text = f"{domain.lower()}.xpt"
    for dataset in result.datasets:
        available_variable_names = {item.name.upper() for item in dataset.variables}
        for variable in dataset.variables:
            domain = dataset.domain.upper()
            variable_name = variable.name.upper()
            rule = methods.get((domain, variable_name))
            if rule:
                method = etree.SubElement(metadata, f"{{{odm_ns}}}MethodDef", OID=f"MT.{domain}.{variable_name}", Name=rule.description, Type="Computation")
                etree.SubElement(method, f"{{{odm_ns}}}Description").append(_translated_text(odm_ns, rule.logic))
            if variable.controlled_terms:
                codelist = etree.SubElement(metadata, f"{{{odm_ns}}}CodeList", OID=f"CL.{domain}.{variable_name}", Name=f"{domain}.{variable_name}", DataType="text")
                for order, term in enumerate(variable.controlled_terms, 1):
                    coded = etree.SubElement(codelist, f"{{{odm_ns}}}CodeListItem", CodedValue=term, OrderNumber=str(order))
                    etree.SubElement(coded, f"{{{odm_ns}}}Decode").append(_translated_text(odm_ns, term))
            if variable.value_level_metadata:
                value_list = etree.SubElement(metadata, f"{{{def_ns}}}ValueListDef", OID=f"VL.{domain}.{variable_name}")
                for index, value_metadata in enumerate(variable.value_level_metadata, 1):
                    item_oid = f"IT.{domain}.{variable_name}.VL{index}"
                    where_oid = f"WC.{domain}.{variable_name}.{index}"
                    etree.SubElement(
                        value_list, f"{{{odm_ns}}}ItemRef", ItemOID=item_oid, OrderNumber=str(index), Mandatory="No"
                    )
                    value_reference = value_list[-1]
                    etree.SubElement(value_reference, f"{{{def_ns}}}WhereClauseRef", WhereClauseOID=where_oid)
                    value_item = etree.SubElement(
                        metadata,
                        f"{{{odm_ns}}}ItemDef",
                        OID=item_oid,
                        Name=variable_name,
                        DataType="text" if value_metadata.data_type == "Char" else "float",
                        Length="200" if value_metadata.data_type == "Char" else "8",
                        SASFieldName=variable_name[:8],
                    )
                    etree.SubElement(value_item, f"{{{odm_ns}}}Description").append(_translated_text(odm_ns, value_metadata.label))
                    value_origin_type, value_origin_source = _define_origin(value_metadata.origin)
                    value_origin = etree.SubElement(value_item, f"{{{def_ns}}}Origin", Type=value_origin_type, Source=value_origin_source)
                    etree.SubElement(value_origin, f"{{{odm_ns}}}Description").append(_translated_text(odm_ns, value_metadata.mapping_expression))
                    if value_metadata.controlled_terms:
                        value_codelist_oid = f"CL.{domain}.{variable_name}.VL{index}"
                        etree.SubElement(value_item, f"{{{odm_ns}}}CodeListRef", CodeListOID=value_codelist_oid)
                        value_codelist = etree.SubElement(metadata, f"{{{odm_ns}}}CodeList", OID=value_codelist_oid, Name=f"{domain}.{variable_name} value-level {index}", DataType="text")
                        for order, term in enumerate(value_metadata.controlled_terms, 1):
                            coded = etree.SubElement(value_codelist, f"{{{odm_ns}}}CodeListItem", CodedValue=term, OrderNumber=str(order))
                            etree.SubElement(coded, f"{{{odm_ns}}}Decode").append(_translated_text(odm_ns, term))
                    where = etree.SubElement(metadata, f"{{{def_ns}}}WhereClauseDef", OID=where_oid)
                    etree.SubElement(where, f"{{{odm_ns}}}Description").append(_translated_text(odm_ns, value_metadata.where_clause))
                    for condition_variable, comparator, values in _parse_define_where_clause(value_metadata.where_clause):
                        if condition_variable not in available_variable_names:
                            continue
                        range_check = etree.SubElement(where, f"{{{odm_ns}}}RangeCheck", Comparator=comparator, SoftHard="Soft")
                        range_check.set(f"{{{def_ns}}}ItemOID", f"IT.{domain}.{condition_variable}")
                        for value in values:
                            etree.SubElement(range_check, f"{{{odm_ns}}}CheckValue").text = value
    for comment_oid, text in comments:
        comment = etree.SubElement(metadata, f"{{{def_ns}}}CommentDef", OID=comment_oid)
        etree.SubElement(comment, f"{{{odm_ns}}}Description").append(_translated_text(odm_ns, text))
    tree = etree.ElementTree(root)
    tree.write(str(path), encoding="UTF-8", xml_declaration=True, pretty_print=True)
    etree.parse(str(path))
    return path


def _define_oid_token(value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-.")
    return token or "STUDY"


def _define_origin(value: str) -> tuple[str, str]:
    normalized = value.strip().lower()
    if normalized in {"crf", "collected", "edc"}:
        return "Collected", "Investigator"
    if normalized == "protocol":
        return "Protocol", "Sponsor"
    if normalized in {"derived", "assigned"}:
        return normalized.title(), "Sponsor"
    return value.strip() or "Assigned", "Sponsor"


def _parse_define_where_clause(expression: str) -> list[tuple[str, str, list[str]]]:
    """Translate common reviewed VLM predicates into Define-XML RangeCheck nodes."""

    comparator_map = {"=": "EQ", "==": "EQ", "!=": "NE", "<>": "NE", "<": "LT", "<=": "LE", ">": "GT", ">=": "GE"}
    results: list[tuple[str, str, list[str]]] = []
    for clause in re.split(r"\s+AND\s+", expression.strip(), flags=re.IGNORECASE):
        in_match = re.fullmatch(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s+(NOT\s+IN|IN)\s*\((.*)\)\s*", clause, flags=re.IGNORECASE)
        if in_match:
            values = [item.strip().strip("'\"") for item in re.split(r"\s*,\s*", in_match.group(3)) if item.strip()]
            if values:
                results.append((in_match.group(1).upper(), "NOTIN" if in_match.group(2).upper().startswith("NOT") else "IN", values))
                continue
        comparison = re.fullmatch(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*(==|!=|<>|<=|>=|=|<|>)\s*(.*?)\s*", clause)
        if comparison and comparison.group(3):
            results.append(
                (
                    comparison.group(1).upper(),
                    comparator_map[comparison.group(2)],
                    [comparison.group(3).strip().strip("'\"")],
                )
            )
            continue
        return []
    return results


def _render_define_stylesheet(path: Path) -> Path:
    path.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet version="1.0"
  xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
  xmlns:odm="http://www.cdisc.org/ns/odm/v1.3"
  xmlns:def="http://www.cdisc.org/ns/def/v2.1"
  xmlns:xlink="http://www.w3.org/1999/xlink"
  exclude-result-prefixes="odm def xlink">
<xsl:output method="html" encoding="UTF-8"/>
<xsl:template match="/">
<html><head><meta charset="utf-8"/><title>Define-XML review</title>
<style>
:root{color-scheme:light}body{font-family:Inter,system-ui,sans-serif;margin:0;color:#172033;background:#f8fafc;line-height:1.45}.page{max-width:1500px;margin:auto;padding:2rem}.hero{background:#172554;color:white;padding:1.5rem 2rem;border-radius:14px}.hero h1{margin:0 0 .35rem}.hero p{margin:.2rem 0;color:#cbd5e1}.notice{padding:1rem;margin:1rem 0;background:#fff7ed;border:1px solid #fdba74;border-radius:10px;color:#9a3412}.card{background:white;border:1px solid #dbe3ee;border-radius:12px;padding:1.2rem;margin:1rem 0;box-shadow:0 2px 8px rgba(15,23,42,.05)}table{border-collapse:collapse;width:100%;margin:.75rem 0;font-size:.82rem}th,td{border:1px solid #cbd5e1;padding:.48rem;text-align:left;vertical-align:top}th{background:#e2e8f0;color:#0f172a;position:sticky;top:0}tr:nth-child(even) td{background:#f8fafc}.muted{color:#64748b}.pill{display:inline-block;padding:.15rem .45rem;border-radius:99px;background:#dbeafe;color:#1e40af;font-weight:700;font-size:.72rem}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:.75rem}.metric{padding:.75rem;background:#eff6ff;border-radius:8px}.metric strong{display:block;font-size:1.2rem;color:#1e3a8a}a{color:#1d4ed8}code{font-family:ui-monospace,monospace;font-size:.78rem}h2{color:#172554;margin-bottom:.25rem}h3{color:#1e3a8a}</style></head>
<body><div class="page">
<div class="hero"><h1>Define-XML 2.1 metadata review</h1><p><strong><xsl:value-of select="//odm:StudyName"/></strong></p><p><xsl:value-of select="//odm:MetaDataVersion/@Name"/></p></div>
<p class="notice"><strong>Draft review rendering.</strong> This human-readable view does not replace XSD validation, controlled terminology checks, or qualified standards review.</p>
<div class="card"><h2>Submission metadata</h2><div class="grid">
<div class="metric"><span class="muted">Define version</span><strong><xsl:value-of select="//odm:MetaDataVersion/@def:DefineVersion"/></strong></div>
<div class="metric"><span class="muted">Standard</span><strong><xsl:value-of select="//odm:MetaDataVersion/@def:StandardName"/> <xsl:value-of select="//odm:MetaDataVersion/@def:StandardVersion"/></strong></div>
<div class="metric"><span class="muted">Datasets</span><strong><xsl:value-of select="count(//odm:ItemGroupDef)"/></strong></div>
<div class="metric"><span class="muted">Variables</span><strong><xsl:value-of select="count(//odm:ItemDef[not(contains(@OID,'.VL'))])"/></strong></div>
<div class="metric"><span class="muted">Value lists</span><strong><xsl:value-of select="count(//def:ValueListDef)"/></strong></div>
<div class="metric"><span class="muted">Methods</span><strong><xsl:value-of select="count(//odm:MethodDef)"/></strong></div>
</div></div>
<div class="card"><h2>Dataset inventory</h2><table><thead><tr><th>Dataset</th><th>Label</th><th>Class</th><th>Structure</th><th>Purpose</th><th>Variables</th><th>Location</th></tr></thead><tbody>
<xsl:for-each select="//odm:ItemGroupDef"><tr><td><a href="#{@OID}"><strong><xsl:value-of select="@Name"/></strong></a></td><td><xsl:value-of select="odm:Description/odm:TranslatedText"/></td><td><xsl:value-of select="def:Class/@Name"/></td><td><xsl:value-of select="@def:Structure"/></td><td><xsl:value-of select="@Purpose"/></td><td><xsl:value-of select="count(odm:ItemRef)"/></td><td><a href="{def:leaf/@xlink:href}"><xsl:value-of select="def:leaf/def:title"/></a></td></tr></xsl:for-each>
</tbody></table></div>
<xsl:for-each select="//odm:ItemGroupDef"><div class="card" id="{@OID}"><h2><xsl:value-of select="@Name"/> - <xsl:value-of select="odm:Description/odm:TranslatedText"/></h2><p class="muted"><xsl:value-of select="@def:Structure"/> | Class: <xsl:value-of select="def:Class/@Name"/> | Purpose: <xsl:value-of select="@Purpose"/></p>
<table><thead><tr><th>Order</th><th>Variable</th><th>Label</th><th>Type</th><th>Mandatory</th><th>Key</th><th>Role</th><th>Origin</th><th>Codelist</th><th>Method/comment</th></tr></thead><tbody>
<xsl:for-each select="odm:ItemRef"><xsl:variable name="itemOID" select="@ItemOID"/><xsl:variable name="item" select="//odm:ItemDef[@OID=$itemOID]"/><tr>
<td><xsl:value-of select="@OrderNumber"/></td><td><code><xsl:value-of select="$item/@Name"/></code></td><td><xsl:value-of select="$item/odm:Description/odm:TranslatedText"/></td><td><xsl:value-of select="$item/@DataType"/><xsl:if test="$item/@Length"> (<xsl:value-of select="$item/@Length"/>)</xsl:if></td><td><xsl:value-of select="@Mandatory"/></td><td><xsl:value-of select="@KeySequence"/></td><td><xsl:value-of select="@Role"/></td><td><xsl:value-of select="$item/def:Origin/@Type"/><xsl:if test="$item/def:Origin/@Source"> / <xsl:value-of select="$item/def:Origin/@Source"/></xsl:if></td><td><code><xsl:value-of select="$item/odm:CodeListRef/@CodeListOID"/></code></td><td><xsl:if test="@MethodOID"><span class="pill"><xsl:value-of select="@MethodOID"/></span></xsl:if><xsl:if test="$item/@def:CommentOID"><br/><code><xsl:value-of select="$item/@def:CommentOID"/></code></xsl:if></td>
</tr></xsl:for-each></tbody></table></div></xsl:for-each>
<xsl:if test="//def:ValueListDef"><div class="card"><h2>Value-level metadata</h2><table><thead><tr><th>Value list</th><th>Item</th><th>Where clause</th><th>Label</th><th>Origin</th></tr></thead><tbody>
<xsl:for-each select="//def:ValueListDef/odm:ItemRef"><xsl:variable name="itemOID" select="@ItemOID"/><xsl:variable name="whereOID" select="def:WhereClauseRef/@WhereClauseOID"/><xsl:variable name="item" select="//odm:ItemDef[@OID=$itemOID]"/><tr><td><code><xsl:value-of select="../@OID"/></code></td><td><code><xsl:value-of select="$item/@OID"/></code></td><td><xsl:value-of select="//def:WhereClauseDef[@OID=$whereOID]/odm:Description/odm:TranslatedText"/></td><td><xsl:value-of select="$item/odm:Description/odm:TranslatedText"/></td><td><xsl:value-of select="$item/def:Origin/@Type"/></td></tr></xsl:for-each>
</tbody></table></div></xsl:if>
<xsl:if test="//odm:MethodDef"><div class="card"><h2>Computational methods</h2><table><thead><tr><th>Method</th><th>Name</th><th>Description</th></tr></thead><tbody><xsl:for-each select="//odm:MethodDef"><tr><td><code><xsl:value-of select="@OID"/></code></td><td><xsl:value-of select="@Name"/></td><td><xsl:value-of select="odm:Description/odm:TranslatedText"/></td></tr></xsl:for-each></tbody></table></div></xsl:if>
</div></body></html>
</xsl:template></xsl:stylesheet>""", encoding="utf-8")
    return path


def _render_define_html(xml_path: Path, stylesheet_path: Path, path: Path) -> Path:
    transform = etree.XSLT(etree.parse(str(stylesheet_path)))
    rendered = transform(etree.parse(str(xml_path)))
    path.write_bytes(etree.tostring(rendered, method="html", encoding="UTF-8", pretty_print=True))
    return path


def diagnose_define(path: Path) -> dict:
    diagnostics = {
        "well_formed": False,
        "internal_references_valid": False,
        "missing_references": [],
        "duplicate_identifiers": [],
        "element_counts": {},
        "semantic_warnings": [],
        "xsd_validation": "not_run",
        "standards_validation": "not_run",
        "limitations": ["No Define-XML 2.1 XSD package is bundled; full schema and standards validation were not run."],
    }
    try:
        tree = etree.parse(str(path))
    except etree.XMLSyntaxError as exc:
        diagnostics["parse_error"] = str(exc)
        return diagnostics
    diagnostics["well_formed"] = True
    identifier_values = [value for element in tree.iter() for key, value in element.attrib.items() if key.split("}")[-1] in {"OID", "ID"}]
    identifiers = set(identifier_values)
    duplicate_identifiers = sorted({value for value in identifier_values if identifier_values.count(value) > 1})
    reference_names = {
        "ArchiveLocationID",
        "CodeListOID",
        "CommentOID",
        "ItemGroupOID",
        "ItemOID",
        "MethodOID",
        "StandardOID",
        "ValueListOID",
        "WhereClauseOID",
        "leafID",
    }
    references = [value for element in tree.iter() for key, value in element.attrib.items() if key.split("}")[-1] in reference_names]
    missing = sorted(set(references) - identifiers)
    diagnostics["missing_references"] = missing
    diagnostics["duplicate_identifiers"] = duplicate_identifiers
    diagnostics["internal_references_valid"] = not missing and not duplicate_identifiers
    diagnostics["element_counts"] = {
        name: int(tree.xpath(f"count(//*[local-name()='{name}'])"))
        for name in ["ItemGroupDef", "ItemDef", "CodeList", "ValueListDef", "WhereClauseDef", "MethodDef", "CommentDef", "leaf"]
    }
    warnings = []
    if tree.xpath("//*[local-name()='WhereClauseDef'][not(*[local-name()='RangeCheck'])]"):
        warnings.append("One or more value-level where clauses could not be translated into Define-XML RangeCheck metadata.")
    if tree.xpath("//*[local-name()='ItemGroupDef'][not(*[local-name()='Class'])]"):
        warnings.append("One or more datasets do not have a Define-XML Class element.")
    if tree.xpath("//*[local-name()='ItemDef'][not(*[local-name()='Origin'])]"):
        warnings.append("One or more item definitions do not have origin metadata.")
    diagnostics["semantic_warnings"] = warnings
    return diagnostics


def _translated_text(namespace: str, text: str) -> etree._Element:
    node = etree.Element(f"{{{namespace}}}TranslatedText")
    node.set("{http://www.w3.org/XML/1998/namespace}lang", "en")
    node.text = text
    return node


def _insert_acrf_mapping_box(
    page: fitz.Page,
    question_rect: fitz.Rect | None,
    text: str,
    occupied_boxes: list[fitz.Rect],
    *,
    font_family: str,
    font_size: float,
    text_color: str,
    fill_color: str,
    position: tuple[float, float] | None = None,
    avoid_overlaps: bool = True,
) -> fitz.Rect:
    """Draw one visible aCRF label beside a question or at a persisted page position."""

    font_names = {
        "Helvetica": "helv",
        "Helvetica Bold": "hebo",
        "Times": "tiro",
        "Times Bold": "tibo",
        "Courier": "cour",
        "Courier Bold": "cobo",
    }
    font_name = font_names[font_family]
    text_rgb = tuple(int(text_color[index:index + 2], 16) / 255 for index in (1, 3, 5))
    fill_rgb = tuple(int(fill_color[index:index + 2], 16) / 255 for index in (1, 3, 5))
    margin = 8.0
    gap = 6.0
    box_height = max(24.0, font_size * 2.0 + 6.0)
    box_width = min(max(fitz.get_text_length(text, fontname=font_name, fontsize=font_size) + 16.0, 52.0), 180.0)
    page_rect = page.rect
    candidates: list[fitz.Rect] = []
    if position is not None:
        base_x = min(max(position[0], margin), page_rect.x1 - margin - box_width)
        base_y = min(max(position[1], margin), page_rect.y1 - margin - box_height)
        offsets = [0.0, box_height + 4.0, (box_height + 4.0) * 2] if avoid_overlaps else [0.0]
        candidates = [fitz.Rect(base_x, min(base_y + offset, page_rect.y1 - margin - box_height), base_x + box_width, min(base_y + offset, page_rect.y1 - margin - box_height) + box_height) for offset in offsets]
    elif question_rect is not None:
        centered_y = min(max(question_rect.y0 + (question_rect.height - box_height) / 2, margin), page_rect.y1 - margin - box_height)
        vertical_offsets = [0.0, 23.0, -23.0, 46.0, -46.0, 69.0, -69.0]
        horizontal_positions = [question_rect.x1 + gap, question_rect.x0 - gap - box_width]
        for x0 in horizontal_positions:
            if x0 < margin or x0 + box_width > page_rect.x1 - margin:
                continue
            for offset in vertical_offsets:
                y0 = min(max(centered_y + offset, margin), page_rect.y1 - margin - box_height)
                candidate = fitz.Rect(x0, y0, x0 + box_width, y0 + box_height)
                if candidate not in candidates:
                    candidates.append(candidate)
        if not candidates:
            x0 = min(max(question_rect.x1 + gap, margin), page_rect.x1 - margin - box_width)
            candidates.append(fitz.Rect(x0, centered_y, x0 + box_width, centered_y + box_height))
    else:
        candidates.append(fitz.Rect(margin, margin, margin + box_width, margin + box_height))
    box = next(
        (candidate for candidate in candidates if not avoid_overlaps or not any(candidate.intersects(existing) for existing in occupied_boxes)),
        candidates[0],
    )
    page.draw_rect(box, color=text_rgb, fill=fill_rgb, width=0.8, overlay=True)
    text_rect = fitz.Rect(box.x0 + 4, box.y0 + 3, box.x1 - 4, box.y1 - 2)
    page.insert_textbox(
        text_rect,
        text,
        fontname=font_name,
        fontsize=font_size,
        color=text_rgb,
        align=fitz.TEXT_ALIGN_CENTER,
        overlay=True,
    )
    occupied_boxes.append(box)
    return box


def _annotate_crf(result: SDTMPlan, crf_path: Path, path: Path, coverage_path: Path) -> tuple[Path | None, Path]:
    document = fitz.open(crf_path)
    source_page_count = document.page_count
    searchable = any(page.get_text("text").strip() for page in document)
    coverage: list[dict] = []
    occupied_boxes: dict[int, list[fitz.Rect]] = {}
    domain_pages: dict[str, set[int]] = {dataset.domain: set() for dataset in result.datasets}
    if not searchable:
        coverage_path.write_text(json.dumps({"status": "ocr_required", "searchable": False, "message": "The supplied CRF has no searchable text. OCR is not supported in this iteration; annotation was not performed.", "annotations": [], "pages": []}, indent=2), encoding="utf-8")
        document.close()
        return None, coverage_path
    for dataset in result.datasets:
        for variable in dataset.variables:
            annotations = list(variable.acrf_annotations)
            if not annotations and variable.crf_source_label:
                annotations = [{"source_label": variable.crf_source_label, "mapping_text": ""}]
            for annotation_index, annotation in enumerate(annotations):
                source_label = annotation.source_label if hasattr(annotation, "source_label") else annotation["source_label"]
                configured_mapping_text = annotation.mapping_text if hasattr(annotation, "mapping_text") else annotation["mapping_text"]
                configured_page = annotation.page if hasattr(annotation, "page") else annotation.get("page")
                configured_x = annotation.x if hasattr(annotation, "x") else annotation.get("x")
                configured_y = annotation.y if hasattr(annotation, "y") else annotation.get("y")
                needle = source_label.strip()
                mapping_text = configured_mapping_text.strip() or f"{dataset.domain}.{variable.name}"
                matches: list[tuple[fitz.Page, fitz.Rect]] = []
                if needle and len(needle) >= 2:
                    for page in document:
                        for rect in page.search_for(needle):
                            matches.append((page, rect))
                if matches:
                    page, rect = matches[0]
                    manual_position = configured_page is not None and configured_x is not None and configured_y is not None and 1 <= configured_page <= source_page_count
                    if manual_position:
                        page = document[configured_page - 1]
                    box = _insert_acrf_mapping_box(
                        page,
                        rect,
                        mapping_text,
                        occupied_boxes.setdefault(page.number, []),
                        font_family=dataset.acrf_font_family,
                        font_size=dataset.acrf_font_size,
                        text_color=dataset.acrf_text_color,
                        fill_color=dataset.acrf_fill_color,
                        position=(configured_x, configured_y) if manual_position else None,
                        avoid_overlaps=not manual_position,
                    )
                    domain_pages[dataset.domain].add(page.number + 1)
                else:
                    box = None
                status = "unmatched" if not matches else "ambiguous" if len(matches) > 1 else "matched"
                coverage.append({"annotation_type": "variable", "annotation_id": f"{dataset.domain}.{variable.name}.{annotation_index}", "domain": dataset.domain, "variable": variable.name, "annotation_index": annotation_index, "origin": variable.origin, "mapping": variable.mapping_expression, "label": needle, "mapping_text": mapping_text, "status": status, "page": page.number + 1 if matches else None, "match_count": len(matches), "rendering": "textbox" if box else None, "textbox": [round(value, 2) for value in box] if box else None, "style": {"font_family": dataset.acrf_font_family, "font_size": dataset.acrf_font_size, "text_color": dataset.acrf_text_color.upper(), "fill_color": dataset.acrf_fill_color.upper()}})
    for dataset in result.datasets:
        domain_annotation = dataset.acrf_domain_annotation
        if not domain_annotation.enabled:
            continue
        positions = {position.page: position for position in domain_annotation.positions}
        for page_number in sorted(domain_pages[dataset.domain]):
            page = document[page_number - 1]
            configured = positions.get(page_number)
            box = _insert_acrf_mapping_box(
                page,
                None,
                domain_annotation.text.strip() or dataset.domain,
                occupied_boxes.setdefault(page.number, []),
                font_family=dataset.acrf_font_family,
                font_size=dataset.acrf_font_size,
                text_color=dataset.acrf_text_color,
                fill_color=dataset.acrf_fill_color,
                position=(configured.x, configured.y) if configured else (18.0, 18.0),
                avoid_overlaps=configured is None,
            )
            coverage.append({"annotation_type": "domain", "annotation_id": f"domain:{dataset.domain}:{page_number}", "domain": dataset.domain, "variable": "", "annotation_index": 0, "label": "", "mapping_text": domain_annotation.text.strip() or dataset.domain, "status": "matched", "page": page_number, "match_count": 1, "rendering": "textbox", "textbox": [round(value, 2) for value in box], "style": {"font_family": dataset.acrf_font_family, "font_size": dataset.acrf_font_size, "text_color": dataset.acrf_text_color.upper(), "fill_color": dataset.acrf_fill_color.upper()}})
    for annotation_index, annotation in enumerate(result.acrf_free_annotations):
        valid_page = 1 <= annotation.page <= source_page_count
        box = None
        if valid_page and annotation.text.strip():
            page = document[annotation.page - 1]
            box = _insert_acrf_mapping_box(
                page,
                None,
                annotation.text.strip(),
                occupied_boxes.setdefault(page.number, []),
                font_family=annotation.font_family,
                font_size=annotation.font_size,
                text_color=annotation.text_color,
                fill_color=annotation.fill_color,
                position=(annotation.x, annotation.y),
                avoid_overlaps=False,
            )
        coverage.append({"annotation_type": "free", "annotation_id": annotation.id, "domain": "", "variable": "", "annotation_index": annotation_index, "label": "", "mapping_text": annotation.text.strip(), "status": "matched" if box else "unmatched", "page": annotation.page if valid_page else None, "match_count": 1 if box else 0, "rendering": "textbox" if box else None, "textbox": [round(value, 2) for value in box] if box else None, "style": {"font_family": annotation.font_family, "font_size": annotation.font_size, "text_color": annotation.text_color.upper(), "fill_color": annotation.fill_color.upper()}})
    appendix = document.new_page()
    appendix.insert_textbox(fitz.Rect(48, 48, appendix.rect.width - 48, 110), "Draft aCRF annotation appendix", fontsize=16, color=(0.1, 0.2, 0.35))
    appendix.insert_textbox(fitz.Rect(48, 100, appendix.rect.width - 48, 155), DISCLAIMER.replace("—", "-"), fontsize=9, color=(0.65, 0.05, 0.15))
    issues = []
    for item in coverage:
        if item["status"] == "matched":
            continue
        if item["annotation_type"] == "variable":
            issues.append(f"{item['status'].upper()}: {item['domain']}.{item['variable']} annotation {item['annotation_index'] + 1} <- {item['label'] or '[no CRF label]'}")
        else:
            issues.append(f"{item['status'].upper()}: free annotation {item['annotation_id']} on page {item['page'] or '[invalid]'}")
    appendix.insert_textbox(fitz.Rect(48, 165, appendix.rect.width - 48, appendix.rect.height - 48), "Ambiguous and unmatched mappings:\n\n" + "\n".join(issues or ["None"]), fontsize=9)
    pages = [{"page": page.number + 1, "width": round(page.rect.width, 2), "height": round(page.rect.height, 2)} for page in document]
    document.save(path)
    document.close()
    domain_styles = {dataset.domain: {"font_family": dataset.acrf_font_family, "font_size": dataset.acrf_font_size, "text_color": dataset.acrf_text_color.upper(), "fill_color": dataset.acrf_fill_color.upper()} for dataset in result.datasets}
    coverage_path.write_text(json.dumps({"status": "review_required" if issues else "completed", "searchable": True, "annotations": coverage, "pages": pages, "domain_styles": domain_styles, "summary": {state: sum(1 for item in coverage if item["annotation_type"] == "variable" and item["status"] == state) for state in ("matched", "ambiguous", "unmatched")}}, indent=2), encoding="utf-8")
    return path, coverage_path


def sdtm_program_filename(domain: str, language: str) -> str:
    """Return the stable artifact filename for one reviewed SDTM domain program."""

    normalized_domain = re.sub(r"[^A-Za-z0-9]+", "-", domain.strip()).strip("-").lower()
    if not normalized_domain:
        raise ValueError("An SDTM domain program requires a non-empty domain identifier.")
    extensions = {"r": "R", "sas": "sas"}
    try:
        extension = extensions[language.lower()]
    except KeyError as exc:
        raise ValueError(f"Unsupported SDTM program language: {language}.") from exc
    return f"build-{normalized_domain}.{extension}"


def _render_r_sdtm(result: SDTMPlan, dataset: SDTMDataset, path: Path) -> Path:
    rules = {
        (rule.target_domain.upper(), rule.target_variable.upper()): rule
        for rule in result.rule_augmentations
    }
    lines = [
        f"# {DISCLAIMER}",
        "# Generated from reviewed rule-augmentation metadata.",
        "# EXECUTION STATUS: NOT RUN. This program has not been tested against raw datasets.",
        "library(dplyr)",
        "library(readr)",
        "library(haven)",
        "library(tidyr)",
        "input_dir <- Sys.getenv(\"SDTM_INPUT_DIR\")",
        "output_dir <- Sys.getenv(\"SDTM_OUTPUT_DIR\")",
        "if (!nzchar(input_dir) || !nzchar(output_dir)) stop(\"Runner input/output directories are required\")",
        "read_source <- function(logical_name) {",
        "  candidates <- list.files(input_dir, full.names = TRUE)",
        "  stems <- toupper(tools::file_path_sans_ext(basename(candidates)))",
        "  matches <- candidates[stems == toupper(logical_name)]",
        "  if (length(matches) != 1) stop(paste(\"Expected exactly one input dataset for\", logical_name))",
        "  extension <- tolower(tools::file_ext(matches[[1]]))",
        "  if (extension == \"csv\") return(readr::read_csv(matches[[1]], show_col_types = FALSE, progress = FALSE))",
        "  if (extension == \"xpt\") return(haven::read_xpt(matches[[1]]))",
        "  stop(paste(\"Unsupported input format for\", logical_name))",
        "}",
        "",
    ]
    record_lines, final_source = _compile_r_record_plan(dataset)
    lines.extend([f"# {dataset.domain}: {dataset.description}", *record_lines, ""])
    lines.extend([f"{dataset.domain.lower()} <- {final_source} %>%", "  transmute("])
    for index, variable in enumerate(dataset.variables):
        rule = rules[(dataset.domain.upper(), variable.name.upper())]
        delimiter = "," if index < len(dataset.variables) - 1 else ""
        lines.extend(
            [
                f"    # {rule.rule_id}: {_one_line(rule.description)}",
                f"    {variable.name} = {_safe_r_expression(rule.r_expression)}{delimiter}",
            ]
        )
    lines.extend(["  )", f"haven::write_xpt({dataset.domain.lower()}, file.path(output_dir, \"{dataset.domain.lower()}.xpt\"), version = 5)", ""])
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _render_sas_sdtm(result: SDTMPlan, dataset: SDTMDataset, path: Path) -> Path:
    rules = {
        (rule.target_domain.upper(), rule.target_variable.upper()): rule
        for rule in result.rule_augmentations
    }
    lines = [
        f"/* {DISCLAIMER} */",
        "/* Generated from reviewed rule-augmentation metadata. */",
        "/* EXECUTION STATUS: NOT RUN. This export-only SAS scaffold has not been tested against raw datasets. */",
        "",
    ]
    record_lines, final_source = _compile_sas_record_plan(dataset)
    lines.extend([f"/* {dataset.domain}: {dataset.description} */", *record_lines, f"data sdtm.{dataset.domain.lower()};", f"  set {final_source};"])
    for variable in dataset.variables:
        rule = rules[(dataset.domain.upper(), variable.name.upper())]
        lines.extend(
            [
                f"  /* {rule.rule_id}: {_one_line(rule.description)} */",
                f"  {variable.name} = {rule.sas_expression};",
            ]
        )
    lines.extend(["run;", ""])
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _compile_r_record_plan(dataset: SDTMDataset) -> tuple[list[str], str]:
    lines: list[str] = []
    symbols: dict[str, str] = {}
    for step in dataset.record_plan.steps:
        symbol = _program_symbol(step.output)
        symbols[step.step_id.casefold()] = symbol
        lines.append(f"# {step.step_id} [{step.operation}]: {_one_line(step.description)}")
        if step.operation == "read":
            lines.append(f"{symbol} <- read_source({_r_string(step.source_dataset or '')})")
        elif step.operation == "stack":
            inputs = [symbols[item.casefold()] for item in step.inputs]
            if step.column_alignment:
                rendered_inputs = []
                for reference, input_symbol in zip(step.inputs, inputs):
                    assignments = []
                    for column in step.column_alignment:
                        source = next((item for item in column.sources if item.input.casefold() == reference.casefold()), None)
                        expression = f'.data[[{_r_string(source.variable)}]]' if source else "NA"
                        assignments.append(f"{_r_name(column.target)} = {expression}")
                    rendered_inputs.append(f"dplyr::transmute({input_symbol}, {', '.join(assignments)})")
                lines.append(f"{symbol} <- dplyr::bind_rows({', '.join(rendered_inputs)})")
            else:
                lines.append(f"{symbol} <- dplyr::bind_rows({', '.join(inputs)})")
        elif step.operation == "join":
            left = symbols[(step.left or "").casefold()]
            right = symbols[(step.right or "").casefold()]
            by = ", ".join(f"{_r_string(item.left)} = {_r_string(item.right)}" for item in step.join_keys)
            lines.append(
                f"{symbol} <- dplyr::{step.join_type}_join({left}, {right}, by = c({by}), suffix = c(\".left\", \".right\"))"
            )
            lines.append(f"# Reviewed cardinality: {step.cardinality}")
        elif step.operation == "transpose":
            source = symbols[step.inputs[0].casefold()]
            columns = ", ".join(_r_string(item) for item in step.value_variables)
            expression = (
                f"tidyr::pivot_longer({source}, cols = c({columns}), "
                f"names_to = {_r_string(step.name_variable or 'SOURCE_VARIABLE')}, "
                f"values_to = {_r_string(step.value_variable or 'SOURCE_VALUE')})"
            )
            if step.transpose_values:
                mappings = ", ".join(
                    f"{_r_string(item.source_variable)} = {_r_string(item.name_value)}"
                    for item in step.transpose_values
                )
                expression += (
                    " %>% dplyr::mutate("
                    f"{_r_name(step.name_variable or 'SOURCE_VARIABLE')} = dplyr::recode("
                    f".data[[{_r_string(step.name_variable or 'SOURCE_VARIABLE')}]], {mappings}))"
                )
            lines.append(f"{symbol} <- {expression}")
        elif step.operation == "filter":
            source = symbols[step.inputs[0].casefold()]
            lines.append(f"{symbol} <- dplyr::filter({source}, {_safe_r_expression(step.condition or 'FALSE')})")
        elif step.operation == "deduplicate":
            source = symbols[step.inputs[0].casefold()]
            ordering = step.order_by or step.keys
            order_args = ", ".join(
                f"dplyr::desc(.data[[{_r_string(item)}]])" if step.keep == "last" else f".data[[{_r_string(item)}]]"
                for item in ordering
            )
            keys = ", ".join(f".data[[{_r_string(item)}]]" for item in step.keys)
            lines.append(f"{symbol} <- {source} %>% dplyr::arrange({order_args}) %>% dplyr::distinct({keys}, .keep_all = TRUE)")
        elif step.operation == "aggregate":
            source = symbols[step.inputs[0].casefold()]
            groups = ", ".join(f".data[[{_r_string(item)}]]" for item in step.group_by)
            aggregations = ", ".join(_r_aggregation(item) for item in step.aggregations)
            lines.append(f"{symbol} <- {source} %>% dplyr::group_by({groups}) %>% dplyr::summarise({aggregations}, .groups = \"drop\")")
    return lines, symbols[dataset.record_plan.output_step.casefold()]


def _compile_sas_record_plan(dataset: SDTMDataset) -> tuple[list[str], str]:
    lines: list[str] = []
    symbols: dict[str, str] = {}
    for step in dataset.record_plan.steps:
        symbol = f"work.{_program_symbol(step.output)}"
        symbols[step.step_id.casefold()] = symbol
        lines.append(f"/* {step.step_id} [{step.operation}]: {_one_line(step.description)} */")
        if step.operation == "read":
            lines.extend([f"data {symbol};", f"  set raw.{_sas_name(step.source_dataset or '')};", "run;"])
        elif step.operation == "stack":
            inputs: list[str] = []
            for input_index, reference in enumerate(step.inputs, 1):
                input_symbol = symbols[reference.casefold()]
                if not step.column_alignment:
                    inputs.append(input_symbol)
                    continue
                aligned_symbol = f"{symbol}_aligned_{input_index}"
                assignments: list[str] = []
                keep: list[str] = []
                for column in step.column_alignment:
                    source = next(
                        (item for item in column.sources if item.input.casefold() == reference.casefold()),
                        None,
                    )
                    target = _sas_name(column.target)
                    keep.append(target)
                    assignments.append(
                        f"  {target} = {_sas_name(source.variable)};" if source else f"  {target} = .;"
                    )
                lines.extend([
                    f"data {aligned_symbol};",
                    f"  set {input_symbol};",
                    *assignments,
                    f"  keep {' '.join(keep)};",
                    "run;",
                ])
                inputs.append(aligned_symbol)
            lines.extend([f"data {symbol};", f"  set {' '.join(inputs)};", "run;"])
        elif step.operation == "join":
            left = symbols[(step.left or "").casefold()]
            right = symbols[(step.right or "").casefold()]
            join = "full join" if step.join_type == "full" else f"{step.join_type} join"
            conditions = " and ".join(f"a.{_sas_name(item.left)} = b.{_sas_name(item.right)}" for item in step.join_keys)
            lines.extend(["proc sql;", f"  create table {symbol} as", f"  select a.*, b.* from {left} as a {join} {right} as b on {conditions};", "quit;", f"/* Reviewed cardinality: {step.cardinality} */"])
        elif step.operation == "transpose":
            source = symbols[step.inputs[0].casefold()]
            transpose_input = source
            if step.id_variables:
                transpose_input = f"{symbol}_sorted"
                lines.extend([
                    f"proc sort data={source} out={transpose_input};",
                    f"  by {' '.join(_sas_name(item) for item in step.id_variables)};",
                    "run;",
                ])
            transpose_output = f"{symbol}_wide" if step.transpose_values else symbol
            lines.append(
                f"proc transpose data={transpose_input} out={transpose_output}"
                f"(rename=(_NAME_={_sas_name(step.name_variable or 'SOURCE_VARIABLE')} "
                f"COL1={_sas_name(step.value_variable or 'SOURCE_VALUE')}));"
            )
            if step.id_variables:
                lines.append(f"  by {' '.join(_sas_name(item) for item in step.id_variables)};")
            lines.extend([f"  var {' '.join(_sas_name(item) for item in step.value_variables)};", "run;"])
            if step.transpose_values:
                name_variable = _sas_name(step.name_variable or "SOURCE_VARIABLE")
                lines.extend([f"data {symbol};", f"  set {transpose_output};", f"  select (upcase({name_variable}));"])
                for item in step.transpose_values:
                    lines.append(
                        f'    when ({json.dumps(item.source_variable.upper())}) '
                        f'{name_variable} = {json.dumps(item.name_value)};'
                    )
                lines.extend(["    otherwise;", "  end;", "run;"])
        elif step.operation == "filter":
            source = symbols[step.inputs[0].casefold()]
            lines.extend([f"data {symbol};", f"  set {source};", f"  if {step.sas_condition};", "run;"])
        elif step.operation == "deduplicate":
            source = symbols[step.inputs[0].casefold()]
            lines.extend([f"proc sort data={source} out={symbol} nodupkey;", f"  by {' '.join(_sas_name(item) for item in step.keys)};", "run;"])
        elif step.operation == "aggregate":
            source = symbols[step.inputs[0].casefold()]
            selects = [*_sas_group_columns(step.group_by), *[_sas_aggregation(item) for item in step.aggregations]]
            lines.extend(["proc sql;", f"  create table {symbol} as", f"  select {', '.join(selects)} from {source}", f"  group by {', '.join(_sas_name(item) for item in step.group_by)};", "quit;"])
    return lines, symbols[dataset.record_plan.output_step.casefold()]


def _r_aggregation(item: object) -> str:
    output = _r_name(getattr(item, "output_variable"))
    operation = getattr(item, "operation")
    source = getattr(item, "source_variable")
    if operation == "count":
        return f"{output} = dplyr::n()"
    if operation in {"first", "last"}:
        return f"{output} = dplyr::{operation}(.data[[{_r_string(source or '')}]])"
    function = {"sum": "sum", "min": "min", "max": "max", "mean": "mean"}[operation]
    return f"{output} = {function}(.data[[{_r_string(source or '')}]], na.rm = TRUE)"


def _sas_aggregation(item: object) -> str:
    operation = getattr(item, "operation")
    output = _sas_name(getattr(item, "output_variable"))
    source = "*" if operation == "count" else _sas_name(getattr(item, "source_variable") or "")
    function = "count" if operation == "count" else operation
    return f"{function}({source}) as {output}"


def _sas_group_columns(values: list[str]) -> list[str]:
    return [_sas_name(item) for item in values]


def _program_symbol(value: str) -> str:
    symbol = re.sub(r"[^A-Za-z0-9_]", "_", value.strip().lower())
    if not symbol or symbol[0].isdigit():
        symbol = f"step_{symbol}"
    return symbol


def _r_name(value: str) -> str:
    return f"`{value.replace('`', '')}`"


def _sas_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", value.strip())


def _source_reference_text(references: list[object]) -> str:
    return "; ".join(
        f"{getattr(item, 'dataset')}.{getattr(item, 'variable')} ({getattr(item, 'role')})"
        for item in references
    )


def _one_line(value: str) -> str:
    return " ".join(value.split())


def _r_string(value: str) -> str:
    return json.dumps(value)


def _safe_r_expression(value: str) -> str:
    return normalize_r_mapping_expression(value)


def render_tlf(result: TLFPlan, output_dir: Path, languages: list[str]) -> list[Path]:
    json_path = output_dir / "tlf-specifications.json"
    json_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    xlsx_path = _render_tlf_xlsx(result, output_dir / "tlf-specifications.xlsx")
    programs = {program.output_id.casefold(): program for program in result.programs}
    document = Document()
    _document_header(document, f"TLF Shells — {result.study_name}")
    for index, output in enumerate(result.outputs):
        if index:
            document.add_page_break()
        document.add_heading(f"{output.output_id}: {output.title}", level=1)
        document.add_paragraph(
            f"Type: {output.output_type.title()}\nBasis: {output.basis.replace('_', ' ').title()}\n"
            f"Section: {output.section}\nPopulation: {output.population}\n"
            f"Status: {output.readiness.upper()}\nSource: {output.source_reference}"
        )
        if output.output_type == "table":
            table = document.add_table(rows=max(2, len(output.rows) + 1), cols=max(1, len(output.columns) + 1))
            table.style = "Table Grid"
            table.rows[0].cells[0].text = "Row"
            for column_index, column in enumerate(output.columns, 1):
                table.rows[0].cells[column_index].text = column.heading
            for row_index, row in enumerate(output.rows, 1):
                table.rows[row_index].cells[0].text = row.label
                for column_index in range(1, len(table.columns)):
                    table.rows[row_index].cells[column_index].text = f"<{row.statistic or 'value'}>"
        elif output.output_type == "listing":
            table = document.add_table(rows=2, cols=max(1, len(output.columns)))
            table.style = "Table Grid"
            for column_index, column in enumerate(output.columns):
                table.rows[0].cells[column_index].text = column.heading
                table.rows[1].cells[column_index].text = f"<{column.source}>"
        else:
            table = document.add_table(rows=1, cols=1)
            table.style = "Table Grid"
            figure = output.figure
            table.cell(0, 0).text = (
                f"FIGURE PLACEHOLDER\n{figure.geometry if figure else 'TODO: confirm figure type'}\n"
                f"X: {figure.x_axis if figure else 'TODO'}\nY: {figure.y_axis if figure else 'TODO'}\n"
                f"Group: {figure.group if figure else ''}"
            )
        for footnote in output.footnotes:
            document.add_paragraph(footnote, style="Caption")
        for note in [*output.programming_notes, *output.blocking_items]:
            document.add_paragraph(note, style="Intense Quote")
        program = programs.get(output.output_id.casefold())
        if program and program.adam_sources:
            document.add_heading("ADaM programming links", level=2)
            source_table = document.add_table(rows=1, cols=4)
            source_table.style = "Table Grid"
            for index, heading in enumerate(("Dataset", "Variable", "Role", "Derivation")):
                source_table.rows[0].cells[index].text = heading
            for source in program.adam_sources:
                cells = source_table.add_row().cells
                cells[0].text = source.dataset
                cells[1].text = source.variable
                cells[2].text = source.role
                cells[3].text = source.derivation
    docx_path = output_dir / "tlf-shells.docx"
    document.save(docx_path)
    paths = [json_path, xlsx_path, docx_path]
    filenames: set[str] = {"tlf-setup"}
    if "r" in languages:
        setup = output_dir / "tlf-setup.R"
        setup.write_text(f"# {DISCLAIMER}\nlibrary(dplyr)\nlibrary(ggplot2)\n", encoding="utf-8")
        paths.append(setup)
        for output in result.outputs:
            slug = _unique_program_slug(output.output_id, filenames)
            r_path = output_dir / f"{slug}.R"
            program = programs.get(output.output_id.casefold())
            body = program.r_code if program else "# TODO: add programming augmentation"
            adam_links = ", ".join(f"{source.dataset}.{source.variable}" for source in (program.adam_sources if program else [])) or "TODO: confirm ADaM schema links"
            r_path.write_text(
                f"# {DISCLAIMER}\nsource(\"tlf-setup.R\")\n\n# {output.output_id}: {output.title}\n# Basis: {output.basis}\n# ADaM schema: {adam_links}\n{body}\n",
                encoding="utf-8",
            )
            paths.append(r_path)
    if "sas" in languages:
        setup = output_dir / "tlf-setup.sas"
        setup.write_text(f"/* {DISCLAIMER} */\noptions validvarname=upcase;\n", encoding="utf-8")
        paths.append(setup)
        filenames = {"tlf-setup"}
        for output in result.outputs:
            slug = _unique_program_slug(output.output_id, filenames)
            sas_path = output_dir / f"{slug}.sas"
            program = programs.get(output.output_id.casefold())
            body = program.sas_code if program else "/* TODO: add programming augmentation */"
            adam_links = ", ".join(f"{source.dataset}.{source.variable}" for source in (program.adam_sources if program else [])) or "TODO: confirm ADaM schema links"
            sas_path.write_text(
                f"/* {DISCLAIMER} */\n%include \"tlf-setup.sas\";\n\n/* {output.output_id}: {output.title} */\n/* Basis: {output.basis} */\n/* ADaM schema: {adam_links} */\n{body}\n",
                encoding="utf-8",
            )
            paths.append(sas_path)
    return paths


def _render_tlf_xlsx(result: TLFPlan, path: Path) -> Path:
    workbook = Workbook()
    inventory = workbook.active
    inventory.title = "Output Inventory"
    inventory.append(["Output ID", "Type", "Title", "Basis", "Section", "Purpose", "Population", "Source Reference", "Readiness"])
    for output in result.outputs:
        inventory.append([output.output_id, output.output_type, output.title, output.basis, output.section, output.purpose, output.population, output.source_reference, output.readiness])

    populations = workbook.create_sheet("Populations")
    populations.append(["Output ID", "Population", "Filter", "Treatment Variable", "Analysis Method"])
    for output in result.outputs:
        populations.append([output.output_id, output.population, output.population_filter, output.treatment_variable, output.analysis_method])

    sources = workbook.create_sheet("Source Mapping")
    sources.append(["Output ID", "Dataset", "Variable", "Role", "Derivation"])
    for output in result.outputs:
        for variable in output.source_variables:
            sources.append([output.output_id, variable.dataset, variable.variable, variable.role, variable.derivation])

    display = workbook.create_sheet("Display Elements")
    display.append(["Output ID", "Kind", "Element ID", "Label", "Source", "Statistic", "Condition", "Format"])
    for output in result.outputs:
        for column in output.columns:
            display.append([output.output_id, "column", column.column_id, column.heading, column.source, column.statistic, "", column.format])
        for row in output.rows:
            display.append([output.output_id, "row", row.row_id, row.label, row.source, row.statistic, row.condition, row.format])
        if output.figure:
            display.append([output.output_id, "figure", "FIGURE", output.figure.geometry, output.figure.x_axis, output.figure.y_axis, output.figure.group, output.figure.panel])

    programming = workbook.create_sheet("Programming")
    programming.append(["Output ID", "Input Datasets", "ADaM Schema Links", "Derivation Steps", "R Scaffold", "SAS Scaffold", "Review Notes"])
    for program in result.programs:
        adam_links = "; ".join(
            f"{source.dataset}.{source.variable} [{source.role}; {source.derivation}]"
            for source in program.adam_sources
        )
        programming.append([program.output_id, "; ".join(program.input_datasets), adam_links, "\n".join(program.derivation_steps), program.r_code, program.sas_code, "; ".join(program.review_notes)])

    assumptions = workbook.create_sheet("Assumptions and Blockers")
    assumptions.append(["Type", "Output ID", "Text"])
    assumptions.append(["Disclaimer", "", DISCLAIMER])
    for item in result.assumptions:
        assumptions.append(["Assumption", "", item])
    for item in result.unresolved_items:
        assumptions.append(["Unresolved", "", item])
    for output in result.outputs:
        for item in output.blocking_items:
            assumptions.append(["Blocker", output.output_id, item])

    for sheet in workbook.worksheets:
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for cell in sheet[1]:
            bold = copy(cell.font)
            bold.bold = True
            cell.font = bold
    workbook.save(path)
    return path


def _unique_program_slug(output_id: str, seen: set[str]) -> str:
    base = _slug(output_id) or "tlf-output"
    candidate = base
    suffix = 2
    while candidate.casefold() in seen:
        candidate = f"{base}-{suffix}"
        suffix += 1
    seen.add(candidate.casefold())
    return candidate


def add_manifest_and_bundle(paths: list[Path], output_dir: Path, workflow: str) -> list[Path]:
    manifest_path = output_dir / "manifest.json"
    manifest = {
        "workflow": workflow,
        "disclaimer": DISCLAIMER,
        "files": [
            {"name": path.name, "size_bytes": path.stat().st_size, "sha256": sha256_file(path)}
            for path in paths
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    bundle_path = output_dir / f"{workflow}-artifacts.zip"
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in [*paths, manifest_path]:
            archive.write(path, arcname=path.name)
    return [*paths, manifest_path, bundle_path]


def copy_original(path: Path, output_dir: Path) -> Path:
    destination = output_dir / path.name
    if path.resolve() != destination.resolve():
        shutil.copy2(path, destination)
    return destination


def _slug(value: str) -> str:
    return "-".join("".join(character.lower() if character.isalnum() else " " for character in value).split()) or "clinical-document"
