#!/usr/bin/env python3
"""Load and, when explicitly requested, auto-review the fictional demo FIRs through the API."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "datasets" / "synthetic"


def request(client: httpx.Client, method: str, path: str, **kwargs):
    response = client.request(method, path, **kwargs)
    response.raise_for_status()
    return response.json() if response.content else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:18000/api/v1")
    parser.add_argument("--password", default="SIH1@2026")
    parser.add_argument("--auto-review-synthetic", action="store_true", help="Confirm extraction output only for this explicitly fictional package")
    args = parser.parse_args()
    manifest = json.loads((DATASET / "manifest.json").read_text(encoding="utf-8"))
    with httpx.Client(base_url=args.base_url, timeout=240) as client:
        login = request(client, "POST", "/auth/login", json={"username": "sp.demo", "password": args.password})
        client.headers["Authorization"] = f"Bearer {login['access_token']}"
        for item in manifest["files"]:
            path = DATASET / "firs" / item["filename"]
            with path.open("rb") as handle:
                evidence = request(client, "POST", f"/cases/{item['case_id']}/evidence", files={"file": (path.name, handle, "text/plain")})
            jobs = request(client, "GET", f"/cases/{item['case_id']}/processing-jobs", params={"evidence_id": evidence["id"]})
            job = jobs[0] if jobs else request(client, "POST", f"/cases/{item['case_id']}/evidence/{evidence['id']}/processing-jobs")
            deadline = time.monotonic() + 240
            while job["status"] not in {"completed", "failed"} and time.monotonic() < deadline:
                time.sleep(1)
                jobs = request(client, "GET", f"/cases/{item['case_id']}/processing-jobs", params={"evidence_id": evidence["id"]})
                job = jobs[0]
            if job["status"] != "completed":
                raise RuntimeError(f"Processing failed for {path.name}: {job.get('error_message')}")
            if args.auto_review_synthetic:
                bundle = request(client, "GET", f"/cases/{item['case_id']}/evidence/{evidence['id']}/extractions")
                for mention in bundle["mentions"]:
                    if mention["status"] not in {"confirmed", "corrected", "rejected"}:
                        request(client, "POST", f"/cases/{item['case_id']}/mentions/{mention['id']}/review", json={"decision": "confirm", "notes": "Auto-confirmed for explicitly fictional Phase 8 dataset only."})
                for relation in bundle["relations"]:
                    if relation["status"] not in {"confirmed", "corrected", "rejected"}:
                        request(client, "POST", f"/cases/{item['case_id']}/relations/{relation['id']}/review", json={"decision": "confirm", "notes": "Auto-confirmed for explicitly fictional Phase 8 dataset only."})
                request(client, "POST", f"/cases/{item['case_id']}/graph/rebuild")
                request(client, "POST", f"/cases/{item['case_id']}/graph/analytics")
            print(json.dumps({"case_id": item["case_id"], "evidence_id": evidence["id"], "job": job["status"], "reviewed": args.auto_review_synthetic}))


if __name__ == "__main__":
    main()
