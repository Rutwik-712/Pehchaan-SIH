from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, aliased

from app.entity_policy import is_supported_graph_entity
from app.graph_store import ANALYTICS_VERSION, apply_graph_metrics, replace_case_graph, run_gds_analytics
from app.models import (
    EvidenceSource,
    ExtractedMention,
    ExtractedRelation,
    GraphAlert,
    GraphSnapshot,
    ResolutionRun,
    ResolvedEntity,
    ResolvedMention,
)

TRUSTED_REVIEW_STATUSES = {"confirmed", "corrected"}


def latest_completed_resolution(session: Session, case_id: str) -> ResolutionRun:
    run = session.scalar(
        select(ResolutionRun)
        .where(ResolutionRun.case_id == case_id, ResolutionRun.status == "completed")
        .order_by(ResolutionRun.created_at.desc())
        .limit(1)
    )
    if run is None:
        raise ValueError("Run entity resolution before graph projection")
    return run


def build_projection_rows(
    session: Session, case_id: str, run_id: str
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    entities = list(
        session.scalars(
            select(ResolvedEntity)
            .where(ResolvedEntity.case_id == case_id)
            .order_by(ResolvedEntity.canonical_value.asc())
        ).all()
    )
    nodes: List[Dict[str, Any]] = []
    for entity in entities:
        if not is_supported_graph_entity(entity.entity_type, entity.canonical_value):
            continue
        aliases = list(
            session.scalars(
                select(ExtractedMention.value)
                .join(ResolvedMention, ResolvedMention.mention_id == ExtractedMention.id)
                .where(
                    ResolvedMention.entity_id == entity.id,
                    ResolvedMention.run_id == run_id,
                )
                .distinct()
                .order_by(ExtractedMention.value.asc())
            ).all()
        )
        evidence_count = session.scalar(
            select(func.count(func.distinct(ExtractedMention.evidence_id)))
            .join(ResolvedMention, ResolvedMention.mention_id == ExtractedMention.id)
            .where(
                ResolvedMention.entity_id == entity.id,
                ResolvedMention.run_id == run_id,
            )
        ) or 0
        nodes.append(
            {
                "id": entity.id,
                "case_id": case_id,
                "entity_type": entity.entity_type,
                "canonical_value": entity.canonical_value,
                "normalized_value": entity.normalized_value,
                "aliases": aliases,
                "mention_count": entity.mention_count,
                "evidence_count": int(evidence_count),
                "resolution_method": entity.resolution_method,
                "resolution_confidence": entity.confidence,
            }
        )

    subject_link = aliased(ResolvedMention)
    object_link = aliased(ResolvedMention)
    subject_mention = aliased(ExtractedMention)
    relation_rows = session.execute(
        select(
            ExtractedRelation,
            subject_link.entity_id,
            object_link.entity_id,
            subject_mention.page_number,
            EvidenceSource.created_at,
        )
        .join(subject_link, subject_link.mention_id == ExtractedRelation.subject_mention_id)
        .join(object_link, object_link.mention_id == ExtractedRelation.object_mention_id)
        .join(subject_mention, subject_mention.id == ExtractedRelation.subject_mention_id)
        .join(EvidenceSource, EvidenceSource.id == ExtractedRelation.evidence_id)
        .where(
            ExtractedRelation.case_id == case_id,
            ExtractedRelation.status.in_(TRUSTED_REVIEW_STATUSES),
            subject_link.run_id == run_id,
            object_link.run_id == run_id,
        )
        .order_by(ExtractedRelation.created_at.asc())
    ).all()
    included_entity_ids = {item["id"] for item in nodes}
    edges: List[Dict[str, Any]] = []
    for relation, source_entity_id, target_entity_id, page_number, observed_at in relation_rows:
        if source_entity_id == target_entity_id or source_entity_id not in included_entity_ids or target_entity_id not in included_entity_ids:
            continue
        edges.append(
            {
                "id": relation.id,
                "source": source_entity_id,
                "target": target_entity_id,
                "relation_type": relation.relation_type,
                "evidence_id": relation.evidence_id,
                "document_id": relation.document_id,
                "page_number": int(page_number),
                "source_excerpt": relation.source_excerpt,
                "extraction_method": relation.extraction_method,
                "confidence_percent": relation.confidence_percent,
                "observed_at": observed_at.isoformat(),
            }
        )
    return nodes, edges


def project_case_graph(session: Session, case_id: str, requested_by_id: str) -> GraphSnapshot:
    resolution_run = latest_completed_resolution(session, case_id)
    nodes, edges = build_projection_rows(session, case_id, resolution_run.id)
    replace_case_graph(case_id, nodes, edges)
    snapshot = GraphSnapshot(
        case_id=case_id,
        resolution_run_id=resolution_run.id,
        node_count=len(nodes),
        edge_count=len(edges),
        status="projected",
        created_by_id=requested_by_id,
        algorithm_details={
            "trusted_statuses": sorted(TRUSTED_REVIEW_STATUSES),
            "provenance_on_every_edge": True,
            "guilt_inference": False,
        },
    )
    session.add(snapshot)
    session.flush()
    return snapshot


def _priority_level(score: float) -> int:
    if score >= 4:
        return 1
    if score >= 3:
        return 2
    if score >= 2:
        return 3
    if score >= 1:
        return 4
    return 5


def run_case_analytics(session: Session, case_id: str, snapshot: GraphSnapshot) -> GraphSnapshot:
    entities = [item for item in
        session.scalars(select(ResolvedEntity).where(ResolvedEntity.case_id == case_id)).all()
        if is_supported_graph_entity(item.entity_type, item.canonical_value)
    ]
    raw_metrics = run_gds_analytics(case_id) if entities else {}
    graph_nodes, _edges = build_projection_rows(session, case_id, snapshot.resolution_run_id)
    evidence_counts = {item["id"]: int(item["evidence_count"]) for item in graph_nodes}
    max_pagerank = max((float(values.get("pagerank", 0)) for values in raw_metrics.values()), default=0)
    max_betweenness = max((float(values.get("betweenness", 0)) for values in raw_metrics.values()), default=0)
    max_degree = max((int(values.get("degree", 0)) for values in raw_metrics.values()), default=0)
    max_evidence = max(evidence_counts.values(), default=0)
    metric_rows: List[Dict[str, Any]] = []
    session.execute(
        delete(GraphAlert).where(
            GraphAlert.case_id == case_id,
            GraphAlert.snapshot_id == snapshot.id,
        )
    )
    for entity in entities:
        values = raw_metrics.get(entity.id, {})
        pagerank = float(values.get("pagerank", 0.0))
        betweenness = float(values.get("betweenness", 0.0))
        degree = int(values.get("degree", 0))
        community_id = values.get("community_id")
        structural_score = 5 * (
            0.45 * (pagerank / max_pagerank if max_pagerank else 0)
            + 0.30 * (betweenness / max_betweenness if max_betweenness else 0)
            + 0.15 * (degree / max_degree if max_degree else 0)
            + 0.10 * (evidence_counts.get(entity.id, 0) / max_evidence if max_evidence else 0)
        )
        priority_score = round(min(5.0, structural_score), 4)
        entity.pagerank = pagerank
        entity.betweenness = betweenness
        entity.degree = degree
        entity.community_id = int(community_id) if community_id is not None else None
        entity.priority_score = priority_score
        entity.priority_level = _priority_level(priority_score)
        metric_rows.append(
            {
                "id": entity.id,
                "pagerank": pagerank,
                "betweenness": betweenness,
                "degree": degree,
                "community_id": entity.community_id,
                "priority_score": priority_score,
                "priority_level": entity.priority_level,
            }
        )
        if degree >= 3:
            session.add(
                GraphAlert(
                    case_id=case_id,
                    snapshot_id=snapshot.id,
                    entity_id=entity.id,
                    rule_code="GRAPH-CONNECTIVITY-01",
                    severity_level=2,
                    title="High reviewed connectivity",
                    explanation="This entity has at least three reviewed graph connections and may warrant structural review.",
                    evidence_summary={"degree": degree},
                )
            )
        if betweenness > 0:
            session.add(
                GraphAlert(
                    case_id=case_id,
                    snapshot_id=snapshot.id,
                    entity_id=entity.id,
                    rule_code="GRAPH-BRIDGE-02",
                    severity_level=2,
                    title="Potential community bridge",
                    explanation="Sampled betweenness indicates that this entity lies on reviewed paths between other entities.",
                    evidence_summary={"betweenness": betweenness},
                )
            )
        if evidence_counts.get(entity.id, 0) >= 2:
            session.add(
                GraphAlert(
                    case_id=case_id,
                    snapshot_id=snapshot.id,
                    entity_id=entity.id,
                    rule_code="GRAPH-MULTISOURCE-03",
                    severity_level=3,
                    title="Observed in multiple evidence sources",
                    explanation="Reviewed mentions for this entity occur in more than one evidence source.",
                    evidence_summary={"evidence_count": evidence_counts[entity.id]},
                )
            )
    apply_graph_metrics(case_id, metric_rows)
    snapshot.status = "analytics_completed"
    snapshot.analytics_version = ANALYTICS_VERSION
    snapshot.algorithm_details = {
        **snapshot.algorithm_details,
        "pagerank": "gds.pageRank",
        "betweenness": "gds.betweenness samplingSize=100",
        "community": "gds.louvain",
        "priority_uses_extraction_confidence": False,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    session.flush()
    return snapshot
