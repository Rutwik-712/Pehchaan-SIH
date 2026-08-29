from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.access import case_for_user
from app.assistant_service import answer_question
from app.audit import append_audit
from app.database import get_db
from app.models import AssistantCitation, AssistantQuery, User
from app.permissions import Permission
from app.schemas import AssistantCitationOut, AssistantFeedbackRequest, AssistantQueryOut, AssistantQueryRequest
from app.security import require_permission

router = APIRouter()


def _query_out(session: Session, query: AssistantQuery) -> AssistantQueryOut:
    citations = list(
        session.scalars(
            select(AssistantCitation)
            .where(AssistantCitation.query_id == query.id)
            .order_by(AssistantCitation.citation_number.asc())
        ).all()
    )
    return AssistantQueryOut(
        **{column.name: getattr(query, column.name) for column in AssistantQuery.__table__.columns},
        citations=[AssistantCitationOut.model_validate(item) for item in citations],
    )


@router.post("/cases/{case_id}/assistant/query", response_model=AssistantQueryOut)
def query_assistant(
    case_id: str,
    payload: AssistantQueryRequest,
    request: Request,
    current_user: User = Depends(require_permission(Permission.ASSISTANT_QUERY)),
    session: Session = Depends(get_db),
) -> AssistantQueryOut:
    case_for_user(session, case_id, current_user)
    question = payload.question.strip()
    result = answer_question(session, case_id, question)
    query = AssistantQuery(
        case_id=case_id,
        question=question,
        answer_text=result.answer_text,
        evidence_sufficient=result.evidence_sufficient,
        coverage_percent=result.coverage_percent,
        limitations=result.limitations,
        provider=result.provider,
        model_id=result.model_id,
        requested_by_id=current_user.id,
    )
    session.add(query)
    session.flush()
    for number, fact in enumerate(result.facts, start=1):
        session.add(
            AssistantCitation(
                query_id=query.id,
                case_id=case_id,
                evidence_id=fact.evidence_id,
                document_id=fact.document_id,
                target_type=fact.target_type,
                target_id=fact.target_id,
                citation_number=number,
                source_label=fact.source_label,
                page_number=fact.page_number,
                excerpt=fact.excerpt,
            )
        )
    append_audit(
        session,
        action="assistant.query",
        resource_type="assistant_query",
        resource_id=query.id,
        case_id=case_id,
        user_id=current_user.id,
        request=request,
        details={
            "citation_count": len(result.facts),
            "evidence_sufficient": result.evidence_sufficient,
            "provider": result.provider,
        },
    )
    session.commit()
    session.refresh(query)
    return _query_out(session, query)


@router.get("/cases/{case_id}/assistant/queries", response_model=List[AssistantQueryOut])
def list_assistant_queries(
    case_id: str,
    request: Request,
    current_user: User = Depends(require_permission(Permission.ASSISTANT_QUERY)),
    session: Session = Depends(get_db),
) -> List[AssistantQueryOut]:
    case_for_user(session, case_id, current_user)
    queries = list(
        session.scalars(
            select(AssistantQuery)
            .where(AssistantQuery.case_id == case_id)
            .order_by(AssistantQuery.created_at.desc())
            .limit(50)
        ).all()
    )
    append_audit(
        session,
        action="assistant.history_view",
        resource_type="assistant_query_collection",
        resource_id=case_id,
        case_id=case_id,
        user_id=current_user.id,
        request=request,
        details={"result_count": len(queries)},
    )
    session.commit()
    return [_query_out(session, item) for item in queries]


@router.get("/assistant/queries/{query_id}", response_model=AssistantQueryOut)
def get_assistant_query(
    query_id: str,
    current_user: User = Depends(require_permission(Permission.ASSISTANT_QUERY)),
    session: Session = Depends(get_db),
) -> AssistantQueryOut:
    query = session.get(AssistantQuery, query_id)
    if query is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assistant query not found")
    case_for_user(session, query.case_id, current_user)
    return _query_out(session, query)


@router.post("/assistant/queries/{query_id}/feedback", response_model=AssistantQueryOut)
def submit_assistant_feedback(
    query_id: str,
    payload: AssistantFeedbackRequest,
    request: Request,
    current_user: User = Depends(require_permission(Permission.ASSISTANT_QUERY)),
    session: Session = Depends(get_db),
) -> AssistantQueryOut:
    query = session.get(AssistantQuery, query_id)
    if query is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assistant query not found")
    case_for_user(session, query.case_id, current_user)
    query.feedback = payload.rating
    query.feedback_notes = payload.notes.strip()
    append_audit(
        session,
        action="assistant.feedback",
        resource_type="assistant_query",
        resource_id=query.id,
        case_id=query.case_id,
        user_id=current_user.id,
        request=request,
        details={"rating": payload.rating},
    )
    session.commit()
    session.refresh(query)
    return _query_out(session, query)
