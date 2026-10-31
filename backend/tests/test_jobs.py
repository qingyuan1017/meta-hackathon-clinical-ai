import json
from types import SimpleNamespace

from app.db import SessionLocal
from app.jobs import JobRunner
from app.models import Job
from app.workflows import WorkflowResult
from app.review_patches import new_patch_request
from app.schemas import TLFInventoryPlan
from app.schemas.reviews import ReviewScope
from app.use_cases.sdtm import SDTMUseCase


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


async def test_job_runner_keeps_baseline_and_persists_scoped_patch_preview(tmp_path, monkeypatch) -> None:
    baseline = TLFInventoryPlan.model_validate({
        "study_name": "SYN-101",
        "outputs": [{
            "output_id": "T-01", "output_type": "table", "title": "Adverse events",
            "population": "TODO", "source_reference": "SAP 7.1",
        }],
    }).model_dump(mode="json")
    candidate = json.loads(json.dumps(baseline))
    candidate["outputs"][0]["population"] = "Safety"
    candidate["outputs"][0]["title"] = "Out-of-scope title rewrite"
    request = new_patch_request(
        stage="tlf_inventory",
        message="Use Safety population.",
        scope=ReviewScope(paths=["/outputs/0/population"]),
        baseline=baseline,
    )

    class FakeWorkflowService:
        async def prepare_review(self, workflow, *, inputs, options, job_dir):
            assert workflow == "tlf"
            return WorkflowResult(result=candidate, paths=[], warnings=[], review_stage="tlf_inventory")

    monkeypatch.setattr("app.jobs.WorkflowService", FakeWorkflowService)
    monkeypatch.setattr("app.jobs.get_settings", lambda: SimpleNamespace(jobs_dir=tmp_path))
    with SessionLocal() as session:
        job = Job(
            workflow="tlf",
            title="Scoped review",
            status="queued",
            options_json=json.dumps({
                "_review_patch_request": request,
                "_review_revision_result": baseline,
            }),
            input_files_json="[]",
            result_json=json.dumps(baseline),
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
            assert json.loads(stored.result_json) == baseline
            options = json.loads(stored.options_json)
            patch = options["_pending_review_patch"]
            assert [item["path"] for item in patch["operations"]] == ["/outputs/output_id=T-01/population"]
            assert "Out-of-scope title rewrite" not in json.dumps(patch)
            assert (tmp_path / job_id / "reviews" / request["transaction_id"] / "proposed.json").is_file()
    finally:
        with SessionLocal() as session:
            stored = session.get(Job, job_id)
            if stored:
                session.delete(stored)
                session.commit()


def test_sdtm_agent_options_preserve_scoped_revision_baseline() -> None:
    baseline = {"source_spec": {"datasets": []}}
    options = {
        "edc_source_spec": {"datasets": []},
        "review_feedback": [{"stage": "edc_source", "message": "Revise DM."}],
        "_review_revision_result": baseline,
        "_review_patch_request": {"transaction_id": "not-needed-in-prompt"},
        "_review_stage": "edc_source",
    }
    sanitized = SDTMUseCase._agent_options(options)
    assert sanitized["_review_revision_result"] == baseline
    assert sanitized["review_feedback"] == options["review_feedback"]
    assert "edc_source_spec" not in sanitized
    assert "_review_patch_request" not in sanitized
    assert "_review_stage" not in sanitized
