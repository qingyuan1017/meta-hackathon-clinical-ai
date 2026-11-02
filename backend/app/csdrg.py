from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.platypus.tableofcontents import TableOfContents

from .schemas import DISCLAIMER, SDTMPlan
from .schemas.validation import CSDRGDocument, CSDRGSection, CSDRGTable
from .sdtm_execution import list_attempts
from .sdtm_validation import list_validations
from .sdtm_workbench import read_state


def build_csdrg(job_dir: Path, plan: SDTMPlan) -> CSDRGDocument:
    state = read_state(job_dir)
    attempts = list_attempts(job_dir)
    validations = list_validations(job_dir)
    approved = [
        finding
        for record in validations
        for finding in record.findings
        if finding.approved_at is not None and finding.explanation
    ]
    current_execution_evidence = bool(attempts) and state.lifecycle.execution in {"passed", "failed", "review_required"}
    execution_body = (
        f"Generated R was executed in the isolated runner. {len(attempts)} immutable attempt(s) are recorded; "
        f"latest status: {attempts[-1].status}."
        if current_execution_evidence
        else (
            "The current generated R and SAS programs have not been executed against raw study datasets. "
            f"{len(attempts)} prior immutable attempt(s) are retained as historical evidence for earlier programs."
            if attempts
            else "Generated R and SAS programs were not executed against raw study datasets. No execution evidence is available."
        )
    )
    execution_todos = (
        []
        if current_execution_evidence and attempts[-1].status == "passed"
        else ["Execute the approved R program against the intended synthetic/de-identified raw datasets and review all output checks."]
    )
    current_validation_evidence = bool(validations) and state.lifecycle.validation != "not_run"
    if current_validation_evidence:
        validation_body = (
            "The records below are the validation evidence associated with the current programs. Finding counts are "
            "informational until every finding is reviewed and dispositioned."
        )
    elif validations:
        validation_body = (
            f"No standards validation applies to the current programs. {len(validations)} prior validation record(s) "
            "are retained as historical evidence for earlier programs."
        )
    else:
        validation_body = (
            "External standards validation was not run and no validation report was imported. Internal execution "
            "checks, if any, are not a substitute for standards validation."
        )
    validation_todos = (
        []
        if current_validation_evidence
        else ["Run a qualified external validator or import a supported Pinnacle 21 report, then review and disposition its findings."]
    )
    current_approved = approved if current_validation_evidence else []
    unresolved = (
        [finding for record in validations for finding in record.findings if finding.finding_status == "open"]
        if current_validation_evidence
        else []
    )
    standard_versions = sorted(
        {finding.standard_version for record in validations for finding in record.findings if finding.standard_version}
    )
    terminology_versions = sorted(
        {
            finding.controlled_terminology_version
            for record in validations
            for finding in record.findings
            if finding.controlled_terminology_version
        }
    )
    standards_rows = [
        ["SDTM Implementation Guide", plan.standard, "Approved mapping baseline"],
        ["Define-XML", plan.define_standard, "Draft metadata exchange baseline"],
        ["Validation standard", ", ".join(standard_versions) or "Not reported", "Imported validation evidence" if standard_versions else "Confirmation required"],
        ["Controlled terminology", ", ".join(terminology_versions) or "Not reported", "Imported validation evidence" if terminology_versions else "Confirmation required"],
        ["R", "Generated per domain", "Executable only in the isolated runner after human initiation"],
        ["SAS", "Generated per domain", "Export-only; not executed by the Workbench"],
    ]
    study_rows = [["Study identifier", plan.study_name], ["Submission content", "SDTM tabulation metadata and programs"]]
    study_rows.extend(
        [key.replace("_", " ").title(), value]
        for key, value in sorted(state.inputs.study_metadata.items())
        if value
    )
    raw_rows = [
        [item.logical_name, item.original_name, item.format.upper(), str(item.row_count) if item.row_count is not None else "Not profiled", str(len(item.columns))]
        for item in state.inputs.raw_datasets
    ]
    mapping_rows = [
        [item.source_dataset, item.source_type.upper(), item.relationship.title(), item.target_domain, item.rationale]
        for item in plan.domain_mappings
    ]
    mapping_rows.extend([item.source_dataset, "SOURCE", "Unmapped", "-", item.rationale] for item in plan.unmapped_datasets)
    domain_rows = [
        [item.domain, item.description, item.dataset_class, item.structure, ", ".join(item.key_variables) or "Not specified", str(len(item.variables))]
        for item in plan.datasets
    ]
    special_notes: list[str] = []
    for dataset in plan.datasets:
        value_level_count = sum(len(variable.value_level_metadata) for variable in dataset.variables)
        commented_count = sum(bool(variable.comment) for variable in dataset.variables)
        derived_count = sum(variable.origin.lower() == "derived" for variable in dataset.variables)
        details = []
        if value_level_count:
            details.append(f"{value_level_count} value-level metadata row(s)")
        if derived_count:
            details.append(f"{derived_count} derived variable(s)")
        if commented_count:
            details.append(f"{commented_count} variable comment(s)")
        if details:
            special_notes.append(f"{dataset.domain}: " + "; ".join(details) + ".")
    validation_rows = [
        [record.provider, record.provider_version, record.status, str(len(record.findings)), _format_datetime(record.created_at)]
        for record in validations
    ]
    approved_rows = [
        [item.dataset or "General", item.rule_id, item.severity, item.message, item.explanation or "", item.reviewer or "Not recorded", _format_datetime(item.approved_at) if item.approved_at else "Not approved"]
        for item in current_approved
    ]
    unresolved_rows = [
        [item.dataset or "General", item.variable or "-", item.rule_id, item.severity, item.message]
        for item in unresolved
    ]
    execution_rows = [
        [item.attempt_id, item.status, _format_datetime(item.created_at), str(len(item.input_manifest)), str(len(item.outputs)), str(sum(check.status == "failed" for check in item.checks))]
        for item in attempts
    ]
    trial_domains = [item for item in plan.datasets if item.domain.upper() in {"TA", "TE", "TI", "TS", "TV"}]
    relationship_rows = [
        [item.source_dataset, item.relationship.title(), item.target_domain, item.rationale]
        for item in plan.domain_mappings
        if item.relationship != "direct"
    ]
    limitations = state.limitations or ["This is a draft generated from reviewed metadata and recorded evidence."]
    sections = [
        CSDRGSection(
            heading="1. Introduction and standards inventory",
            body=(
                "This guide supplies reviewer context for the tabulation datasets and terminology that is not fully "
                "expressed in Define-XML. It also summarizes conversion, program execution, validation evidence, "
                "finding dispositions, and known limitations."
            ),
            tables=[CSDRGTable(title="Standards and software inventory", columns=["Standard or software", "Version or state", "Use"], rows=standards_rows)],
            todos=["Confirm the exact SDTMIG, SDTM, and controlled terminology package versions with the study team."],
        ),
        CSDRGSection(
            heading="2. Study and submission overview",
            body=(
                f"Study: {plan.study_name}. This draft supports review and evidence collection; it does not certify "
                "conformance or submission readiness. Protocol design details are shown only when supplied as reviewed study metadata."
            ),
            tables=[CSDRGTable(title="Study metadata", columns=["Attribute", "Value"], rows=study_rows)],
            todos=[] if state.inputs.study_metadata else ["Add reviewed protocol title, phase, design, and amendment history when available."],
        ),
        CSDRGSection(
            heading="3. Source data and conversion approach",
            body=(
                "Mappings and expressions were human-reviewed before deterministic per-domain R and SAS generation. "
                "Relationship types distinguish direct mappings, stacks, joins, splits, and derived domains. SAS is export-only."
            ),
            tables=[
                CSDRGTable(title="Raw dataset inventory", columns=["Logical name", "Original file", "Format", "Rows", "Columns"], rows=raw_rows),
                CSDRGTable(title="Source-to-SDTM mapping inventory", columns=["Source", "Source type", "Relationship", "Target", "Rationale"], rows=mapping_rows),
            ],
            evidence_controlled=True,
        ),
        CSDRGSection(
            heading="4. Dataset descriptions and special considerations",
            body="\n".join(special_notes) or "No additional dataset-specific special considerations are recorded in the approved mapping metadata.",
            tables=[CSDRGTable(title="Submitted dataset inventory", columns=["Dataset", "Label", "Class", "Structure", "Keys", "Variables"], rows=domain_rows)],
        ),
        CSDRGSection(
            heading="5. Conformance and validation summary",
            body=validation_body,
            tables=[CSDRGTable(title="Validation inputs", columns=["Provider", "Version", "Status", "Findings", "Created"], rows=validation_rows)],
            todos=validation_todos,
            evidence_controlled=True,
        ),
        CSDRGSection(
            heading="6. Reviewer-approved explanations",
            body=(
                "Only explanations with explicit reviewer identity and approval time are included below.\n"
                + "\n".join(f"{item.rule_id} ({item.dataset or 'General'}): {item.explanation}" for item in current_approved)
                if approved_rows
                else "No reviewer-approved finding explanations are available for the current programs."
            ),
            tables=[CSDRGTable(title="Approved finding explanations", columns=["Dataset", "Rule", "Severity", "Diagnostic message", "Explanation", "Reviewer", "Approved"], rows=approved_rows)],
            evidence_controlled=True,
        ),
        CSDRGSection(
            heading="7. Unresolved issues",
            body="The following imported findings remain open for the current programs." if unresolved_rows else "No open imported findings are currently recorded.",
            tables=[CSDRGTable(title="Open validation findings", columns=["Dataset", "Variable", "Rule", "Severity", "Diagnostic message"], rows=unresolved_rows)],
            todos=["Resolve every open finding and obtain reviewer approval for explanations used in the final guide."] if unresolved else [],
            evidence_controlled=True,
        ),
        CSDRGSection(
            heading="8. Trial design and relationships",
            body="Trial-design datasets in the approved plan: " + ", ".join(item.domain for item in trial_domains) + "." if trial_domains else "No trial-design domains are present in the approved plan.",
            tables=[CSDRGTable(title="Non-direct dataset relationships", columns=["Source", "Relationship", "Target", "Rationale"], rows=relationship_rows)],
            todos=[] if trial_domains else ["Add trial-design domain and relationship notes when applicable."],
        ),
        CSDRGSection(
            heading="9. Software, execution, and traceability",
            body=execution_body,
            tables=[CSDRGTable(title="Immutable execution attempts", columns=["Attempt", "Status", "Created", "Inputs", "Outputs", "Failed checks"], rows=execution_rows)],
            todos=execution_todos,
            evidence_controlled=True,
        ),
        CSDRGSection(heading="10. Limitations", body="\n".join(limitations), evidence_controlled=True),
    ]
    return CSDRGDocument(study_name=plan.study_name, sections=sections, limitations=[DISCLAIMER], generated_at=datetime.now(timezone.utc))


