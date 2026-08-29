from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Dict

from celery import Task

from app.celery_app import celery_app
from app.database import SessionLocal
from app.config import get_settings
from app.extraction import (
    ALLOWED_ENTITY_TYPES,
    ALLOWED_RELATION_TYPES,
    detect_language,
    extract_document_text,
    extract_entities,
    extract_relations,
    text_digest,
)
from app.jobs import complete_stage, fail_stage, retry_stage, start_stage
from app.models import (
    EvidenceSource,
    ExtractedDocument,
    ExtractedMention,
    ExtractedRelation,
    ProcessingJob,
)
from app.storage import ObjectNotFoundError, get_object_storage


class TransientPipelineError(RuntimeError):
    pass


def _evidence(job_id: str) -> EvidenceSource:
    with SessionLocal() as session:
        job = session.get(ProcessingJob, job_id)
        if job is None:
            raise ValueError("Processing job not found")
        evidence = session.get(EvidenceSource, job.evidence_id)
        if evidence is None:
            raise ValueError("Evidence metadata not found")
        session.expunge(evidence)
        return evidence


def _execute(
    task: Task,
    job_id: str,
    stage_name: str,
    operation: Callable[[str], Dict[str, Any]],
) -> str:
    requested_attempt = int(task.request.retries) + 1
    attempt_number = start_stage(job_id, stage_name, task.request.id, requested_attempt)
    if attempt_number == 0:
        return job_id
    try:
        output = operation(job_id)
    except TransientPipelineError as exc:
        if task.request.retries < task.max_retries:
            retry_stage(job_id, stage_name, attempt_number, exc)
            raise task.retry(exc=exc, countdown=min(2 ** attempt_number, 10))
        fail_stage(job_id, stage_name, attempt_number, exc)
        raise
    except Exception as exc:
        fail_stage(job_id, stage_name, attempt_number, exc)
        raise
    complete_stage(job_id, stage_name, attempt_number, output)
    return job_id


def _verify_integrity(job_id: str) -> Dict[str, Any]:
    evidence = _evidence(job_id)
    digest = sha256()
    size = 0
    try:
        for chunk in get_object_storage().iter_bytes(evidence.object_key):
            digest.update(chunk)
            size += len(chunk)
    except ObjectNotFoundError as exc:
        raise TransientPipelineError("Evidence object is temporarily unavailable") from exc
    actual_hash = digest.hexdigest()
    if actual_hash != evidence.sha256 or size != evidence.size_bytes:
        raise ValueError("Evidence integrity mismatch")
    return {"sha256": actual_hash, "size_bytes": size, "valid": True}


def _inspect_source(job_id: str) -> Dict[str, Any]:
    evidence = _evidence(job_id)
    chunk_count = 0
    try:
        for _chunk in get_object_storage().iter_bytes(evidence.object_key):
            chunk_count += 1
    except ObjectNotFoundError as exc:
        raise TransientPipelineError("Evidence object is temporarily unavailable") from exc
    return {
        "media_type": evidence.media_type,
        "extension": Path(evidence.original_filename).suffix.lower(),
        "chunk_count": chunk_count,
        "requires_ocr": evidence.media_type not in {"text/plain", "text/csv"},
    }


def _document_for_job(session, job_id: str) -> ExtractedDocument:
    from sqlalchemy import select

    document = session.scalar(select(ExtractedDocument).where(ExtractedDocument.job_id == job_id))
    if document is None:
        raise ValueError("Extracted document is not available")
    return document


def _extract_text(job_id: str) -> Dict[str, Any]:
    from sqlalchemy import select

    with SessionLocal() as session:
        existing = session.scalar(select(ExtractedDocument).where(ExtractedDocument.job_id == job_id))
        if existing is not None:
            return {
                "method": existing.extraction_method,
                "page_count": existing.page_count,
                "text_sha256": existing.text_sha256,
                "character_count": len(existing.extracted_text),
            }
        job = session.get(ProcessingJob, job_id)
        if job is None:
            raise ValueError("Processing job not found")
        evidence = session.get(EvidenceSource, job.evidence_id)
        if evidence is None:
            raise ValueError("Evidence metadata not found")
        result = extract_document_text(evidence)
        if not result.text.strip():
            raise ValueError("Text extraction produced no readable text")
        document = ExtractedDocument(
            job_id=job.id,
            case_id=job.case_id,
            evidence_id=evidence.id,
            extracted_text=result.text,
            text_sha256=text_digest(result.text),
            extraction_method=result.method,
            page_count=result.page_count,
            mean_confidence_percent=result.mean_confidence_percent,
            needs_review=(
                result.mean_confidence_percent is None
                or result.mean_confidence_percent < get_settings().extraction_review_threshold
            ),
        )
        session.add(document)
        session.commit()
        return {
            "method": result.method,
            "page_count": result.page_count,
            "text_sha256": document.text_sha256,
            "character_count": len(result.text),
            "mean_confidence_percent": result.mean_confidence_percent,
        }


