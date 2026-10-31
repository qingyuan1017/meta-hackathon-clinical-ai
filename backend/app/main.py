from __future__ import annotations

import json
import shutil
import wave
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from io import BytesIO
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
from .agents.runtime import verify_result
from .ai import AIResponseError, MetaAIClient
from .artifacts import artifact_record
from .config import get_settings
from .db import get_db, initialize_database
from .jobs import runner
from .models import Artifact, Job
from .parsers import parse_source
from .schemas import (
    AgentEventRead,
    AgentProgressRead,
    AgentRead,
    ArtifactRead,
    CDISCDatasetRead,
    DISCLAIMER,
    EDCSourceSpecificationUpdate,
    HealthRead,
    JobList,
    JobRead,
    JobResultUpdate,
    ReviewPatchDecision,
    ReviewFeedbackUpdate,
    ReviewScopeProposal,
    ReviewScopeProposalRequest,
    SDTMDomainMappingUpdate,
    SDTMDomainMappingPlan,
    SDTMDomainMappingReview,
    ExecutionAttempt,
    ExecutionAttemptList,
    RepairApproval,
    ValidationFinding,
    ValidationFindingUpdate,
    ValidationRecord,
    ValidationRunRequest,
    CSDRGDocument,
    SDTMPlan,
    SDTMVariableMappingUpdate,
    SDTMVariableMappingPlan,
    SDTMVariableMappingReview,
    TLFInventoryPlanUpdate,
    TLFProgrammingPlanUpdate,
    TLFShellPlanUpdate,
    UseCaseRead,
    VoiceTranscriptionRead,
)
from .security import detect_identifiers, validate_upload_metadata, verify_signature
from .sdtm_workbench import initialize_state, inventory_raw_dataset, read_state
from .sdtm_workbench import write_state
from .sdtm_execution import (
    RemoteRExecutionProvider,
    SDTMExecutionService,
    UnavailableRExecutionProvider,
    list_attempts,
    load_attempt,
    save_attempt,
    apply_typed_repair,
    ensure_repair_allowed,
)
from .sdtm_validation import (
    InternalChecksProvider,
    Pinnacle21CLIProvider,
    find_finding,
    import_pinnacle21_report,
    list_validations,
    save_validation,
    update_readiness,
)
from .csdrg import build_csdrg, render_csdrg, render_csdrg_document
from .sdtm_audit import refresh_evidence_bundle, refresh_evidence_manifest
from .review_patches import (
    load_patch_record,
    new_patch_request,
    propose_scope,
    public_patch,
    result_revision,
    three_way_merge,
    validate_scope,
    write_patch_record,
)
from .review_validation import validate_review_result
from .use_cases import USE_CASES, get_use_case
from .use_cases.sdtm import SDTMUseCase
from .use_cases.tlf import TLFUseCase
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
        meta_transcription_model=settings.meta_transcription_model or None,
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
        "synthetic-protocol.md": ("synthetic-protocol.md", "synthetic-protocol.md"),
        "edc-specification.json": ("edc-specification.json", "edc-specification.json"),
        "synthetic-sap.md": ("synthetic-sap.md", "synthetic-sap.md"),
        "adam-metadata.json": ("adam-metadata.json", "adam-metadata.json"),
        "blank-crf.pdf": ("blank-crf.pdf", "blank-crf.pdf"),
        "sdtm-demo-edc.json": ("sdtm-demo-edc.json", "sdtm-demo-edc.json"),
        "sdtm-raw-dm.csv": ("RAW_DM.csv", "RAW_DM.csv"),
        "sdtm-raw-ae.csv": ("RAW_AE.csv", "RAW_AE.csv"),
        "sdtm-raw-ae-mismatch.csv": ("RAW_AE-mismatch.csv", "RAW_AE.csv"),
        "pinnacle21-demo-report.csv": ("pinnacle21-demo-report.csv", "pinnacle21-demo-report.csv"),
    }
    selected = allowed.get(sample_name)
    if selected is None:
        raise HTTPException(status_code=404, detail="Sample not found.")
    source_name, download_name = selected
    if source_name == "blank-crf.pdf":
        path = settings.data_dir / "samples" / source_name
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_sample_crf(path)
    else:
        path = Path(__file__).parent / "sample_data" / source_name
    return FileResponse(path, filename=download_name)