def render_csdrg(job_dir: Path, plan: SDTMPlan, output_dir: Path | None = None) -> list[Path]:
    target = output_dir or (job_dir / "output")
    target.mkdir(parents=True, exist_ok=True)
    return render_csdrg_document(build_csdrg(job_dir, plan), target)


def render_csdrg_document(document: CSDRGDocument, target: Path) -> list[Path]:
    target.mkdir(parents=True, exist_ok=True)
    json_path = target / "csdrg.json"
    json_path.write_text(document.model_dump_json(indent=2), encoding="utf-8")
    markdown_path = target / "csdrg.md"
    lines = [f"# {document.title}", "", f"> {DISCLAIMER}", "", f"Study: **{document.study_name}**", ""]
    for section in document.sections:
        lines.extend([f"## {section.heading}", "", section.body, ""])
        for table in section.tables:
            if table.title:
                lines.extend([f"### {table.title}", ""])
            lines.extend(_markdown_table(table) if table.rows else ["No records.", ""])
        if section.todos:
            lines.extend(["### TODO", "", *[f"- {item}" for item in section.todos], ""])
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    pdf_path = target / "csdrg.pdf"
    _render_csdrg_pdf(document, pdf_path)
    return [json_path, markdown_path, pdf_path]


def _markdown_table(table: CSDRGTable) -> list[str]:
    def cell(value: str) -> str:
        return value.replace("|", "\\|").replace("\r", " ").replace("\n", "<br>")

    result = ["| " + " | ".join(cell(value) for value in table.columns) + " |"]
    result.append("| " + " | ".join("---" for _ in table.columns) + " |")
    result.extend("| " + " | ".join(cell(value) for value in row) + " |" for row in table.rows)
    result.append("")
    return result


