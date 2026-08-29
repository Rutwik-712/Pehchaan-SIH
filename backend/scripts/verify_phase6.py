from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import httpx
import psycopg
from neo4j import GraphDatabase

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


def review_mention(client: httpx.Client, headers: dict[str, str], mention_id: str) -> None:
    response = client.post(
        f"{BASE_URL}/cases/{CASE_ID}/mentions/{mention_id}/review",
        headers=headers,
        json={"decision": "confirm", "notes": "Synthetic Phase 6 graph verification."},
    )
    response.raise_for_status()


def main() -> None:
    marker = datetime.now(timezone.utc).strftime("%H%M%S%f")
    first_name = f"Mahesh Kulkarni {marker}"
    alias_name = f"Mahesh Kulkarny {marker}"
    other_name = f"Rohan Mehta {marker}"

    with httpx.Client(timeout=30) as client:
        investigator = login(client, "investigator.demo")
        constable = login(client, "constable.demo")
        payload = (
            f"Synthetic Phase 6 proof {marker}\n"
            f"Person: {first_name}\n"
            f"Person: {alias_name}\n"
            f"Person: {other_name}\n"
            "Location: Pune Station\n"
            "Phone: 9876543210\n"
            f"{first_name} called {other_name} near Pune Station.\n"
            "All records are synthetic. Graph prominence is not a finding of guilt.\n"
        ).encode()
        upload = client.post(
            f"{BASE_URL}/cases/{CASE_ID}/evidence",
            headers={**investigator, "X-Request-ID": "phase6-live-proof"},
            files={"file": (f"phase6-live-{marker}.txt", payload, "text/plain")},
        )
        upload.raise_for_status()
        evidence_id = upload.json()["id"]

        job = None
        for _ in range(180):
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
        assert job is not None and job["status"] == "completed", job

        extraction = client.get(
            f"{BASE_URL}/cases/{CASE_ID}/evidence/{evidence_id}/extractions",
            headers=investigator,
        )
        extraction.raise_for_status()
        bundle = extraction.json()
        labelled_mentions = {
            item["value"]: item
            for item in bundle["mentions"]
            if item["extraction_method"] == "spacy_labeled_field_rule"
        }
        first = labelled_mentions[first_name]
        alias = labelled_mentions[alias_name]
        other = labelled_mentions[other_name]
        relation = next(
            item
            for item in bundle["relations"]
            if item["subject_mention_id"] == first["id"]
            and item["object_mention_id"] == other["id"]
        )

        initial_snapshot = client.post(
            f"{BASE_URL}/cases/{CASE_ID}/graph/rebuild", headers=investigator
        )
        initial_snapshot.raise_for_status()
        initial_graph = client.get(f"{BASE_URL}/cases/{CASE_ID}/graph", headers=investigator)
        initial_graph.raise_for_status()
        assert relation["id"] not in {item["id"] for item in initial_graph.json()["edges"]}

        for mention in (first, alias, other):
            review_mention(client, investigator, mention["id"])
        relation_review = client.post(
            f"{BASE_URL}/cases/{CASE_ID}/relations/{relation['id']}/review",
            headers=investigator,
            json={"decision": "confirm", "notes": "Synthetic reviewed relationship."},
        )
        relation_review.raise_for_status()

        resolution = client.post(
            f"{BASE_URL}/cases/{CASE_ID}/resolution/run", headers=investigator
        )
        resolution.raise_for_status()
        candidates = client.get(
            f"{BASE_URL}/cases/{CASE_ID}/resolution/candidates",
            headers=investigator,
        )
        candidates.raise_for_status()
        candidate = next(
            item
            for item in candidates.json()
            if {item["left_mention_id"], item["right_mention_id"]} == {first["id"], alias["id"]}
        )
        assert 0.60 <= candidate["match_probability"] < 1.0
        candidate_review = client.post(
            f"{BASE_URL}/cases/{CASE_ID}/resolution/candidates/{candidate['id']}/review",
            headers=investigator,
            json={"decision": "confirm", "notes": "Synthetic alias pair confirmed."},
        )
        candidate_review.raise_for_status()
        repeated = client.post(
            f"{BASE_URL}/cases/{CASE_ID}/resolution/candidates/{candidate['id']}/review",
            headers=investigator,
            json={"decision": "confirm"},
        )
        assert repeated.status_code == 409

        assert client.post(
            f"{BASE_URL}/cases/{CASE_ID}/graph/rebuild", headers=constable
        ).status_code == 403
        snapshot = client.post(
            f"{BASE_URL}/cases/{CASE_ID}/graph/rebuild", headers=investigator
        )
        snapshot.raise_for_status()
        assert snapshot.json()["node_count"] >= 2
        assert snapshot.json()["edge_count"] >= 1

        graph = client.get(f"{BASE_URL}/cases/{CASE_ID}/graph", headers=investigator)
        graph.raise_for_status()
        graph_body = graph.json()
        assert "not guilt" in graph_body["disclaimer"].lower()
        projected_relation = next(item for item in graph_body["edges"] if item["id"] == relation["id"])
        assert projected_relation["source_excerpt"]
        resolved_alias_node = next(
            item
            for item in graph_body["nodes"]
            if first_name in item["aliases"] and alias_name in item["aliases"]
        )
        assert resolved_alias_node["mention_count"] >= 2

        analytics_denied = client.post(
            f"{BASE_URL}/cases/{CASE_ID}/graph/analytics", headers=constable
        )
        assert analytics_denied.status_code == 403
        analytics = client.post(
            f"{BASE_URL}/cases/{CASE_ID}/graph/analytics", headers=investigator
        )
        analytics.raise_for_status()
        analytics_body = analytics.json()
        assert analytics_body["snapshot"]["status"] == "analytics_completed"
        assert analytics_body["rankings"]
        assert analytics_body["snapshot"]["algorithm_details"]["priority_uses_extraction_confidence"] is False
        assert "not indicate guilt" in analytics_body["disclaimer"].lower()

        timeline = client.get(
            f"{BASE_URL}/cases/{CASE_ID}/graph/timeline", headers=investigator
        )
        timeline.raise_for_status()
        assert relation["id"] in {item["relation_id"] for item in timeline.json()}

        path = client.get(
            f"{BASE_URL}/cases/{CASE_ID}/graph/path",
            headers=investigator,
            params={
                "source_id": projected_relation["source"],
                "target_id": projected_relation["target"],
            },
        )
        path.raise_for_status()
        assert path.json()["found"] is True
        assert path.json()["hop_count"] >= 1
        assert "not guilt" in path.json()["disclaimer"].lower()

        sp = login(client, "sp.demo")
        chain = client.get(f"{BASE_URL}/cases/{CASE_ID}/audit-chain/verify", headers=sp)
        chain.raise_for_status()
        assert chain.json()["valid"] is True

    with psycopg.connect("postgresql://sih:sih_dev_only@127.0.0.1:55432/sih") as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM resolution_runs WHERE case_id = %s AND status = 'completed'),
                    (SELECT COUNT(*) FROM resolved_entities WHERE case_id = %s),
                    (SELECT COUNT(*) FROM resolution_candidates WHERE id = %s AND status = 'confirmed'),
                    (SELECT COUNT(*) FROM graph_snapshots WHERE case_id = %s AND status = 'analytics_completed')
                """,
                (CASE_ID, CASE_ID, candidate["id"], CASE_ID),
            )
            run_count, entity_count, confirmed_candidate_count, analytics_snapshot_count = cursor.fetchone()
    assert run_count >= 1
    assert entity_count >= 2
    assert confirmed_candidate_count == 1
    assert analytics_snapshot_count >= 1

    driver = GraphDatabase.driver(
        "bolt://127.0.0.1:17687", auth=("neo4j", PASSWORD)
    )
    try:
        driver.verify_connectivity()
        with driver.session(database="neo4j") as graph_session:
            neo4j_counts = graph_session.run(
                """
                MATCH (node:Entity {case_id: $case_id})
                OPTIONAL MATCH (node)-[edge:EVIDENCE_RELATION]->(:Entity {case_id: $case_id})
                RETURN count(DISTINCT node) AS nodes, count(DISTINCT edge) AS edges
                """,
                case_id=CASE_ID,
            ).single()
            gds_version = graph_session.run("RETURN gds.version() AS version").single()["version"]
    finally:
        driver.close()
    assert neo4j_counts["nodes"] == snapshot.json()["node_count"]
    assert neo4j_counts["edges"] == snapshot.json()["edge_count"]

    print(
        json.dumps(
            {
                "reviewed_only_projection_gate": "passed",
                "splink_duckdb_candidate": "passed",
                "candidate_human_review": "passed",
                "neo4j_projection": "passed",
                "gds_algorithms": ["PageRank", "sampled betweenness", "Louvain"],
                "gds_version": gds_version,
                "timeline": "passed",
                "shortest_evidence_path": "passed",
                "graph_rbac": "passed",
                "not_guilt_disclaimers": "passed",
                "postgres_resolution_runs": run_count,
                "postgres_resolved_entities": entity_count,
                "neo4j_nodes": neo4j_counts["nodes"],
                "neo4j_edges": neo4j_counts["edges"],
                "audit_chain": chain.json(),
                "snapshot_id": snapshot.json()["id"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
