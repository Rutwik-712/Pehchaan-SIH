from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Case, CaseAssignment, User
from app.permissions import Permission, has_permission


def case_for_user(session: Session, case_id: str, user: User) -> Case:
    case = session.get(Case, case_id)
    if case is None or not case.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
    if has_permission(user.role, Permission.CASE_VIEW_ALL):
        return case
    assigned = session.scalar(
        select(CaseAssignment).where(
            CaseAssignment.case_id == case_id,
            CaseAssignment.user_id == user.id,
        )
    )
    if assigned is None:
        # Do not reveal whether an unassigned case exists.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
    return case

