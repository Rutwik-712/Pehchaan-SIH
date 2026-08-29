from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from neo4j.exceptions import Neo4jError, ServiceUnavailable
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.access import case_for_user
from app.audit import append_audit
from app.database import get_db
from app.entity_policy import is_supported_graph_entity
from app.entity_resolution import run_entity_resolution
from app.graph_service import project_case_graph, run_case_analytics
from app.graph_store import read_case_graph, shortest_evidence_path
from app.models import (
    GraphAlert,
    GraphSnapshot,
    ResolutionCandidate,
    ResolvedEntity,
    ReviewDecision,
    User,
)
from app.permissions import Permission
from app.schemas import (
    EvidencePathOut,
    GraphAlertOut,
    GraphAlertReview,
    GraphAnalyticsOut,
    GraphBundleOut,
    GraphEdgeOut,
    GraphNodeOut,
    GraphSnapshotOut,
    ResolutionCandidateOut,
    ResolutionCandidateReview,
    ResolutionRunOut,
    ResolvedEntityOut,
    ReviewDecisionOut,
    TimelineEventOut,
)
from app.security import get_current_user, require_permission

router = APIRouter(prefix="/cases")


def _candidate_out(session: Session, candidate: ResolutionCandidate) -> ResolutionCandidateOut:
    from app.models import ExtractedMention

    left = session.get(ExtractedMention, candidate.left_mention_id)
    right = session.get(ExtractedMention, candidate.right_mention_id)
    if left is None or right is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Resolution candidate source mention missing",
        )
    return ResolutionCandidateOut(
        id=candidate.id,
        case_id=candidate.case_id,
        left_mention_id=candidate.left_mention_id,
        right_mention_id=candidate.right_mention_id,
        left_value=left.value,
        right_value=right.value,
        entity_type=candidate.entity_type,
        match_probability=candidate.match_probability,
        method=candidate.method,
        status=candidate.status,
        reviewed_by_id=candidate.reviewed_by_id,
        reviewed_at=candidate.reviewed_at,
        created_at=candidate.created_at,
    )


def _graph_unavailable(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=f"Local Neo4j graph service unavailable ({type(exc).__name__})",
    )


def _latest_snapshot(session: Session, case_id: str) -> GraphSnapshot:
    snapshot = session.scalar(
        select(GraphSnapshot)
        .where(GraphSnapshot.case_id == case_id)
        .order_by(GraphSnapshot.created_at.desc())
        .limit(1)
    )
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Build the case graph first")
    return snapshot


@router.post("/{case_id}/resolution/run", response_model=ResolutionRunOut)
def resolve_case_entities(
    case_id: str,
    request: Request,
    current_user: User = Depends(require_permission(Permission.ANALYTICS_RUN)),
    session: Session = Depends(get_db),
) -> ResolutionRunOut:
    case_for_user(session, case_id, current_user)
    try:
        run = run_entity_resolution(session, case_id, current_user.id)
        append_audit(
            session,
            action="resolution.run",
            resource_type="resolution_run",
            resource_id=run.id,
            case_id=case_id,
            user_id=current_user.id,
            request=request,
            details={
                "mentions": run.mention_count,
                "entities": run.entity_count,
                "pending_candidates": run.candidate_count,
            },
        )
        session.commit()
        session.refresh(run)
        return ResolutionRunOut.model_validate(run)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/{case_id}/resolution/candidates", response_model=List[ResolutionCandidateOut])
def list_resolution_candidates(
    case_id: str,
    request: Request,
    pending_only: bool = True,
    current_user: User = Depends(require_permission(Permission.ENTITY_REVIEW)),
    session: Session = Depends(get_db),
) -> List[ResolutionCandidateOut]:
    case_for_user(session, case_id, current_user)
    statement = select(ResolutionCandidate).where(ResolutionCandidate.case_id == case_id)
    if pending_only:
        statement = statement.where(ResolutionCandidate.status == "pending_review")
    candidates = list(
        session.scalars(statement.order_by(ResolutionCandidate.match_probability.desc())).all()
    )
    append_audit(
        session,
        action="resolution.candidates_view",
        resource_type="resolution_candidate_collection",
        resource_id=case_id,
        case_id=case_id,
        user_id=current_user.id,
        request=request,
        details={"result_count": len(candidates), "pending_only": pending_only},
    )
    session.commit()
    return [_candidate_out(session, item) for item in candidates]


