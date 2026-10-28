import json
import shutil
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.core_conformance import CoreConformanceResult
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
    assert protocol["agent_id"] == "clinical-protocol-extraction-agent"
    assert "properties" in protocol["result_schema"]
    sdtm = next(item for item in definitions if item["id"] == "sdtm")
    assert sdtm["stages"] == [
        "Domain mapping",
        "Variable & value-level mapping",
        "Rule augmentation",
    ]
    assert "domain_rule_augmentations" in sdtm["result_schema"]["properties"]


def test_agent_registry_is_exposed() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/agents")
    assert response.status_code == 200
    agents = response.json()
    assert {item["workflow"] for item in agents} == {
        "protocol-extraction",
        "clinical-document",
        "edc-design",
        "sdtm",
        "tlf",
    }
    assert all("submit_result" in item["tools"] for item in agents)


def test_cdisc_dataset_proxy_returns_versioned_metadata(monkeypatch) -> None:
    calls = []

    class FakeMCPClient:
        def __init__(self, url):
            calls.append(("url", url))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def call_tool(self, name, arguments):
            calls.append((name, arguments))
            return SimpleNamespace(
                is_error=False,
                structured_content={
                    "name": "DM",
                    "label": "Demographics",
                    "variables": [{"name": "USUBJID", "label": "Unique Subject Identifier"}],
                },
                content=[],
            )

    monkeypatch.setattr("app.main.MCPClient", FakeMCPClient)
    monkeypatch.setattr(settings, "cdisc_mcp_enabled", True)
    monkeypatch.setattr(settings, "cdisc_mcp_url", "http://cdisc.test/mcp")

    with TestClient(app) as client:
        response = client.get("/api/v1/standards/sdtm/datasets/dm?version=3-4&standard=sdtmig")

    assert response.status_code == 200
    assert response.json()["payload"]["variables"][0]["name"] == "USUBJID"
    assert calls[-1] == (
        "cdisc_get_dataset",
        {"standard": "sdtmig", "version": "3-4", "dataset": "DM"},
    )


def test_queued_job_has_safe_agent_progress_summary() -> None:
    with TestClient(app) as client:
        with SessionLocal() as session:
            job = Job(
                workflow="protocol-extraction",
                title="Agent progress",
                status="queued",
                options_json='{"deidentified_acknowledged": true}',
                input_files_json='[]',
            )
            session.add(job)
            session.commit()
            job_id = job.id
        try:
            response = client.get(f"/api/v1/jobs/{job_id}/agent")
            assert response.status_code == 200
            payload = response.json()
            assert payload["agent_id"] == "clinical-protocol-extraction-agent"
            assert payload["status"] == "queued"
            assert payload["events"] == []
        finally:
            with SessionLocal() as session:
                stored = session.get(Job, job_id)
                if stored:
                    session.delete(stored)
                    session.commit()


def test_reviewed_edc_source_spec_resumes_sdtm_job(monkeypatch) -> None:
    queued = []
    monkeypatch.setattr("app.main.runner.enqueue", queued.append)
    source_spec = {
        "study_name": "SYN-101",
        "datasets": [
            {
                "name": "RAW_DM",
                "label": "Demographics",
                "key_variables": ["SUBJID"],
                "variables": [
                    {
                        "name": "SUBJID",
                        "label": "Subject identifier",
                        "data_type": "text",
                        "provenance": {"file": "edc.json"},
                    }
                ],
                "provenance": {"file": "edc.json"},
            }
        ],
    }
    with SessionLocal() as session:
        job = Job(
            workflow="sdtm",
            title="SDTM source review",
            status="review_required",
            options_json='{"deidentified_acknowledged": true, "languages": ["r"]}',
            input_files_json='["01-blank.pdf", "02-edc.json"]',
            result_json=json.dumps(source_spec),
        )
        session.add(job)
        session.commit()
        job_id = job.id
    try:
        with TestClient(app) as client:
            response = client.put(
                f"/api/v1/jobs/{job_id}/edc-source-spec",
                json={"source_spec": source_spec},
            )
        assert response.status_code == 202, response.text
        assert response.json()["status"] == "queued"
        assert queued == [job_id]
        with SessionLocal() as session:
            stored = session.get(Job, job_id)
            assert stored is not None
            assert json.loads(stored.options_json)["edc_source_spec"]["datasets"][0]["name"] == "RAW_DM"
    finally:
        with SessionLocal() as session:
            stored = session.get(Job, job_id)
            if stored:
                session.delete(stored)
                session.commit()


def test_completed_result_can_be_revised_and_rerendered(monkeypatch) -> None:
    def conformant_core(usdm_path, output_dir):
        report = output_dir / "core-report.json"
        decision = output_dir / "core-conformance.json"
        report.write_text('{"Rules_Report": []}', encoding="utf-8")
        decision.write_text('{"conformant": true}', encoding="utf-8")
        return CoreConformanceResult(
            conformant=True,
            report_path=report,
            decision_path=decision,
            status_counts={"SUCCESS": 207},
            blocking_rules=(),
            allowed_skipped_rules=(),
            reported_rule_count=207,
        )

    monkeypatch.setattr("app.artifacts.run_core_conformance", conformant_core)
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
