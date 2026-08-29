from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.access import case_for_user
from app.audit import append_audit
from app.database import get_db
from app.models import CaseReport, User
from app.permissions import Permission
from app.schemas import CaseReportOut, ReportCreateRequest, ReportDecisionRequest
from app.security import require_permission
from app.storage import ObjectNotFoundError, get_object_storage
from app.tasks.reports import generate_case_report

router = APIRouter()


@router.post("/cases/{case_id}/reports", response_model=CaseReportOut, status_code=status.HTTP_202_ACCEPTED)
def create_report(
    case_id: str,
    payload: ReportCreateRequest,
    request: Request,
    current_user: User = Depends(require_permission(Permission.BRIEF_DRAFT)),
    session: Session = Depends(get_db),
) -> CaseReport:
    case = case_for_user(session, case_id, current_user)
    latest_version = session.scalar(select(func.max(CaseReport.version)).where(CaseReport.case_id == case_id)) or 0
    report = CaseReport(
        case_id=case_id,
        version=int(latest_version) + 1,
        title=payload.title.strip(),
        scope_note=payload.scope_note.strip(),
        classification=case.classification,
        created_by_id=current_user.id,
    )
    session.add(report)
    session.flush()
    append_audit(
        session,
        action="report.queued",
        resource_type="case_report",
        resource_id=report.id,
        case_id=case_id,
        user_id=current_user.id,
        request=request,
        details={"version": report.version, "classification": report.classification},
    )
    session.commit()
    task = generate_case_report.apply_async(args=[report.id])
    report.celery_task_id = task.id
    session.commit()
    session.refresh(report)
    return report


@router.get("/cases/{case_id}/reports", response_model=List[CaseReportOut])
def list_reports(
    case_id: str,
    request: Request,
    current_user: User = Depends(require_permission(Permission.BRIEF_DRAFT)),
    session: Session = Depends(get_db),
) -> List[CaseReport]:
    case_for_user(session, case_id, current_user)
    reports = list(
        session.scalars(
            select(CaseReport)
            .where(CaseReport.case_id == case_id)
            .order_by(CaseReport.version.desc())
        ).all()
    )
    append_audit(
        session,
        action="report.list",
        resource_type="case_report_collection",
        resource_id=case_id,
        case_id=case_id,
        user_id=current_user.id,
        request=request,
        details={"result_count": len(reports)},
    )
    session.commit()
    return reports


def _authorized_report(session: Session, report_id: str, current_user: User) -> CaseReport:
    report = session.get(CaseReport, report_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    case_for_user(session, report.case_id, current_user)
    return report


@router.get("/reports/{report_id}", response_model=CaseReportOut)
def get_report(
    report_id: str,
    current_user: User = Depends(require_permission(Permission.BRIEF_DRAFT)),
    session: Session = Depends(get_db),
) -> CaseReport:
    return _authorized_report(session, report_id, current_user)


@router.post("/reports/{report_id}/decision", response_model=CaseReportOut)
def decide_report(
    report_id: str,
    payload: ReportDecisionRequest,
    request: Request,
    current_user: User = Depends(require_permission(Permission.BRIEF_APPROVE)),
    session: Session = Depends(get_db),
) -> CaseReport:
    report = _authorized_report(session, report_id, current_user)
    if report.status not in {"completed", "rejected"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only a completed report can be reviewed")
    report.status = "approved" if payload.decision == "approve" else "rejected"
    report.approved_by_id = current_user.id if payload.decision == "approve" else None
    report.approved_at = datetime.now(timezone.utc) if payload.decision == "approve" else None
    report.approval_notes = payload.notes.strip()
    append_audit(
        session,
        action=f"report.{payload.decision}",
        resource_type="case_report",
        resource_id=report.id,
        case_id=report.case_id,
        user_id=current_user.id,
        request=request,
        details={"version": report.version},
    )
    session.commit()
    session.refresh(report)
    return report


@router.get("/reports/{report_id}/download")
def download_report(
    report_id: str,
    request: Request,
    current_user: User = Depends(require_permission(Permission.BRIEF_DRAFT)),
    session: Session = Depends(get_db),
) -> StreamingResponse:
    report = _authorized_report(session, report_id, current_user)
    if report.status not in {"completed", "approved", "rejected"} or not report.object_key or not report.sha256:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Report PDF is not ready")
    try:
        iterator = get_object_storage().iter_bytes(report.object_key)
    except ObjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report object not found") from exc
    append_audit(
        session,
        action="report.download",
        resource_type="case_report",
        resource_id=report.id,
        case_id=report.case_id,
        user_id=current_user.id,
        request=request,
        details={"version": report.version, "sha256": report.sha256},
    )
    session.commit()
    filename = f"{report.case_id}-case-brief-v{report.version}.pdf"
    return StreamingResponse(
        iterator,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-SHA256": report.sha256,
            "Cache-Control": "no-store",
        },
    )