@router.post(
    "/{case_id}/resolution/candidates/{candidate_id}/review",
    response_model=ReviewDecisionOut,
)
def review_resolution_candidate(
    case_id: str,
    candidate_id: str,
    payload: ResolutionCandidateReview,
    request: Request,
    current_user: User = Depends(require_permission(Permission.ENTITY_REVIEW)),
    session: Session = Depends(get_db),
) -> ReviewDecisionOut:
    case_for_user(session, case_id, current_user)
    candidate = session.scalar(
        select(ResolutionCandidate).where(
            ResolutionCandidate.id == candidate_id,
            ResolutionCandidate.case_id == case_id,
        )
    )
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resolution candidate not found")
    if candidate.status != "pending_review":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Candidate already has a final decision")
    candidate.status = "confirmed" if payload.decision == "confirm" else "rejected"
    candidate.reviewed_by_id = current_user.id
    candidate.reviewed_at = datetime.now(timezone.utc)
    decision = ReviewDecision(
        case_id=case_id,
        job_id=_candidate_job_id(session, candidate),
        target_type="resolution_candidate",
        target_id=candidate.id,
        decision=payload.decision,
        original_value={
            "left_mention_id": candidate.left_mention_id,
            "right_mention_id": candidate.right_mention_id,
            "match_probability": candidate.match_probability,
        },
        corrected_value={"resolution_status": candidate.status},
        notes=payload.notes.strip(),
        reviewed_by_id=current_user.id,
    )
    session.add(decision)
    append_audit(
        session,
        action="resolution.candidate_decision",
        resource_type="resolution_candidate",
        resource_id=candidate.id,
        case_id=case_id,
        user_id=current_user.id,
        request=request,
        details={"decision": payload.decision},
    )
    session.commit()
    session.refresh(decision)
    return ReviewDecisionOut.model_validate(decision)


def _candidate_job_id(session: Session, candidate: ResolutionCandidate) -> str:
    from app.models import ExtractedMention

    mention = session.get(ExtractedMention, candidate.left_mention_id)
    if mention is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Candidate source mention missing")
    return mention.job_id


@router.post("/{case_id}/graph/rebuild", response_model=GraphSnapshotOut)
def rebuild_case_graph(
    case_id: str,
    request: Request,
    current_user: User = Depends(require_permission(Permission.ANALYTICS_RUN)),
    session: Session = Depends(get_db),
) -> GraphSnapshotOut:
    case_for_user(session, case_id, current_user)
    try:
        resolution_run = run_entity_resolution(session, case_id, current_user.id)
        snapshot = project_case_graph(session, case_id, current_user.id)
        append_audit(
            session,
            action="graph.rebuild",
            resource_type="graph_snapshot",
            resource_id=snapshot.id,
            case_id=case_id,
            user_id=current_user.id,
            request=request,
            details={
                "resolution_run_id": resolution_run.id,
                "nodes": snapshot.node_count,
                "edges": snapshot.edge_count,
                "reviewed_only": True,
            },
        )
        session.commit()
        session.refresh(snapshot)
        return GraphSnapshotOut.model_validate(snapshot)
    except (Neo4jError, ServiceUnavailable, OSError) as exc:
        session.rollback()
        raise _graph_unavailable(exc) from exc
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/{case_id}/graph/analytics", response_model=GraphAnalyticsOut)
def analyze_case_graph(
    case_id: str,
    request: Request,
    current_user: User = Depends(require_permission(Permission.ANALYTICS_RUN)),
    session: Session = Depends(get_db),
) -> GraphAnalyticsOut:
    case_for_user(session, case_id, current_user)
    snapshot = _latest_snapshot(session, case_id)
    try:
        run_case_analytics(session, case_id, snapshot)
        append_audit(
            session,
            action="graph.analytics_run",
            resource_type="graph_snapshot",
            resource_id=snapshot.id,
            case_id=case_id,
            user_id=current_user.id,
            request=request,
            details={"analytics_version": snapshot.analytics_version},
        )
        session.commit()
        return _analytics_output(session, case_id, snapshot)
    except (Neo4jError, ServiceUnavailable, OSError) as exc:
        session.rollback()
        raise _graph_unavailable(exc) from exc


def _analytics_output(session: Session, case_id: str, snapshot: GraphSnapshot) -> GraphAnalyticsOut:
    entities = [item for item in
        session.scalars(
            select(ResolvedEntity)
            .where(ResolvedEntity.case_id == case_id)
            .order_by(ResolvedEntity.priority_score.desc(), ResolvedEntity.canonical_value.asc())
        ).all()
        if is_supported_graph_entity(item.entity_type, item.canonical_value)
    ]
    alerts = list(
        session.scalars(
            select(GraphAlert)
            .where(GraphAlert.case_id == case_id, GraphAlert.snapshot_id == snapshot.id)
            .order_by(GraphAlert.severity_level.asc(), GraphAlert.created_at.asc())
        ).all()
    )
    return GraphAnalyticsOut(
        snapshot=GraphSnapshotOut.model_validate(snapshot),
        rankings=[ResolvedEntityOut.model_validate(item) for item in entities],
        alerts=[GraphAlertOut.model_validate(item) for item in alerts],
    )


