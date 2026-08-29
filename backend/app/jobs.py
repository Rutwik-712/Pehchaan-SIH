from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from celery import chain
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import append_audit
from app.database import SessionLocal
from app.models import EvidenceSource, ProcessingJob, ProcessingStage, ProcessingStageAttempt

PIPELINE_NAME = "evidence_extraction"
PIPELINE_VERSION = "phase5-v1"
PIPELINE_STAGES: Tuple[Tuple[str, int], ...] = (
    ("integrity_check", 1),
    ("source_inspection", 2),
    ("text_extraction", 3),
    ("language_detection", 4),
    ("entity_extraction", 5),
    ("relation_extraction", 6),
    ("schema_validation", 7),
    ("review_queue", 8),
)
ACTIVE_JOB_STATUSES = ("queued", "running", "retrying")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_error(exc: BaseException) -> Tuple[str, str]:
    code = type(exc).__name__[:80]
    message = str(exc).strip() or code
    return code, message[:500]


def create_processing_job(
    session: Session,
    *,
    evidence: EvidenceSource,
    requested_by_id: str,
    request: Optional[Request] = None,
) -> Tuple[ProcessingJob, bool]:
    existing = session.scalar(
        select(ProcessingJob)
        .where(
            ProcessingJob.evidence_id == evidence.id,
            ProcessingJob.pipeline_name == PIPELINE_NAME,
            ProcessingJob.pipeline_version == PIPELINE_VERSION,
        )
        .order_by(ProcessingJob.created_at.desc())
        .limit(1)
    )
    if existing is not None:
        return existing, False

    job = ProcessingJob(
        case_id=evidence.case_id,
        evidence_id=evidence.id,
        requested_by_id=requested_by_id,
        pipeline_name=PIPELINE_NAME,
        pipeline_version=PIPELINE_VERSION,
        status="queued",
        result_summary={"purpose": "phase5_extraction"},
    )
    session.add(job)
    session.flush()
    for stage_name, sequence in PIPELINE_STAGES:
        session.add(
            ProcessingStage(
                job_id=job.id,
                stage_name=stage_name,
                sequence=sequence,
                status="queued",
            )
        )
    append_audit(
        session,
        action="processing.job_created",
        resource_type="processing_job",
        resource_id=job.id,
        case_id=job.case_id,
        user_id=requested_by_id,
        request=request,
        details={
            "evidence_id": evidence.id,
            "pipeline_name": PIPELINE_NAME,
            "pipeline_version": PIPELINE_VERSION,
        },
    )
    return job, True


def dispatch_processing_job(job_id: str) -> Optional[str]:
    from app.tasks.pipeline import (
        entity_extraction,
        integrity_check,
        language_detection,
        relation_extraction,
        review_queue,
        schema_validation,
        source_inspection,
        text_extraction,
    )

    workflow = chain(
        integrity_check.si(job_id),
        source_inspection.si(job_id),
        text_extraction.si(job_id),
        language_detection.si(job_id),
        entity_extraction.si(job_id),
        relation_extraction.si(job_id),
        schema_validation.si(job_id),
        review_queue.si(job_id),
    )
    try:
        result = workflow.apply_async()
    except Exception as exc:
        code, message = _safe_error(exc)
        with SessionLocal() as session:
            job = session.get(ProcessingJob, job_id)
            if job is not None:
                job.status = "dispatch_failed"
                job.error_code = code
                job.error_message = message
                job.completed_at = _utc_now()
                append_audit(
                    session,
                    action="processing.dispatch_failed",
                    resource_type="processing_job",
                    resource_id=job.id,
                    case_id=job.case_id,
                    user_id=job.requested_by_id,
                    outcome="failure",
                    details={"error_code": code},
                )
                session.commit()
        return None

    with SessionLocal() as session:
        job = session.get(ProcessingJob, job_id)
        if job is not None:
            job.celery_task_id = result.id
            session.commit()
    return result.id


def reset_job_for_retry(session: Session, job: ProcessingJob, requested_by_id: str, request: Request) -> None:
    job.status = "queued"
    job.current_stage = None
    job.progress_percent = 0
    job.retry_count += 1
    job.error_code = None
    job.error_message = None
    job.completed_at = None
    job.started_at = None
    job.result_summary = {"purpose": "phase5_extraction", "retry": job.retry_count}
    stages = session.scalars(
        select(ProcessingStage).where(ProcessingStage.job_id == job.id)
    ).all()
    for stage in stages:
        stage.status = "queued"
        stage.progress_percent = 0
        stage.output_details = {}
        stage.error_code = None
        stage.error_message = None
        stage.started_at = None
        stage.completed_at = None
    append_audit(
        session,
        action="processing.job_retry",
        resource_type="processing_job",
        resource_id=job.id,
        case_id=job.case_id,
        user_id=requested_by_id,
        request=request,
        details={"retry_count": job.retry_count},
    )


