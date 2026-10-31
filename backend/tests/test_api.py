import io
import json
import shutil
import wave
from threading import Event
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.artifacts import artifact_record
from app.db import SessionLocal
from app.core_conformance import CoreConformanceResult
from app.main import app, settings
from app.jobs import runner
from app.models import Artifact, Job
from app.schemas import StudySummary


def test_health_does_not_expose_secret() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert "meta_api_key" not in response.json()


def test_artifact_can_be_requested_inline_for_review() -> None:
    with SessionLocal() as session:
        job = Job(
            workflow="sdtm",
            title="Inline artifact review",
            status="succeeded",
            options_json="{}",
            input_files_json="[]",
        )
        session.add(job)
        session.flush()
        job_dir = settings.jobs_dir / job.id
        artifact_path = job_dir / "output" / "define.xml"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text("<ODM />", encoding="utf-8")
        artifact = Artifact(**artifact_record(artifact_path, job_dir))
        job.artifacts.append(artifact)
        session.commit()
        job_id, artifact_id = job.id, artifact.id
    try:
        with TestClient(app) as client:
            response = client.get(f"/api/v1/jobs/{job_id}/artifacts/{artifact_id}?inline=true")
        assert response.status_code == 200
        assert response.headers["content-disposition"].startswith("inline;")
        assert response.text == "<ODM />"
    finally:
        with SessionLocal() as session:
            stored = session.get(Job, job_id)
            if stored:
                session.delete(stored)
                session.commit()
        shutil.rmtree(job_dir, ignore_errors=True)


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


def test_retry_schedules_job_on_application_event_loop(monkeypatch) -> None:
    original_key, original_model = settings.meta_api_key, settings.meta_model
    settings.meta_api_key, settings.meta_model = "test", "test-model"
    started = Event()
    received_job_ids: list[str] = []

    async def fake_run(job_id: str) -> None:
        received_job_ids.append(job_id)
        started.set()

    monkeypatch.setattr(runner, "run", fake_run)
    with SessionLocal() as session:
        job = Job(
            workflow="tlf",
            title="Retry scheduling",
            status="failed",
            options_json='{"deidentified_acknowledged": true}',
            input_files_json="[]",
            error="Previous attempt failed.",
        )
        session.add(job)
        session.commit()
        job_id = job.id
    progress_path = settings.jobs_dir / job_id / "agent" / "progress.json"
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    progress_path.write_text('{"status": "paused"}', encoding="utf-8")
    try:
        with TestClient(app) as client:
            response = client.post(f"/api/v1/jobs/{job_id}/retry")
            assert response.status_code == 202, response.text
            assert response.json()["status"] == "queued"
            assert started.wait(1)
        assert received_job_ids == [job_id]
        assert not progress_path.exists()
    finally:
        settings.meta_api_key, settings.meta_model = original_key, original_model
        with SessionLocal() as session:
            stored = session.get(Job, job_id)
            if stored:
                session.delete(stored)
                session.commit()
        shutil.rmtree(settings.jobs_dir / job_id, ignore_errors=True)


def test_sdtm_job_accepts_edc_without_blank_crf(monkeypatch) -> None:
    original_key, original_model = settings.meta_api_key, settings.meta_model
    settings.meta_api_key, settings.meta_model = "test", "test-model"
    queued: list[str] = []
    monkeypatch.setattr("app.main.runner.enqueue", queued.append)
    job_id = ""
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/jobs/sdtm",
                data={"options": '{"deidentified_acknowledged": true, "languages": ["r"]}'},
                files={"files": ("edc.json", b'{"study": "SYN-101", "datasets": []}', "application/json")},
            )
        assert response.status_code == 202, response.text
        job_id = response.json()["id"]
        assert response.json()["status"] == "queued"
        assert queued == [job_id]
    finally:
        settings.meta_api_key, settings.meta_model = original_key, original_model
        if job_id:
            with SessionLocal() as session:
                stored = session.get(Job, job_id)
                if stored:
                    session.delete(stored)
                    session.commit()
            shutil.rmtree(settings.jobs_dir / job_id, ignore_errors=True)


