from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from typing import Dict
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.assistant_service import GroundedFact, _qwen_answer
from app.database import SessionLocal
from app.main import app
from app.models import (
    EvidenceSource,
    ExtractedDocument,
    ExtractedMention,
    ExtractedRelation,
    ProcessingJob,
    User,
)
from app.storage import get_object_storage

PASSWORD = "SIH1@2026"
CASE_ID = "KSP-CR-2048"


def test_qwen_adapter_renders_validated_structured_citations(monkeypatch) -> None:
    observed = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": '{"answer":"Bob Sharma","citation_numbers":[1]}'}}

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, url, json):
            observed["url"] = url
            observed["payload"] = json
            return FakeResponse()

    monkeypatch.setattr(
        "app.assistant_service.get_settings",
        lambda: SimpleNamespace(
            qwen_enabled=True,
            qwen_timeout_seconds=5,
            qwen_base_url="http://ollama:11434",
            qwen_model="qwen2.5:test",
            qwen_num_ctx=4096,
        ),
    )
    monkeypatch.setattr("app.assistant_service.httpx.Client", FakeClient)
    facts = [
        GroundedFact(
            evidence_id="ev-1",
            document_id="doc-1",
            target_type="relation",
            target_id="rel-1",
            source_label="fir.png",
            page_number=1,
            excerpt="Alice Mehta called Bob Sharma.",
            fact_text="Alice Mehta called Bob Sharma.",
            score=100,
        )
    ]

    assert _qwen_answer("Who did Alice call?", facts) == "Bob Sharma [1]"
    assert observed["url"].endswith("/api/chat")
    assert observed["payload"]["options"]["num_ctx"] == 4096


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def login(client: TestClient, username: str) -> Dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture(scope="module")
def reviewed_fact(client: TestClient, tmp_path_factory) -> dict:
    del client
    payload = b"Suspect: Asha Rao\nPerson: Dev Kumar\nAsha Rao called Dev Kumar from Majestic.\n"
    digest = sha256(payload).hexdigest()
    temp_path = Path(tmp_path_factory.mktemp("phase8")) / "reviewed-fir.txt"
    temp_path.write_bytes(payload)
    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.username == "investigator.demo"))
        evidence_id = str(uuid4())
        object_key = f"cases/{CASE_ID}/evidence/{evidence_id}/{digest}.txt"
        get_object_storage().put_file(object_key, temp_path, "text/plain", {"sha256": digest})
        evidence = EvidenceSource(
            id=evidence_id,
            case_id=CASE_ID,
            original_filename="reviewed-phase8-fir.txt",
            media_type="text/plain",
            size_bytes=len(payload),
            sha256=digest,
            object_key=object_key,
            storage_backend=get_object_storage().backend_name,
            uploaded_by_id=user.id,
            status="registered",
        )
        session.add(evidence)
        job = ProcessingJob(case_id=CASE_ID, evidence_id=evidence_id, requested_by_id=user.id, status="completed")
        session.add(job)
        session.flush()
        document = ExtractedDocument(
            job_id=job.id,
            case_id=CASE_ID,
            evidence_id=evidence_id,
            extracted_text=payload.decode(),
            text_sha256=digest,
            extraction_method="direct_utf8",
            page_count=1,
        )
        session.add(document)
        session.flush()
        left = ExtractedMention(
            job_id=job.id, document_id=document.id, case_id=CASE_ID, evidence_id=evidence_id,
            entity_type="PERSON", value="Asha Rao", normalized_value="asha rao", start_char=9, end_char=17,
            page_number=1, source_excerpt="Asha Rao called Dev Kumar from Majestic.", extraction_method="test",
            confidence_percent=99, status="confirmed", needs_review=False,
        )
        right = ExtractedMention(
            job_id=job.id, document_id=document.id, case_id=CASE_ID, evidence_id=evidence_id,
            entity_type="PERSON", value="Dev Kumar", normalized_value="dev kumar", start_char=26, end_char=35,
            page_number=1, source_excerpt="Asha Rao called Dev Kumar from Majestic.", extraction_method="test",
            confidence_percent=99, status="confirmed", needs_review=False,
        )
        session.add_all([left, right])
        session.flush()
        relation = ExtractedRelation(
            job_id=job.id, document_id=document.id, case_id=CASE_ID, evidence_id=evidence_id,
            subject_mention_id=left.id, object_mention_id=right.id, relation_type="CALLED",
            source_excerpt="Asha Rao called Dev Kumar from Majestic.", extraction_method="test",
            confidence_percent=98, status="confirmed", needs_review=False,
        )
        session.add(relation)
        session.commit()
        target_ids = {"relation": relation.id, "left": left.id, "right": right.id}
    yield {"evidence_id": evidence_id}
    with SessionLocal() as session:
        for model, identifier in (
            (ExtractedRelation, target_ids["relation"]),
            (ExtractedMention, target_ids["left"]),
            (ExtractedMention, target_ids["right"]),
        ):
            item = session.get(model, identifier)
            if item is not None:
                session.delete(item)
        session.commit()


