import json
import shutil

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app, settings
from app.models import Job
from app.schemas import StudySummary


def test_health_does_not_expose_secret() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert "meta_api_key" not in response.json()


def test_generation_requires_meta_configuration() -> None:
    original_key, original_model = settings.meta_api_key, settings.meta_model
    settings.meta_api_key = ""
    settings.meta_model = ""
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/jobs/clinical-document",
                data={"options": '{"deidentified_acknowledged": true, "study_brief": "Synthetic study"}'},
            )
        assert response.status_code == 503
    finally:
        settings.meta_api_key, settings.meta_model = original_key, original_model


def test_unknown_workflow_is_rejected() -> None:
    original_key, original_model = settings.meta_api_key, settings.meta_model
    settings.meta_api_key, settings.meta_model = "test", "test-model"
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/jobs/nope", data={"options": "{}"})
        assert response.status_code == 404
    finally:
        settings.meta_api_key, settings.meta_model = original_key, original_model


def test_use_case_registry_is_exposed() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/use-cases")
    assert response.status_code == 200
    definitions = response.json()
    assert {item["id"] for item in definitions} == {
        "protocol-extraction",
        "clinical-document",
        "edc-design",
        "sdtm",
        "tlf",
    }
    protocol = next(item for item in definitions if item["id"] == "protocol-extraction")
    assert protocol["skill_name"] == "clinical-protocol-extraction"
    assert "properties" in protocol["result_schema"]


def test_completed_result_can_be_revised_and_rerendered() -> None:
    result = StudySummary(study_title="Original synthetic study")
    with SessionLocal() as session:
        job = Job(
            workflow="protocol-extraction",
            title="Editable protocol extraction",
            status="succeeded",
            options_json='{"deidentified_acknowledged": true}',
            input_files_json='["01-protocol.md"]',
            result_json=result.model_dump_json(),
        )
        session.add(job)
        session.commit()
        job_id = job.id

    job_dir = settings.jobs_dir / job_id
    input_dir = job_dir / "input"
    input_dir.mkdir(parents=True)
    (input_dir / "01-protocol.md").write_text("# Synthetic protocol", encoding="utf-8")
    revised = result.model_copy(update={"study_title": "Revised synthetic study"}).model_dump()
    try:
        with TestClient(app) as client:
            response = client.put(f"/api/v1/jobs/{job_id}/result", json={"result": revised})
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["result"]["study_title"] == "Revised synthetic study"
        assert any(item["name"] == "protocol-extraction.md" for item in payload["artifacts"])
        rendered = (job_dir / "output" / "protocol-extraction.json").read_text(encoding="utf-8")
        assert json.loads(rendered)["study_title"] == "Revised synthetic study"
    finally:
        with SessionLocal() as session:
            stored = session.get(Job, job_id)
            if stored:
                session.delete(stored)
                session.commit()
        shutil.rmtree(job_dir, ignore_errors=True)
