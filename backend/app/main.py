from __future__ import annotations

import json
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from mcp import Client as MCPClient
from reportlab.pdfgen import canvas
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .agents import AGENTS, get_agent
from .artifacts import artifact_record
from .config import get_settings
from .db import get_db, initialize_database
from .jobs import runner
from .models import Artifact, Job
from .parsers import parse_source
from .schemas import AgentEventRead, AgentProgressRead, AgentRead, ArtifactRead, CDISCDatasetRead, DISCLAIMER, HealthRead, JobList, JobRead, JobResultUpdate, UseCaseRead
from .security import detect_identifiers, validate_upload_metadata, verify_signature
from .use_cases import USE_CASES, get_use_case
from .workflows import DOCUMENT_TYPES, WORKFLOWS, WorkflowService


settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.ensure_directories()
    initialize_database()
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Draft clinical artifact generation for synthetic or de-identified hackathon data.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)


@app.get(f"{settings.api_prefix}/health", response_model=HealthRead)
def health(db: Session = Depends(get_db)) -> HealthRead:
    database = "ok"
    try:
        db.execute(select(func.count(Job.id))).scalar_one()
    except Exception:
        database = "error"
    storage = "ok" if settings.jobs_dir.exists() and settings.jobs_dir.is_dir() else "error"
    overall = "ok" if database == "ok" and storage == "ok" else "degraded"
    return HealthRead(
        status=overall,
        database=database,
        storage=storage,
        meta_configured=settings.meta_configured,
        meta_base_url=settings.meta_api_base_url,
        meta_model=settings.meta_model or None,
    )


@app.get(f"{settings.api_prefix}/use-cases", response_model=list[UseCaseRead])
def list_use_cases() -> list[UseCaseRead]:
    """Discover every supported skill/API use case from the shared registry."""

    return [UseCaseRead.model_validate(use_case.public_definition()) for use_case in USE_CASES.values()]


@app.get(f"{settings.api_prefix}/use-cases/{{use_case_id}}", response_model=UseCaseRead)
def read_use_case(use_case_id: str) -> UseCaseRead:
    try:
        use_case = get_use_case(use_case_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Use case not found.") from exc
    return UseCaseRead.model_validate(use_case.public_definition())


@app.get(
    f"{settings.api_prefix}/standards/sdtm/datasets/{{domain}}",
    response_model=CDISCDatasetRead,
)
async def read_cdisc_sdtm_dataset(
    domain: str,
    version: str = Query("3-4", min_length=1, max_length=80),
    standard: Literal["sdtm", "sdtmig"] = Query("sdtmig"),
) -> CDISCDatasetRead:
    """Read one versioned SDTM dataset through the configured CDISC Library MCP service."""

    normalized_domain = domain.strip().upper()
    if not normalized_domain or len(normalized_domain) > 12 or not normalized_domain.isalnum():
        raise HTTPException(status_code=422, detail="Domain must be an alphanumeric SDTM dataset identifier.")
    if not settings.cdisc_mcp_enabled:
        raise HTTPException(status_code=503, detail="CDISC Library integration is disabled.")
    try:
        async with MCPClient(settings.cdisc_mcp_url) as client:
            result = await client.call_tool(
                "cdisc_get_dataset",
                {"standard": standard, "version": version.strip(), "dataset": normalized_domain},
            )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="The configured CDISC Library service could not retrieve this dataset.",
        ) from exc
    if result.is_error:
        raise HTTPException(status_code=502, detail="CDISC Library rejected the dataset request.")
    payload = result.structured_content
    if payload is None:
        content = [item.model_dump(exclude_none=True) for item in result.content]
        if len(content) == 1 and content[0].get("type") == "text":
            try:
                payload = json.loads(str(content[0].get("text", "")))
            except json.JSONDecodeError:
                payload = content
        else:
            payload = content
    if isinstance(payload, dict) and set(payload) == {"result"}:
        payload = payload["result"]
    if not isinstance(payload, (dict, list)):
        raise HTTPException(status_code=502, detail="CDISC Library returned an unsupported dataset payload.")
    return CDISCDatasetRead(
        standard=standard,
        version=version.strip(),
        domain=normalized_domain,
        payload=payload,
    )


