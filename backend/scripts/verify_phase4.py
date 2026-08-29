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


def login(client: httpx.Client, username: str) -> dict[str, str]:
    response = client.post(
        f"{BASE_URL}/auth/login",
        json={"username": username, "password": PASSWORD},
    )
    response.raise_for_status()
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def main() -> None:
    with httpx.Client(timeout=10) as client:
        investigator = login(client, "investigator.demo")
        payload = (
            "Synthetic Phase 4 Celery proof\n"
            f"Generated: {datetime.now(timezone.utc).isoformat()}\n"
            "No real personal data.\n"
        ).encode()
        upload = client.post(
            f"{BASE_URL}/cases/{CASE_ID}/evidence",
            headers={**investigator, "X-Request-ID": "phase4-live-proof"},
            files={"file": ("phase4-live-proof.txt", payload, "text/plain")},
        )
        upload.raise_for_status()
        evidence_id = upload.json()["id"]

        job = None
        for _ in range(60):
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
        assert len(job["stages"]) == 3
        assert all(stage["status"] == "completed" for stage in job["stages"])
        assert all(stage["attempts"][0]["celery_task_id"] for stage in job["stages"])

        reused = client.post(
            f"{BASE_URL}/cases/{CASE_ID}/evidence/{evidence_id}/processing-jobs",
            headers=investigator,
        )
        reused.raise_for_status()
        assert reused.json()["reused"] is True
        assert reused.json()["id"] == job["id"]

        sp = login(client, "sp.demo")
        audit = client.get(f"{BASE_URL}/cases/{CASE_ID}/audit-logs", headers=sp)
        audit.raise_for_status()
        actions = {entry["action"] for entry in audit.json()}
        assert "processing.job_created" in actions
        assert "processing.job_completed" in actions
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

    with psycopg.connect(
        "postgresql://sih:sih_dev_only@127.0.0.1:55432/sih"
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT j.status, COUNT(DISTINCT s.id), COUNT(a.id)
                FROM processing_jobs j
                JOIN processing_stages s ON s.job_id = j.id
                JOIN processing_stage_attempts a ON a.stage_id = s.id
                WHERE j.id = %s
                GROUP BY j.status
                """,
                (job["id"],),
            )
            status_value, stage_count, attempt_count = cursor.fetchone()
    assert status_value == "completed"
    assert stage_count == 3
    assert attempt_count == 3

    flower = httpx.get(
        "http://127.0.0.1:15555/",
        auth=("sih_flower", PASSWORD),
        timeout=10,
    )
    flower.raise_for_status()

    print(
        json.dumps(
            {
                "api_auto_dispatch": "passed",
                "celery_worker_execution": "passed",
                "redis_broker": "passed",
                "postgres_job_ledger": "passed",
                "durable_stages": stage_count,
                "durable_attempts": attempt_count,
                "idempotent_enqueue": "passed",
                "flower_basic_auth": "passed",
                "audit_chain": chain.json(),
                "job_id": job["id"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