def test_assistant_returns_persisted_citations_or_explicit_insufficiency(client: TestClient, reviewed_fact: dict) -> None:
    investigator = login(client, "investigator.demo")
    response = client.post(
        f"/api/v1/cases/{CASE_ID}/assistant/query",
        headers=investigator,
        json={"question": "Who called Dev Kumar?"},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["evidence_sufficient"] is True
    assert result["citations"][0]["evidence_id"] == reviewed_fact["evidence_id"]
    assert "[1]" in result["answer_text"]
    assert "does not determine guilt" in result["disclaimer"]

    unsupported = client.post(
        f"/api/v1/cases/{CASE_ID}/assistant/query",
        headers=investigator,
        json={"question": "What happened on the moon?"},
    )
    assert unsupported.status_code == 200
    assert unsupported.json()["evidence_sufficient"] is False
    assert unsupported.json()["citations"] == []
    assert "insufficient" in unsupported.json()["answer_text"].lower()


def test_assistant_and_report_permissions_are_backend_enforced(client: TestClient) -> None:
    constable = login(client, "constable.demo")
    assert client.post(
        f"/api/v1/cases/{CASE_ID}/assistant/query", headers=constable, json={"question": "Summarize evidence"}
    ).status_code == 403
    assert client.post(
        f"/api/v1/cases/{CASE_ID}/reports", headers=constable, json={"title": "Denied report"}
    ).status_code == 403


def test_case_report_is_generated_downloadable_and_sp_approved(client: TestClient, reviewed_fact: dict) -> None:
    del reviewed_fact
    investigator = login(client, "investigator.demo")
    created = client.post(
        f"/api/v1/cases/{CASE_ID}/reports",
        headers=investigator,
        json={"title": "Phase 8 reviewed evidence brief", "scope_note": "Reviewed evidence only"},
    )
    assert created.status_code == 202, created.text
    report = created.json()
    assert report["status"] == "completed"
    assert report["citation_count"] >= 1
    assert report["sha256"] and report["size_bytes"] > 0
    download = client.get(f"/api/v1/reports/{report['id']}/download", headers=investigator)
    assert download.status_code == 200
    assert download.content.startswith(b"%PDF")
    assert download.headers["x-content-sha256"] == report["sha256"]

    denied = client.post(
        f"/api/v1/reports/{report['id']}/decision",
        headers=investigator,
        json={"decision": "approve", "notes": "not authorized"},
    )
    assert denied.status_code == 403
    sp = login(client, "sp.demo")
    approved = client.post(
        f"/api/v1/reports/{report['id']}/decision",
        headers=sp,
        json={"decision": "approve", "notes": "Reviewed against citations"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert approved.json()["approved_by_id"]