@app.get(f"{settings.api_prefix}/agents", response_model=list[AgentRead])
def list_agents() -> list[AgentRead]:
    """List the five tool-driven agents that execute the registered use cases."""

    return [
        AgentRead.model_validate(agent.public_definition(settings.agent_max_turns))
        for agent in AGENTS.values()
    ]


@app.get(f"{settings.api_prefix}/agents/{{workflow}}", response_model=AgentRead)
def read_agent(workflow: str) -> AgentRead:
    try:
        agent = get_agent(workflow)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Agent not found.") from exc
    return AgentRead.model_validate(agent.public_definition(settings.agent_max_turns))


@app.get(f"{settings.api_prefix}/samples/{{sample_name}}")
def download_sample(sample_name: str) -> FileResponse:
    allowed = {
        "synthetic-protocol.md": "synthetic-protocol.md",
        "edc-specification.json": "edc-specification.json",
        "synthetic-sap.md": "synthetic-sap.md",
        "adam-metadata.json": "adam-metadata.json",
        "blank-crf.pdf": "blank-crf.pdf",
    }
    filename = allowed.get(sample_name)
    if filename is None:
        raise HTTPException(status_code=404, detail="Sample not found.")
    if filename == "blank-crf.pdf":
        path = settings.data_dir / "samples" / filename
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            _write_sample_crf(path)
    else:
        path = Path(__file__).parent / "sample_data" / filename
    return FileResponse(path, filename=filename)


@app.post(f"{settings.api_prefix}/jobs/{{workflow}}", response_model=JobRead, status_code=status.HTTP_202_ACCEPTED)
async def create_job(
    workflow: str,
    options: str = Form("{}"),
    files: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
) -> JobRead:
    if workflow not in WORKFLOWS:
        raise HTTPException(status_code=404, detail="Unknown workflow.")
    if not settings.meta_configured:
        raise HTTPException(status_code=503, detail="Meta API key and model are not configured.")
    try:
        parsed_options = json.loads(options)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="The options field must contain valid JSON.") from exc
    if not isinstance(parsed_options, dict):
        raise HTTPException(status_code=422, detail="The options field must contain a JSON object.")
    if parsed_options.get("deidentified_acknowledged") is not True:
        raise HTTPException(status_code=422, detail="Synthetic/de-identified data acknowledgement is required.")
    _validate_required_inputs(workflow, files, parsed_options)

    title = str(parsed_options.get("title") or _default_title(workflow, parsed_options))[:240]
    job = Job(
        workflow=workflow,
        title=title,
        status="queued",
        options_json=json.dumps(parsed_options),
        model_name=settings.meta_model,
    )
    db.add(job)
    db.flush()
    job_dir = settings.jobs_dir / job.id
    input_dir = job_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=False)
    saved_names: list[str] = []
    try:
        for index, upload in enumerate(files):
            safe_name = validate_upload_metadata(upload)
            unique_name = f"{index + 1:02d}-{safe_name}"
            destination = input_dir / unique_name
            await _save_limited(upload, destination)
            verify_signature(destination)
            source_text = parse_source(destination)
            identifiers = detect_identifiers(source_text)
            if identifiers:
                raise HTTPException(
                    status_code=422,
                    detail=f"Potential direct identifiers detected in {safe_name}: {', '.join(identifiers)}. Remove them before upload.",
                )
            saved_names.append(unique_name)
        study_brief = str(parsed_options.get("study_brief", ""))
        identifiers = detect_identifiers(study_brief)
        if identifiers:
            raise HTTPException(status_code=422, detail=f"Potential direct identifiers detected in the study brief: {', '.join(identifiers)}.")
        job.input_files_json = json.dumps(saved_names)
        db.commit()
        db.refresh(job)
    except Exception:
        db.rollback()
        shutil.rmtree(job_dir, ignore_errors=True)
        raise
    runner.enqueue(job.id)
    return _job_read(job)


