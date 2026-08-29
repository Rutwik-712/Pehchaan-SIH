from __future__ import annotations

from hashlib import sha256
from typing import Dict
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import AuditLog

PASSWORD = "SIH1@2026"
CASE_ID = "KSP-CR-2048"
EVIDENCE_BYTES = f"Synthetic FIR narrative {uuid4()}\nNo real personal data.\n".encode("utf-8")


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
def uploaded_evidence(client: TestClient) -> dict:
    headers = login(client, "constable.demo")
    headers["X-Request-ID"] = "phase3-upload-test"
    response = client.post(
        f"/api/v1/cases/{CASE_ID}/evidence",
        headers=headers,
        files={"file": ("FIR_phase3_demo.txt", EVIDENCE_BYTES, "text/plain")},
    )
    assert response.status_code == 201, response.text
    return {"record": response.json(), "headers": headers}


def test_secure_upload_records_hash_and_hides_object_key(uploaded_evidence: dict) -> None:
    record = uploaded_evidence["record"]
    assert record["sha256"] == sha256(EVIDENCE_BYTES).hexdigest()
    assert record["size_bytes"] == len(EVIDENCE_BYTES)
    assert record["media_type"] == "text/plain"
    assert record["storage_backend"] == "local"
    assert record["deduplicated"] is False
    assert "object_key" not in record


def test_duplicate_upload_reuses_immutable_source(client: TestClient, uploaded_evidence: dict) -> None:
    response = client.post(
        f"/api/v1/cases/{CASE_ID}/evidence",
        headers=uploaded_evidence["headers"],
        files={"file": ("same-content-different-name.txt", EVIDENCE_BYTES, "text/plain")},
    )
    assert response.status_code == 201
    assert response.json()["id"] == uploaded_evidence["record"]["id"]
    assert response.json()["deduplicated"] is True


def test_download_matches_original_bytes_and_hash(client: TestClient, uploaded_evidence: dict) -> None:
    record = uploaded_evidence["record"]
    response = client.get(
        f"/api/v1/cases/{CASE_ID}/evidence/{record['id']}/download",
        headers=uploaded_evidence["headers"],
    )
    assert response.status_code == 200
    assert response.content == EVIDENCE_BYTES
    assert response.headers["x-content-sha256"] == record["sha256"]
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_integrity_endpoint_rehashes_stored_object(client: TestClient, uploaded_evidence: dict) -> None:
    record = uploaded_evidence["record"]
    response = client.post(
        f"/api/v1/cases/{CASE_ID}/evidence/{record['id']}/verify-integrity",
        headers=uploaded_evidence["headers"],
    )
    assert response.status_code == 200
    assert response.json()["valid"] is True
    assert response.json()["expected_sha256"] == response.json()["actual_sha256"]
    assert response.json()["expected_size"] == response.json()["actual_size"]


def test_unsafe_filename_and_spoofed_content_are_rejected(client: TestClient) -> None:
    headers = login(client, "constable.demo")
    traversal = client.post(
        f"/api/v1/cases/{CASE_ID}/evidence",
        headers=headers,
        files={"file": ("../../escape.txt", b"safe text", "text/plain")},
    )
    spoofed_pdf = client.post(
        f"/api/v1/cases/{CASE_ID}/evidence",
        headers=headers,
        files={"file": ("not-really.pdf", b"not a pdf", "application/pdf")},
    )
    executable = client.post(
        f"/api/v1/cases/{CASE_ID}/evidence",
        headers=headers,
        files={"file": ("payload.exe", b"MZ", "application/octet-stream")},
    )
    assert traversal.status_code == 400
    assert spoofed_pdf.status_code == 415
    assert executable.status_code == 415


def test_evidence_access_is_case_scoped(client: TestClient, uploaded_evidence: dict) -> None:
    response = client.get(
        "/api/v1/cases/KSP-CR-2099/evidence",
        headers=uploaded_evidence["headers"],
    )
    assert response.status_code == 404


def test_audit_log_is_sp_only_and_contains_custody_events(
    client: TestClient, uploaded_evidence: dict
) -> None:
    constable = uploaded_evidence["headers"]
    assert client.get(f"/api/v1/cases/{CASE_ID}/audit-logs", headers=constable).status_code == 403

    sp_headers = login(client, "sp.demo")
    response = client.get(f"/api/v1/cases/{CASE_ID}/audit-logs", headers=sp_headers)
    assert response.status_code == 200
    actions = {entry["action"] for entry in response.json()}
    assert {
        "evidence.upload",
        "evidence.upload_duplicate",
        "evidence.download",
        "evidence.integrity_verify",
    }.issubset(actions)
    upload_event = next(entry for entry in response.json() if entry["action"] == "evidence.upload")
    assert upload_event["request_id"] == "phase3-upload-test"
    assert len(upload_event["entry_hash"]) == 64


def test_audit_hash_chain_verifies(client: TestClient) -> None:
    sp_headers = login(client, "sp.demo")
    response = client.get(f"/api/v1/cases/{CASE_ID}/audit-chain/verify", headers=sp_headers)
    assert response.status_code == 200
    assert response.json()["valid"] is True
    assert response.json()["entries_checked"] > 0
    assert response.json()["first_invalid_entry_id"] is None


def test_audit_rows_cannot_be_updated() -> None:
    with SessionLocal() as session:
        entry = session.scalar(select(AuditLog).limit(1))
        assert entry is not None
        entry.outcome = "tampered"
        with pytest.raises(ValueError, match="append-only"):
            session.commit()
        session.rollback()

