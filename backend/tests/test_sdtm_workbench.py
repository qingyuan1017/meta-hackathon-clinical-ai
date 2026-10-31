from __future__ import annotations

import io
import shutil

from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas

from app.db import SessionLocal
from app.main import app, settings
from app.models import Job
from app.sdtm_workbench import inventory_raw_dataset, logical_dataset_name, read_state


def _searchable_pdf() -> bytes:
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    pdf.drawString(72, 720, "Synthetic blank CRF")
    pdf.save()
    return buffer.getvalue()


def test_csv_inventory_is_deterministic_and_contains_no_rows(tmp_path) -> None:
    path = tmp_path / "dm.csv"
    path.write_text("USUBJID,AGE,SEX\nSYN-001,42,F\nSYN-002,35,M\n", encoding="utf-8")
    inventory = inventory_raw_dataset(path, "dm.csv")
    assert inventory.logical_name == "DM"
    assert inventory.row_count == 2
    assert [column.name for column in inventory.columns] == ["USUBJID", "AGE", "SEX"]
    serialized = inventory.model_dump_json()
    assert "SYN-001" not in serialized
    assert len(inventory.sha256) == 64


def test_invalid_and_duplicate_logical_names_are_rejected(tmp_path) -> None:
    assert logical_dataset_name("ae.csv") == "AE"
    try:
        logical_dataset_name("a-dataset-name-that-is-too-long.csv")
    except ValueError as exc:
        assert "valid SAS dataset name" in str(exc)
    else:
        raise AssertionError("long logical name should be rejected")


def test_sdtm_submission_accepts_independently_optional_raw_crf_and_report(monkeypatch) -> None:
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
                files=[
                    ("files", ("edc.json", b'{"study": "SYN-101", "datasets": []}', "application/json")),
                    ("raw_files", ("dm.csv", b"USUBJID,AGE\nSYN-001,42\n", "text/csv")),
                    ("crf_file", ("blank.pdf", _searchable_pdf(), "application/pdf")),
                    ("validation_report", ("p21.csv", b"Rule ID,Severity,Message\nSD0001,Warning,Example\n", "text/csv")),
                ],
            )
        assert response.status_code == 202, response.text
        job_id = response.json()["id"]
        state = read_state(settings.jobs_dir / job_id)
        assert state.lifecycle.execution == "not_run"
        assert state.lifecycle.validation == "not_run"
        assert state.lifecycle.submission_readiness == "blocked"
        assert state.inputs.blank_crf is not None
        assert state.inputs.validation_report is not None
        assert [item.logical_name for item in state.inputs.raw_datasets] == ["DM"]
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


def test_duplicate_raw_dataset_names_fail_before_queueing(monkeypatch) -> None:
    original_key, original_model = settings.meta_api_key, settings.meta_model
    settings.meta_api_key, settings.meta_model = "test", "test-model"
    monkeypatch.setattr("app.main.runner.enqueue", lambda _: None)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/jobs/sdtm",
                data={"options": '{"deidentified_acknowledged": true}'},
                files=[
                    ("files", ("edc.json", b'{"study": "SYN"}', "application/json")),
                    ("raw_files", ("dm.csv", b"A\n1\n", "text/csv")),
                    ("raw_files", ("DM.CSV", b"A\n2\n", "text/csv")),
                ],
            )
        assert response.status_code == 422
        assert "Duplicate raw dataset logical name" in response.text
    finally:
        settings.meta_api_key, settings.meta_model = original_key, original_model
