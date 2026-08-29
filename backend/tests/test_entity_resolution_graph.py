from __future__ import annotations

from types import SimpleNamespace
from typing import Dict
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.entity_resolution import _splink_predictions
from app.main import app

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


def test_splink_produces_review_candidate_without_automatic_merge() -> None:
    mentions = [
        SimpleNamespace(id="m1", entity_type="PERSON", normalized_value="vikram sharma"),
        SimpleNamespace(id="m2", entity_type="PERSON", normalized_value="vikram sharama"),
        SimpleNamespace(id="m3", entity_type="LOCATION", normalized_value="pune"),
    ]
    predictions = _splink_predictions(mentions)
    assert len(predictions) == 1
    assert predictions[0][0:2] == ("m1", "m2")
    assert 0.60 <= predictions[0][2] < 1


def test_reviewed_only_resolution_projection_and_analytics(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    investigator = login(client, "investigator.demo")
    constable = login(client, "constable.demo")
    payload = (
        f"Synthetic graph proof {uuid4()}\n"
        "Person: Asha Kulkarni\n"
        "Person: Rohan Mehta\n"
        "Location: Pune Station\n"
        "Phone: 9876543210\n"
        "Asha Kulkarni called Rohan Mehta near Pune Station.\n"
    ).encode()
    upload = client.post(
        f"/api/v1/cases/{CASE_ID}/evidence",
        headers=investigator,
        files={"file": ("phase6-unit.txt", payload, "text/plain")},
    )
    assert upload.status_code == 201, upload.text
    evidence_id = upload.json()["id"]
    bundle_response = client.get(
        f"/api/v1/cases/{CASE_ID}/evidence/{evidence_id}/extractions",
        headers=investigator,
    )
    assert bundle_response.status_code == 200, bundle_response.text
    bundle = bundle_response.json()

    empty_run = client.post(f"/api/v1/cases/{CASE_ID}/resolution/run", headers=investigator)
    assert empty_run.status_code == 200
    assert empty_run.json()["mention_count"] == 0

    relation = bundle["relations"][0]
    trusted_mention_ids = {relation["subject_mention_id"], relation["object_mention_id"]}
    for mention_id in trusted_mention_ids:
        reviewed = client.post(
            f"/api/v1/cases/{CASE_ID}/mentions/{mention_id}/review",
            headers=investigator,
            json={"decision": "confirm", "notes": "Phase 6 reviewed graph fact."},
        )
        assert reviewed.status_code == 200, reviewed.text
    relation_review = client.post(
        f"/api/v1/cases/{CASE_ID}/relations/{relation['id']}/review",
        headers=investigator,
        json={"decision": "confirm", "notes": "Phase 6 reviewed graph edge."},
    )
    assert relation_review.status_code == 200, relation_review.text

    resolution = client.post(f"/api/v1/cases/{CASE_ID}/resolution/run", headers=investigator)
    assert resolution.status_code == 200, resolution.text
    assert resolution.json()["mention_count"] == len(trusted_mention_ids)
    assert resolution.json()["entity_count"] >= 1
    assert client.get(
        f"/api/v1/cases/{CASE_ID}/resolution/candidates", headers=constable
    ).status_code == 403

    captured = {}

    def fake_replace(case_id, nodes, edges):
        captured["case_id"] = case_id
        captured["nodes"] = nodes
        captured["edges"] = edges

    monkeypatch.setattr("app.graph_service.replace_case_graph", fake_replace)
    snapshot = client.post(f"/api/v1/cases/{CASE_ID}/graph/rebuild", headers=investigator)
    assert snapshot.status_code == 200, snapshot.text
    assert snapshot.json()["node_count"] == len(captured["nodes"])
    assert snapshot.json()["edge_count"] == 1
    assert captured["edges"][0]["id"] == relation["id"]
    assert all(item["source_excerpt"] for item in captured["edges"])

    entity_ids = [item["id"] for item in captured["nodes"]]
    metrics = {
        entity_id: {
            "pagerank": 1.0 / max(1, len(entity_ids)),
            "betweenness": 0.5 if index == 0 else 0.0,
            "degree": 1,
            "community_id": 7,
        }
        for index, entity_id in enumerate(entity_ids)
    }
    monkeypatch.setattr("app.graph_service.run_gds_analytics", lambda _case_id: metrics)
    monkeypatch.setattr("app.graph_service.apply_graph_metrics", lambda _case_id, _rows: None)
    analytics = client.post(f"/api/v1/cases/{CASE_ID}/graph/analytics", headers=investigator)
    assert analytics.status_code == 200, analytics.text
    assert analytics.json()["snapshot"]["status"] == "analytics_completed"
    assert analytics.json()["rankings"]
    assert "not indicate guilt" in analytics.json()["disclaimer"]
    assert any(item["rule_code"] == "GRAPH-BRIDGE-02" for item in analytics.json()["alerts"])

    alert_id = analytics.json()["alerts"][0]["id"]
    reviewed_alert = client.post(
        f"/api/v1/cases/{CASE_ID}/graph/alerts/{alert_id}/review",
        headers=investigator,
        json={"notes": "Reviewed as an analytical lead."},
    )
    assert reviewed_alert.status_code == 200, reviewed_alert.text
    assert reviewed_alert.json()["status"] == "reviewed"
    assert client.post(
        f"/api/v1/cases/{CASE_ID}/graph/alerts/{alert_id}/review",
        headers=investigator,
        json={"notes": "Repeated review should fail."},
    ).status_code == 409
    assert client.post(
        f"/api/v1/cases/{CASE_ID}/graph/alerts/{alert_id}/review",
        headers=constable,
        json={},
    ).status_code == 403

    fake_graph = {
        "nodes": [
            {
                **item,
                "pagerank": metrics[item["id"]]["pagerank"],
                "betweenness": metrics[item["id"]]["betweenness"],
                "degree": 1,
                "community_id": 7,
                "priority_score": 2.5,
                "priority_level": 3,
            }
            for item in captured["nodes"]
        ],
        "edges": [captured["edges"][0]],
    }
    monkeypatch.setattr("app.api.routes.graph.read_case_graph", lambda _case_id: fake_graph)
    graph = client.get(f"/api/v1/cases/{CASE_ID}/graph", headers=investigator)
    assert graph.status_code == 200, graph.text
    assert len(graph.json()["edges"]) == 1
    assert "not guilt determinations" in graph.json()["disclaimer"]

    monkeypatch.setattr(
        "app.api.routes.graph.shortest_evidence_path",
        lambda *_args, **_kwargs: {"node_ids": entity_ids, "edges": fake_graph["edges"]},
    )
    if len(entity_ids) >= 2:
        path = client.get(
            f"/api/v1/cases/{CASE_ID}/graph/path",
            headers=investigator,
            params={"source_id": entity_ids[0], "target_id": entity_ids[1]},
        )
        assert path.status_code == 200, path.text
        assert path.json()["found"] is True
        assert path.json()["hop_count"] == 1