def _detect_document_language(job_id: str) -> Dict[str, Any]:
    with SessionLocal() as session:
        document = _document_for_job(session, job_id)
        result = detect_language(document.extracted_text)
        document.language_code = result.code
        document.language_name = result.name
        document.language_confidence_percent = result.confidence_percent
        if result.code == "und" or result.confidence_percent < 60:
            document.needs_review = True
        session.commit()
        return {
            "language_code": result.code,
            "language_name": result.name,
            "confidence_percent": result.confidence_percent,
        }


def _extract_document_entities(job_id: str) -> Dict[str, Any]:
    from sqlalchemy import select

    settings = get_settings()
    with SessionLocal() as session:
        document = _document_for_job(session, job_id)
        existing = list(
            session.scalars(select(ExtractedMention).where(ExtractedMention.job_id == job_id)).all()
        )
        if existing:
            return {
                "mention_count": len(existing),
                "review_required": sum(1 for item in existing if item.needs_review),
            }
        candidates = extract_entities(document.extracted_text, document.language_code or "und")
        for candidate in candidates:
            needs_review = candidate.confidence_percent < settings.extraction_review_threshold
            session.add(
                ExtractedMention(
                    job_id=job_id,
                    document_id=document.id,
                    case_id=document.case_id,
                    evidence_id=document.evidence_id,
                    entity_type=candidate.entity_type,
                    value=candidate.value,
                    normalized_value=candidate.normalized_value,
                    start_char=candidate.start_char,
                    end_char=candidate.end_char,
                    page_number=candidate.page_number,
                    source_excerpt=candidate.source_excerpt,
                    extraction_method=candidate.method,
                    confidence_percent=candidate.confidence_percent,
                    status="pending_review" if needs_review else "validated",
                    needs_review=needs_review,
                )
            )
        session.commit()
        return {
            "mention_count": len(candidates),
            "review_required": sum(
                1 for item in candidates if item.confidence_percent < settings.extraction_review_threshold
            ),
            "entity_types": sorted({item.entity_type for item in candidates}),
        }


def _extract_document_relations(job_id: str) -> Dict[str, Any]:
    from sqlalchemy import select

    settings = get_settings()
    with SessionLocal() as session:
        document = _document_for_job(session, job_id)
        existing = list(
            session.scalars(select(ExtractedRelation).where(ExtractedRelation.job_id == job_id)).all()
        )
        if existing:
            return {
                "relation_count": len(existing),
                "provider": existing[0].extraction_method,
                "review_required": sum(1 for item in existing if item.needs_review),
            }
        mentions = list(
            session.scalars(
                select(ExtractedMention)
                .where(ExtractedMention.job_id == job_id, ExtractedMention.status != "rejected")
                .order_by(ExtractedMention.start_char.asc())
            ).all()
        )
        candidates, provider, fallback_reason = extract_relations(document.extracted_text, mentions)
        for candidate in candidates:
            needs_review = (
                provider != "qwen"
                or candidate.confidence_percent < settings.extraction_review_threshold
            )
            session.add(
                ExtractedRelation(
                    job_id=job_id,
                    document_id=document.id,
                    case_id=document.case_id,
                    evidence_id=document.evidence_id,
                    subject_mention_id=candidate.subject_mention_id,
                    object_mention_id=candidate.object_mention_id,
                    relation_type=candidate.relation_type,
                    source_excerpt=candidate.source_excerpt,
                    extraction_method=candidate.method,
                    confidence_percent=candidate.confidence_percent,
                    status="pending_review" if needs_review else "validated",
                    needs_review=needs_review,
                )
            )
        session.commit()
        return {
            "relation_count": len(candidates),
            "provider": provider,
            "fallback_reason": fallback_reason,
            "review_required": sum(
                1
                for item in candidates
                if provider != "qwen" or item.confidence_percent < settings.extraction_review_threshold
            ),
        }


