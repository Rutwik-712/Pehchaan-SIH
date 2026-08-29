from __future__ import annotations

from app.audit import append_audit
from app.celery_app import celery_app
from app.database import SessionLocal
from app.models import CaseReport
from app.report_service import generate_and_store_report


@celery_app.task(name="threadline.generate_case_report", bind=True, max_retries=1)
def generate_case_report(self, report_id: str) -> str:
    with SessionLocal() as session:
        report = session.get(CaseReport, report_id)
        if report is None:
            raise ValueError("Report not found")
        if report.status in {"completed", "approved"} and report.object_key:
            return report.id
        report.status = "generating"
        session.commit()
        try:
            generate_and_store_report(session, report)
            append_audit(
                session,
                action="report.generated",
                resource_type="case_report",
                resource_id=report.id,
                case_id=report.case_id,
                user_id=report.created_by_id,
                details={"version": report.version, "sha256": report.sha256, "citation_count": report.citation_count},
            )
            session.commit()
            return report.id
        except Exception as exc:
            session.rollback()
            report = session.get(CaseReport, report_id)
            if report is not None:
                report.status = "failed"
                report.error_message = f"{type(exc).__name__}: {str(exc)[:420]}"
                session.commit()
            raise
