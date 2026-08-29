from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import httpx
import psycopg
import redis

BASE_URL = "http://127.0.0.1:18000/api/v1"
CASE_ID = "KSP-CR-2048"
PASSWORD = "SIH1@2026"
EXPECTED_STAGES = [
    "integrity_check",
    "source_inspection",
    "text_extraction",
    "language_detection",
    "entity_extraction",
    "relation_extraction",
    "schema_validation",
    "review_queue",
]


def login(client: httpx.Client, username: str) -> dict[str, str]:
    response = client.post(
        f"{BASE_URL}/auth/login",
        json={"username": username, "password": PASSWORD},
    )
    response.raise_for_status()
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def main() -> None:
    with httpx.Client(timeout=15) as client:
        investigator = login(client, "investigator.demo")
        constable = login(client, "constable.demo")
        marker = datetime.now(timezone.utc).isoformat()
        payload = (
            f"Synthetic Phase 5 proof {marker}\n"
            "Suspect: Vikram Sharma\n"
            "Person: Suresh Kumar\n"
            "Location: Majestic Bus Stand\n"
            "Organization: Example Cooperative Bank\n"
            "Phone: 9876543210\n"
            "Vehicle: KA01AB1234\n"
            "Amount: INR 25,000\n"
            "Vikram Sharma called Suresh Kumar at Majestic Bus Stand.\n"
            "This is synthetic demonstration data and is not a finding of guilt.\n"
        ).encode()
        upload = client.post(
            f"{BASE_URL}/cases/{CASE_ID}/evidence",
            headers={**investigator, "X-Request-ID": "phase5-live-proof"},
            files={"file": ("phase5-live-proof.txt", payload, "text/plain")},
        )
        upload.raise_for_status()
        evidence_id = upload.json()["id"]

        job = None
        for _ in range(120):
            jobs = client.get(
                f"{BASE_URL}/cases/{CASE_ID}/processing-jobs",
                params={"evidence_id": evidence_id},
                headers=investigator,
            )
            jobs.raise_for_status()
            if jobs.json():
                job = jobs.json()[0]
                if job["status"] in {"completed", "failed", "dispatch_failed"}:
                    break
            time.sleep(0.5)
        assert job is not None
        assert job["status"] == "completed", job
        assert job["progress_percent"] == 100
        assert job["pipeline_version"] == "phase5-v1"
        assert [stage["stage_name"] for stage in job["stages"]] == EXPECTED_STAGES
        assert all(stage["status"] == "completed" for stage in job["stages"])
        assert all(stage["attempts"][0]["celery_task_id"] for stage in job["stages"])

        extraction = client.get(
            f"{BASE_URL}/cases/{CASE_ID}/evidence/{evidence_id}/extractions",
            headers=investigator,
        )
        extraction.raise_for_status()
        bundle = extraction.json()
        assert "extracted_text" not in bundle["document"]
        assert bundle["document"]["extraction_method"] == "direct_utf8"
        assert bundle["document"]["language_code"] == "en"
        entity_types = {mention["entity_type"] for mention in bundle["mentions"]}
        assert {
            "PERSON",
            "LOCATION",
            "ORGANIZATION",
            "PHONE_NUMBER",
            "VEHICLE",
            "AMOUNT",
        }.issubset(entity_types)
        assert bundle["relations"]
        assert all(item["source_excerpt"] for item in bundle["mentions"])

        raw_denied = client.get(
            f"{BASE_URL}/cases/{CASE_ID}/evidence/{evidence_id}/extracted-text",
            headers=constable,
        )
        assert raw_denied.status_code == 403
        raw_allowed = client.get(
            f"{BASE_URL}/cases/{CASE_ID}/evidence/{evidence_id}/extracted-text",
            headers=investigator,
        )
        raw_allowed.raise_for_status()
        assert marker in raw_allowed.json()["extracted_text"]

        target_relation = bundle["relations"][0]
        decision = client.post(
            f"{BASE_URL}/cases/{CASE_ID}/relations/{target_relation['id']}/review",
            headers=investigator,
            json={"decision": "confirm", "notes": "Phase 5 synthetic verification."},
        )
        decision.raise_for_status()
        assert decision.json()["decision"] == "confirm"
        repeated = client.post(
            f"{BASE_URL}/cases/{CASE_ID}/relations/{target_relation['id']}/review",
            headers=investigator,
            json={"decision": "confirm"},
        )
        assert repeated.status_code == 409

        sp = login(client, "sp.demo")
        chain = client.get(f"{BASE_URL}/cases/{CASE_ID}/audit-chain/verify", headers=sp)
        chain.raise_for_status()
        assert chain.json()["valid"] is True

    redis_client = redis.Redis(
        host="127.0.0.1",
        port=16379,
        password="sih_redis_dev_only",
        decode_responses=True,
    )
    assert redis_client.ping() is True
    for database in (0, 1):
        redis_client.execute_command("SELECT", database)
        for key in redis_client.scan_iter(match="*"):
            key_type = redis_client.type(key)
            if key_type == "string":
                value = redis_client.get(key) or ""
                assert "Vikram Sharma" not in value
                assert "9876543210" not in value

    with psycopg.connect("postgresql://sih:sih_dev_only@127.0.0.1:55432/sih") as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(DISTINCT s.id), COUNT(a.id)
                FROM processing_stages s
                JOIN processing_stage_attempts a ON a.stage_id = s.id
                WHERE s.job_id = %s
                """,
                (job["id"],),
            )
            stage_count, attempt_count = cursor.fetchone()
            cursor.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM extracted_documents WHERE job_id = %s),
                    (SELECT COUNT(*) FROM extracted_mentions WHERE job_id = %s),
                    (SELECT COUNT(*) FROM extracted_relations WHERE job_id = %s),
                    (SELECT COUNT(*) FROM review_decisions WHERE job_id = %s)
                """,
                (job["id"], job["id"], job["id"], job["id"]),
            )
            document_count, mention_count, relation_count, decision_count = cursor.fetchone()
    assert stage_count == 8
    assert attempt_count == 8
    assert document_count == 1
    assert mention_count >= 6
    assert relation_count >= 1
    assert decision_count == 1

    flower = httpx.get(
        "http://127.0.0.1:15555/",
        auth=("sih_flower", PASSWORD),
        timeout=10,
    )
    flower.raise_for_status()

    relation_stage = next(
        stage for stage in job["stages"] if stage["stage_name"] == "relation_extraction"
    )
    print(
        json.dumps(
            {
                "api_auto_dispatch": "passed",
                "eight_stage_celery_pipeline": "passed",
                "postgres_extraction_persistence": "passed",
                "provenance_fields": "passed",
                "raw_text_rbac": "passed",
                "human_review_and_repeat_guard": "passed",
                "redis_broker": "passed",
                "redis_contains_no_evidence_text": "passed",
                "flower_basic_auth": "passed",
                "entity_types": sorted(entity_types),
                "durable_stages": stage_count,
                "durable_attempts": attempt_count,
                "mentions": mention_count,
                "relations": relation_count,
                "review_decisions": decision_count,
                "relation_provider": relation_stage["output_details"].get("provider"),
                "relation_fallback_reason": relation_stage["output_details"].get("fallback_reason"),
                "audit_chain": chain.json(),
                "job_id": job["id"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
