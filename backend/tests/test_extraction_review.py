from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Dict
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.extraction import _extract_pdf, _paddle_ocr_paths, detect_language, extract_relations
from app.main import app
from app.models import ReviewDecision

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
def extracted(client: TestClient) -> dict:
    investigator = login(client, "investigator.demo")
    content = (
        f"FIR reference {uuid4()}\n"
        "Suspect: Vikram Sharma\n"
        "Person: Suresh Kumar\n"
        "Location: Majestic Bus Stand\n"
        "Organization: Example Cooperative Bank\n"
        "Phone: 9876543210\n"
        "Vehicle: KA01AB1234\n"
        "Amount: INR 25,000\n"
        "Vikram Sharma called Suresh Kumar at Majestic Bus Stand on 2026-08-24.\n"
    ).encode()
    upload = client.post(
        f"/api/v1/cases/{CASE_ID}/evidence",
        headers=investigator,
        files={"file": ("phase5-review.txt", content, "text/plain")},
    )
    assert upload.status_code == 201, upload.text
    evidence = upload.json()
    bundle = client.get(
        f"/api/v1/cases/{CASE_ID}/evidence/{evidence['id']}/extractions",
        headers=investigator,
    )
    assert bundle.status_code == 200, bundle.text
    return {"evidence": evidence, "bundle": bundle.json(), "investigator": investigator}


def test_multilingual_script_router() -> None:
    assert detect_language("आरोपी का नाम विक्रम शर्मा है").code == "hi"
    assert detect_language("ಆರೋಪಿ ಹೆಸರು ವಿಕ್ರಮ್ ಶರ್ಮಾ").code == "kn"
    assert detect_language("Suspect name is Vikram Sharma").code == "en"


def test_extraction_bundle_has_provenance_and_no_raw_text(extracted: dict) -> None:
    bundle = extracted["bundle"]
    assert bundle["document"]["extraction_method"] == "direct_utf8"
    assert bundle["document"]["language_code"] == "en"
    assert "extracted_text" not in bundle["document"]
    types = {item["entity_type"] for item in bundle["mentions"]}
    assert {"PERSON", "LOCATION", "ORGANIZATION", "PHONE_NUMBER", "VEHICLE"}.issubset(types)
    assert "AMOUNT" not in types
    assert all(item["source_excerpt"] for item in bundle["mentions"])
    assert all(0 <= item["confidence_percent"] <= 100 for item in bundle["mentions"])
    assert bundle["relations"]
    assert all(item["needs_review"] for item in bundle["relations"])


def test_raw_text_and_review_queue_require_investigator_role(extracted: dict, client: TestClient) -> None:
    evidence_id = extracted["evidence"]["id"]
    constable = login(client, "constable.demo")
    assert client.get(
        f"/api/v1/cases/{CASE_ID}/evidence/{evidence_id}/extracted-text",
        headers=constable,
    ).status_code == 403
    assert client.get(f"/api/v1/cases/{CASE_ID}/review-queue", headers=constable).status_code == 403

    text_response = client.get(
        f"/api/v1/cases/{CASE_ID}/evidence/{evidence_id}/extracted-text",
        headers=extracted["investigator"],
    )
    assert text_response.status_code == 200
    assert "Vikram Sharma" in text_response.json()["extracted_text"]
    queue = client.get(
        f"/api/v1/cases/{CASE_ID}/review-queue",
        headers=extracted["investigator"],
    )
    assert queue.status_code == 200
    assert queue.json()["total_pending"] >= 1


def test_human_review_decisions_are_case_scoped_and_append_only(extracted: dict, client: TestClient) -> None:
    relation = extracted["bundle"]["relations"][0]
    decision_response = client.post(
        f"/api/v1/cases/{CASE_ID}/relations/{relation['id']}/review",
        headers=extracted["investigator"],
        json={"decision": "correct", "corrected_type": "ASSOCIATED_WITH", "notes": "Confirmed from source text."},
    )
    assert decision_response.status_code == 200, decision_response.text
    decision = decision_response.json()
    assert decision["target_type"] == "relation"
    assert decision["decision"] == "correct"
    assert decision["corrected_value"]["relation_type"] == "ASSOCIATED_WITH"

    repeated = client.post(
        f"/api/v1/cases/{CASE_ID}/relations/{relation['id']}/review",
        headers=extracted["investigator"],
        json={"decision": "confirm"},
    )
    assert repeated.status_code == 409

    wrong_case = client.post(
        f"/api/v1/cases/KSP-CR-2099/relations/{relation['id']}/review",
        headers=extracted["investigator"],
        json={"decision": "confirm"},
    )
    assert wrong_case.status_code == 404

    with SessionLocal() as session:
        stored = session.scalar(select(ReviewDecision).where(ReviewDecision.id == decision["id"]))
        assert stored is not None
        stored.notes = "tampered"
        with pytest.raises(ValueError, match="append-only"):
            session.commit()
        session.rollback()


def test_paddleocr_adapter_parses_local_engine_output(monkeypatch, tmp_path: Path) -> None:
    class FakeResult:
        json = {"res": {"rec_texts": ["आरोपी", "विक्रम"], "rec_scores": [0.9, 0.8]}}

    class FakePaddleOCR:
        def __init__(self, **_kwargs):
            pass

        def predict(self, _path):
            return [FakeResult()]

    monkeypatch.setattr(
        "app.extraction.get_settings",
        lambda: SimpleNamespace(paddleocr_enabled=True, paddleocr_language="hi"),
    )
    monkeypatch.setitem(sys.modules, "paddleocr", SimpleNamespace(PaddleOCR=FakePaddleOCR))
    image = tmp_path / "fir.png"
    image.write_bytes(b"synthetic")
    text, confidence = _paddle_ocr_paths([image])
    assert text == "आरोपी\nविक्रम"
    assert confidence == 85


def test_embedded_pdf_text_is_extracted_without_ocr() -> None:
    import fitz

    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Suspect: Anil Kumar | Phone: 9876543210")
    payload = pdf.tobytes()
    pdf.close()
    result = _extract_pdf(payload)
    assert result.method == "pymupdf_embedded_text"
    assert "Anil Kumar" in result.text
    assert result.page_count == 1


def test_qwen_relation_extraction_validates_structured_local_response(monkeypatch) -> None:
    mentions = [
        SimpleNamespace(id="m1", entity_type="PERSON", value="Vikram", start_char=0, end_char=6, page_number=1),
        SimpleNamespace(id="m2", entity_type="PERSON", value="Suresh", start_char=14, end_char=20, page_number=1),
    ]
    observed = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "message": {
                    "content": '{"relations":[{"subject_id":"m1","object_id":"m2","relation_type":"CALLED","confidence":0.81,"evidence_excerpt":"invented unsupported excerpt"}]}'
                }
            }

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
        "app.extraction.get_settings",
        lambda: SimpleNamespace(
            qwen_enabled=True,
            qwen_timeout_seconds=5,
            qwen_base_url="http://127.0.0.1:11434",
            qwen_model="qwen2.5:test",
        ),
    )
    monkeypatch.setattr("app.extraction.httpx.Client", FakeClient)
    relations, provider, error = extract_relations("Vikram called Suresh", mentions)
    assert provider == "qwen"
    assert error is None
    assert relations[0].relation_type == "CALLED"
    assert relations[0].source_excerpt == "Vikram called Suresh"
    assert relations[0].confidence_percent == 60
    assert observed["url"].endswith("/api/chat")
    assert observed["payload"]["stream"] is False
    assert isinstance(observed["payload"]["format"], dict)