def _validate_extraction_schema(job_id: str) -> Dict[str, Any]:
    from sqlalchemy import select

    invalid_mentions = 0
    invalid_relations = 0
    with SessionLocal() as session:
        mentions = list(
            session.scalars(select(ExtractedMention).where(ExtractedMention.job_id == job_id)).all()
        )
        mention_ids = {item.id for item in mentions}
        for mention in mentions:
            if mention.entity_type not in ALLOWED_ENTITY_TYPES or not mention.normalized_value:
                mention.status = "rejected"
                mention.needs_review = False
                invalid_mentions += 1
        relations = list(
            session.scalars(select(ExtractedRelation).where(ExtractedRelation.job_id == job_id)).all()
        )
        for relation in relations:
            if (
                relation.relation_type not in ALLOWED_RELATION_TYPES
                or relation.subject_mention_id not in mention_ids
                or relation.object_mention_id not in mention_ids
                or relation.subject_mention_id == relation.object_mention_id
            ):
                relation.status = "rejected"
                relation.needs_review = False
                invalid_relations += 1
        session.commit()
    return {
        "schema_valid": invalid_mentions == 0 and invalid_relations == 0,
        "invalid_mentions": invalid_mentions,
        "invalid_relations": invalid_relations,
    }


def _prepare_review_queue(job_id: str) -> Dict[str, Any]:
    from sqlalchemy import func, select

    with SessionLocal() as session:
        mention_count = session.scalar(
            select(func.count()).select_from(ExtractedMention).where(ExtractedMention.job_id == job_id)
        ) or 0
        relation_count = session.scalar(
            select(func.count()).select_from(ExtractedRelation).where(ExtractedRelation.job_id == job_id)
        ) or 0
        pending_mentions = session.scalar(
            select(func.count()).select_from(ExtractedMention).where(
                ExtractedMention.job_id == job_id,
                ExtractedMention.needs_review.is_(True),
                ExtractedMention.status == "pending_review",
            )
        ) or 0
        pending_relations = session.scalar(
            select(func.count()).select_from(ExtractedRelation).where(
                ExtractedRelation.job_id == job_id,
                ExtractedRelation.needs_review.is_(True),
                ExtractedRelation.status == "pending_review",
            )
        ) or 0
    return {
        "mentions": int(mention_count),
        "relations": int(relation_count),
        "pending_review": int(pending_mentions + pending_relations),
        "human_review_gate": "active",
    }


@celery_app.task(bind=True, name="threadline.integrity_check", max_retries=2)
def integrity_check(self: Task, job_id: str) -> str:
    return _execute(self, job_id, "integrity_check", _verify_integrity)


@celery_app.task(bind=True, name="threadline.source_inspection", max_retries=2)
def source_inspection(self: Task, job_id: str) -> str:
    return _execute(self, job_id, "source_inspection", _inspect_source)


@celery_app.task(bind=True, name="threadline.text_extraction", max_retries=2)
def text_extraction(self: Task, job_id: str) -> str:
    return _execute(self, job_id, "text_extraction", _extract_text)


@celery_app.task(bind=True, name="threadline.language_detection", max_retries=2)
def language_detection(self: Task, job_id: str) -> str:
    return _execute(self, job_id, "language_detection", _detect_document_language)


@celery_app.task(bind=True, name="threadline.entity_extraction", max_retries=2)
def entity_extraction(self: Task, job_id: str) -> str:
    return _execute(self, job_id, "entity_extraction", _extract_document_entities)


@celery_app.task(bind=True, name="threadline.relation_extraction", max_retries=2)
def relation_extraction(self: Task, job_id: str) -> str:
    return _execute(self, job_id, "relation_extraction", _extract_document_relations)


@celery_app.task(bind=True, name="threadline.schema_validation", max_retries=2)
def schema_validation(self: Task, job_id: str) -> str:
    return _execute(self, job_id, "schema_validation", _validate_extraction_schema)


@celery_app.task(bind=True, name="threadline.review_queue", max_retries=2)
def review_queue(self: Task, job_id: str) -> str:
    return _execute(self, job_id, "review_queue", _prepare_review_queue)
