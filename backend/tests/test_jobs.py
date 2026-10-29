import json
from types import SimpleNamespace

from app.db import SessionLocal
from app.jobs import JobRunner
from app.models import Job
from app.workflows import WorkflowResult


async def test_sdtm_job_pauses_for_edc_source_review(tmp_path, monkeypatch) -> None:
    source_spec = {
        "study_name": "SYN-101",
        "datasets": [
            {
                "name": "RAW_DM",
                "label": "Demographics",
                "variables": [],
            }
        ],
    }

    class FakeWorkflowService:
        async def prepare_review(self, workflow, *, inputs, options, job_dir):
            assert workflow == "sdtm"
            return WorkflowResult(
                result=source_spec,
                paths=[],
                warnings=["Review source metadata"],
                review_stage="edc_source",
            )

        async def execute(self, *_args, **_kwargs):
            raise AssertionError("Final generation must not run before source approval.")

    monkeypatch.setattr("app.jobs.WorkflowService", FakeWorkflowService)
    monkeypatch.setattr("app.jobs.get_settings", lambda: SimpleNamespace(jobs_dir=tmp_path))
    with SessionLocal() as session:
        job = Job(
            workflow="sdtm",
            title="Review gate",
            status="queued",
            options_json='{"deidentified_acknowledged": true}',
            input_files_json='["01-blank.pdf", "02-edc.json"]',
        )
        session.add(job)
        session.commit()
        job_id = job.id
    try:
        await JobRunner().run(job_id)
        with SessionLocal() as session:
            stored = session.get(Job, job_id)
            assert stored is not None
            assert stored.status == "review_required"
            assert json.loads(stored.options_json)["_review_stage"] == "edc_source"
            assert json.loads(stored.result_json)["study_name"] == "SYN-101"
            assert "Review source metadata" in json.loads(stored.warnings_json)
    finally:
        with SessionLocal() as session:
            stored = session.get(Job, job_id)
            if stored:
                session.delete(stored)
                session.commit()
