from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

from .schemas import DISCLAIMER, SDTMPlan
from .schemas.validation import CSDRGDocument, CSDRGSection
from .sdtm_execution import list_attempts
from .sdtm_validation import list_validations
from .sdtm_workbench import read_state


def build_csdrg(job_dir: Path, plan: SDTMPlan) -> CSDRGDocument:
    state = read_state(job_dir)
    attempts = list_attempts(job_dir)
    validations = list_validations(job_dir)
    approved = [finding for record in validations for finding in record.findings if finding.approved_at is not None and finding.explanation]
    raw_names = ", ".join(item.logical_name for item in state.inputs.raw_datasets) or "None supplied"
    current_execution_evidence = bool(attempts) and state.lifecycle.execution in {"passed", "failed", "review_required"}
    execution_body = (
        f"Generated R was executed in the isolated runner. {len(attempts)} immutable attempt(s) are recorded; latest status: {attempts[-1].status}."
        if current_execution_evidence else
        (
            f"The current generated R and SAS programs have not been executed against raw study datasets. "
            f"{len(attempts)} prior immutable attempt(s) are retained as historical evidence for earlier programs."
            if attempts else
            "Generated R and SAS programs were not executed against raw study datasets. No execution evidence is available."
        )
    )
    execution_todos = [] if current_execution_evidence and attempts[-1].status == "passed" else ["Execute the approved R program against the intended synthetic/de-identified raw datasets and review all output checks."]
    current_validation_evidence = bool(validations) and state.lifecycle.validation != "not_run"
    if current_validation_evidence:
        validation_body = "\n".join(f"{record.provider} {record.provider_version}: {record.status}; {len(record.findings)} finding(s)." for record in validations)
    elif validations:
        validation_body = f"No standards validation applies to the current programs. {len(validations)} prior validation record(s) are retained as historical evidence for earlier programs."
    else:
        validation_body = "External standards validation was not run and no validation report was imported. Internal execution checks, if any, are not a substitute for standards validation."
    validation_todos = [] if current_validation_evidence else ["Run a qualified external validator or import a supported Pinnacle 21 report, then review and disposition its findings."]
    current_approved = approved if current_validation_evidence else []
    explanation_text = "\n".join(f"{item.rule_id} ({item.dataset or 'general'}): {item.explanation} — approved by {item.reviewer} at {item.approved_at.isoformat()}" for item in current_approved) or "No reviewer-approved finding explanations are available for the current programs."
    unresolved = [finding for record in validations for finding in record.findings if finding.finding_status == "open"] if current_validation_evidence else []
    sections = [
        CSDRGSection(heading="1. Study and submission overview", body=f"Study: {plan.study_name}. This draft supports review and evidence collection; it does not certify conformance or submission readiness."),
        CSDRGSection(heading="2. Standards and controlled terminology", body=f"Planned standard: {plan.standard}; metadata exchange: {plan.define_standard}. Controlled terminology versions are retained from imported validation evidence when reported.", todos=["Confirm the exact SDTMIG, SDTM, and controlled terminology package versions with the study team."]),
        CSDRGSection(heading="3. Source data and conversion approach", body=f"Raw dataset inventory: {raw_names}. Mappings and expressions were human-reviewed before deterministic R/SAS generation. SAS is export-only and was not executed."),
        CSDRGSection(heading="4. Dataset descriptions and special considerations", body="\n".join(f"{item.domain}: {item.description}; structure: {item.structure}; keys: {', '.join(item.key_variables)}." for item in plan.datasets)),
        CSDRGSection(heading="5. Conformance and validation summary", body=validation_body, todos=validation_todos),
        CSDRGSection(heading="6. Reviewer-approved explanations", body=explanation_text),
        CSDRGSection(heading="7. Unresolved issues", body="\n".join(f"{item.rule_id}: {item.message}" for item in unresolved) or "No open imported findings are currently recorded.", todos=["Resolve every open finding and obtain reviewer approval for explanations used in the final guide."] if unresolved else []),
        CSDRGSection(heading="8. Trial design and relationships", body="Trial-design and cross-domain relationship notes are included only when present in the approved mapping metadata.", todos=["Add trial-design domain and relationship notes when applicable."]),
        CSDRGSection(heading="9. Software, execution, and traceability", body=execution_body, todos=execution_todos),
        CSDRGSection(heading="10. Limitations", body="\n".join(state.limitations or ["This is a draft generated from reviewed metadata and recorded evidence."])),
    ]
    return CSDRGDocument(study_name=plan.study_name, sections=sections, limitations=[DISCLAIMER], generated_at=datetime.now(timezone.utc))


def render_csdrg(job_dir: Path, plan: SDTMPlan, output_dir: Path | None = None) -> list[Path]:
    target = output_dir or (job_dir / "output")
    target.mkdir(parents=True, exist_ok=True)
    document = build_csdrg(job_dir, plan)
    return render_csdrg_document(document, target)


def render_csdrg_document(document: CSDRGDocument, target: Path) -> list[Path]:
    target.mkdir(parents=True, exist_ok=True)
    json_path = target / "csdrg.json"
    json_path.write_text(document.model_dump_json(indent=2), encoding="utf-8")
    markdown_path = target / "csdrg.md"
    lines = [f"# {document.title}", "", f"> {DISCLAIMER}", "", f"Study: **{document.study_name}**", ""]
    for section in document.sections:
        lines.extend([f"## {section.heading}", "", section.body, ""])
        if section.todos:
            lines.extend(["### TODO", "", *[f"- {item}" for item in section.todos], ""])
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    pdf_path = target / "csdrg.pdf"
    styles = getSampleStyleSheet()
    story = [Paragraph(escape(document.title), styles["Title"]), Paragraph(escape(f"Study: {document.study_name}"), styles["Heading2"]), Paragraph(escape(DISCLAIMER), styles["BodyText"]), PageBreak()]
    for section in document.sections:
        story.extend([Paragraph(escape(section.heading), styles["Heading2"]), Paragraph(escape(section.body).replace("\n", "<br/>"), styles["BodyText"]), Spacer(1, 10)])
        for todo in section.todos:
            story.append(Paragraph(f"<b>TODO:</b> {escape(todo)}", styles["BodyText"]))
        story.append(Spacer(1, 12))
    SimpleDocTemplate(str(pdf_path), pagesize=letter, title=document.title, author="Clinical AI Artifact Workbench").build(story)
    return [json_path, markdown_path, pdf_path]

