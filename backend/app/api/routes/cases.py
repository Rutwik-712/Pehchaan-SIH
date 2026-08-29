from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.access import case_for_user
from app.audit import append_audit
from app.database import get_db
from app.models import Case, CaseAssignment, User
from app.permissions import Permission, has_permission
from app.schemas import AccessCheckOut, AssignmentCreate, AssignmentOut, CaseOut
from app.security import get_current_user, require_permission

router = APIRouter(prefix="/cases")


@router.get("", response_model=List[CaseOut])
def list_cases(
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> List[Case]:
    if has_permission(current_user.role, Permission.CASE_VIEW_ALL):
        cases = list(session.scalars(select(Case).where(Case.is_active.is_(True))).all())
    else:
        cases = list(session.scalars(
            select(Case).join(CaseAssignment).where(
                CaseAssignment.user_id == current_user.id,
                Case.is_active.is_(True),
            )
        ).all())
    append_audit(
        session,
        action="case.list",
        resource_type="case_collection",
        user_id=current_user.id,
        request=request,
        details={"result_count": len(cases)},
    )
    session.commit()
    return cases


@router.get("/{case_id}", response_model=CaseOut)
def get_case(
    case_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Case:
    case = case_for_user(session, case_id, current_user)
    append_audit(
        session,
        action="case.view",
        resource_type="case",
        resource_id=case_id,
        case_id=case_id,
        user_id=current_user.id,
        request=request,
    )
    session.commit()
    return case


@router.post("/{case_id}/assignments", response_model=AssignmentOut)
def assign_case(
    case_id: str,
    payload: AssignmentCreate,
    request: Request,
    current_user: User = Depends(require_permission(Permission.CASE_ASSIGN)),
    session: Session = Depends(get_db),
) -> AssignmentOut:
    case = case_for_user(session, case_id, current_user)
    target = session.scalar(select(User).where(User.username == payload.username.strip().lower()))
    if target is None or not target.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    assignment = session.scalar(
        select(CaseAssignment).where(CaseAssignment.case_id == case.id, CaseAssignment.user_id == target.id)
    )
    if assignment is None:
        assignment = CaseAssignment(case_id=case.id, user_id=target.id, assigned_by_id=current_user.id)
        session.add(assignment)
    append_audit(
        session,
        action="case.assign",
        resource_type="case_assignment",
        resource_id=assignment.id,
        case_id=case.id,
        user_id=current_user.id,
        request=request,
        details={"assigned_username": target.username, "assigned_user_id": target.id},
    )
    session.commit()
    session.refresh(assignment)
    return AssignmentOut(
        case_id=case.id,
        user_id=target.id,
        username=target.username,
        assigned_by_id=assignment.assigned_by_id or current_user.id,
    )


def _access_check(
    case_id: str,
    user: User,
    session: Session,
    permission: Permission,
    request: Request,
) -> AccessCheckOut:
    case_for_user(session, case_id, user)
    append_audit(
        session,
        action="permission.use",
        resource_type="case",
        resource_id=case_id,
        case_id=case_id,
        user_id=user.id,
        request=request,
        details={"permission": permission.value},
    )
    session.commit()
    return AccessCheckOut(case_id=case_id, user=user.username, role=user.role, permission=permission.value)


@router.post("/{case_id}/review-access", response_model=AccessCheckOut)
def review_access(
    case_id: str,
    request: Request,
    user: User = Depends(require_permission(Permission.ENTITY_REVIEW)),
    session: Session = Depends(get_db),
) -> AccessCheckOut:
    return _access_check(case_id, user, session, Permission.ENTITY_REVIEW, request)


@router.post("/{case_id}/approve-access", response_model=AccessCheckOut)
def approve_access(
    case_id: str,
    request: Request,
    user: User = Depends(require_permission(Permission.BRIEF_APPROVE)),
    session: Session = Depends(get_db),
) -> AccessCheckOut:
    return _access_check(case_id, user, session, Permission.BRIEF_APPROVE, request)
