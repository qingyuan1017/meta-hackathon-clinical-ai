from __future__ import annotations

import asyncio
import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from .artifacts import artifact_record
from .config import get_settings
from .db import SessionLocal
from .models import Artifact, Job
from .schemas import DISCLAIMER
from .workflows import WorkflowService


logger = logging.getLogger(__name__)


class JobRunner:
    def __init__(self) -> None:
        self.tasks: set[asyncio.Task] = set()

    def enqueue(self, job_id: str) -> None:
        task = asyncio.create_task(self.run(job_id), name=f"job-{job_id}")
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

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
            result = await WorkflowService().execute(
                workflow,
                inputs=inputs,
                options=options,
                output_dir=output_dir,
            )
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


def sanitize_error(exc: Exception) -> str:
    message = " ".join(str(exc).split())[:1_000]
    lowered = message.lower()
    if "api key" in lowered or "authorization" in lowered or "unauthorized" in lowered:
        return "The Meta API rejected the configured credentials. Check the server configuration."
    if "timeout" in lowered:
        return "The Meta API request timed out. Retry the job or choose a smaller input."
    return message or "Generation failed. Review the API logs for details."


runner = JobRunner()