def test_unknown_workflow_is_rejected() -> None:
    original_key, original_model = settings.meta_api_key, settings.meta_model
    settings.meta_api_key, settings.meta_model = "test", "test-model"
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/jobs/nope", data={"options": "{}"})
        assert response.status_code == 404
    finally:
        settings.meta_api_key, settings.meta_model = original_key, original_model


def test_sdtm_demo_samples_are_downloadable_with_stable_logical_names() -> None:
    with TestClient(app) as client:
        metadata = client.get("/api/v1/samples/sdtm-demo-edc.json")
        raw_dm = client.get("/api/v1/samples/sdtm-raw-dm.csv")
        mismatch = client.get("/api/v1/samples/sdtm-raw-ae-mismatch.csv")
        report = client.get("/api/v1/samples/pinnacle21-demo-report.csv")
    assert metadata.status_code == raw_dm.status_code == mismatch.status_code == report.status_code == 200
    assert json.loads(metadata.text)["study"] == "SYN-DMAE-001"
    assert raw_dm.text.startswith("STUDYID,USUBJID")
    assert "filename=\"RAW_AE.csv\"" in mismatch.headers["content-disposition"]
    assert mismatch.text.startswith("STUDYID,USUBJID,AESEQ,AETERM_RAW")
    assert "Rule ID,Severity" in report.text


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
    tlf = next(item for item in definitions if item["id"] == "tlf")
    assert tlf["stages"] == [
        "Output inventory",
        "Analysis & display specification",
        "Programming augmentation",
    ]
    assert "programs" in tlf["result_schema"]["properties"]
    assert "xlsx" in tlf["output_formats"]


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


