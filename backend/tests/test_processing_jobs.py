from __future__ import annotations

from typing import Dict
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import ProcessingJob, ProcessingStage, ProcessingStageAttempt

PASSWORD = "SIH1@2026"
CASE_ID = "KSP-CR-2048"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def login(client: TestClient, username: str) -> Dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture(scope="module")
def completed_job(client: TestClient) -> dict:
    headers = login(client, "constable.demo")
    content = (
        f"Synthetic Phase 5 extraction evidence {uuid4()}\n"
        "Suspect: Ramesh Sharma\n"
        "Person: Suresh Patil\n"
        "Location: Pune Railway Station\n"
        "Phone: +91 98765 43210\n"
        "Vehicle: MH-12-AB-1234\n"
        "Ramesh Sharma called Suresh Patil on 24/08/2026.\n"
    ).encode()
    upload = client.post(
        f"/api/v1/cases/{CASE_ID}/evidence",
        headers=headers,
        files={"file": ("phase4-preflight.txt", content, "text/plain")},
    )
    assert upload.status_code == 201, upload.text
    evidence = upload.json()
    response = client.get(
        f"/api/v1/cases/{CASE_ID}/processing-jobs",
        params={"evidence_id": evidence["id"]},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert len(response.json()) == 1
    return {"job": response.json()[0], "evidence": evidence, "headers": headers}


def test_upload_auto_runs_durable_preflight(completed_job: dict) -> None:
    job = completed_job["job"]
    assert job["status"] == "completed"
    assert job["progress_percent"] == 100
    assert job["result_summary"]["pipeline"] == "extraction_completed"
    assert [stage["stage_name"] for stage in job["stages"]] == [
        "integrity_check",
        "source_inspection",
        "text_extraction",
        "language_detection",
        "entity_extraction",
        "relation_extraction",
        "schema_validation",
        "review_queue",
    ]
    assert all(stage["status"] == "completed" for stage in job["stages"])
    assert all(stage["attempt_count"] == 1 for stage in job["stages"])
    assert all(stage["attempts"][0]["celery_task_id"] for stage in job["stages"])
    assert job["stages"][0]["output_details"]["valid"] is True
    assert job["stages"][2]["output_details"]["method"] == "direct_utf8"
    assert job["stages"][4]["output_details"]["mention_count"] >= 5
    assert job["stages"][7]["output_details"]["human_review_gate"] == "active"


def test_job_creation_is_idempotent(completed_job: dict, client: TestClient) -> None:
    evidence = completed_job["evidence"]
    response = client.post(
        f"/api/v1/cases/{CASE_ID}/evidence/{evidence['id']}/processing-jobs",
        headers=completed_job["headers"],
    )
    assert response.status_code == 202
    assert response.json()["id"] == completed_job["job"]["id"]
    assert response.json()["reused"] is True


def test_job_records_and_attempt_history_are_in_postgres_compatible_tables(completed_job: dict) -> None:
    job_id = completed_job["job"]["id"]
    with SessionLocal() as session:
        job = session.get(ProcessingJob, job_id)
        assert job is not None and job.status == "completed"
        stages = session.scalars(select(ProcessingStage).where(ProcessingStage.job_id == job_id)).all()
        attempts = session.scalars(
            select(ProcessingStageAttempt).where(
                ProcessingStageAttempt.stage_id.in_([stage.id for stage in stages])
            )
        ).all()
        assert len(stages) == 8
        assert len(attempts) == 8


def test_job_access_is_case_scoped(completed_job: dict, client: TestClient) -> None:
    job_id = completed_job["job"]["id"]
    response = client.get(
        f"/api/v1/cases/KSP-CR-2099/processing-jobs/{job_id}",
        headers=completed_job["headers"],
    )
    assert response.status_code == 404


def test_only_analytical_roles_can_retry_and_attempts_are_preserved(
    completed_job: dict, client: TestClient
) -> None:
    job_id = completed_job["job"]["id"]
    constable_retry = client.post(
        f"/api/v1/cases/{CASE_ID}/processing-jobs/{job_id}/retry",
        headers=completed_job["headers"],
    )
    assert constable_retry.status_code == 403

    with SessionLocal() as session:
        job = session.get(ProcessingJob, job_id)
        assert job is not None
        job.status = "failed"
        job.error_code = "SyntheticFailure"
        session.commit()

    investigator = login(client, "investigator.demo")
    retried = client.post(
        f"/api/v1/cases/{CASE_ID}/processing-jobs/{job_id}/retry",
        headers=investigator,
    )
    assert retried.status_code == 202, retried.text
    payload = retried.json()
    assert payload["status"] == "completed"
    assert payload["retry_count"] == 1
    assert all(stage["attempt_count"] == 2 for stage in payload["stages"])
    assert all(len(stage["attempts"]) == 2 for stage in payload["stages"])


def test_processing_transitions_are_audited(completed_job: dict, client: TestClient) -> None:
    sp = login(client, "sp.demo")
    response = client.get(f"/api/v1/cases/{CASE_ID}/audit-logs", headers=sp)
    assert response.status_code == 200
    actions = {entry["action"] for entry in response.json()}
    assert {
        "processing.job_created",
        "processing.stage_started",
        "processing.stage_completed",
        "processing.job_completed",
        "processing.job_retry",
    }.issubset(actions)