@app.post(f"{settings.api_prefix}/jobs/{{workflow}}", response_model=JobRead, status_code=status.HTTP_202_ACCEPTED)
async def create_job(
    workflow: str,
    options: str = Form("{}"),
    files: list[UploadFile] = File(default=[]),
    raw_files: list[UploadFile] = File(default=[]),
    crf_file: UploadFile | None = File(default=None),
    validation_report: UploadFile | None = File(default=None),
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
    role_uploads: list[tuple[str, UploadFile]] = [("source", item) for item in files]
    if workflow == "sdtm":
        role_uploads.extend(("raw", item) for item in raw_files)
        if crf_file is not None:
            role_uploads.append(("crf", crf_file))
        if validation_report is not None:
            role_uploads.append(("validation", validation_report))
    elif raw_files or crf_file is not None or validation_report is not None:
        raise HTTPException(status_code=422, detail="Specialized SDTM uploads are only accepted for the SDTM workflow.")
    _validate_required_inputs(workflow, [item for _, item in role_uploads], parsed_options)

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
    input_roles: dict[str, list[str]] = {"source": [], "raw": [], "crf": [], "validation": []}
    raw_inventory = []
    try:
        raw_logical_names: set[str] = set()
        for index, (role, upload) in enumerate(role_uploads):
            safe_name = validate_upload_metadata(upload)
            prefix = "validation-" if role == "validation" else f"{index + 1:02d}-"
            unique_name = f"{prefix}{safe_name}"
            destination = input_dir / unique_name
            await _save_limited(upload, destination)
            verify_signature(destination)
            if role == "raw" or (role == "source" and destination.suffix.lower() in {".csv", ".xpt"}):
                role = "raw"
                try:
                    inventory = inventory_raw_dataset(destination, safe_name)
                except (OSError, UnicodeError, ValueError) as exc:
                    raise HTTPException(status_code=422, detail=str(exc)) from exc
                if inventory.logical_name in raw_logical_names:
                    raise HTTPException(status_code=422, detail=f"Duplicate raw dataset logical name: {inventory.logical_name}.")
                raw_logical_names.add(inventory.logical_name)
                raw_inventory.append(inventory)
            elif role != "validation":
                source_text = parse_source(destination)
                identifiers = detect_identifiers(source_text)
                if identifiers:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Potential direct identifiers detected in {safe_name}: {', '.join(identifiers)}. Remove them before upload.",
                    )
            saved_names.append(unique_name)
            input_roles[role].append(unique_name)
        study_brief = str(parsed_options.get("study_brief", ""))
        identifiers = detect_identifiers(study_brief)
        if identifiers:
            raise HTTPException(status_code=422, detail=f"Potential direct identifiers detected in the study brief: {', '.join(identifiers)}.")
        parsed_options["_input_roles"] = input_roles
        job.options_json = json.dumps(parsed_options, ensure_ascii=False)
        job.input_files_json = json.dumps(saved_names)
        if workflow == "sdtm":
            metadata_files = [
                name for name in input_roles["source"]
                if Path(name).suffix.lower() in {".json", ".xlsx"}
            ]
            initialize_state(
                job_dir,
                metadata_files=metadata_files,
                blank_crf=input_roles["crf"][0] if input_roles["crf"] else next((name for name in input_roles["source"] if Path(name).suffix.lower() == ".pdf"), None),
                raw_datasets=raw_inventory,
                validation_report=input_roles["validation"][0] if input_roles["validation"] else None,
                study_metadata={str(k): str(v) for k, v in parsed_options.get("study_metadata", {}).items()} if isinstance(parsed_options.get("study_metadata"), dict) else {},
            )
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
            model=settings.meta_model,
            turn=0,
            max_turns=settings.agent_max_turns,
            stage=None,
            stage_index=1,
            stage_count=1,
            completed_stages=[],
            total_source_chunks=0,
            read_source_chunks=[],
            started_at=None,
            updated_at=None,
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
            actor=event.get("actor") if event.get("actor") in {"agent", "user", "system"} else "agent",
            name=str(event["name"]) if event.get("name") else None,
            stage=str(event["stage"]) if event.get("stage") else None,
            ok=event.get("ok") if isinstance(event.get("ok"), bool) else None,
            error=str(event["error"])[:500] if event.get("error") else None,
            summary=str(event["summary"])[:4000] if event.get("summary") else None,
            intent=str(event["intent"])[:4000] if event.get("intent") else None,
            input_summary=str(event["input_summary"])[:4000] if event.get("input_summary") else None,
            output_summary=str(event["output_summary"])[:4000] if event.get("output_summary") else None,
            input_details=event.get("input_details") if isinstance(event.get("input_details"), dict) else {},
            output_details=event.get("output_details") if isinstance(event.get("output_details"), dict) else {},
            evidence=[str(item)[:500] for item in event.get("evidence", []) if isinstance(item, (str, int, float))],
            duration_ms=int(event["duration_ms"]) if isinstance(event.get("duration_ms"), (int, float)) else None,
            occurred_at=event.get("occurred_at"),
        )
        for event in progress.get("events", [])
        if isinstance(event, dict)
    ]
    return AgentProgressRead(
        agent_id=definition.id,
        workflow=job.workflow,
        status=str(progress.get("status", job.status)),
        model=str(progress["model"]) if progress.get("model") else settings.meta_model,
        turn=int(progress.get("turn", 0)),
        max_turns=int(progress.get("max_turns", settings.agent_max_turns)),
        stage=str(progress["stage"]) if progress.get("stage") else None,
        stage_index=int(progress.get("stage_index", 1)),
        stage_count=int(progress.get("stage_count", 1)),
        completed_stages=[str(item) for item in progress.get("completed_stages", [])],
        total_source_chunks=int(progress.get("total_source_chunks", 0)),
        read_source_chunks=[int(item) for item in progress.get("read_source_chunks", [])],
        started_at=progress.get("started_at"),
        updated_at=progress.get("updated_at"),
        events=events,
    )


@app.post(
    f"{settings.api_prefix}/jobs/{{job_id}}/feedback",
    response_model=JobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_review_feedback(
    job_id: str,
    update: ReviewFeedbackUpdate,
    db: Session = Depends(get_db),
) -> JobRead:
    """Record human guidance and rerun the current review stage without approving it."""

    if not settings.meta_configured:
        raise HTTPException(status_code=503, detail="Meta API key and model are not configured.")
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    options = json.loads(job.options_json)
    review_stage = options.get("_review_stage")
    if job.status != "review_required" or not isinstance(review_stage, str):
        raise HTTPException(status_code=409, detail="This job is not waiting for human review feedback.")

    if options.get("_pending_review_patch") or options.get("_review_patch_request"):
        raise HTTPException(status_code=409, detail="Decide the current review patch before requesting another revision.")
    message = update.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="Review feedback cannot be empty.")
    _reject_review_identifiers(message, "review feedback")
    if update.scope is None or update.current_result is None or update.baseline_revision is None:
        raise HTTPException(
            status_code=422,
            detail="Scoped feedback requires a confirmed scope, the current draft, and its server revision.",
        )
    stored_result = json.loads(job.result_json) if job.result_json else None
    if not isinstance(stored_result, dict):
        raise HTTPException(status_code=409, detail="This review stage has no structured draft to revise.")
    stored_revision = result_revision(stored_result)
    if update.baseline_revision != stored_revision:
        raise HTTPException(status_code=409, detail="The review draft changed. Reload it before requesting a revision.")
    try:
        current_result = validate_review_result(job.workflow, review_stage, update.current_result, options)
        validate_scope(review_stage, update.scope, current_result)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    submitted_at = datetime.now(timezone.utc).isoformat()
    request = new_patch_request(stage=review_stage, message=message, scope=update.scope, baseline=current_result)
    prior_feedback = options.get("review_feedback")
    feedback = list(prior_feedback) if isinstance(prior_feedback, list) else []
    feedback.append({
        "stage": review_stage,
        "message": message,
        "scope": update.scope.model_dump(mode="json"),
        "transaction_id": request["transaction_id"],
        "baseline_revision": request["baseline_revision"],
        "submitted_at": submitted_at,
    })
    options["review_feedback"] = feedback
    options["_review_revision_result"] = current_result
    options["_review_patch_request"] = request
    job.result_json = json.dumps(current_result, ensure_ascii=False)
    write_patch_record(settings.jobs_dir / job.id, {**request, "baseline": current_result})
    _append_user_feedback_event(job, review_stage, message, submitted_at, scope=update.scope.model_dump(mode="json"))
    return _resume_review(job, options, db, preserve_review_context=True)