def start_stage(job_id: str, stage_name: str, task_id: Optional[str], requested_attempt: int) -> int:
    with SessionLocal() as session:
        job = session.get(ProcessingJob, job_id)
        if job is None:
            raise ValueError("Processing job not found")
        stage = session.scalar(
            select(ProcessingStage).where(
                ProcessingStage.job_id == job_id,
                ProcessingStage.stage_name == stage_name,
            )
        )
        if stage is None:
            raise ValueError("Processing stage not found")
        if stage.status == "completed" and requested_attempt <= stage.attempt_count:
            return 0

        attempt_number = max(stage.attempt_count + 1, requested_attempt)

        now = _utc_now()
        job.status = "running"
        job.current_stage = stage_name
        job.started_at = job.started_at or now
        job.updated_at = now
        stage.status = "running"
        stage.progress_percent = 10
        stage.started_at = now
        stage.completed_at = None
        stage.attempt_count = max(stage.attempt_count, attempt_number)
        attempt = session.scalar(
            select(ProcessingStageAttempt).where(
                ProcessingStageAttempt.stage_id == stage.id,
                ProcessingStageAttempt.attempt_number == attempt_number,
            )
        )
        if attempt is None:
            attempt = ProcessingStageAttempt(
                stage_id=stage.id,
                attempt_number=attempt_number,
                celery_task_id=task_id,
                status="running",
                started_at=now,
            )
            session.add(attempt)
        else:
            attempt.status = "running"
            attempt.celery_task_id = task_id
            attempt.started_at = now
            attempt.completed_at = None
        append_audit(
            session,
            action="processing.stage_started",
            resource_type="processing_stage",
            resource_id=stage.id,
            case_id=job.case_id,
            user_id=job.requested_by_id,
            details={"job_id": job.id, "stage": stage_name, "attempt": attempt_number},
        )
        session.commit()
        return attempt_number


def _duration_ms(started_at: datetime, completed_at: datetime) -> int:
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    return max(0, int((completed_at - started_at).total_seconds() * 1000))


def complete_stage(job_id: str, stage_name: str, attempt_number: int, output: Dict[str, Any]) -> None:
    with SessionLocal() as session:
        job = session.get(ProcessingJob, job_id)
        stage = session.scalar(
            select(ProcessingStage).where(
                ProcessingStage.job_id == job_id,
                ProcessingStage.stage_name == stage_name,
            )
        )
        if job is None or stage is None:
            raise ValueError("Processing job stage not found")
        attempt = session.scalar(
            select(ProcessingStageAttempt).where(
                ProcessingStageAttempt.stage_id == stage.id,
                ProcessingStageAttempt.attempt_number == attempt_number,
            )
        )
        if attempt is None:
            raise ValueError("Processing stage attempt not found")
        now = _utc_now()
        attempt.status = "completed"
        attempt.completed_at = now
        attempt.duration_ms = _duration_ms(attempt.started_at, now)
        attempt.output_details = output
        stage.status = "completed"
        stage.progress_percent = 100
        stage.output_details = output
        stage.error_code = None
        stage.error_message = None
        stage.completed_at = now
        job.progress_percent = int(stage.sequence * 100 / len(PIPELINE_STAGES))
        job.updated_at = now
        if stage.sequence == len(PIPELINE_STAGES):
            job.status = "completed"
            job.current_stage = stage_name
            job.progress_percent = 100
            job.completed_at = now
            job.error_code = None
            job.error_message = None
            job.result_summary = {
                "pipeline": "extraction_completed",
                "stages_completed": len(PIPELINE_STAGES),
                **output,
            }
        append_audit(
            session,
            action="processing.stage_completed",
            resource_type="processing_stage",
            resource_id=stage.id,
            case_id=job.case_id,
            user_id=job.requested_by_id,
            details={"job_id": job.id, "stage": stage_name, "attempt": attempt_number},
        )
        if job.status == "completed":
            append_audit(
                session,
                action="processing.job_completed",
                resource_type="processing_job",
                resource_id=job.id,
                case_id=job.case_id,
                user_id=job.requested_by_id,
                details={"pipeline_version": job.pipeline_version},
            )
        session.commit()


def retry_stage(job_id: str, stage_name: str, attempt_number: int, exc: BaseException) -> None:
    _finish_failed_attempt(job_id, stage_name, attempt_number, exc, retrying=True)


def fail_stage(job_id: str, stage_name: str, attempt_number: int, exc: BaseException) -> None:
    _finish_failed_attempt(job_id, stage_name, attempt_number, exc, retrying=False)


def _finish_failed_attempt(
    job_id: str,
    stage_name: str,
    attempt_number: int,
    exc: BaseException,
    *,
    retrying: bool,
) -> None:
    code, message = _safe_error(exc)
    with SessionLocal() as session:
        job = session.get(ProcessingJob, job_id)
        stage = session.scalar(
            select(ProcessingStage).where(
                ProcessingStage.job_id == job_id,
                ProcessingStage.stage_name == stage_name,
            )
        )
        if job is None or stage is None:
            return
        attempt = session.scalar(
            select(ProcessingStageAttempt).where(
                ProcessingStageAttempt.stage_id == stage.id,
                ProcessingStageAttempt.attempt_number == attempt_number,
            )
        )
        now = _utc_now()
        if attempt is not None:
            attempt.status = "retrying" if retrying else "failed"
            attempt.completed_at = now
            attempt.duration_ms = _duration_ms(attempt.started_at, now)
            attempt.error_code = code
            attempt.error_message = message
        stage.status = "retrying" if retrying else "failed"
        stage.error_code = code
        stage.error_message = message
        if not retrying:
            stage.completed_at = now
        job.status = "retrying" if retrying else "failed"
        job.error_code = code
        job.error_message = message
        job.updated_at = now
        if not retrying:
            job.completed_at = now
        append_audit(
            session,
            action="processing.stage_retry" if retrying else "processing.stage_failed",
            resource_type="processing_stage",
            resource_id=stage.id,
            case_id=job.case_id,
            user_id=job.requested_by_id,
            outcome="retrying" if retrying else "failure",
            details={"job_id": job.id, "stage": stage_name, "attempt": attempt_number, "error_code": code},
        )
        session.commit()
