from __future__ import annotations

import asyncio
import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .ai import MetaAIClient
from .artifacts import artifact_record
from .config import get_settings
from .db import SessionLocal
from .models import Artifact, Job
from .schemas import DISCLAIMER, SDTMPlan
from .sdtm_workbench import read_state, write_state
from .sdtm_audit import refresh_evidence_bundle, refresh_evidence_manifest
from .review_patches import build_patch_record, public_patch, scope_candidate, scope_completed_sdtm_candidate, write_patch_record
from .schemas.reviews import ReviewScope
from .review_validation import validate_review_result
from .use_cases.base import UseCaseContext
from .use_cases.sdtm import SDTMUseCase
from .workflows import WorkflowService


logger = logging.getLogger(__name__)


class JobRunner:
    def __init__(self) -> None:
        self.tasks: set[asyncio.Task] = set()

    def enqueue(self, job_id: str) -> None:
        task = asyncio.create_task(self.run(job_id), name=f"job-{job_id}")
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    def enqueue_sdtm_domain_rerun(self, job_id: str) -> None:
        task = asyncio.create_task(self.run_sdtm_domain_rerun(job_id), name=f"sdtm-domain-rerun-{job_id}")
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def run_sdtm_domain_rerun(self, job_id: str) -> None:
        """Generate a completed-job domain proposal without replacing approved artifacts."""

        settings = get_settings()
        with SessionLocal() as session:
            job = session.get(Job, job_id)
            if job is None:
                return
            options = json.loads(job.options_json)
            request = options.get("_sdtm_domain_rerun_request")
            baseline_raw = json.loads(job.result_json) if job.result_json else None
            if not isinstance(request, dict) or not isinstance(baseline_raw, dict):
                return
            job.status = "running"
            job.updated_at = datetime.now(timezone.utc)
            session.commit()
            input_names = json.loads(job.input_files_json)

        job_dir = settings.jobs_dir / job_id
        inputs = [(job_dir / "input" / name).resolve() for name in input_names]
        try:
            baseline = SDTMPlan.model_validate(baseline_raw)
            context = UseCaseContext(
                inputs=inputs,
                options=options,
                ai=MetaAIClient(settings),
                settings=settings,
                agent_progress_path=job_dir / "agent" / "progress.json",
            )
            if request["rerun_stage"] == "domain_mapping":
                generated = await SDTMUseCase().regenerate_completed_domain_mapping(
                    context,
                    baseline=baseline,
                )
            else:
                generated = await SDTMUseCase().regenerate_completed_domain(
                    context,
                    baseline=baseline,
                    stage=str(request["rerun_stage"]),
                    target_domain=str(request["target_domain"]),
                )
            proposed = generated.value.model_dump(mode="json")
            proposed = scope_completed_sdtm_candidate(
                baseline_raw,
                proposed,
                rerun_stage=str(request["rerun_stage"]),
                target_domain=request.get("target_domain"),
                scope=ReviewScope.model_validate(request.get("scope", {})),
            )
            proposed = SDTMUseCase().validate_result(proposed).model_dump(mode="json")
            patch_record = build_patch_record(request, baseline_raw, proposed)
            write_patch_record(job_dir, patch_record)
            with SessionLocal() as session:
                job = session.get(Job, job_id)
                if job is None:
                    return
                saved_options = json.loads(job.options_json)
                saved_options.pop("_sdtm_domain_rerun_request", None)
                saved_options["_pending_review_patch"] = public_patch(patch_record)
                saved_options["_review_stage"] = str(request["stage"])
                job.options_json = json.dumps(saved_options, ensure_ascii=False)
                job.warnings_json = json.dumps(
                    [
                        DISCLAIMER,
                        *generated.warnings,
                        (
                            "A complete domain-mapping proposal is awaiting human approval; current artifacts remain unchanged."
                            if request["rerun_stage"] == "domain_mapping"
                            else f"A domain-scoped {request['rerun_stage'].replace('_', ' ')} proposal for {request['target_domain']} is awaiting human approval; current artifacts remain unchanged."
                        ),
                    ],
                    ensure_ascii=False,
                )
                job.status = "review_required"
                job.error = None
                job.completed_at = None
                job.updated_at = datetime.now(timezone.utc)
                session.commit()
            state = read_state(job_dir)
            state.lifecycle.program_generation = "review_required"
            state.lifecycle.submission_readiness = "blocked"
            write_state(job_dir, state)
        except Exception as exc:
            logger.exception("SDTM domain rerun %s failed", job_id)
            safe_error = sanitize_error(exc)
            with SessionLocal() as session:
                job = session.get(Job, job_id)
                if job is None:
                    return
                saved_options = json.loads(job.options_json)
                saved_options.pop("_sdtm_domain_rerun_request", None)
                saved_options.pop("_review_stage", None)
                saved_options.pop("_review_revision_result", None)
                saved_options["review_feedback"] = [
                    item for item in saved_options.get("review_feedback", [])
                    if not isinstance(item, dict) or item.get("transaction_id") != request.get("transaction_id")
                ]
                if not saved_options["review_feedback"]:
                    saved_options.pop("review_feedback", None)
                job.options_json = json.dumps(saved_options, ensure_ascii=False)
                existing_warnings = json.loads(job.warnings_json or "[]")
                job.warnings_json = json.dumps(
                    [*existing_warnings, f"Domain rerun failed; the approved result and artifacts were preserved: {safe_error}"],
                    ensure_ascii=False,
                )
                job.status = "succeeded"
                job.error = None
                job.completed_at = datetime.now(timezone.utc)
                job.updated_at = job.completed_at
                session.commit()
            state = read_state(job_dir)
            state.lifecycle.program_generation = "completed"
            state.lifecycle.submission_readiness = "blocked"
            write_state(job_dir, state)

    async def run(self, job_id: str) -> None:
        settings = get_settings()
        with SessionLocal() as session:
            job = session.get(Job, job_id)
            if job is None:
                return
            job.status = "running"
            job.updated_at = datetime.now(timezone.utc)
            session.commit()
            workflow = job.workflow
            options = json.loads(job.options_json)
            input_names = json.loads(job.input_files_json)

        job_dir = settings.jobs_dir / job_id
        inputs = [(job_dir / "input" / name).resolve() for name in input_names]
        output_dir = job_dir / "output"
        try:
            service = WorkflowService()
            review = await service.prepare_review(
                workflow,
                inputs=inputs,
                options=options,
                job_dir=job_dir,
            )
            if review is not None:
                with SessionLocal() as session:
                    job = session.get(Job, job_id)
                    if job is None:
                        shutil.rmtree(job_dir, ignore_errors=True)
                        return
                    saved_options = json.loads(job.options_json)
                    patch_request = options.get("_review_patch_request")
                    if isinstance(patch_request, dict):
                        baseline = options.get("_review_revision_result")
                        if not isinstance(baseline, dict):
                            raise ValueError("The scoped review baseline is unavailable.")
                        saved_options.pop("_review_patch_request", None)
                        saved_options.pop("_review_revision_result", None)
                        job.result_json = json.dumps(baseline, ensure_ascii=False)
                        try:
                            scope = ReviewScope.model_validate(patch_request.get("scope", {}))
                            proposed = scope_candidate(str(patch_request["stage"]), baseline, review.result, scope)
                            proposed = validate_review_result(workflow, str(patch_request["stage"]), proposed, options)
                            patch_record = build_patch_record(patch_request, baseline, proposed)
                        except (KeyError, TypeError, ValueError) as exc:
                            write_patch_record(job_dir, {**patch_request, "status": "failed", "error": str(exc)})
                            saved_options["review_feedback"] = [
                                item for item in saved_options.get("review_feedback", [])
                                if not isinstance(item, dict)
                                or item.get("transaction_id") != patch_request.get("transaction_id")
                            ]
                            review.warnings.append(
                                f"The scoped revision was not proposed and nothing was applied: {exc}"
                            )
                        else:
                            write_patch_record(job_dir, patch_record)
                            saved_options["_pending_review_patch"] = public_patch(patch_record)
                            review.warnings.append(
                                f"Scoped revision proposed {len(patch_record['operations'])} change(s); human approval is required before merge."
                            )
                    else:
                        job.result_json = json.dumps(review.result, ensure_ascii=False)
                    job.warnings_json = json.dumps([DISCLAIMER, *review.warnings], ensure_ascii=False)
                    saved_options["_review_stage"] = review.review_stage
                    job.options_json = json.dumps(saved_options, ensure_ascii=False)
                    job.status = "review_required"
                    job.completed_at = None
                    job.updated_at = datetime.now(timezone.utc)
                    session.commit()
                if workflow == "sdtm":
                    state = read_state(job_dir)
                    state.lifecycle.program_generation = "not_started"
                    state.lifecycle.submission_readiness = "blocked"
                    write_state(job_dir, state)
                return
            result = await service.execute(
                workflow,
                inputs=inputs,
                options=options,
                output_dir=output_dir,
            )
            if workflow == "sdtm":
                state = read_state(job_dir)
                state.lifecycle.program_generation = "completed"
                state.lifecycle.execution = "not_run"
                state.lifecycle.submission_readiness = "blocked"
                if not state.inputs.raw_datasets:
                    limitation = "Generated R and SAS programs were not tested against raw datasets."
                    if limitation not in state.limitations:
                        state.limitations.append(limitation)
                write_state(job_dir, state)
            with SessionLocal() as session:
                job = session.get(Job, job_id)
                if job is None:
                    shutil.rmtree(job_dir, ignore_errors=True)
                    return
                job.result_json = json.dumps(result.result, ensure_ascii=False)
                job.warnings_json = json.dumps([DISCLAIMER, *result.warnings], ensure_ascii=False)
                job.status = "succeeded"
                job.completed_at = datetime.now(timezone.utc)
                job.updated_at = job.completed_at
                for path in result.paths:
                    record = artifact_record(path, job_dir)
                    job.artifacts.append(Artifact(**record))
                if workflow == "sdtm":
                    manifest_path = refresh_evidence_manifest(job_dir)
                    manifest_record = artifact_record(manifest_path, job_dir)
                    manifest_artifact = next((item for item in job.artifacts if item.relative_path == manifest_record["relative_path"]), None)
                    if manifest_artifact is None:
                        job.artifacts.append(Artifact(**manifest_record))
                    else:
                        manifest_artifact.size_bytes = manifest_record["size_bytes"]
                        manifest_artifact.sha256 = manifest_record["sha256"]
                    bundle_path = refresh_evidence_bundle(job_dir)
                    bundle_artifact = next((item for item in job.artifacts if item.relative_path == bundle_path.relative_to(job_dir).as_posix()), None)
                    if bundle_artifact is not None:
                        record = artifact_record(bundle_path, job_dir)
                        bundle_artifact.size_bytes = record["size_bytes"]
                        bundle_artifact.sha256 = record["sha256"]
                session.commit()
        except Exception as exc:
            logger.exception("Job %s failed", job_id)
            safe_error = sanitize_error(exc)
            with SessionLocal() as session:
                job = session.get(Job, job_id)
                if job is None:
                    return
                job.status = "failed"
                job.error = safe_error
                result_data = getattr(exc, "result_data", None)
                if isinstance(result_data, dict):
                    job.result_json = json.dumps(result_data, ensure_ascii=False)
                for path in getattr(exc, "artifact_paths", []):
                    if not isinstance(path, Path) or not path.is_file():
                        continue
                    try:
                        path.resolve().relative_to(job_dir.resolve())
                    except ValueError:
                        logger.warning("Ignoring failure artifact outside job directory: %s", path)
                        continue
                    job.artifacts.append(Artifact(**artifact_record(path, job_dir)))
                job.updated_at = datetime.now(timezone.utc)
                job.completed_at = job.updated_at
                session.commit()
            if workflow == "sdtm":
                state = read_state(job_dir)
                state.lifecycle.program_generation = "failed"
                state.lifecycle.submission_readiness = "blocked"
                write_state(job_dir, state)


def _leaf_exception_messages(exc: BaseException) -> list[str]:
    if isinstance(exc, BaseExceptionGroup):
        messages: list[str] = []
        for child in exc.exceptions:
            messages.extend(_leaf_exception_messages(child))
        return messages
    message = " ".join(str(exc).split())
    return [message] if message else []


def sanitize_error(exc: BaseException) -> str:
    messages = list(dict.fromkeys(_leaf_exception_messages(exc)))
    message = " | ".join(messages)[:1_000]
    lowered = message.lower()
    if "api key" in lowered or "authorization" in lowered or "unauthorized" in lowered:
        return "The Meta API rejected the configured credentials. Check the server configuration."
    if "timeout" in lowered or "timed out" in lowered:
        return "The Meta API request timed out. Retry the job or choose a smaller input."
    return message or "Generation failed. Review the API logs for details."


runner = JobRunner()
