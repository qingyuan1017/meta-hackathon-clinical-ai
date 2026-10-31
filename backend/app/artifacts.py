from __future__ import annotations

from copy import copy
import hashlib
import json
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


MEDIA_TYPES = {
    ".json": "application/json",
    ".md": "text/markdown",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pdf": "application/pdf",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xml": "application/xml",
    ".r": "text/x-r-source",
    ".sas": "text/x-sas",
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
    json_path = output_dir / "sdtm-mapping.json"
    json_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    paths.append(json_path)
    paths.append(_render_sdtm_xlsx(result, output_dir / "sdtm-mapping.xlsx"))
    paths.append(_render_define_xml(result, output_dir / "define.xml"))
    if crf_path is not None:
        paths.append(_annotate_crf(result, crf_path, output_dir / "annotated-crf.pdf"))
    if "r" in languages:
        paths.append(_render_r_sdtm(result, output_dir / "build-sdtm.R"))
    if "sas" in languages:
        paths.append(_render_sas_sdtm(result, output_dir / "build-sdtm.sas"))
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

    variables = workbook.create_sheet("Variable Mappings")
    variables.append(
        [
            "Domain",
            "Dataset",
            "Variable",
            "Label",
            "Type",
            "Source Dataset",
            "Source Field",
            "Origin",
            "Mapping",
            "Controlled Terms",
            "CRF Source Label",
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
                    variable.source_dataset,
                    variable.source_field,
                    variable.origin,
                    variable.mapping_expression,
                    "; ".join(variable.controlled_terms),
                    variable.crf_source_label or "",
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
                        "; ".join(metadata.controlled_terms),
                    ]
                )

    domain_rules = workbook.create_sheet("Domain Rule Augmentation")
    domain_rules.append(
        [
            "Rule ID",
            "Target Domain",
            "Source Datasets",
            "Description",
            "Logic",
            "R Input Expression",
            "SAS Input Statement",
            "Review Notes",
        ]
    )
    for rule in result.domain_rule_augmentations:
        domain_rules.append(
            [
                rule.rule_id,
                rule.target_domain,
                "; ".join(rule.source_datasets),
                rule.description,
                rule.logic,
                rule.r_input_expression,
                rule.sas_input_statement,
                "; ".join(rule.review_notes),
            ]
        )

    rules = workbook.create_sheet("Variable Rule Augmentation")
    rules.append(
        [
            "Rule ID",
            "Target Domain",
            "Target Variable",
            "Source Dependencies",
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
                "; ".join(rule.source_dependencies),
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
    for current in (sheet, variables, value_level, domain_rules, rules):
        current.freeze_panes = "A2"
        current.auto_filter.ref = current.dimensions
    workbook.save(path)
    return path


def _render_define_xml(result: SDTMPlan, path: Path) -> Path:
    odm_ns = "http://www.cdisc.org/ns/odm/v1.3"
    def_ns = "http://www.cdisc.org/ns/def/v2.1"
    root = etree.Element(f"{{{odm_ns}}}ODM", nsmap={None: odm_ns, "def": def_ns}, FileOID="WORKBENCH.DEFINE", ODMVersion="1.3.2", FileType="Snapshot")
    root.addprevious(etree.Comment(DISCLAIMER))
    study = etree.SubElement(root, f"{{{odm_ns}}}Study", OID="STUDY.1")
    etree.SubElement(study, f"{{{odm_ns}}}GlobalVariables")
    metadata = etree.SubElement(study, f"{{{odm_ns}}}MetaDataVersion", OID="MDV.1", Name=result.study_name, Description=DISCLAIMER)
    for dataset in result.datasets:
        group = etree.SubElement(metadata, f"{{{odm_ns}}}ItemGroupDef", OID=f"IG.{dataset.domain}", Name=dataset.domain, Repeating="Yes", IsReferenceData="No", Purpose="Tabulation")
        etree.SubElement(group, f"{{{odm_ns}}}Description").append(_translated_text(odm_ns, dataset.description))
        for order, variable in enumerate(dataset.variables, 1):
            etree.SubElement(group, f"{{{odm_ns}}}ItemRef", ItemOID=f"IT.{dataset.domain}.{variable.name}", OrderNumber=str(order), Mandatory="No")
            item = etree.SubElement(metadata, f"{{{odm_ns}}}ItemDef", OID=f"IT.{dataset.domain}.{variable.name}", Name=variable.name, DataType="text" if variable.data_type == "Char" else "float", Length="200" if variable.data_type == "Char" else "8")
            description = etree.SubElement(item, f"{{{odm_ns}}}Description")
            description.append(_translated_text(odm_ns, variable.label))
            origin = etree.SubElement(item, f"{{{def_ns}}}Origin", Type=variable.origin)
            origin_description = etree.SubElement(origin, f"{{{odm_ns}}}Description")
            origin_description.append(_translated_text(odm_ns, variable.source_field))
    tree = etree.ElementTree(root)
    tree.write(str(path), encoding="UTF-8", xml_declaration=True, pretty_print=True)
    etree.parse(str(path))
    return path


def _translated_text(namespace: str, text: str) -> etree._Element:
    node = etree.Element(f"{{{namespace}}}TranslatedText", lang="en")
    node.text = text
    return node


def _annotate_crf(result: SDTMPlan, crf_path: Path, path: Path) -> Path:
    document = fitz.open(crf_path)
    unmatched: list[str] = []
    for dataset in result.datasets:
        for variable in dataset.variables:
            matches: list[tuple[fitz.Page, fitz.Rect]] = []
            needle = (variable.crf_source_label or variable.source_field).strip()
            if needle and len(needle) >= 2:
                for page in document:
                    for rect in page.search_for(needle)[:1]:
                        matches.append((page, rect))
            if matches:
                page, rect = matches[0]
                point = fitz.Point(min(rect.x1 + 8, page.rect.width - 24), max(rect.y0, 24))
                value_level = "\n".join(
                    f"VLM: {item.where_clause} — {item.mapping_expression}"
                    for item in variable.value_level_metadata
                )
                text = f"{dataset.domain}.{variable.name}\n{variable.label}\n{variable.mapping_expression}"
                if value_level:
                    text = f"{text}\n{value_level}"
                annotation = page.add_text_annot(point, text)
                annotation.set_info(title="Clinical AI Workbench — DRAFT")
                annotation.update()
            else:
                unmatched.append(f"{dataset.domain}.{variable.name} ← {needle or '[no CRF label]'}")
    appendix = document.new_page()
    appendix.insert_textbox(fitz.Rect(48, 48, appendix.rect.width - 48, 110), "Draft aCRF annotation appendix", fontsize=16, color=(0.1, 0.2, 0.35))
    appendix.insert_textbox(fitz.Rect(48, 100, appendix.rect.width - 48, 155), DISCLAIMER, fontsize=9, color=(0.65, 0.05, 0.15))
    appendix.insert_textbox(fitz.Rect(48, 165, appendix.rect.width - 48, appendix.rect.height - 48), "Mappings not positioned on a source label:\n\n" + "\n".join(unmatched or ["None"]), fontsize=9)
    document.save(path)
    document.close()
    return path


def _render_r_sdtm(result: SDTMPlan, path: Path) -> Path:
    domain_rules = {
        rule.target_domain.upper(): rule for rule in result.domain_rule_augmentations
    }
    rules = {
        (rule.target_domain.upper(), rule.target_variable.upper()): rule
        for rule in result.rule_augmentations
    }
    lines = [
        f"# {DISCLAIMER}",
        "# Generated from reviewed rule-augmentation metadata.",
        "# EXECUTION STATUS: NOT RUN. This program has not been tested against raw datasets.",
        "library(dplyr)",
        "",
    ]
    for dataset in result.datasets:
        domain_rule = domain_rules[dataset.domain.upper()]
        lines.extend(
            [
                f"# {dataset.domain}: {dataset.description}",
                f"# {domain_rule.rule_id}: {_one_line(domain_rule.description)}",
                f"# Source datasets: {', '.join(domain_rule.source_datasets)}",
                f"{dataset.domain.lower()} <- {domain_rule.r_input_expression} %>%",
                "  transmute(",
            ]
        )
        for index, variable in enumerate(dataset.variables):
            rule = rules[(dataset.domain.upper(), variable.name.upper())]
            delimiter = "," if index < len(dataset.variables) - 1 else ""
            lines.extend(
                [
                    f"    # {rule.rule_id}: {_one_line(rule.description)}",
                    f"    {variable.name} = {rule.r_expression}{delimiter}",
                ]
            )
        lines.extend(["  )", "", f"# TODO: write_xpt({dataset.domain.lower()}, 'output/{dataset.domain.lower()}.xpt')", ""])
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _render_sas_sdtm(result: SDTMPlan, path: Path) -> Path:
    domain_rules = {
        rule.target_domain.upper(): rule for rule in result.domain_rule_augmentations
    }
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
    for dataset in result.datasets:
        domain_rule = domain_rules[dataset.domain.upper()]
        lines.extend(
            [
                f"/* {dataset.domain}: {dataset.description} */",
                f"/* {domain_rule.rule_id}: {_one_line(domain_rule.description)} */",
                f"/* Source datasets: {', '.join(domain_rule.source_datasets)} */",
                f"data sdtm.{dataset.domain.lower()};",
            ]
        )
        lines.extend(f"  {line}" for line in domain_rule.sas_input_statement.splitlines())
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


def _one_line(value: str) -> str:
    return " ".join(value.split())


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