@app.post(
    f"{settings.api_prefix}/jobs/{{job_id}}/feedback/scope",
    response_model=ReviewScopeProposal,
)
async def propose_review_feedback_scope(
    job_id: str,
    request: ReviewScopeProposalRequest,
    db: Session = Depends(get_db),
) -> ReviewScopeProposal:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    options = json.loads(job.options_json)
    stage = options.get("_review_stage")
    if job.status != "review_required" or not isinstance(stage, str):
        raise HTTPException(status_code=409, detail="This job is not waiting for human review feedback.")
    current = request.current_result or (json.loads(job.result_json) if job.result_json else None)
    if not isinstance(current, dict):
        raise HTTPException(status_code=409, detail="This review stage has no structured draft to scope.")
    scope, matched, explanation = propose_scope(stage, request.message, current)
    return ReviewScopeProposal(
        stage=stage,
        scope=scope,
        matched_terms=matched,
        requires_confirmation=True,
        explanation=explanation,
    )


@app.post(
    f"{settings.api_prefix}/jobs/{{job_id}}/feedback/{{transaction_id}}/decision",
    response_model=JobRead,
)
async def decide_review_patch(
    job_id: str,
    transaction_id: str,
    decision: ReviewPatchDecision,
    db: Session = Depends(get_db),
) -> JobRead:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    options = json.loads(job.options_json)
    pending = options.get("_pending_review_patch")
    if job.status != "review_required" or not isinstance(pending, dict) or pending.get("transaction_id") != transaction_id:
        raise HTTPException(status_code=409, detail="This review patch is not awaiting a decision.")
    stored_current = json.loads(job.result_json) if job.result_json else None
    if not isinstance(stored_current, dict):
        raise HTTPException(status_code=409, detail="The current review draft is unavailable.")
    current_revision = result_revision(stored_current)
    if decision.expected_revision != current_revision:
        raise HTTPException(status_code=409, detail="The review draft changed. Reload it before deciding this patch.")
    try:
        record = load_patch_record(settings.jobs_dir / job.id, transaction_id)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=500, detail="The saved review patch is unavailable.") from exc
    try:
        current = validate_review_result(job.workflow, str(pending.get("stage")), decision.current_result, options)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    now = datetime.now(timezone.utc).isoformat()
    if decision.approved:
        merged, conflicts = three_way_merge(record["baseline"], current, record["proposed"])
        if conflicts:
            record.update({"status": "conflict", "conflicts": conflicts, "decided_at": now, "reviewer": decision.reviewer})
            write_patch_record(settings.jobs_dir / job.id, record)
            options["_pending_review_patch"] = public_patch(record)
            job.options_json = json.dumps(options, ensure_ascii=False)
            db.commit()
            raise HTTPException(
                status_code=409,
                detail={"message": "The patch conflicts with newer edits and was not applied.", "conflicts": conflicts},
            )
        try:
            merged = validate_review_result(job.workflow, str(record["stage"]), merged, options)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        job.result_json = json.dumps(merged, ensure_ascii=False)
        record.update({"status": "approved", "conflicts": [], "decided_at": now, "reviewer": decision.reviewer})
        output_summary = "The scoped patch was approved and merged; untouched paths were preserved."
    else:
        job.result_json = json.dumps(current, ensure_ascii=False)
        record.update({"status": "rejected", "conflicts": [], "decided_at": now, "reviewer": decision.reviewer})
        output_summary = "The scoped patch was rejected; the current draft was not changed."
    write_patch_record(settings.jobs_dir / job.id, record)
    remaining_feedback = [
        item for item in options.get("review_feedback", [])
        if not isinstance(item, dict) or item.get("transaction_id") != transaction_id
    ]
    if remaining_feedback:
        options["review_feedback"] = remaining_feedback
    else:
        options.pop("review_feedback", None)
    options.pop("_pending_review_patch", None)
    options.pop("_review_patch_request", None)
    options.pop("_review_revision_result", None)
    job.options_json = json.dumps(options, ensure_ascii=False)
    job.updated_at = datetime.now(timezone.utc)
    _append_patch_decision_event(job, record, output_summary)
    db.commit()
    db.refresh(job)
    return _job_read(job)


@app.post(
    f"{settings.api_prefix}/jobs/{{job_id}}/transcription",
    response_model=VoiceTranscriptionRead,
)
async def transcribe_review_guidance(
    job_id: str,
    audio: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> VoiceTranscriptionRead:
    """Transcribe synthetic/de-identified review guidance without storing the audio."""

    if not settings.meta_voice_configured:
        raise HTTPException(status_code=503, detail="Meta voice transcription is not configured.")
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    options = json.loads(job.options_json)
    if job.status != "review_required" or not isinstance(options.get("_review_stage"), str):
        raise HTTPException(status_code=409, detail="This job is not waiting for human review guidance.")
    if audio.content_type not in {"audio/wav", "audio/wave", "audio/x-wav"}:
        raise HTTPException(status_code=415, detail="Voice guidance must be a WAV recording.")

    limit = settings.max_audio_mb * 1024 * 1024
    payload = await audio.read(limit + 1)
    await audio.close()
    if not payload:
        raise HTTPException(status_code=422, detail="The voice recording is empty.")
    if len(payload) > limit:
        raise HTTPException(status_code=413, detail=f"Voice recordings are limited to {settings.max_audio_mb} MB.")
    _validate_voice_wav(payload)
    try:
        result = await MetaAIClient(settings).transcribe_wav(payload)
    except AIResponseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return VoiceTranscriptionRead(
        transcript=str(result["transcript"]).strip(),
        model=settings.meta_transcription_model,
        duration_ms=int(result["audioDurationMs"]) if isinstance(result.get("audioDurationMs"), (int, float)) else None,
        session_id=str(result["sessionId"]) if result.get("sessionId") else None,
    )


@app.post(f"{settings.api_prefix}/jobs/{{job_id}}/retry", response_model=JobRead, status_code=status.HTTP_202_ACCEPTED)
async def retry_job(job_id: str, db: Session = Depends(get_db)) -> JobRead:
    if not settings.meta_configured:
        raise HTTPException(status_code=503, detail="Meta API key and model are not configured.")
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.status in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="This job is already in progress.")
    output_dir = settings.jobs_dir / job_id / "output"
    shutil.rmtree(output_dir, ignore_errors=True)
    for artifact in list(job.artifacts):
        if artifact.relative_path.startswith("output/"):
            job.artifacts.remove(artifact)
    options = json.loads(job.options_json)
    options.pop("_review_stage", None)
    if job.workflow == "tlf":
        options.pop("tlf_inventory_plan", None)
        options.pop("tlf_shell_plan", None)
        options.pop("tlf_programming_plan", None)
    job.options_json = json.dumps(options, ensure_ascii=False)
    job.status = "queued"
    job.result_json = None
    job.warnings_json = "[]"
    job.error = None
    job.completed_at = None
    progress_path = settings.jobs_dir / job.id / "agent" / "progress.json"
    progress_path.unlink(missing_ok=True)
    db.commit()
    db.refresh(job)
    runner.enqueue(job.id)
    return _job_read(job)