def _format_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


class _CSDRGDocTemplate(SimpleDocTemplate):
    def afterFlowable(self, flowable):  # noqa: N802 - ReportLab callback name
        if isinstance(flowable, Paragraph) and flowable.style.name == "CSDRGHeading1" and flowable.getPlainText() != "Contents":
            self.notify("TOCEntry", (0, flowable.getPlainText(), self.page))


def _numbered_canvas_factory(study_name: str):
    class NumberedCanvas(canvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._saved_page_states = []

        def showPage(self):  # noqa: N802 - ReportLab callback name
            self._saved_page_states.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            page_count = len(self._saved_page_states)
            for state in self._saved_page_states:
                self.__dict__.update(state)
                self.setFont("Helvetica", 8)
                self.setFillColor(colors.HexColor("#4B5563"))
                self.drawCentredString(letter[0] / 2, 0.45 * inch, f"Page {self._pageNumber} of {page_count}")
                super().showPage()
            super().save()

    NumberedCanvas.__name__ = f"CSDRGCanvas_{study_name}"
    return NumberedCanvas


def _render_csdrg_pdf(document: CSDRGDocument, path: Path) -> None:
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="CSDRGTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=23, leading=28, textColor=colors.HexColor("#172554"), alignment=TA_CENTER, spaceAfter=18))
    styles.add(ParagraphStyle(name="CSDRGHeading1", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=14, leading=18, textColor=colors.HexColor("#172554"), spaceBefore=8, spaceAfter=8, keepWithNext=True))
    styles.add(ParagraphStyle(name="CSDRGTableTitle", parent=styles["Heading3"], fontName="Helvetica-Bold", fontSize=10, leading=13, textColor=colors.HexColor("#1E3A8A"), spaceBefore=8, spaceAfter=5, keepWithNext=True))
    styles.add(ParagraphStyle(name="CSDRGBody", parent=styles["BodyText"], fontName="Helvetica", fontSize=9.5, leading=14, textColor=colors.HexColor("#1F2937"), alignment=TA_LEFT, spaceAfter=7))
    styles.add(ParagraphStyle(name="CSDRGSmall", parent=styles["BodyText"], fontName="Helvetica", fontSize=7.4, leading=9.2, textColor=colors.HexColor("#111827")))
    doc = _CSDRGDocTemplate(str(path), pagesize=letter, rightMargin=0.58 * inch, leftMargin=0.58 * inch, topMargin=0.72 * inch, bottomMargin=0.72 * inch, title=document.title, author="Clinical AI Artifact Workbench", subject=f"Draft cSDRG for {document.study_name}")
    story = [Spacer(1, 1.1 * inch), Paragraph(_pdf_text(document.title), styles["CSDRGTitle"]), Spacer(1, 0.2 * inch)]
    story.append(Paragraph(_pdf_text(document.study_name), ParagraphStyle(name="CoverStudy", parent=styles["Heading2"], alignment=TA_CENTER, textColor=colors.HexColor("#334155"))))
    story.append(Spacer(1, 0.45 * inch))
    notice = Table([[Paragraph(f"<b>DRAFT STATUS</b><br/>{_pdf_text(DISCLAIMER)}", styles["CSDRGBody"])]], colWidths=[6.45 * inch])
    notice.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFF7ED")), ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#C2410C")), ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12), ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 10)]))
    story.extend([notice, Spacer(1, 0.35 * inch)])
    story.append(Paragraph(_pdf_text(f"Generated: {document.generated_at.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"), ParagraphStyle(name="CoverDate", parent=styles["BodyText"], alignment=TA_CENTER, textColor=colors.HexColor("#64748B"))))
    story.extend([PageBreak(), Paragraph("Contents", styles["CSDRGHeading1"])])
    toc = TableOfContents()
    toc.levelStyles = [ParagraphStyle(name="TOCLevel1", fontName="Helvetica", fontSize=9.5, leading=15, leftIndent=8, firstLineIndent=-8, textColor=colors.HexColor("#1F2937"))]
    story.extend([toc, PageBreak()])
    for section in document.sections:
        story.append(Paragraph(_pdf_text(section.heading), styles["CSDRGHeading1"]))
        for paragraph in section.body.split("\n"):
            if paragraph.strip():
                story.append(Paragraph(_pdf_text(paragraph), styles["CSDRGBody"]))
        for table in section.tables:
            if table.title:
                story.append(Paragraph(_pdf_text(table.title), styles["CSDRGTableTitle"]))
            if table.rows:
                story.extend([_pdf_table(table, doc.width, styles["CSDRGSmall"]), Spacer(1, 8)])
            else:
                story.append(Paragraph("No records.", styles["CSDRGBody"]))
        if section.todos:
            todo_content = [Paragraph("<b>Review actions</b>", styles["CSDRGBody"])]
            todo_content.extend(Paragraph(f"- {_pdf_text(item)}", styles["CSDRGBody"]) for item in section.todos)
            todo_table = Table([[todo_content]], colWidths=[doc.width])
            todo_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EFF6FF")), ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#93C5FD")), ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9), ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
            story.append(KeepTogether(todo_table))
        story.append(Spacer(1, 10))

    def header_footer(canv, _doc):
        if _doc.page <= 1:
            return
        canv.saveState()
        canv.setStrokeColor(colors.HexColor("#CBD5E1"))
        canv.setLineWidth(0.5)
        canv.line(0.58 * inch, letter[1] - 0.48 * inch, letter[0] - 0.58 * inch, letter[1] - 0.48 * inch)
        canv.setFont("Helvetica", 8)
        canv.setFillColor(colors.HexColor("#475569"))
        canv.drawString(0.58 * inch, letter[1] - 0.36 * inch, _pdf_plain(document.study_name)[:70])
        canv.drawRightString(letter[0] - 0.58 * inch, letter[1] - 0.36 * inch, "Study Data Reviewer's Guide")
        canv.restoreState()

    doc.multiBuild(story, onFirstPage=header_footer, onLaterPages=header_footer, canvasmaker=_numbered_canvas_factory(document.study_name))


def _pdf_table(table: CSDRGTable, available_width: float, cell_style: ParagraphStyle) -> Table:
    values = [table.columns, *table.rows]
    data = [[Paragraph(f"<b>{_pdf_text(value)}</b>" if row_index == 0 else _pdf_text(value), cell_style) for value in row] for row_index, row in enumerate(values)]
    weights = []
    for column_index, heading in enumerate(table.columns):
        lengths = [len(heading), *[len(row[column_index]) for row in table.rows]]
        weights.append(min(max(max(lengths, default=12), 12), 34))
    total = sum(weights) or 1
    result = Table(data, colWidths=[available_width * weight / total for weight in weights], repeatRows=1, hAlign="LEFT")
    result.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E2E8F0")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#0F172A")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#94A3B8")), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]), ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    return result


def _pdf_text(value: str) -> str:
    return escape(_pdf_plain(value))


def _pdf_plain(value: str) -> str:
    return str(value).replace("\u2014", "-").replace("\u2013", "-").replace("\u2011", "-")
