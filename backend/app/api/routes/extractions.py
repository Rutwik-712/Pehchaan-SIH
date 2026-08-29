from __future__ import annotations

from typing import List, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.access import case_for_user
from app.audit import append_audit
from app.database import get_db
from app.extraction import ALLOWED_ENTITY_TYPES, ALLOWED_RELATION_TYPES, normalize_entity_value
from app.models import (
    EvidenceSource,
    ExtractedDocument,
    ExtractedMention,
    ExtractedRelation,
    ProcessingJob,
    ReviewDecision,
    User,
)
from app.permissions import Permission
from app.schemas import (
    ExtractedDocumentOut,
    ExtractedMentionOut,
    ExtractedRelationOut,
    ExtractedTextOut,
    ExtractionBundleOut,
    ReviewDecisionOut,
    ReviewQueueOut,
    ReviewRelationOut,
    ReviewRequest,
)
from app.security import get_current_user, require_permission

router = APIRouter(prefix="/cases")


def _document_for_evidence(
    session: Session, case_id: str, evidence_id: str
) -> Tuple[ProcessingJob, ExtractedDocument]:
    evidence = session.scalar(
        select(EvidenceSource).where(
            EvidenceSource.id == evidence_id,
            EvidenceSource.case_id == case_id,
        )
    )
    if evidence is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evidence not found")
    job = session.scalar(
        select(ProcessingJob)
        .where(
            ProcessingJob.evidence_id == evidence_id,
            ProcessingJob.case_id == case_id,
            ProcessingJob.pipeline_version == "phase5-v1",
        )
        .order_by(ProcessingJob.created_at.desc())
        .limit(1)
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Extraction job not found")
    document = session.scalar(select(ExtractedDocument).where(ExtractedDocument.job_id == job.id))
    if document is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Extraction is not available yet")
    return job, document


def _bundle(session: Session, document: ExtractedDocument) -> ExtractionBundleOut:
    mentions = list(
        session.scalars(
            select(ExtractedMention)
            .where(ExtractedMention.document_id == document.id)
            .order_by(ExtractedMention.page_number.asc(), ExtractedMention.start_char.asc())
        ).all()
    )
    relations = list(
        session.scalars(
            select(ExtractedRelation)
            .where(ExtractedRelation.document_id == document.id)
            .order_by(ExtractedRelation.created_at.asc())
        ).all()
    )
    return ExtractionBundleOut(
        document=ExtractedDocumentOut.model_validate(document),
        mentions=[ExtractedMentionOut.model_validate(item) for item in mentions],
        relations=[ExtractedRelationOut.model_validate(item) for item in relations],
    )


@router.get("/{case_id}/evidence/{evidence_id}/extractions", response_model=ExtractionBundleOut)
def get_extractions(
    case_id: str,
    evidence_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> ExtractionBundleOut:
    case_for_user(session, case_id, current_user)
    job, document = _document_for_evidence(session, case_id, evidence_id)
    result = _bundle(session, document)
    append_audit(
        session,
        action="extraction.view",
        resource_type="extracted_document",
        resource_id=document.id,
        case_id=case_id,
        user_id=current_user.id,
        request=request,
        details={"job_id": job.id, "evidence_id": evidence_id},
    )
    session.commit()
    return result


@router.get("/{case_id}/evidence/{evidence_id}/extracted-text", response_model=ExtractedTextOut)
def get_extracted_text(
    case_id: str,
    evidence_id: str,
    request: Request,
    current_user: User = Depends(require_permission(Permission.ENTITY_REVIEW)),
    session: Session = Depends(get_db),
) -> ExtractedTextOut:
    case_for_user(session, case_id, current_user)
    job, document = _document_for_evidence(session, case_id, evidence_id)
    append_audit(
        session,
        action="extraction.text_view",
        resource_type="extracted_document",
        resource_id=document.id,
        case_id=case_id,
        user_id=current_user.id,
        request=request,
        details={"job_id": job.id, "evidence_id": evidence_id},
    )
    session.commit()
    return ExtractedTextOut.model_validate(document)


@router.get("/{case_id}/review-queue", response_model=ReviewQueueOut)
def get_review_queue(
    case_id: str,
    request: Request,
    current_user: User = Depends(require_permission(Permission.ENTITY_REVIEW)),
    session: Session = Depends(get_db),
) -> ReviewQueueOut:
    case_for_user(session, case_id, current_user)
    mentions = list(
        session.scalars(
            select(ExtractedMention)
            .where(
                ExtractedMention.case_id == case_id,
                ExtractedMention.needs_review.is_(True),
                ExtractedMention.status == "pending_review",
            )
            .order_by(ExtractedMention.created_at.asc())
            .limit(500)
        ).all()
    )
    relations = list(
        session.scalars(
            select(ExtractedRelation)
            .where(
                ExtractedRelation.case_id == case_id,
                ExtractedRelation.needs_review.is_(True),
                ExtractedRelation.status == "pending_review",
            )
            .order_by(ExtractedRelation.created_at.asc())
            .limit(500)
        ).all()
    )
    relation_mention_ids = {
        mention_id
        for relation in relations
        for mention_id in (relation.subject_mention_id, relation.object_mention_id)
    }
    relation_mentions = list(
        session.scalars(
            select(ExtractedMention).where(
                ExtractedMention.case_id == case_id,
                ExtractedMention.id.in_(relation_mention_ids),
            )
        ).all()
    ) if relation_mention_ids else []
    relation_mention_map = {mention.id: mention for mention in relation_mentions}
    append_audit(
        session,
        action="review.queue_view",
        resource_type="review_queue",
        resource_id=case_id,
        case_id=case_id,
        user_id=current_user.id,
        request=request,
        details={"mentions": len(mentions), "relations": len(relations)},
    )
    session.commit()
    return ReviewQueueOut(
        mentions=[ExtractedMentionOut.model_validate(item) for item in mentions],
        relations=[
            ReviewRelationOut(
                **ExtractedRelationOut.model_validate(item).model_dump(),
                subject_value=relation_mention_map[item.subject_mention_id].value,
                subject_entity_type=relation_mention_map[item.subject_mention_id].entity_type,
                object_value=relation_mention_map[item.object_mention_id].value,
                object_entity_type=relation_mention_map[item.object_mention_id].entity_type,
                page_number=relation_mention_map[item.subject_mention_id].page_number,
            )
            for item in relations
            if item.subject_mention_id in relation_mention_map and item.object_mention_id in relation_mention_map
        ],
        total_pending=len(mentions) + len(relations),
    )


def _review_mention(
    session: Session,
    case_id: str,
    mention_id: str,
    payload: ReviewRequest,
    current_user: User,
    request: Request,
) -> ReviewDecision:
    mention = session.scalar(
        select(ExtractedMention).where(
            ExtractedMention.id == mention_id,
            ExtractedMention.case_id == case_id,
        )
    )
    if mention is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mention not found")
    if mention.status in {"confirmed", "corrected", "rejected"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Mention already has a final review decision",
        )
    original = {"entity_type": mention.entity_type, "value": mention.value, "status": mention.status}
    corrected = {}
    if payload.decision == "correct":
        corrected_type = payload.corrected_type or mention.entity_type
        corrected_value = (payload.corrected_value or "").strip()
        if corrected_type not in ALLOWED_ENTITY_TYPES or not corrected_value:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Valid corrected type and value are required")
        mention.entity_type = corrected_type
        mention.value = corrected_value
        mention.normalized_value = normalize_entity_value(corrected_type, corrected_value)
        mention.status = "corrected"
        corrected = {"entity_type": corrected_type, "value": corrected_value}
    elif payload.decision == "confirm":
        mention.status = "confirmed"
    else:
        mention.status = "rejected"
    mention.needs_review = False
    decision = ReviewDecision(
        case_id=case_id,
        job_id=mention.job_id,
        target_type="mention",
        target_id=mention.id,
        decision=payload.decision,
        original_value=original,
        corrected_value=corrected,
        notes=payload.notes.strip(),
        reviewed_by_id=current_user.id,
    )
    session.add(decision)
    append_audit(
        session,
        action="review.mention_decision",
        resource_type="extracted_mention",
        resource_id=mention.id,
        case_id=case_id,
        user_id=current_user.id,
        request=request,
        details={"decision": payload.decision, "job_id": mention.job_id},
    )
    session.commit()
    session.refresh(decision)
    return decision


def _review_relation(
    session: Session,
    case_id: str,
    relation_id: str,
    payload: ReviewRequest,
    current_user: User,
    request: Request,
) -> ReviewDecision:
    relation = session.scalar(
        select(ExtractedRelation).where(
            ExtractedRelation.id == relation_id,
            ExtractedRelation.case_id == case_id,
        )
    )
    if relation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Relation not found")
    if relation.status in {"confirmed", "corrected", "rejected"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Relation already has a final review decision",
        )
    original = {"relation_type": relation.relation_type, "status": relation.status}
    corrected = {}
    if payload.decision == "correct":
        corrected_type = (payload.corrected_type or "").strip()
        if corrected_type not in ALLOWED_RELATION_TYPES:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Valid corrected relation type is required")
        relation.relation_type = corrected_type
        relation.status = "corrected"
        corrected = {"relation_type": corrected_type}
    elif payload.decision == "confirm":
        relation.status = "confirmed"
    else:
        relation.status = "rejected"
    relation.needs_review = False
    decision = ReviewDecision(
        case_id=case_id,
        job_id=relation.job_id,
        target_type="relation",
        target_id=relation.id,
        decision=payload.decision,
        original_value=original,
        corrected_value=corrected,
        notes=payload.notes.strip(),
        reviewed_by_id=current_user.id,
    )
    session.add(decision)
    append_audit(
        session,
        action="review.relation_decision",
        resource_type="extracted_relation",
        resource_id=relation.id,
        case_id=case_id,
        user_id=current_user.id,
        request=request,
        details={"decision": payload.decision, "job_id": relation.job_id},
    )
    session.commit()
    session.refresh(decision)
    return decision


@router.post("/{case_id}/mentions/{mention_id}/review", response_model=ReviewDecisionOut)
def review_mention(
    case_id: str,
    mention_id: str,
    payload: ReviewRequest,
    request: Request,
    current_user: User = Depends(require_permission(Permission.ENTITY_REVIEW)),
    session: Session = Depends(get_db),
) -> ReviewDecision:
    case_for_user(session, case_id, current_user)
    return _review_mention(session, case_id, mention_id, payload, current_user, request)


@router.post("/{case_id}/relations/{relation_id}/review", response_model=ReviewDecisionOut)
def review_relation(
    case_id: str,
    relation_id: str,
    payload: ReviewRequest,
    request: Request,
    current_user: User = Depends(require_permission(Permission.ENTITY_REVIEW)),
    session: Session = Depends(get_db),
) -> ReviewDecision:
    case_for_user(session, case_id, current_user)
    return _review_relation(session, case_id, relation_id, payload, current_user, request)