@app.put(
    f"{settings.api_prefix}/jobs/{{job_id}}/edc-source-spec",
    response_model=JobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def approve_edc_source_spec(
    job_id: str,
    update: EDCSourceSpecificationUpdate,
    db: Session = Depends(get_db),
) -> JobRead:
    """Approve normalized EDC metadata and resume the three SDTM mapping stages."""

    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    options = json.loads(job.options_json)
    _ensure_no_pending_review_patch(options)
    if job.workflow != "sdtm" or job.status != "review_required" or options.get("_review_stage") != "edc_source":
        raise HTTPException(status_code=409, detail="This job is not waiting for EDC source review.")
    problems = verify_result("sdtm-source-normalization", update.source_spec)
    if problems:
        raise HTTPException(status_code=422, detail=problems)
    serialized = update.source_spec.model_dump_json()
    identifiers = detect_identifiers(serialized)
    if identifiers:
        raise HTTPException(
            status_code=422,
            detail=f"Potential direct identifiers detected in the EDC source specification: {', '.join(identifiers)}.",
        )
    options["edc_source_spec"] = update.source_spec.model_dump(mode="json")
    return _resume_sdtm_review(job, options, db)


@app.put(
    f"{settings.api_prefix}/jobs/{{job_id}}/sdtm-domain-mapping",
    response_model=JobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def approve_sdtm_domain_mapping(
    job_id: str,
    update: SDTMDomainMappingUpdate,
    db: Session = Depends(get_db),
) -> JobRead:
    """Approve the domain-level source-to-SDTM mapping and start variable mapping."""

    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    options = json.loads(job.options_json)
    _ensure_no_pending_review_patch(options)
    if job.workflow != "sdtm" or job.status != "review_required" or options.get("_review_stage") != "domain_mapping":
        raise HTTPException(status_code=409, detail="This job is not waiting for SDTM domain mapping review.")
    source_spec = SDTMUseCase._approved_source_spec(options)
    try:
        SDTMUseCase.validate_domain_mapping(source_spec, update.domain_mapping)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _reject_review_identifiers(update.domain_mapping.model_dump_json(), "SDTM domain mapping")
    previous_mapping_raw = options.pop("_sdtm_domain_mapping_baseline", None)
    baseline_variables_raw = options.pop("_sdtm_variable_mapping_baseline", None)
    if previous_mapping_raw is not None or baseline_variables_raw is not None:
        if not isinstance(previous_mapping_raw, dict) or not isinstance(baseline_variables_raw, dict):
            raise HTTPException(status_code=409, detail="The prior mapping baseline is incomplete; return to variable mapping and try again.")
        try:
            previous_mapping = SDTMDomainMappingPlan.model_validate(previous_mapping_raw)
            baseline_variables = SDTMVariableMappingPlan.model_validate(baseline_variables_raw)
            SDTMUseCase.validate_domain_mapping(source_spec, previous_mapping)
            SDTMUseCase.validate_variable_mapping(source_spec, previous_mapping, baseline_variables)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=f"The prior mapping baseline is invalid: {exc}") from exc
        options["_sdtm_variable_mapping_reconcile"] = SDTMUseCase.build_variable_mapping_reconciliation(
            previous_mapping,
            update.domain_mapping,
            baseline_variables,
        )
    options["sdtm_domain_mapping"] = update.domain_mapping.model_dump(mode="json")
    return _resume_sdtm_review(job, options, db)


@app.post(
    f"{settings.api_prefix}/jobs/{{job_id}}/sdtm-domain-mapping/reopen",
    response_model=JobRead,
)
async def reopen_sdtm_domain_mapping(
    job_id: str,
    db: Session = Depends(get_db),
) -> JobRead:
    """Return a variable-mapping review to the domain gate without a model call."""

    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    options = json.loads(job.options_json)
    _ensure_no_pending_review_patch(options)
    if job.workflow != "sdtm" or job.status != "review_required" or options.get("_review_stage") != "variable_mapping":
        raise HTTPException(status_code=409, detail="This job is not waiting for SDTM variable mapping review.")
    if not job.result_json:
        raise HTTPException(status_code=409, detail="The variable-mapping review draft is unavailable.")
    source_spec = SDTMUseCase._approved_source_spec(options)
    domain_mapping = SDTMUseCase._approved_domain_mapping(options, source_spec)
    try:
        current_review = SDTMVariableMappingReview.model_validate(json.loads(job.result_json))
        SDTMUseCase.validate_variable_mapping(source_spec, domain_mapping, current_review.variable_mapping)
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=f"The variable-mapping review draft cannot be preserved: {exc}") from exc

    options["_sdtm_domain_mapping_baseline"] = domain_mapping.model_dump(mode="json")
    options["_sdtm_variable_mapping_baseline"] = current_review.variable_mapping.model_dump(mode="json")
    options.pop("_sdtm_variable_mapping_reconcile", None)
    options.pop("sdtm_variable_mapping", None)
    options["_review_stage"] = "domain_mapping"
    options.pop("review_feedback", None)
    options.pop("_review_revision_result", None)
    options.pop("_review_patch_request", None)
    options.pop("_pending_review_patch", None)
    job.options_json = json.dumps(options, ensure_ascii=False)
    job.result_json = SDTMDomainMappingReview(
        source_spec=source_spec,
        domain_mapping=domain_mapping,
    ).model_dump_json()
    job.warnings_json = json.dumps([DISCLAIMER], ensure_ascii=False)
    job.error = None
    job.completed_at = None
    job.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(job)
    return _job_read(job)