def test_agent_progress_returns_detailed_source_safe_turns() -> None:
    with TestClient(app) as client:
        with SessionLocal() as session:
            job = Job(
                workflow="protocol-extraction",
                title="Detailed agent progress",
                status="running",
                options_json='{"deidentified_acknowledged": true}',
                input_files_json='[]',
            )
            session.add(job)
            session.commit()
            job_id = job.id
        progress_path = settings.jobs_dir / job_id / "agent" / "progress.json"
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        progress_path.write_text(
            json.dumps(
                {
                    "agent_id": "clinical-protocol-extraction-agent",
                    "workflow": "protocol-extraction",
                    "model": "meta-test-model",
                    "status": "running",
                    "turn": 1,
                    "max_turns": 20,
                    "stage": "Extraction",
                    "stage_index": 1,
                    "stage_count": 2,
                    "completed_stages": [],
                    "total_source_chunks": 2,
                    "read_source_chunks": [1],
                    "started_at": "2026-10-30T12:00:00+00:00",
                    "updated_at": "2026-10-30T12:00:01+00:00",
                    "messages": [{"role": "tool", "content": "private source content"}],
                    "events": [
                        {
                            "turn": 1,
                            "type": "tool",
                            "name": "read_source_chunk",
                            "stage": "Extraction",
                            "ok": True,
                            "summary": "Read one bounded section of the submitted source material.",
                            "intent": "Review source chunk 1 so the draft is grounded in the submitted material.",
                            "input_summary": "Requested source chunk 1 of 2.",
                            "output_summary": "Reviewed source chunk 1; 1 chunk(s) remain.",
                            "input_details": {"Chunk requested": 1},
                            "output_details": {"Status": "Reviewed", "Chunks remaining": 1},
                            "evidence": ["Submitted source · chunk 1 of 2"],
                            "duration_ms": 25,
                            "occurred_at": "2026-10-30T12:00:01+00:00",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        try:
            response = client.get(f"/api/v1/jobs/{job_id}/agent")
            assert response.status_code == 200
            payload = response.json()
            assert payload["model"] == "meta-test-model"
            assert payload["started_at"] == "2026-10-30T12:00:00Z"
            assert payload["events"][0]["input_summary"] == "Requested source chunk 1 of 2."
            assert payload["events"][0]["output_summary"].startswith("Reviewed source chunk 1")
            assert payload["events"][0]["intent"].startswith("Review source chunk 1")
            assert payload["events"][0]["input_details"] == {"Chunk requested": 1}
            assert payload["events"][0]["output_details"]["Chunks remaining"] == 1
            assert payload["events"][0]["evidence"] == ["Submitted source · chunk 1 of 2"]
            assert payload["events"][0]["duration_ms"] == 25
            assert "messages" not in payload
            assert "private source content" not in response.text
        finally:
            with SessionLocal() as session:
                stored = session.get(Job, job_id)
                if stored:
                    session.delete(stored)
                    session.commit()
            shutil.rmtree(settings.jobs_dir / job_id, ignore_errors=True)


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
            options_json='{"deidentified_acknowledged": true, "languages": ["r"], "_review_stage": "edc_source"}',
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


def test_reviewed_domain_and_variable_mappings_resume_each_sdtm_gate(monkeypatch) -> None:
    queued = []
    monkeypatch.setattr("app.main.runner.enqueue", queued.append)
    source_spec = {
        "study_name": "SYN-101",
        "datasets": [
            {
                "name": "RAW_DM",
                "label": "Demographics",
                "variables": [
                    {
                        "name": "AGE",
                        "label": "Age",
                        "data_type": "integer",
                        "provenance": {"file": "edc.json"},
                    }
                ],
                "provenance": {"file": "edc.json"},
            }
        ],
    }
    domain_mapping = {
        "study_name": "SYN-101",
        "domain_mappings": [
            {
                "source_dataset": "RAW_DM",
                "source_type": "raw",
                "target_domain": "DM",
                "relationship": "direct",
                "rationale": "Demographics source",
            }
        ],
    }
    variable_mapping = {
        "study_name": "SYN-101",
        "datasets": [
            {
                "domain": "DM",
                "description": "Demographics",
                "variables": [
                    {
                        "name": "AGE",
                        "label": "Age",
                        "data_type": "Num",
                        "source_dataset": "RAW_DM",
                        "source_field": "AGE",
                    }
                ],
            }
        ],
    }

    with SessionLocal() as session:
        domain_job = Job(
            workflow="sdtm",
            title="Domain review",
            status="review_required",
            options_json=json.dumps({"edc_source_spec": source_spec, "_review_stage": "domain_mapping"}),
            input_files_json='["01-edc.json"]',
        )
        variable_job = Job(
            workflow="sdtm",
            title="Variable review",
            status="review_required",
            options_json=json.dumps(
                {
                    "edc_source_spec": source_spec,
                    "sdtm_domain_mapping": domain_mapping,
                    "_review_stage": "variable_mapping",
                }
            ),
            input_files_json='["01-edc.json"]',
        )
        session.add_all([domain_job, variable_job])
        session.commit()
        domain_job_id, variable_job_id = domain_job.id, variable_job.id
    try:
        with TestClient(app) as client:
            domain_response = client.put(
                f"/api/v1/jobs/{domain_job_id}/sdtm-domain-mapping",
                json={"domain_mapping": domain_mapping},
            )
            variable_response = client.put(
                f"/api/v1/jobs/{variable_job_id}/sdtm-variable-mapping",
                json={"variable_mapping": variable_mapping},
            )
        assert domain_response.status_code == 202, domain_response.text
        assert variable_response.status_code == 202, variable_response.text
        assert domain_response.json()["review_stage"] is None
        assert variable_response.json()["review_stage"] is None
        assert queued == [domain_job_id, variable_job_id]
        with SessionLocal() as session:
            stored_domain = session.get(Job, domain_job_id)
            stored_variable = session.get(Job, variable_job_id)
            assert stored_domain is not None and stored_variable is not None
            assert json.loads(stored_domain.options_json)["sdtm_domain_mapping"]["domain_mappings"][0]["target_domain"] == "DM"
            assert json.loads(stored_variable.options_json)["sdtm_variable_mapping"]["datasets"][0]["domain"] == "DM"
    finally:
        with SessionLocal() as session:
            for job_id in (domain_job_id, variable_job_id):
                stored = session.get(Job, job_id)
                if stored:
                    session.delete(stored)
            session.commit()


def test_reviewed_tlf_inventory_resumes_shell_generation(monkeypatch) -> None:
    queued = []
    monkeypatch.setattr("app.main.runner.enqueue", queued.append)
    inventory = {
        "study_name": "SYN-101",
        "outputs": [{
            "output_id": "T-01",
            "output_type": "table",
            "title": "Change from baseline",
            "population": "Intent-to-Treat",
            "source_reference": "SAP 7.1",
        }],
    }
    with SessionLocal() as session:
        job = Job(
            workflow="tlf",
            title="TLF inventory review",
            status="review_required",
            options_json=json.dumps({"languages": ["r", "sas"], "_review_stage": "tlf_inventory"}),
            input_files_json='["01-sap.md"]',
            result_json=json.dumps(inventory),
        )
        session.add(job)
        session.commit()
        job_id = job.id
    try:
        with TestClient(app) as client:
            response = client.put(f"/api/v1/jobs/{job_id}/tlf-inventory", json={"inventory_plan": inventory})
        assert response.status_code == 202, response.text
        assert response.json()["status"] == "queued"
        assert queued == [job_id]
        with SessionLocal() as session:
            stored = session.get(Job, job_id)
            assert stored is not None
            assert json.loads(stored.options_json)["tlf_inventory_plan"]["outputs"][0]["output_id"] == "T-01"
    finally:
        with SessionLocal() as session:
            stored = session.get(Job, job_id)
            if stored:
                session.delete(stored)
                session.commit()


def test_review_feedback_records_user_turn_and_reruns_current_stage(monkeypatch) -> None:
    queued = []
    monkeypatch.setattr("app.main.runner.enqueue", queued.append)
    original_key, original_model = settings.meta_api_key, settings.meta_model
    settings.meta_api_key, settings.meta_model = "test", "test-model"
    draft = {
        "study_name": "SYN-101",
        "outputs": [{
            "output_id": "T-01",
            "output_type": "table",
            "title": "Adverse events",
            "population": "TODO: confirm population",
            "source_reference": "SAP 7.1",
        }],
    }
    with SessionLocal() as session:
        job = Job(
            workflow="tlf",
            title="TLF feedback review",
            status="review_required",
            options_json=json.dumps({"languages": ["r"], "_review_stage": "tlf_inventory"}),
            input_files_json='["01-sap.md"]',
            result_json=json.dumps(draft),
        )
        session.add(job)
        session.commit()
        job_id = job.id
    progress_path = settings.jobs_dir / job_id / "agent" / "progress.json"
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    progress_path.write_text(json.dumps({
        "agent_id": "clinical-tlf-artifacts-agent",
        "workflow": "tlf",
        "status": "completed",
        "turn": 3,
        "max_turns": 60,
        "stage": "Output inventory",
        "events": [{"turn": 3, "type": "tool", "name": "submit_result", "ok": True}],
    }), encoding="utf-8")
    try:
        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/jobs/{job_id}/feedback",
                json={"message": "Use the Safety population for all adverse-event outputs."},
            )
        assert response.status_code == 202, response.text
        assert response.json()["status"] == "queued"
        assert response.json()["result"] == draft
        assert queued == [job_id]
        with SessionLocal() as session:
            stored = session.get(Job, job_id)
            assert stored is not None
            saved_options = json.loads(stored.options_json)
            assert saved_options["review_feedback"][-1]["stage"] == "tlf_inventory"
            assert saved_options["_review_revision_result"] == draft
        trace = json.loads(progress_path.read_text(encoding="utf-8"))
        assert trace["status"] == "queued"
        assert trace["turn"] == 4
        assert trace["events"][-1]["actor"] == "user"
        assert trace["events"][-1]["summary"].startswith("Use the Safety population")
    finally:
        settings.meta_api_key, settings.meta_model = original_key, original_model
        with SessionLocal() as session:
            stored = session.get(Job, job_id)
            if stored:
                session.delete(stored)
                session.commit()
        shutil.rmtree(settings.jobs_dir / job_id, ignore_errors=True)


def test_voice_guidance_is_transcribed_for_review_without_storing_audio(monkeypatch) -> None:
    captured: list[bytes] = []

    async def fake_transcribe(_client, audio: bytes, filename: str = "guidance.wav") -> dict:
        captured.append(audio)
        assert filename == "guidance.wav"
        return {
            "transcript": "Use the Safety population for every adverse-event output.",
            "audioDurationMs": 1250,
            "sessionId": "voice-session",
        }

    monkeypatch.setattr("app.main.MetaAIClient.transcribe_wav", fake_transcribe)
    original_key, original_voice_model = settings.meta_api_key, settings.meta_transcription_model
    settings.meta_api_key = "test"
    settings.meta_transcription_model = "muse-voice-transcribe-1.0"
    with SessionLocal() as session:
        job = Job(
            workflow="tlf",
            title="TLF voice review",
            status="review_required",
            options_json=json.dumps({"_review_stage": "tlf_inventory"}),
            input_files_json="[]",
        )
        session.add(job)
        session.commit()
        job_id = job.id
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, "wb") as recording:
        recording.setnchannels(1)
        recording.setsampwidth(2)
        recording.setframerate(24_000)
        recording.writeframes(b"\x00\x00" * 2_400)
    try:
        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/jobs/{job_id}/transcription",
                files={"audio": ("guidance.wav", wav_buffer.getvalue(), "audio/wav")},
            )
        assert response.status_code == 200, response.text
        assert response.json() == {
            "transcript": "Use the Safety population for every adverse-event output.",
            "model": "muse-voice-transcribe-1.0",
            "duration_ms": 1250,
            "session_id": "voice-session",
        }
        assert len(captured) == 1
        assert captured[0].startswith(b"RIFF")
        assert not (settings.jobs_dir / job_id / "input" / "guidance.wav").exists()
    finally:
        settings.meta_api_key, settings.meta_transcription_model = original_key, original_voice_model
        with SessionLocal() as session:
            stored = session.get(Job, job_id)
            if stored:
                session.delete(stored)
                session.commit()
        shutil.rmtree(settings.jobs_dir / job_id, ignore_errors=True)


def test_voice_guidance_rejects_non_wav_audio_before_meta_call(monkeypatch) -> None:
    called = False

    async def fake_transcribe(_client, _audio: bytes, filename: str = "guidance.wav") -> dict:
        nonlocal called
        called = True
        return {"transcript": "unexpected"}

    monkeypatch.setattr("app.main.MetaAIClient.transcribe_wav", fake_transcribe)
    original_key = settings.meta_api_key
    settings.meta_api_key = "test"
    with SessionLocal() as session:
        job = Job(
            workflow="tlf",
            title="Invalid voice review",
            status="review_required",
            options_json=json.dumps({"_review_stage": "tlf_inventory"}),
            input_files_json="[]",
        )
        session.add(job)
        session.commit()
        job_id = job.id
    try:
        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/jobs/{job_id}/transcription",
                files={"audio": ("guidance.webm", b"not wav", "audio/webm")},
            )
        assert response.status_code == 415
        assert called is False
    finally:
        settings.meta_api_key = original_key
        with SessionLocal() as session:
            stored = session.get(Job, job_id)
            if stored:
                session.delete(stored)
                session.commit()


def test_reviewed_tlf_shell_resumes_programming_augmentation(monkeypatch) -> None:
    queued = []
    monkeypatch.setattr("app.main.runner.enqueue", queued.append)
    shell = {
        "study_name": "SYN-101",
        "outputs": [{
            "output_id": "T-01",
            "output_type": "table",
            "title": "Change from baseline",
            "population": "Intent-to-Treat",
            "population_filter": "ADSL.ITTFL = 'Y'",
            "analysis_datasets": ["ADSL", "ADEFF"],
            "source_variables": [{"dataset": "ADEFF", "variable": "CHG"}],
            "treatment_variable": "ADSL.TRT01P",
            "analysis_method": "ANCOVA",
            "columns": [{"column_id": "TRT", "heading": "Treatment", "source": "ADSL.TRT01P", "format": "text"}],
            "rows": [{"row_id": "LSMEAN", "label": "LS mean", "source": "ADEFF.CHG", "statistic": "LS mean", "format": "8.2"}],
            "source_reference": "SAP 7.1",
            "blocking_items": ["Confirm missing-data handling"],
        }],
    }
    inventory = {
        "study_name": shell["study_name"],
        "outputs": [{
            key: shell["outputs"][0][key]
            for key in ("output_id", "output_type", "title", "population", "source_reference")
        }],
    }
    with SessionLocal() as session:
        job = Job(
            workflow="tlf",
            title="TLF shell review",
            status="review_required",
            options_json=json.dumps({"languages": ["r", "sas"], "tlf_inventory_plan": inventory, "_review_stage": "tlf_shell"}),
            input_files_json='["01-sap.md"]',
            result_json=json.dumps(shell),
        )
        session.add(job)
        session.commit()
        job_id = job.id
    try:
        with TestClient(app) as client:
            response = client.put(f"/api/v1/jobs/{job_id}/tlf-shell", json={"shell_plan": shell})
        assert response.status_code == 202, response.text
        assert response.json()["status"] == "queued"
        assert response.json()["review_stage"] is None
        assert queued == [job_id]
        with SessionLocal() as session:
            stored = session.get(Job, job_id)
            assert stored is not None
            assert json.loads(stored.options_json)["tlf_shell_plan"]["outputs"][0]["output_id"] == "T-01"
    finally:
        with SessionLocal() as session:
            stored = session.get(Job, job_id)
            if stored:
                session.delete(stored)
                session.commit()


def test_reviewed_tlf_programming_resumes_final_render(monkeypatch) -> None:
    queued = []
    monkeypatch.setattr("app.main.runner.enqueue", queued.append)
    shell = {
        "study_name": "SYN-101",
        "outputs": [{
            "output_id": "T-01",
            "output_type": "table",
            "title": "Change from baseline",
            "population": "Intent-to-Treat",
            "population_filter": "ADSL.ITTFL = 'Y'",
            "analysis_datasets": ["ADSL", "ADEFF"],
            "source_variables": [{"dataset": "ADEFF", "variable": "CHG"}],
            "treatment_variable": "ADSL.TRT01P",
            "analysis_method": "ANCOVA",
            "columns": [{"column_id": "TRT", "heading": "Treatment", "source": "ADSL.TRT01P", "format": "text"}],
            "rows": [{"row_id": "LSMEAN", "label": "LS mean", "source": "ADEFF.CHG", "statistic": "LS mean", "format": "8.2"}],
            "source_reference": "SAP 7.1",
        }],
    }
    inventory = {
        "study_name": shell["study_name"],
        "outputs": [{
            key: shell["outputs"][0][key]
            for key in ("output_id", "output_type", "title", "population", "source_reference")
        }],
    }
    programming = {
        **shell,
        "programs": [{
            "output_id": "T-01",
            "input_datasets": ["ADSL", "ADEFF"],
            "adam_sources": [{"dataset": "ADEFF", "variable": "CHG"}],
            "derivation_steps": ["Join ADSL and ADEFF", "Fit ANCOVA"],
            "r_code": "fit <- lm(CHG ~ TRT01P + BASE, data = adeff)",
            "sas_code": "proc glm data=adeff; model chg=trt01p base; run;",
        }],
    }
    with SessionLocal() as session:
        job = Job(
            workflow="tlf",
            title="TLF programming review",
            status="review_required",
            options_json=json.dumps({
                "languages": ["r", "sas"],
                "tlf_inventory_plan": inventory,
                "tlf_shell_plan": shell,
                "_review_stage": "tlf_programming",
            }),
            input_files_json='["01-sap.md"]',
            result_json=json.dumps(programming),
        )
        session.add(job)
        session.commit()
        job_id = job.id
    try:
        with TestClient(app) as client:
            response = client.put(f"/api/v1/jobs/{job_id}/tlf-programming", json={"programming_plan": programming})
        assert response.status_code == 202, response.text
        assert response.json()["status"] == "queued"
        assert queued == [job_id]
        with SessionLocal() as session:
            stored = session.get(Job, job_id)
            assert stored is not None
            saved = json.loads(stored.options_json)["tlf_programming_plan"]
            assert saved["programs"][0]["adam_sources"][0]["variable"] == "CHG"
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
