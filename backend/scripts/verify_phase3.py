"""Live PostgreSQL + MinIO custody proof. Does not print tokens or credentials."""

import json
from hashlib import sha256
from uuid import uuid4

import httpx
import psycopg
from minio import Minio

BASE_URL = "http://127.0.0.1:18000/api/v1"
PASSWORD = "SIH1@2026"
CASE_ID = "KSP-CR-2048"


def login(client: httpx.Client, username: str) -> dict:
    response = client.post(
        f"{BASE_URL}/auth/login",
        json={"username": username, "password": PASSWORD},
    )
    response.raise_for_status()
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def main() -> None:
    payload = f"Phase 3 MinIO custody proof {uuid4()}\nSynthetic data only.\n".encode("utf-8")
    expected_hash = sha256(payload).hexdigest()

    with httpx.Client(timeout=20) as client:
        assert client.get(f"{BASE_URL}/cases/{CASE_ID}/evidence").status_code == 401
        investigator = login(client, "investigator.demo")
        upload = client.post(
            f"{BASE_URL}/cases/{CASE_ID}/evidence",
            headers={**investigator, "X-Request-ID": "phase3-live-proof"},
            files={"file": ("FIR_phase3_live.txt", payload, "text/plain")},
        )
        upload.raise_for_status()
        evidence = upload.json()
        assert evidence["sha256"] == expected_hash
        assert evidence["storage_backend"] == "minio"

        duplicate = client.post(
            f"{BASE_URL}/cases/{CASE_ID}/evidence",
            headers=investigator,
            files={"file": ("duplicate-name.txt", payload, "text/plain")},
        )
        duplicate.raise_for_status()
        assert duplicate.json()["id"] == evidence["id"]
        assert duplicate.json()["deduplicated"] is True

        download = client.get(
            f"{BASE_URL}/cases/{CASE_ID}/evidence/{evidence['id']}/download",
            headers=investigator,
        )
        download.raise_for_status()
        assert download.content == payload
        assert download.headers["x-content-sha256"] == expected_hash

        integrity = client.post(
            f"{BASE_URL}/cases/{CASE_ID}/evidence/{evidence['id']}/verify-integrity",
            headers=investigator,
        )
        integrity.raise_for_status()
        assert integrity.json()["valid"] is True

        sp = login(client, "sp.demo")
        audit = client.get(f"{BASE_URL}/cases/{CASE_ID}/audit-logs", headers=sp)
        audit.raise_for_status()
        chain = client.get(f"{BASE_URL}/cases/{CASE_ID}/audit-chain/verify", headers=sp)
        chain.raise_for_status()
        assert chain.json()["valid"] is True

    with psycopg.connect(
        "postgresql://sih:sih_dev_only@127.0.0.1:55432/sih"
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT object_key, sha256, size_bytes FROM evidence_sources WHERE id = %s",
                (evidence["id"],),
            )
            object_key, stored_hash, stored_size = cursor.fetchone()
            cursor.execute("SELECT count(*) FROM audit_logs")
            audit_count = cursor.fetchone()[0]
    assert stored_hash == expected_hash
    assert stored_size == len(payload)

    minio = Minio(
        "127.0.0.1:19000",
        access_key="sih_minio",
        secret_key="sih_minio_dev_only",
        secure=False,
    )
    stored = minio.get_object("evidence", object_key)
    try:
        minio_bytes = stored.read()
    finally:
        stored.close()
        stored.release_conn()
    assert minio_bytes == payload
    assert sha256(minio_bytes).hexdigest() == expected_hash

    print(
        json.dumps(
            {
                "api_status": "passed",
                "postgres_metadata": "passed",
                "minio_bytes": "passed",
                "sha256": expected_hash,
                "size_bytes": len(payload),
                "duplicate_detection": "passed",
                "protected_download": "passed",
                "integrity_verification": "passed",
                "audit_chain": chain.json(),
                "audit_rows": audit_count,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

