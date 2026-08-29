from __future__ import annotations

from functools import lru_cache
from hashlib import sha256
from typing import Any, Dict, Iterable, List, Optional

from neo4j import GraphDatabase

from app.config import get_settings

ANALYTICS_VERSION = "neo4j-gds-phase6-v1"


@lru_cache(maxsize=1)
def get_graph_driver():
    settings = get_settings()
    return GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )


def verify_graph_connection() -> None:
    get_graph_driver().verify_connectivity()


def ensure_graph_schema() -> None:
    settings = get_settings()
    statements = (
        "CREATE CONSTRAINT entity_case_id IF NOT EXISTS FOR (n:Entity) REQUIRE (n.case_id, n.id) IS UNIQUE",
        "CREATE INDEX entity_case IF NOT EXISTS FOR (n:Entity) ON (n.case_id)",
        "CREATE INDEX evidence_relation_case IF NOT EXISTS FOR ()-[r:EVIDENCE_RELATION]-() ON (r.case_id)",
    )
    with get_graph_driver().session(database=settings.neo4j_database) as graph_session:
        for statement in statements:
            graph_session.run(statement).consume()


def replace_case_graph(case_id: str, nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> None:
    settings = get_settings()
    ensure_graph_schema()
    with get_graph_driver().session(database=settings.neo4j_database) as graph_session:
        graph_session.run(
            "MATCH (n:Entity {case_id: $case_id}) DETACH DELETE n",
            case_id=case_id,
        ).consume()
        if nodes:
            graph_session.run(
                """
                UNWIND $rows AS row
                CREATE (n:Entity {
                    id: row.id,
                    case_id: row.case_id,
                    entity_type: row.entity_type,
                    canonical_value: row.canonical_value,
                    normalized_value: row.normalized_value,
                    aliases: row.aliases,
                    mention_count: row.mention_count,
                    evidence_count: row.evidence_count,
                    resolution_method: row.resolution_method,
                    resolution_confidence: row.resolution_confidence,
                    pagerank: 0.0,
                    betweenness: 0.0,
                    degree: 0,
                    priority_score: 0.0,
                    priority_level: 5
                })
                """,
                rows=nodes,
            ).consume()
        if edges:
            graph_session.run(
                """
                UNWIND $rows AS row
                MATCH (source:Entity {case_id: $case_id, id: row.source})
                MATCH (target:Entity {case_id: $case_id, id: row.target})
                CREATE (source)-[r:EVIDENCE_RELATION {
                    id: row.id,
                    case_id: $case_id,
                    source: row.source,
                    target: row.target,
                    relation_type: row.relation_type,
                    evidence_id: row.evidence_id,
                    document_id: row.document_id,
                    page_number: row.page_number,
                    source_excerpt: row.source_excerpt,
                    extraction_method: row.extraction_method,
                    confidence_percent: row.confidence_percent,
                    observed_at: datetime(row.observed_at)
                }]->(target)
                """,
                case_id=case_id,
                rows=edges,
            ).consume()


def _projection_name(case_id: str) -> str:
    return f"case_{sha256(case_id.encode()).hexdigest()[:20]}"


def run_gds_analytics(case_id: str) -> Dict[str, Dict[str, Any]]:
    settings = get_settings()
    graph_name = _projection_name(case_id)
    with get_graph_driver().session(database=settings.neo4j_database) as graph_session:
        exists = graph_session.run(
            "CALL gds.graph.exists($name) YIELD exists RETURN exists",
            name=graph_name,
        ).single()["exists"]
        if exists:
            graph_session.run(
                "CALL gds.graph.drop($name, false) YIELD graphName RETURN graphName",
                name=graph_name,
            ).consume()
        graph_session.run(
            """
            CALL gds.graph.project.cypher(
                $name,
                'MATCH (n:Entity) WHERE n.case_id = $case_id RETURN id(n) AS id',
                'MATCH (a:Entity)-[r:EVIDENCE_RELATION]->(b:Entity) WHERE r.case_id = $case_id RETURN id(a) AS source, id(b) AS target',
                {parameters: {case_id: $case_id}, validateRelationships: false}
            )
            YIELD graphName, nodeCount, relationshipCount
            RETURN graphName, nodeCount, relationshipCount
            """,
            name=graph_name,
            case_id=case_id,
        ).consume()

        metrics: Dict[str, Dict[str, Any]] = {}
        for record in graph_session.run(
            """
            CALL gds.pageRank.stream($name)
            YIELD nodeId, score
            RETURN gds.util.asNode(nodeId).id AS id, score
            """,
            name=graph_name,
        ):
            metrics.setdefault(record["id"], {})["pagerank"] = float(record["score"])
        for record in graph_session.run(
            """
            CALL gds.betweenness.stream($name, {samplingSize: 100})
            YIELD nodeId, score
            RETURN gds.util.asNode(nodeId).id AS id, score
            """,
            name=graph_name,
        ):
            metrics.setdefault(record["id"], {})["betweenness"] = float(record["score"])
        for record in graph_session.run(
            """
            CALL gds.louvain.stream($name)
            YIELD nodeId, communityId
            RETURN gds.util.asNode(nodeId).id AS id, communityId
            """,
            name=graph_name,
        ):
            metrics.setdefault(record["id"], {})["community_id"] = int(record["communityId"])
        for record in graph_session.run(
            """
            MATCH (n:Entity {case_id: $case_id})
            OPTIONAL MATCH (n)-[r:EVIDENCE_RELATION]-(:Entity {case_id: $case_id})
            RETURN n.id AS id, count(r) AS degree
            """,
            case_id=case_id,
        ):
            metrics.setdefault(record["id"], {})["degree"] = int(record["degree"])
        graph_session.run(
            "CALL gds.graph.drop($name, false) YIELD graphName RETURN graphName",
            name=graph_name,
        ).consume()
    return metrics


def apply_graph_metrics(case_id: str, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    settings = get_settings()
    with get_graph_driver().session(database=settings.neo4j_database) as graph_session:
        graph_session.run(
            """
            UNWIND $rows AS row
            MATCH (n:Entity {case_id: $case_id, id: row.id})
            SET n.pagerank = row.pagerank,
                n.betweenness = row.betweenness,
                n.degree = row.degree,
                n.community_id = row.community_id,
                n.priority_score = row.priority_score,
                n.priority_level = row.priority_level
            """,
            case_id=case_id,
            rows=rows,
        ).consume()


def read_case_graph(case_id: str) -> Dict[str, List[Dict[str, Any]]]:
    settings = get_settings()
    with get_graph_driver().session(database=settings.neo4j_database) as graph_session:
        nodes = [
            dict(record["node"])
            for record in graph_session.run(
                "MATCH (n:Entity {case_id: $case_id}) RETURN properties(n) AS node ORDER BY n.canonical_value",
                case_id=case_id,
            )
        ]
        edges = [
            dict(record["edge"])
            for record in graph_session.run(
                """
                MATCH (:Entity {case_id: $case_id})-[r:EVIDENCE_RELATION]->(:Entity {case_id: $case_id})
                RETURN properties(r) AS edge ORDER BY r.observed_at, r.id
                """,
                case_id=case_id,
            )
        ]
    for edge in edges:
        if edge.get("observed_at") is not None:
            edge["observed_at"] = edge["observed_at"].to_native()
    return {"nodes": nodes, "edges": edges}


def shortest_evidence_path(
    case_id: str, source_id: str, target_id: str, max_hops: int = 8
) -> Optional[Dict[str, Any]]:
    if max_hops < 1 or max_hops > 8:
        raise ValueError("max_hops must be between 1 and 8")
    settings = get_settings()
    query = f"""
        MATCH (source:Entity {{case_id: $case_id, id: $source_id}})
        MATCH (target:Entity {{case_id: $case_id, id: $target_id}})
        MATCH path = shortestPath((source)-[:EVIDENCE_RELATION*..{max_hops}]-(target))
        RETURN [node IN nodes(path) | node.id] AS node_ids,
               [edge IN relationships(path) | properties(edge)] AS edges
    """
    with get_graph_driver().session(database=settings.neo4j_database) as graph_session:
        record = graph_session.run(
            query,
            case_id=case_id,
            source_id=source_id,
            target_id=target_id,
        ).single()
    if record is None:
        return None
    edges = [dict(item) for item in record["edges"]]
    for edge in edges:
        if edge.get("observed_at") is not None:
            edge["observed_at"] = edge["observed_at"].to_native()
    return {"node_ids": list(record["node_ids"]), "edges": edges}