@router.get("/{case_id}/graph", response_model=GraphBundleOut)
def get_case_graph(
    case_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> GraphBundleOut:
    case_for_user(session, case_id, current_user)
    snapshot = session.scalar(
        select(GraphSnapshot)
        .where(GraphSnapshot.case_id == case_id)
        .order_by(GraphSnapshot.created_at.desc())
        .limit(1)
    )
    try:
        graph = read_case_graph(case_id)
    except (Neo4jError, ServiceUnavailable, OSError) as exc:
        raise _graph_unavailable(exc) from exc
    append_audit(
        session,
        action="graph.view",
        resource_type="case_graph",
        resource_id=case_id,
        case_id=case_id,
        user_id=current_user.id,
        request=request,
        details={"nodes": len(graph["nodes"]), "edges": len(graph["edges"])},
    )
    session.commit()
    return GraphBundleOut(
        case_id=case_id,
        snapshot_id=snapshot.id if snapshot else None,
        generated_at=snapshot.created_at if snapshot else None,
        nodes=[
            GraphNodeOut(
                id=item["id"],
                entity_type=item["entity_type"],
                label=item["canonical_value"],
                aliases=list(item.get("aliases", [])),
                mention_count=int(item.get("mention_count", 0)),
                evidence_count=int(item.get("evidence_count", 0)),
                pagerank=float(item.get("pagerank", 0)),
                betweenness=float(item.get("betweenness", 0)),
                degree=int(item.get("degree", 0)),
                community_id=item.get("community_id"),
                priority_score=float(item.get("priority_score", 0)),
                priority_level=int(item.get("priority_level", 5)),
            )
            for item in graph["nodes"]
        ],
        edges=[GraphEdgeOut(**item) for item in graph["edges"]],
    )


@router.get("/{case_id}/graph/analytics", response_model=GraphAnalyticsOut)
def get_case_analytics(
    case_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> GraphAnalyticsOut:
    case_for_user(session, case_id, current_user)
    snapshot = _latest_snapshot(session, case_id)
    append_audit(
        session,
        action="graph.analytics_view",
        resource_type="graph_snapshot",
        resource_id=snapshot.id,
        case_id=case_id,
        user_id=current_user.id,
        request=request,
    )
    session.commit()
    return _analytics_output(session, case_id, snapshot)


@router.post(
    "/{case_id}/graph/alerts/{alert_id}/review",
    response_model=GraphAlertOut,
)
def review_graph_alert(
    case_id: str,
    alert_id: str,
    payload: GraphAlertReview,
    request: Request,
    current_user: User = Depends(require_permission(Permission.ANALYTICS_RUN)),
    session: Session = Depends(get_db),
) -> GraphAlertOut:
    case_for_user(session, case_id, current_user)
    alert = session.scalar(
        select(GraphAlert).where(GraphAlert.id == alert_id, GraphAlert.case_id == case_id)
    )
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Graph alert not found")
    if alert.status == "reviewed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Graph alert already reviewed")
    alert.status = "reviewed"
    append_audit(
        session,
        action="graph.alert_review",
        resource_type="graph_alert",
        resource_id=alert.id,
        case_id=case_id,
        user_id=current_user.id,
        request=request,
        details={"rule_code": alert.rule_code, "notes": payload.notes.strip()},
    )
    session.commit()
    session.refresh(alert)
    return GraphAlertOut.model_validate(alert)


@router.get("/{case_id}/graph/timeline", response_model=List[TimelineEventOut])
def get_graph_timeline(
    case_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> List[TimelineEventOut]:
    case_for_user(session, case_id, current_user)
    try:
        graph = read_case_graph(case_id)
    except (Neo4jError, ServiceUnavailable, OSError) as exc:
        raise _graph_unavailable(exc) from exc
    events = [
        TimelineEventOut(
            relation_id=item["id"],
            observed_at=item["observed_at"],
            source_entity_id=item["source"],
            target_entity_id=item["target"],
            relation_type=item["relation_type"],
            evidence_id=item["evidence_id"],
            source_excerpt=item["source_excerpt"],
        )
        for item in graph["edges"]
    ]
    append_audit(
        session,
        action="graph.timeline_view",
        resource_type="case_graph",
        resource_id=case_id,
        case_id=case_id,
        user_id=current_user.id,
        request=request,
        details={"event_count": len(events)},
    )
    session.commit()
    return events


@router.get("/{case_id}/graph/path", response_model=EvidencePathOut)
def get_evidence_path(
    case_id: str,
    source_id: str,
    target_id: str,
    request: Request,
    max_hops: int = Query(default=8, ge=1, le=8),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> EvidencePathOut:
    case_for_user(session, case_id, current_user)
    if source_id == target_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Path endpoints must differ")
    try:
        path = shortest_evidence_path(case_id, source_id, target_id, max_hops=max_hops)
    except (Neo4jError, ServiceUnavailable, OSError, ValueError) as exc:
        if isinstance(exc, ValueError):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        raise _graph_unavailable(exc) from exc
    append_audit(
        session,
        action="graph.path_query",
        resource_type="case_graph",
        resource_id=case_id,
        case_id=case_id,
        user_id=current_user.id,
        request=request,
        details={"source_id": source_id, "target_id": target_id, "found": path is not None},
    )
    session.commit()
    if path is None:
        return EvidencePathOut(found=False, node_ids=[], edges=[], hop_count=0)
    return EvidencePathOut(
        found=True,
        node_ids=path["node_ids"],
        edges=[GraphEdgeOut(**item) for item in path["edges"]],
        hop_count=len(path["edges"]),
    )
