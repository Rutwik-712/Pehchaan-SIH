#!/usr/bin/env python3
"""Load the explicitly fictional five-person mobile-fraud demonstration case."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[2]
SEED_FILE = ROOT / "sample-data" / "mobile-fraud" / "01_mobile_fraud_seed_fir.txt"
CASE_ID = "KSP-MF-2101"
PEOPLE = {
    "alice mehta",
    "bob kapoor",
    "carol fernandes",
    "david khan",
    "eva nair",
}
RELATIONS = {
    ("alice mehta", "bob kapoor"): "CALLED",
    ("bob kapoor", "carol fernandes"): "TRANSFERRED_TO",
    ("carol fernandes", "david khan"): "ASSOCIATED_WITH",
    ("david khan", "eva nair"): "MET_WITH",
}


def request(client: httpx.Client, method: str, path: str, **kwargs):
    response = client.request(method, path, **kwargs)
    response.raise_for_status()
    return response.json() if response.content else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:18000/api/v1")
    parser.add_argument("--password", default="SIH1@2026")
    args = parser.parse_args()

    with httpx.Client(base_url=args.base_url, timeout=240) as client:
        login = request(client, "POST", "/auth/login", json={"username": "sp.demo", "password": args.password})
        client.headers["Authorization"] = f"Bearer {login['access_token']}"

        cases = request(client, "GET", "/cases")
        if CASE_ID not in {item["id"] for item in cases}:
            raise RuntimeError(f"{CASE_ID} is not seeded; restart the rebuilt backend before loading the demo")

        with SEED_FILE.open("rb") as handle:
            evidence = request(
                client,
                "POST",
                f"/cases/{CASE_ID}/evidence",
                files={"file": (SEED_FILE.name, handle, "text/plain")},
            )

        deadline = time.monotonic() + 240
        job = None
        while time.monotonic() < deadline:
            jobs = request(client, "GET", f"/cases/{CASE_ID}/processing-jobs", params={"evidence_id": evidence["id"]})
            job = jobs[0] if jobs else None
            if job and job["status"] in {"completed", "failed"}:
                break
            time.sleep(1)
        if not job or job["status"] != "completed":
            raise RuntimeError(f"Evidence processing did not complete: {job}")

        bundle = request(client, "GET", f"/cases/{CASE_ID}/evidence/{evidence['id']}/extractions")
        mentions = {item["id"]: item for item in bundle["mentions"]}

        for mention in bundle["mentions"]:
            if mention["status"] in {"confirmed", "corrected", "rejected"}:
                continue
            normalized = mention["normalized_value"].strip().casefold()
            decision = "confirm" if mention["entity_type"] == "PERSON" and normalized in PEOPLE else "reject"
            request(
                client,
                "POST",
                f"/cases/{CASE_ID}/mentions/{mention['id']}/review",
                json={"decision": decision, "notes": "Explicitly reviewed fictional mobile-fraud demonstration data."},
            )

        selected_pairs = set()
        for relation in bundle["relations"]:
            subject = mentions[relation["subject_mention_id"]]["normalized_value"].strip().casefold()
            target = mentions[relation["object_mention_id"]]["normalized_value"].strip().casefold()
            pair = (subject, target)
            desired_type = RELATIONS.get(pair)
            if relation["status"] in {"confirmed", "corrected", "rejected"}:
                if (
                    desired_type
                    and relation["status"] in {"confirmed", "corrected"}
                    and relation["relation_type"] == desired_type
                ):
                    selected_pairs.add(pair)
                continue
            if desired_type and pair not in selected_pairs:
                selected_pairs.add(pair)
                payload = {
                    "decision": "correct",
                    "corrected_type": desired_type,
                    "notes": "Corrected to the relationship explicitly stated in the fictional source.",
                }
            else:
                payload = {
                    "decision": "reject",
                    "notes": "Rejected unrelated deterministic co-occurrence proposal.",
                }
            request(client, "POST", f"/cases/{CASE_ID}/relations/{relation['id']}/review", json=payload)

        missing = set(RELATIONS) - selected_pairs
        if missing:
            raise RuntimeError(f"Expected relationships were not extracted: {sorted(missing)}")

        request(client, "POST", f"/cases/{CASE_ID}/graph/rebuild")
        request(client, "POST", f"/cases/{CASE_ID}/graph/analytics")
        graph = request(client, "GET", f"/cases/{CASE_ID}/graph")
        person_values = sorted(
            node["label"] for node in graph["nodes"] if node["entity_type"] == "PERSON"
        )
        if {value.casefold() for value in person_values} != PEOPLE:
            raise RuntimeError(f"Expected exactly five reviewed people, received: {person_values}")
        print(
            {
                "case_id": CASE_ID,
                "evidence_id": evidence["id"],
                "people": person_values,
                "reviewed_relationships": len(graph["edges"]),
            }
        )


if __name__ == "__main__":
    main()
