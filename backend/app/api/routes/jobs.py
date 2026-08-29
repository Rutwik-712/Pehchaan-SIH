from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.access import case_for_user
from app.audit import append_audit
from app.database import get_db
from app.jobs import create_processing_job, dispatch_processing_job, reset_job_for_retry
from app.models import EvidenceSource, ProcessingJob, ProcessingStage, ProcessingStageAttempt, User
from app.permissions import Permission
from app.schemas import ProcessingJobOut, ProcessingStageAttemptOut, ProcessingStageOut
from app.security import get_current_user, require_permission

router = APIRouter(prefix="/cases")


def _job_for_case(session: Session, case_id: str, job_id: str) -> ProcessingJob:
    job = session.scalar(
        select(ProcessingJob).where(
            ProcessingJob.id == job_id,
            ProcessingJob.case_id == case_id,
        )
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Processing job not found")
    return job


def _job_out(session: Session, job: ProcessingJob, *, reused: bool = False) -> ProcessingJobOut:
    stages = list(
        session.scalars(
            select(ProcessingStage)
            .where(ProcessingStage.job_id == job.id)
            .order_by(ProcessingStage.sequence.asc())
        ).all()
    )
    stage_outputs: List[ProcessingStageOut] = []
    for stage in stages:
        attempts = list(
            session.scalars(
                select(ProcessingStageAttempt)
                .where(ProcessingStageAttempt.stage_id == stage.id)
                .order_by(ProcessingStageAttempt.attempt_number.asc())
            ).all()
        )
        stage_out = ProcessingStageOut.model_validate(stage)
        stage_out.attempts = [ProcessingStageAttemptOut.model_validate(item) for item in attempts]
        stage_outputs.append(stage_out)
    result = ProcessingJobOut.model_validate(job)
    result.reused = reused
    result.stages = stage_outputs
    return result


@router.post(
    "/{case_id}/evidence/{evidence_id}/processing-jobs",
    response_model=ProcessingJobOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_processing_job(
    case_id: str,
    evidence_id: str,
    request: Request,
    current_user: User = Depends(require_permission(Permission.EVIDENCE_UPLOAD)),
    session: Session = Depends(get_db),
) -> ProcessingJobOut:
    case_for_user(session, case_id, current_user)
    evidence = session.scalar(
        select(EvidenceSource).where(
            EvidenceSource.id == evidence_id,
            EvidenceSource.case_id == case_id,
        )
    )
    if evidence is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evidence not found")
    job, created = create_processing_job(
        session,
        evidence=evidence,
        requested_by_id=current_user.id,
        request=request,
    )
    if not created:
        append_audit(
            session,
            action="processing.job_reused",
            resource_type="processing_job",
            resource_id=job.id,
            case_id=case_id,
            user_id=current_user.id,
            request=request,
            details={"evidence_id": evidence.id, "status": job.status},
        )
    session.commit()
    if created:
        dispatch_processing_job(job.id)
    session.expire_all()
    job = _job_for_case(session, case_id, job.id)
    return _job_out(session, job, reused=not created)


@router.get("/{case_id}/processing-jobs", response_model=List[ProcessingJobOut])
def list_processing_jobs(
    case_id: str,
    request: Request,
    evidence_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> List[ProcessingJobOut]:
    case_for_user(session, case_id, current_user)
    statement = select(ProcessingJob).where(ProcessingJob.case_id == case_id)
    if evidence_id is not None:
        statement = statement.where(ProcessingJob.evidence_id == evidence_id)
    jobs = list(session.scalars(statement.order_by(ProcessingJob.created_at.desc()).limit(200)).all())
    append_audit(
        session,
        action="processing.job_list",
        resource_type="processing_job_collection",
        case_id=case_id,
        user_id=current_user.id,
        request=request,
        details={"result_count": len(jobs), "evidence_id": evidence_id},
    )
    session.commit()
    return [_job_out(session, job) for job in jobs]


@router.get("/{case_id}/processing-jobs/{job_id}", response_model=ProcessingJobOut)
def get_processing_job(
    case_id: str,
    job_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> ProcessingJobOut:
    case_for_user(session, case_id, current_user)
    job = _job_for_case(session, case_id, job_id)
    append_audit(
        session,
        action="processing.job_view",
        resource_type="processing_job",
        resource_id=job.id,
        case_id=case_id,
        user_id=current_user.id,
        request=request,
    )
    session.commit()
    return _job_out(session, job)


@router.post(
    "/{case_id}/processing-jobs/{job_id}/retry",
    response_model=ProcessingJobOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_processing_job(
    case_id: str,
    job_id: str,
    request: Request,
    current_user: User = Depends(require_permission(Permission.ANALYTICS_RUN)),
    session: Session = Depends(get_db),
) -> ProcessingJobOut:
    case_for_user(session, case_id, current_user)
    job = _job_for_case(session, case_id, job_id)
    if job.status not in {"failed", "dispatch_failed"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only failed processing jobs can be retried",
        )
    reset_job_for_retry(session, job, current_user.id, request)
    session.commit()
    dispatch_processing_job(job.id)
    session.expire_all()
    job = _job_for_case(session, case_id, job.id)
    return _job_out(session, job)