@app.put(
    f"{settings.api_prefix}/jobs/{{job_id}}/sdtm-variable-mapping",
    response_model=JobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def approve_sdtm_variable_mapping(
    job_id: str,
    update: SDTMVariableMappingUpdate,
    db: Session = Depends(get_db),
) -> JobRead:
    """Approve variable and value-level mappings and start rule/code generation."""

    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    options = json.loads(job.options_json)
    _ensure_no_pending_review_patch(options)
    if job.workflow != "sdtm" or job.status != "review_required" or options.get("_review_stage") != "variable_mapping":
        raise HTTPException(status_code=409, detail="This job is not waiting for SDTM variable mapping review.")
    source_spec = SDTMUseCase._approved_source_spec(options)
    domain_mapping = SDTMUseCase._approved_domain_mapping(options, source_spec)
    try:
        SDTMUseCase.validate_variable_mapping(source_spec, domain_mapping, update.variable_mapping)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _reject_review_identifiers(update.variable_mapping.model_dump_json(), "SDTM variable mapping")
    options.pop("_sdtm_variable_mapping_reconcile", None)
    options["sdtm_variable_mapping"] = update.variable_mapping.model_dump(mode="json")
    return _resume_sdtm_review(job, options, db)


@app.get(
    f"{settings.api_prefix}/jobs/{{job_id}}/sdtm-executions",
    response_model=ExecutionAttemptList,
)
def read_sdtm_executions(job_id: str, db: Session = Depends(get_db)) -> ExecutionAttemptList:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.workflow != "sdtm":
        raise HTTPException(status_code=409, detail="Execution history is available only for SDTM jobs.")
    return ExecutionAttemptList(items=list_attempts(settings.jobs_dir / job_id))


@app.post(
    f"{settings.api_prefix}/jobs/{{job_id}}/sdtm-executions",
    response_model=ExecutionAttempt,
    status_code=status.HTTP_201_CREATED,
)
async def create_sdtm_execution(
    job_id: str,
    raw_files: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
) -> ExecutionAttempt:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.workflow != "sdtm" or job.status != "succeeded" or not job.result_json:
        raise HTTPException(status_code=409, detail="An approved, completed SDTM plan is required before execution.")
    job_dir = settings.jobs_dir / job_id
    if raw_files:
        state = read_state(job_dir)
        known = {item.logical_name for item in state.inputs.raw_datasets}
        input_dir = job_dir / "input"
        for upload in raw_files:
            safe_name = validate_upload_metadata(upload)
            if Path(safe_name).suffix.lower() not in {".csv", ".xpt"}:
                raise HTTPException(status_code=415, detail="Execution inputs must be CSV or XPT datasets.")
            destination = input_dir / f"execution-{uuid4().hex[:8]}-{safe_name}"
            await _save_limited(upload, destination)
            verify_signature(destination)
            try:
                inventory = inventory_raw_dataset(destination, safe_name)
            except (OSError, UnicodeError, ValueError) as exc:
                destination.unlink(missing_ok=True)
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            if inventory.logical_name in known:
                destination.unlink(missing_ok=True)
                raise HTTPException(status_code=422, detail=f"Duplicate raw dataset logical name: {inventory.logical_name}.")
            known.add(inventory.logical_name)
            state.inputs.raw_datasets.append(inventory)
        state.limitations = [item for item in state.limitations if "No raw datasets" not in item and "not tested against raw" not in item]
        state.lifecycle.execution = "not_run"
        write_state(job_dir, state)
    plan = SDTMPlan.model_validate(json.loads(job.result_json))
    provider = (
        RemoteRExecutionProvider(settings.sdtm_runner_url)
        if settings.sdtm_runner_url.strip()
        else UnavailableRExecutionProvider()
    )
    try:
        attempt = SDTMExecutionService(provider, settings.sdtm_runner_timeout_seconds).execute(job_dir, plan)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    attempt_dir = job_dir / "sdtm" / "executions" / attempt.attempt_id
    for path in [attempt_dir / "program.R", attempt_dir / "attempt.json", *(attempt_dir / "output").glob("*.xpt")]:
        relative = path.relative_to(job_dir).as_posix()
        if not any(item.relative_path == relative for item in job.artifacts):
            job.artifacts.append(Artifact(**artifact_record(path, job_dir)))
    _refresh_csdrg_artifacts(job, db)
    db.commit()
    return attempt


@app.post(
    f"{settings.api_prefix}/jobs/{{job_id}}/sdtm-executions/{{attempt_id}}/repair",
    response_model=ExecutionAttempt,
    status_code=status.HTTP_201_CREATED,
)
def review_and_run_sdtm_repair(
    job_id: str,
    attempt_id: str,
    approval: RepairApproval,
    db: Session = Depends(get_db),
) -> ExecutionAttempt:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.workflow != "sdtm" or job.status != "succeeded" or not job.result_json:
        raise HTTPException(status_code=409, detail="An approved, completed SDTM plan is required before repair.")
    job_dir = settings.jobs_dir / job_id
    try:
        failed_attempt = load_attempt(job_dir, attempt_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    proposal = failed_attempt.repair_proposal
    if proposal is None or proposal.proposal_id != approval.proposal_id or proposal.status != "proposed":
        raise HTTPException(status_code=409, detail="This attempt has no matching open repair proposal.")
    proposal.reviewer = approval.reviewer
    proposal.decided_at = datetime.now(timezone.utc)
    if not approval.approved:
        proposal.status = "rejected"
        save_attempt(job_dir, failed_attempt)
        return failed_attempt
    try:
        ensure_repair_allowed(job_dir, failed_attempt)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    proposal.status = "approved"
    save_attempt(job_dir, failed_attempt)

    try:
        plan = apply_typed_repair(SDTMPlan.model_validate(json.loads(job.result_json)), proposal)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    inputs = [(job_dir / "input" / name).resolve() for name in json.loads(job.input_files_json)]
    options = json.loads(job.options_json)
    next_output = job_dir / f"output-next-{uuid4()}"
    current_output = job_dir / "output"
    backup_output = job_dir / f"output-backup-{uuid4()}"
    try:
        rendered = WorkflowService().render_revision("sdtm", result=plan.model_dump(mode="json"), inputs=inputs, options=options, output_dir=next_output)
        if current_output.exists():
            current_output.rename(backup_output)
        next_output.rename(current_output)
        for artifact in list(job.artifacts):
            if artifact.relative_path.startswith("output/"):
                job.artifacts.remove(artifact)
        db.flush()
        for old_path in rendered.paths:
            final_path = current_output / old_path.relative_to(next_output)
            job.artifacts.append(Artifact(**artifact_record(final_path, job_dir)))
        job.result_json = json.dumps(rendered.result, ensure_ascii=False)
        job.warnings_json = json.dumps([DISCLAIMER, f"Typed repair {proposal.proposal_id} was approved by {approval.reviewer}; artifacts were regenerated before rerun.", *rendered.warnings], ensure_ascii=False)
        db.commit()
    except Exception as exc:
        db.rollback()
        if current_output.exists() and backup_output.exists():
            shutil.rmtree(current_output, ignore_errors=True)
        if backup_output.exists():
            backup_output.rename(current_output)
        shutil.rmtree(next_output, ignore_errors=True)
        raise HTTPException(status_code=422, detail="The approved typed repair could not be regenerated safely.") from exc
    finally:
        shutil.rmtree(next_output, ignore_errors=True)
        shutil.rmtree(backup_output, ignore_errors=True)

    provider = RemoteRExecutionProvider(settings.sdtm_runner_url) if settings.sdtm_runner_url.strip() else UnavailableRExecutionProvider()
    repaired = SDTMExecutionService(provider, settings.sdtm_runner_timeout_seconds).execute(job_dir, SDTMPlan.model_validate(rendered.result), parent_attempt_id=attempt_id)
    repaired_dir = job_dir / "sdtm" / "executions" / repaired.attempt_id
    for path in [repaired_dir / "program.R", repaired_dir / "attempt.json", *(repaired_dir / "output").glob("*.xpt")]:
        job.artifacts.append(Artifact(**artifact_record(path, job_dir)))
    _refresh_csdrg_artifacts(job, db)
    db.commit()
    return repaired


@app.get(f"{settings.api_prefix}/jobs/{{job_id}}/validations", response_model=list[ValidationRecord])
def read_validations(job_id: str, db: Session = Depends(get_db)) -> list[ValidationRecord]:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.workflow != "sdtm":
        raise HTTPException(status_code=409, detail="Validation review is available only for SDTM jobs.")
    return list_validations(settings.jobs_dir / job_id)


@app.post(f"{settings.api_prefix}/jobs/{{job_id}}/validations/import", response_model=ValidationRecord, status_code=status.HTTP_201_CREATED)
async def import_validation_report(job_id: str, report: UploadFile | None = File(default=None), db: Session = Depends(get_db)) -> ValidationRecord:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.workflow != "sdtm" or not job.result_json:
        raise HTTPException(status_code=409, detail="A completed SDTM plan is required before validation import.")
    job_dir = settings.jobs_dir / job_id
    source: Path | None = None
    if report is not None:
        safe_name = validate_upload_metadata(report)
        if Path(safe_name).suffix.lower() not in {".csv", ".xlsx"}:
            raise HTTPException(status_code=415, detail="Validation report must be CSV or XLSX.")
        source = job_dir / "input" / f"validation-import-{uuid4().hex[:8]}-{safe_name}"
        await _save_limited(report, source)
        verify_signature(source)
    else:
        state = read_state(job_dir)
        if state.inputs.validation_report:
            source = job_dir / "input" / state.inputs.validation_report
    if source is None or not source.is_file():
        raise HTTPException(status_code=422, detail="Upload a supported Pinnacle 21 CSV/XLSX report.")
    try:
        record = import_pinnacle21_report(job_dir, source)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _register_validation_artifacts(job, record, db)
    _refresh_csdrg_artifacts(job, db)
    db.commit()
    return record


@app.post(f"{settings.api_prefix}/jobs/{{job_id}}/validations/run", response_model=ValidationRecord, status_code=status.HTTP_201_CREATED)
def run_validation(job_id: str, request: ValidationRunRequest, db: Session = Depends(get_db)) -> ValidationRecord:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.workflow != "sdtm" or not job.result_json:
        raise HTTPException(status_code=409, detail="A completed SDTM plan is required before validation.")
    job_dir = settings.jobs_dir / job_id
    provider = InternalChecksProvider() if request.provider == "internal" else Pinnacle21CLIProvider(settings.pinnacle21_cli_path, settings.pinnacle21_java_path, settings.pinnacle21_timeout_seconds)
    record = provider.run(job_dir)
    save_validation(job_dir, record)
    state = read_state(job_dir)
    state.lifecycle.validation = record.status
    if record.status in {"failed", "unavailable"}:
        state.lifecycle.submission_readiness = "blocked"
    write_state(job_dir, state)
    update_readiness(job_dir)
    _register_validation_artifacts(job, record, db)
    _refresh_csdrg_artifacts(job, db)
    db.commit()
    return record


@app.put(f"{settings.api_prefix}/jobs/{{job_id}}/validation-findings/{{finding_id}}", response_model=ValidationFinding)
def update_validation_finding(job_id: str, finding_id: str, update: ValidationFindingUpdate, db: Session = Depends(get_db)) -> ValidationFinding:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.workflow != "sdtm":
        raise HTTPException(status_code=409, detail="Findings are available only for SDTM jobs.")
    job_dir = settings.jobs_dir / job_id
    try:
        record, finding = find_finding(job_dir, finding_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    finding.finding_status = update.finding_status
    finding.disposition = update.disposition
    finding.explanation = update.explanation
    finding.reviewer = update.reviewer if update.approved else None
    finding.approved_at = datetime.now(timezone.utc) if update.approved else None
    save_validation(job_dir, record)
    update_readiness(job_dir)
    _register_validation_artifacts(job, record, db)
    _refresh_csdrg_artifacts(job, db)
    db.commit()
    return finding


@app.put(f"{settings.api_prefix}/jobs/{{job_id}}/csdrg", response_model=CSDRGDocument)
def update_csdrg(job_id: str, document: CSDRGDocument, db: Session = Depends(get_db)) -> CSDRGDocument:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.workflow != "sdtm" or not job.result_json:
        raise HTTPException(status_code=409, detail="A completed SDTM plan is required before cSDRG review.")
    job_dir = settings.jobs_dir / job_id
    plan = SDTMPlan.model_validate(json.loads(job.result_json))
    if document.study_name != plan.study_name:
        raise HTTPException(status_code=422, detail="The cSDRG study name must match the approved SDTM plan.")
    authoritative = build_csdrg(job_dir, plan)
    protected = {"3. Source data and conversion approach", "5. Conformance and validation summary", "6. Reviewer-approved explanations", "7. Unresolved issues", "9. Software, execution, and traceability", "10. Limitations"}
    expected = {section.heading: section for section in authoritative.sections}
    received = {section.heading: section for section in document.sections}
    if any(heading not in received or received[heading].body != expected[heading].body or received[heading].todos != expected[heading].todos for heading in protected):
        raise HTTPException(status_code=422, detail="Execution, validation, approved-explanation, unresolved-issue, and limitation sections are evidence-controlled and cannot be overwritten.")
    document.generated_at = datetime.now(timezone.utc)
    for path in render_csdrg_document(document, job_dir / "output"):
        _upsert_artifact(job, path, job_dir)
    db.commit()
    return document


@app.put(
    f"{settings.api_prefix}/jobs/{{job_id}}/tlf-inventory",
    response_model=JobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def approve_tlf_inventory(
    job_id: str,
    update: TLFInventoryPlanUpdate,
    db: Session = Depends(get_db),
) -> JobRead:
    """Approve the output table of contents and start detailed shell generation."""

    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    options = json.loads(job.options_json)
    _ensure_no_pending_review_patch(options)
    if job.workflow != "tlf" or job.status != "review_required" or options.get("_review_stage") != "tlf_inventory":
        raise HTTPException(status_code=409, detail="This job is not waiting for TLF output inventory review.")
    try:
        TLFUseCase.validate_inventory_plan(update.inventory_plan)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _reject_review_identifiers(update.inventory_plan.model_dump_json(), "TLF output inventory")
    options["tlf_inventory_plan"] = update.inventory_plan.model_dump(mode="json")
    return _resume_review(job, options, db)


@app.put(
    f"{settings.api_prefix}/jobs/{{job_id}}/tlf-shell",
    response_model=JobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def approve_tlf_shell(
    job_id: str,
    update: TLFShellPlanUpdate,
    db: Session = Depends(get_db),
) -> JobRead:
    """Approve the TLF shell and start programming augmentation."""

    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    options = json.loads(job.options_json)
    _ensure_no_pending_review_patch(options)
    if job.workflow != "tlf" or job.status != "review_required" or options.get("_review_stage") != "tlf_shell":
        raise HTTPException(status_code=409, detail="This job is not waiting for TLF shell review.")
    try:
        if options.get("tlf_inventory_plan") is None:
            options["tlf_inventory_plan"] = TLFUseCase.inventory_from_shell(update.shell_plan).model_dump(mode="json")
        TLFUseCase.validate_shell_plan(update.shell_plan, TLFUseCase._approved_inventory_plan(options))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _reject_review_identifiers(update.shell_plan.model_dump_json(), "TLF shell")
    options["tlf_shell_plan"] = update.shell_plan.model_dump(mode="json")
    return _resume_review(job, options, db)


@app.put(
    f"{settings.api_prefix}/jobs/{{job_id}}/tlf-programming",
    response_model=JobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def approve_tlf_programming(
    job_id: str,
    update: TLFProgrammingPlanUpdate,
    db: Session = Depends(get_db),
) -> JobRead:
    """Approve ADaM-linked programming scaffolds and render final artifacts."""

    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    options = json.loads(job.options_json)
    _ensure_no_pending_review_patch(options)
    if job.workflow != "tlf" or job.status != "review_required" or options.get("_review_stage") != "tlf_programming":
        raise HTTPException(status_code=409, detail="This job is not waiting for TLF programming review.")
    try:
        TLFUseCase.validate_programming_plan(
            update.programming_plan,
            TLFUseCase._approved_shell_plan(options),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _reject_review_identifiers(update.programming_plan.model_dump_json(), "TLF programming plan")
    options["tlf_programming_plan"] = update.programming_plan.model_dump(mode="json")
    return _resume_review(job, options, db)


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
        for artifact in list(job.artifacts):
            if artifact.relative_path.startswith("output/"):
                job.artifacts.remove(artifact)
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
        if job.workflow == "sdtm":
            _upsert_artifact(job, refresh_evidence_manifest(job_dir), job_dir)
            _upsert_artifact(job, refresh_evidence_bundle(job_dir), job_dir)
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
def download_artifact(
    job_id: str,
    artifact_id: str,
    inline: bool = Query(False),
    db: Session = Depends(get_db),
) -> FileResponse:
    artifact = db.scalar(select(Artifact).where(Artifact.id == artifact_id, Artifact.job_id == job_id))
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found.")
    path = _safe_artifact_path(job_id, artifact.relative_path)
    if not path.is_file():
        raise HTTPException(status_code=410, detail="Artifact file is no longer available.")
    return FileResponse(
        path,
        media_type=artifact.media_type,
        filename=artifact.name,
        content_disposition_type="inline" if inline else "attachment",
    )


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


def _validate_voice_wav(payload: bytes) -> None:
    try:
        with wave.open(BytesIO(payload), "rb") as recording:
            channels = recording.getnchannels()
            sample_width = recording.getsampwidth()
            sample_rate = recording.getframerate()
            frame_count = recording.getnframes()
    except (wave.Error, EOFError) as exc:
        raise HTTPException(status_code=422, detail="The voice recording is not a valid WAV file.") from exc
    if channels != 1 or sample_width != 2 or sample_rate not in {16_000, 24_000}:
        raise HTTPException(
            status_code=422,
            detail="Voice guidance must be mono 16-bit PCM WAV at 16 kHz or 24 kHz.",
        )
    if frame_count <= 0:
        raise HTTPException(status_code=422, detail="The voice recording contains no audio frames.")
    if frame_count > sample_rate * 600:
        raise HTTPException(status_code=413, detail="Voice recordings are limited to 10 minutes.")


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
    options = json.loads(job.options_json)
    pending_patch = options.get("_pending_review_patch")
    review_stage = options.get("_review_stage") if job.status == "review_required" else None
    if review_stage not in {
        "edc_source",
        "domain_mapping",
        "variable_mapping",
        "tlf_inventory",
        "tlf_shell",
        "tlf_programming",
    }:
        review_stage = None
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
        review_stage=review_stage,
        result=result,
        warnings=warnings,
        error=job.error,
        artifacts=artifacts,
        sdtm_workbench=read_state(settings.jobs_dir / job.id) if job.workflow == "sdtm" else None,
        result_revision=result_revision(result) if result is not None else None,
        review_patch=public_patch(pending_patch) if isinstance(pending_patch, dict) else None,
    )


def _upsert_artifact(job: Job, path: Path, job_dir: Path) -> None:
    record = artifact_record(path, job_dir)
    existing = next((item for item in job.artifacts if item.relative_path == record["relative_path"]), None)
    if existing is None:
        job.artifacts.append(Artifact(**record))
        return
    existing.name = record["name"]
    existing.media_type = record["media_type"]
    existing.size_bytes = record["size_bytes"]
    existing.sha256 = record["sha256"]


def _register_validation_artifacts(job: Job, record: ValidationRecord, db: Session) -> None:
    job_dir = settings.jobs_dir / job.id
    record_path = job_dir / "sdtm" / "validation" / f"{record.validation_id}.json"
    if record_path.is_file():
        _upsert_artifact(job, record_path, job_dir)
    if record.source_artifact:
        source = job_dir / record.source_artifact
        if source.is_file():
            _upsert_artifact(job, source, job_dir)
    db.flush()


def _refresh_csdrg_artifacts(job: Job, db: Session) -> None:
    if job.workflow != "sdtm" or not job.result_json:
        return
    job_dir = settings.jobs_dir / job.id
    plan = SDTMPlan.model_validate(json.loads(job.result_json))
    for path in render_csdrg(job_dir, plan):
        _upsert_artifact(job, path, job_dir)
    _upsert_artifact(job, refresh_evidence_manifest(job_dir), job_dir)
    _upsert_artifact(job, refresh_evidence_bundle(job_dir), job_dir)
    db.flush()


def _reject_review_identifiers(serialized: str, label: str) -> None:
    identifiers = detect_identifiers(serialized)
    if identifiers:
        raise HTTPException(
            status_code=422,
            detail=f"Potential direct identifiers detected in the {label}: {', '.join(identifiers)}.",
        )


def _ensure_no_pending_review_patch(options: dict) -> None:
    if options.get("_pending_review_patch") or options.get("_review_patch_request"):
        raise HTTPException(
            status_code=409,
            detail="Approve or reject the current scoped revision before approving this review stage.",
        )


def _resume_sdtm_review(job: Job, options: dict, db: Session) -> JobRead:
    return _resume_review(job, options, db)


def _resume_review(job: Job, options: dict, db: Session, *, preserve_review_context: bool = False) -> JobRead:
    options.pop("_review_stage", None)
    if not preserve_review_context:
        options.pop("review_feedback", None)
        options.pop("_review_revision_result", None)
        options.pop("_review_patch_request", None)
        options.pop("_pending_review_patch", None)
    job.options_json = json.dumps(options, ensure_ascii=False)
    job.status = "queued"
    if not preserve_review_context:
        job.result_json = None
    job.warnings_json = "[]"
    job.error = None
    job.completed_at = None
    job.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(job)
    runner.enqueue(job.id)
    return _job_read(job)


def _append_user_feedback_event(
    job: Job,
    stage: str,
    message: str,
    occurred_at: str,
    *,
    scope: dict | None = None,
) -> None:
    path = settings.jobs_dir / job.id / "agent" / "progress.json"
    progress: dict = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                progress = loaded
        except (OSError, json.JSONDecodeError):
            progress = {}
    events = progress.get("events")
    if not isinstance(events, list):
        events = []
    event_turns = [event.get("turn", 0) for event in events if isinstance(event, dict)]
    next_turn = max([int(progress.get("turn", 0)), *[int(value) for value in event_turns if isinstance(value, int)]]) + 1
    events.append({
        "turn": next_turn,
        "type": "user_feedback",
        "actor": "user",
        "name": "review_feedback",
        "stage": stage,
        "summary": message,
        "intent": "Guide a revision of the current draft without approving or advancing the workflow stage.",
        "input_summary": message,
        "output_summary": "The current stage was queued for an agent revision.",
        "input_details": {"Review stage": stage, "Scope": scope or {}},
        "output_details": {"Decision": "Revise current stage"},
        "evidence": ["Human review guidance"],
        "occurred_at": occurred_at,
    })
    definition = get_agent(job.workflow)
    progress.update({
        "agent_id": progress.get("agent_id", definition.id),
        "workflow": job.workflow,
        "status": "queued",
        "model": progress.get("model", settings.meta_model),
        "turn": next_turn,
        "max_turns": max(int(progress.get("max_turns", settings.agent_max_turns)), next_turn + settings.agent_max_turns),
        "stage": stage,
        "updated_at": occurred_at,
        "events": events,
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(progress, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def _append_patch_decision_event(job: Job, record: dict, output_summary: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    path = settings.jobs_dir / job.id / "agent" / "progress.json"
    progress: dict = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                progress = loaded
        except (OSError, json.JSONDecodeError):
            progress = {}
    events = progress.get("events") if isinstance(progress.get("events"), list) else []
    turn = max(
        [int(progress.get("turn", 0)), *[int(item.get("turn", 0)) for item in events if isinstance(item, dict)]]
    ) + 1
    events.append({
        "turn": turn,
        "type": "human_patch_decision",
        "actor": "user",
        "name": "review_patch_decision",
        "stage": record.get("stage"),
        "ok": record.get("status") == "approved",
        "summary": f"Review patch {record.get('status')} by {record.get('reviewer')}.",
        "intent": "Decide a scoped mapping revision without changing paths outside the approved patch.",
        "input_summary": f"Decision for patch {record.get('transaction_id')}.",
        "output_summary": output_summary,
        "input_details": {"Scope": record.get("scope", {}), "Reviewer": record.get("reviewer")},
        "output_details": {"Status": record.get("status"), "Operations": len(record.get("operations", []))},
        "evidence": [f"Review transaction {record.get('transaction_id')}", str(record.get("baseline_revision", ""))],
        "occurred_at": now,
    })
    progress.update({"events": events, "turn": turn, "status": "completed", "updated_at": now})
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(progress, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)




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
    pdf.drawString(54, 760, "SYNTHETIC STUDY — ADVERSE EVENTS")
    y = 690
    for label in ["Adverse Event Term", "Adverse Event Start Date", "Adverse Event End Date", "Severity", "Serious Event"]:
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(54, y, label)
        pdf.line(54, y - 20, 540, y - 20)
        y -= 64
    pdf.save()