@app.get(f"{settings.api_prefix}/jobs", response_model=JobList)
def list_jobs(
    workflow: str | None = None,
    job_status: str | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> JobList:
    filters = []
    if workflow:
        filters.append(Job.workflow == workflow)
    if job_status:
        filters.append(Job.status == job_status)
    total = db.scalar(select(func.count(Job.id)).where(*filters)) or 0
    jobs = db.scalars(
        select(Job)
        .where(*filters)
        .order_by(Job.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return JobList(items=[_job_read(job, include_result=False) for job in jobs], total=total, page=page, page_size=page_size)


@app.get(f"{settings.api_prefix}/jobs/{{job_id}}", response_model=JobRead)
def get_job(job_id: str, db: Session = Depends(get_db)) -> JobRead:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return _job_read(job)


@app.get(f"{settings.api_prefix}/jobs/{{job_id}}/agent", response_model=AgentProgressRead)
def get_job_agent_progress(job_id: str, db: Session = Depends(get_db)) -> AgentProgressRead:
    """Return a source-free summary of the specialist agent's persisted tool trace."""

    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    definition = get_agent(job.workflow)
    path = settings.jobs_dir / job.id / "agent" / "progress.json"
    if not path.is_file():
        return AgentProgressRead(
            agent_id=definition.id,
            workflow=job.workflow,
            status=job.status,
            turn=0,
            max_turns=settings.agent_max_turns,
            stage=None,
            stage_index=1,
            stage_count=1,
            completed_stages=[],
            total_source_chunks=0,
            read_source_chunks=[],
            events=[],
        )
    try:
        progress = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="The saved agent trace is unavailable.") from exc
    events = [
        AgentEventRead(
            turn=int(event.get("turn", 0)),
            type=str(event.get("type", "unknown")),
            name=str(event["name"]) if event.get("name") else None,
            stage=str(event["stage"]) if event.get("stage") else None,
            ok=event.get("ok") if isinstance(event.get("ok"), bool) else None,
            error=str(event["error"])[:500] if event.get("error") else None,
        )
        for event in progress.get("events", [])
        if isinstance(event, dict)
    ]
    return AgentProgressRead(
        agent_id=definition.id,
        workflow=job.workflow,
        status=str(progress.get("status", job.status)),
        turn=int(progress.get("turn", 0)),
        max_turns=int(progress.get("max_turns", settings.agent_max_turns)),
        stage=str(progress["stage"]) if progress.get("stage") else None,
        stage_index=int(progress.get("stage_index", 1)),
        stage_count=int(progress.get("stage_count", 1)),
        completed_stages=[str(item) for item in progress.get("completed_stages", [])],
        total_source_chunks=int(progress.get("total_source_chunks", 0)),
        read_source_chunks=[int(item) for item in progress.get("read_source_chunks", [])],
        events=events,
    )


@app.post(f"{settings.api_prefix}/jobs/{{job_id}}/retry", response_model=JobRead, status_code=status.HTTP_202_ACCEPTED)
def retry_job(job_id: str, db: Session = Depends(get_db)) -> JobRead:
    if not settings.meta_configured:
        raise HTTPException(status_code=503, detail="Meta API key and model are not configured.")
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.status in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="This job is already in progress.")
    output_dir = settings.jobs_dir / job_id / "output"
    shutil.rmtree(output_dir, ignore_errors=True)
    job.artifacts.clear()
    job.status = "queued"
    job.result_json = None
    job.warnings_json = "[]"
    job.error = None
    job.completed_at = None
    db.commit()
    db.refresh(job)
    runner.enqueue(job.id)
    return _job_read(job)


@app.put(f"{settings.api_prefix}/jobs/{{job_id}}/result", response_model=JobRead)
def update_job_result(job_id: str, update: JobResultUpdate, db: Session = Depends(get_db)) -> JobRead:
    """Validate a human revision and deterministically rebuild all downloadable artifacts."""

    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.status != "succeeded" or not job.result_json:
        raise HTTPException(status_code=409, detail="Only a completed job result can be revised.")

    serialized = json.dumps(update.result, ensure_ascii=False)
    identifiers = detect_identifiers(serialized)
    if identifiers:
        raise HTTPException(
            status_code=422,
            detail=f"Potential direct identifiers detected in the revised result: {', '.join(identifiers)}.",
        )

    job_dir = settings.jobs_dir / job.id
    inputs = [(job_dir / "input" / name).resolve() for name in json.loads(job.input_files_json)]
    options = json.loads(job.options_json)
    next_output = job_dir / f"output-next-{uuid4()}"
    current_output = job_dir / "output"
    backup_output = job_dir / f"output-backup-{uuid4()}"
    try:
        rendered = WorkflowService().render_revision(
            job.workflow,
            result=update.result,
            inputs=inputs,
            options=options,
            output_dir=next_output,
        )
    except Exception as exc:
        shutil.rmtree(next_output, ignore_errors=True)
        detail = getattr(exc, "errors", lambda: str(exc))()
        raise HTTPException(status_code=422, detail=detail) from exc

    try:
        if current_output.exists():
            current_output.rename(backup_output)
        next_output.rename(current_output)
        job.artifacts.clear()
        db.flush()
        for old_path in rendered.paths:
            final_path = current_output / old_path.relative_to(next_output)
            job.artifacts.append(Artifact(**artifact_record(final_path, job_dir)))
        job.result_json = json.dumps(rendered.result, ensure_ascii=False)
        job.warnings_json = json.dumps(
            [
                DISCLAIMER,
                "Result revised by a user and artifacts regenerated without another model call.",
                *rendered.warnings,
            ],
            ensure_ascii=False,
        )
        db.commit()
        db.refresh(job)
    except Exception:
        db.rollback()
        shutil.rmtree(current_output, ignore_errors=True)
        if backup_output.exists():
            backup_output.rename(current_output)
        raise
    finally:
        shutil.rmtree(next_output, ignore_errors=True)
        shutil.rmtree(backup_output, ignore_errors=True)
    return _job_read(job)


@app.get(f"{settings.api_prefix}/jobs/{{job_id}}/artifacts/{{artifact_id}}")
def download_artifact(job_id: str, artifact_id: str, db: Session = Depends(get_db)) -> FileResponse:
    artifact = db.scalar(select(Artifact).where(Artifact.id == artifact_id, Artifact.job_id == job_id))
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found.")
    path = _safe_artifact_path(job_id, artifact.relative_path)
    if not path.is_file():
        raise HTTPException(status_code=410, detail="Artifact file is no longer available.")
    return FileResponse(path, media_type=artifact.media_type, filename=artifact.name)


@app.get(f"{settings.api_prefix}/jobs/{{job_id}}/bundle")
def download_bundle(job_id: str, db: Session = Depends(get_db)) -> FileResponse:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    artifact = next((item for item in job.artifacts if item.name.endswith("-artifacts.zip")), None)
    if artifact is None:
        raise HTTPException(status_code=409, detail="A bundle is not available for this job yet.")
    path = _safe_artifact_path(job_id, artifact.relative_path)
    if not path.is_file():
        raise HTTPException(status_code=410, detail="Artifact bundle is no longer available.")
    return FileResponse(path, media_type="application/zip", filename=artifact.name)


@app.delete(f"{settings.api_prefix}/jobs/{{job_id}}", status_code=status.HTTP_204_NO_CONTENT)
def delete_job(job_id: str, db: Session = Depends(get_db)) -> None:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    db.delete(job)
    db.commit()
    shutil.rmtree(settings.jobs_dir / job_id, ignore_errors=True)


async def _save_limited(upload: UploadFile, destination: Path) -> None:
    limit = settings.max_file_mb * 1024 * 1024
    written = 0
    with destination.open("wb") as handle:
        while chunk := await upload.read(1024 * 1024):
            written += len(chunk)
            if written > limit:
                raise HTTPException(status_code=413, detail=f"Each file must be {settings.max_file_mb} MB or smaller.")
            handle.write(chunk)
    await upload.close()


def _validate_required_inputs(workflow: str, files: list[UploadFile], options: dict) -> None:
    use_case = get_use_case(workflow)
    filenames = [upload.filename or "" for upload in files]
    accepted = set(use_case.descriptor.accepted_extensions)
    unsupported = sorted(
        {Path(filename).suffix.lower() for filename in filenames}
        - accepted
    )
    if unsupported:
        raise HTTPException(status_code=415, detail=f"Unsupported file type for {workflow}: {', '.join(unsupported)}")
    try:
        use_case.validate_submission(filenames, options)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _default_title(workflow: str, options: dict) -> str:
    if workflow == "clinical-document":
        return DOCUMENT_TYPES.get(str(options.get("document_type")), "Clinical document")
    return workflow.replace("-", " ").title()


def _job_read(job: Job, include_result: bool = True) -> JobRead:
    result = json.loads(job.result_json) if include_result and job.result_json else None
    warnings = json.loads(job.warnings_json or "[]") if include_result else []
    artifacts = [
        ArtifactRead(
            id=item.id,
            name=item.name,
            media_type=item.media_type,
            size_bytes=item.size_bytes,
            sha256=item.sha256,
            download_url=f"{settings.api_prefix}/jobs/{job.id}/artifacts/{item.id}",
        )
        for item in job.artifacts
    ]
    return JobRead(
        id=job.id,
        workflow=job.workflow,
        title=job.title,
        status=job.status,
        model_name=job.model_name,
        created_at=job.created_at,
        updated_at=job.updated_at,
        completed_at=job.completed_at,
        result=result,
        warnings=warnings,
        error=job.error,
        artifacts=artifacts,
    )


def _safe_artifact_path(job_id: str, relative_path: str) -> Path:
    job_dir = (settings.jobs_dir / job_id).resolve()
    path = (job_dir / relative_path).resolve()
    if job_dir not in path.parents:
        raise HTTPException(status_code=400, detail="Invalid artifact path.")
    return path


def _write_sample_crf(path: Path) -> None:
    pdf = canvas.Canvas(str(path))
    pdf.setTitle("Synthetic blank CRF")
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(54, 760, "SYNTHETIC STUDY — DEMOGRAPHICS")
    pdf.setFont("Helvetica", 9)
    pdf.drawString(54, 742, "HACKATHON SAMPLE · NO PATIENT DATA")
    fields = [
        ("Subject Identifier", "DM.USUBJID"),
        ("Informed Consent Date", "DS.DSSTDTC"),
        ("Birth Year", "DM.BRTHDTC"),
        ("Age", "DM.AGE"),
        ("Sex", "DM.SEX"),
        ("Race", "DM.RACE"),
        ("Ethnicity", "DM.ETHNIC"),
    ]
    y = 690
    for label, hint in fields:
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(54, y, label)
        pdf.setFont("Helvetica", 8)
        pdf.drawRightString(540, y, f"Expected mapping: {hint}")
        pdf.line(54, y - 20, 540, y - 20)
        y -= 64
    pdf.showPage()
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(54, 760, "SYNTHETIC STUDY — VITAL SIGNS")
    y = 690
    for label in ["Visit Date", "Height", "Weight", "Systolic Blood Pressure", "Diastolic Blood Pressure", "Pulse Rate"]:
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(54, y, label)
        pdf.line(54, y - 20, 540, y - 20)
        y -= 64
    pdf.save()
