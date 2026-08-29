"""Phase 8 live-stack verification through the frontend reverse proxy."""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from uuid import uuid4

import httpx

BASE_URL = "http://127.0.0.1:15173/api/v1"
CASE_ID = "KSP-CR-2048"
PASSWORD = "SIH1@2026"
ROOT = Path(__file__).resolve().parents[2]


def login(client: httpx.Client, username: str) -> dict[str, str]:
    response = client.post(f"{BASE_URL}/auth/login", json={"username": username, "password": PASSWORD})
    response.raise_for_status()
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def main() -> None:
    manifest = json.loads((ROOT / "datasets/synthetic/manifest.json").read_text(encoding="utf-8"))
    with (ROOT / "datasets/synthetic/subjects.csv").open(encoding="utf-8") as handle:
        subjects = list(csv.DictReader(handle))
    assert (manifest["case_count"], manifest["subject_count"], manifest["fir_count"]) == (20, 100, 20)
    assert len(subjects) == 100

    with httpx.Client(timeout=240) as client:
        health = client.get(f"{BASE_URL}/health")
        health.raise_for_status()
        assert health.json()["version"] == "0.8.0-phase8"
        investigator = login(client, "investigator.demo")
        cases = client.get(f"{BASE_URL}/cases", headers=investigator)
        cases.raise_for_status()
        assert len(cases.json()) == 19

        grounded = client.post(
            f"{BASE_URL}/cases/{CASE_ID}/assistant/query",
            headers=investigator,
            json={"question": "Summarize the reviewed evidence"},
        )
        grounded.raise_for_status()
        grounded_payload = grounded.json()
        if not grounded_payload["evidence_sufficient"]:
            proof_name = f"phase8-grounding-proof-{uuid4()}.txt"
            proof = (
                "SYNTHETIC DATASET — NO REAL PERSONS OR ALLEGATIONS\n"
                "Person: Asha Verify, Phone: 9876501234, associated with this fictional verification record.\n"
                "Person: Dev Verify, Phone: 9876505678, associated with this fictional verification record.\n"
                "This record does not establish guilt, identity, intent, or a basis for enforcement action.\n"
            ).encode()
            upload = client.post(
                f"{BASE_URL}/cases/{CASE_ID}/evidence",
                headers=investigator,
                files={"file": (proof_name, proof, "text/plain")},
            )
            assert upload.status_code == 201, upload.text
            evidence_id = upload.json()["id"]
            deadline = time.monotonic() + 90
            job = None
            while time.monotonic() < deadline:
                jobs = client.get(
                    f"{BASE_URL}/cases/{CASE_ID}/processing-jobs",
                    headers=investigator,
                    params={"evidence_id": evidence_id},
                )
                jobs.raise_for_status()
                if jobs.json():
                    job = jobs.json()[0]
                    if job["status"] in {"completed", "failed"}:
                        break
                time.sleep(1)
            assert job and job["status"] == "completed", job
            bundle = client.get(
                f"{BASE_URL}/cases/{CASE_ID}/evidence/{evidence_id}/extractions",
                headers=investigator,
            )
            bundle.raise_for_status()
            for mention in bundle.json()["mentions"]:
                if mention["status"] not in {"confirmed", "corrected", "rejected"}:
                    decision = client.post(
                        f"{BASE_URL}/cases/{CASE_ID}/mentions/{mention['id']}/review",
                        headers=investigator,
                        json={"decision": "confirm", "notes": "Fictional Phase 8 verification record."},
                    )
                    decision.raise_for_status()
            for relation in bundle.json()["relations"]:
                if relation["status"] not in {"confirmed", "corrected", "rejected"}:
                    decision = client.post(
                        f"{BASE_URL}/cases/{CASE_ID}/relations/{relation['id']}/review",
                        headers=investigator,
                        json={"decision": "confirm", "notes": "Fictional Phase 8 verification record."},
                    )
                    decision.raise_for_status()
            grounded = client.post(
                f"{BASE_URL}/cases/{CASE_ID}/assistant/query",
                headers=investigator,
                json={"question": "Which reviewed facts mention Asha Verify?"},
            )
            grounded.raise_for_status()
            grounded_payload = grounded.json()
        assert grounded_payload["evidence_sufficient"] is True
        assert grounded_payload["citations"]
        unsupported = client.post(
            f"{BASE_URL}/cases/{CASE_ID}/assistant/query",
            headers=investigator,
            json={"question": "What happened on the moon?"},
        )
        unsupported.raise_for_status()
        assert unsupported.json()["evidence_sufficient"] is False
        assert not unsupported.json()["citations"]

        created = client.post(
            f"{BASE_URL}/cases/{CASE_ID}/reports",
            headers=investigator,
            json={"title": "Phase 8 verification brief", "scope_note": "Reviewed evidence verification snapshot"},
        )
        assert created.status_code == 202, created.text
        report = created.json()
        deadline = time.monotonic() + 90
        while report["status"] in {"queued", "generating"} and time.monotonic() < deadline:
            time.sleep(1)
            response = client.get(f"{BASE_URL}/reports/{report['id']}", headers=investigator)
            response.raise_for_status(); report = response.json()
        assert report["status"] == "completed", report
        download = client.get(f"{BASE_URL}/reports/{report['id']}/download", headers=investigator)
        download.raise_for_status()
        assert download.content.startswith(b"%PDF")
        assert download.headers["x-content-sha256"] == report["sha256"]

        constable = login(client, "constable.demo")
        assert client.post(
            f"{BASE_URL}/cases/{CASE_ID}/assistant/query", headers=constable, json={"question": "Summarize evidence"}
        ).status_code == 403
        assert client.post(
            f"{BASE_URL}/cases/{CASE_ID}/reports", headers=constable, json={"title": "Denied report"}
        ).status_code == 403

        sp = login(client, "sp.demo")
        all_cases = client.get(f"{BASE_URL}/cases", headers=sp)
        all_cases.raise_for_status()
        dashboard_person_nodes = 0
        loaded_synthetic_firs = 0
        for case in all_cases.json():
            graph = client.get(f"{BASE_URL}/cases/{case['id']}/graph", headers=sp)
            graph.raise_for_status()
            dashboard_person_nodes += sum(1 for node in graph.json()["nodes"] if node["entity_type"] == "PERSON")
            sources = client.get(f"{BASE_URL}/cases/{case['id']}/evidence", headers=sp)
            sources.raise_for_status()
            loaded_synthetic_firs += sum(1 for item in sources.json() if item["original_filename"].startswith("SYN-FIR-"))
        assert len(all_cases.json()) == 20
        assert loaded_synthetic_firs == 20
        assert dashboard_person_nodes >= 100
        approved = client.post(
            f"{BASE_URL}/reports/{report['id']}/decision",
            headers=sp,
            json={"decision": "approve", "notes": "Phase 8 automated contract verification"},
        )
        approved.raise_for_status()
        assert approved.json()["status"] == "approved"
        chain = client.get(f"{BASE_URL}/cases/{CASE_ID}/audit-chain/verify", headers=sp)
        chain.raise_for_status(); assert chain.json()["valid"] is True

    print(json.dumps({
        "phase": 8,
        "version": health.json()["version"],
        "assistant_grounded_citations": len(grounded_payload["citations"]),
        "assistant_insufficiency": "passed",
        "report_pdf_hash": report["sha256"],
        "report_approval": "passed",
        "constable_denials": "passed",
        "audit_chain": chain.json(),
        "synthetic_dataset": {"cases": 20, "subjects": 100, "firs": 20, "languages": manifest["languages"]},
        "dashboard_seed": {"loaded_firs": loaded_synthetic_firs, "reviewed_person_nodes": dashboard_person_nodes},
    }, indent=2))


if __name__ == "__main__":
    main()
