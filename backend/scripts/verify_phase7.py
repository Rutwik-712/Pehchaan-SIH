"""Read-only Phase 7 frontend-proxy contract verification. Prints no credentials or tokens."""

from __future__ import annotations

import json

import httpx

BASE_URL = "http://127.0.0.1:15173/api/v1"
CASE_ID = "KSP-CR-2048"
PASSWORD = "SIH1@2026"


def login(client: httpx.Client, username: str) -> dict[str, str]:
    response = client.post(
        f"{BASE_URL}/auth/login",
        json={"username": username, "password": PASSWORD},
    )
    response.raise_for_status()
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def get(client: httpx.Client, path: str, headers: dict[str, str]):
    response = client.get(f"{BASE_URL}{path}", headers=headers)
    response.raise_for_status()
    return response.json()


def main() -> None:
    with httpx.Client(timeout=30) as client:
        investigator = login(client, "investigator.demo")
        cases = get(client, "/cases", investigator)
        assert any(item["id"] == CASE_ID for item in cases)

        evidence = get(client, f"/cases/{CASE_ID}/evidence", investigator)
        jobs = get(client, f"/cases/{CASE_ID}/processing-jobs", investigator)
        queue = get(client, f"/cases/{CASE_ID}/review-queue", investigator)
        candidates = get(
            client,
            f"/cases/{CASE_ID}/resolution/candidates?pending_only=false",
            investigator,
        )
        graph = get(client, f"/cases/{CASE_ID}/graph", investigator)
        timeline = get(client, f"/cases/{CASE_ID}/graph/timeline", investigator)
        analytics_response = client.get(
            f"{BASE_URL}/cases/{CASE_ID}/graph/analytics", headers=investigator
        )
        assert analytics_response.status_code in {200, 409}
        analytics = analytics_response.json() if analytics_response.status_code == 200 else None

        assert all(item["case_id"] == CASE_ID for item in evidence)
        assert all(item["case_id"] == CASE_ID and "stages" in item for item in jobs)
        assert queue["total_pending"] == len(queue["mentions"]) + len(queue["relations"])
        assert all(item["left_value"] and item["right_value"] for item in candidates)
        assert "not guilt" in graph["disclaimer"]
        assert all(item["evidence_id"] and item["source_excerpt"] for item in graph["edges"])
        assert all(item["evidence_id"] and item["source_excerpt"] for item in timeline)
        if analytics:
            assert "do not indicate guilt" in analytics["disclaimer"]
            assert all("evidence_summary" in item for item in analytics["alerts"])

        constable = login(client, "constable.demo")
        assert client.get(
            f"{BASE_URL}/cases/{CASE_ID}/review-queue", headers=constable
        ).status_code == 403
        constable_graph = get(client, f"/cases/{CASE_ID}/graph", constable)
        assert len(constable_graph["nodes"]) == len(graph["nodes"])
        assert client.post(
            f"{BASE_URL}/cases/{CASE_ID}/graph/analytics", headers=constable
        ).status_code == 403

        sp = login(client, "sp.demo")
        chain = get(client, f"/cases/{CASE_ID}/audit-chain/verify", sp)
        assert chain["valid"] is True

    print(
        json.dumps(
            {
                "frontend_reverse_proxy": "passed",
                "investigator_case_scope": "passed",
                "evidence_and_job_views": "passed",
                "review_queue_contract": "passed",
                "resolution_candidate_labels": "passed",
                "reviewed_graph_contract": "passed",
                "timeline_provenance": "passed",
                "analytics_contract": "passed" if analytics else "graph_not_built",
                "constable_rbac": "passed",
                "sp_audit_chain": chain,
                "evidence_sources": len(evidence),
                "processing_jobs": len(jobs),
                "pending_review": queue["total_pending"],
                "resolution_candidates": len(candidates),
                "graph_nodes": len(graph["nodes"]),
                "graph_edges": len(graph["edges"]),
                "timeline_events": len(timeline),
                "graph_alerts": len(analytics["alerts"]) if analytics else 0,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
