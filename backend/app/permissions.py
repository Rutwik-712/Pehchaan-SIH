from __future__ import annotations

from enum import Enum
from typing import Dict, FrozenSet

from app.models import Role


class Permission(str, Enum):
    CASE_VIEW_ASSIGNED = "case:view_assigned"
    CASE_VIEW_ALL = "case:view_all"
    CASE_ASSIGN = "case:assign"
    EVIDENCE_UPLOAD = "evidence:upload"
    ENTITY_REVIEW = "entity:review"
    ANALYTICS_RUN = "analytics:run"
    ASSISTANT_QUERY = "assistant:query"
    BRIEF_DRAFT = "brief:draft"
    BRIEF_APPROVE = "brief:approve"
    AUDIT_VIEW = "audit:view"


ROLE_PERMISSIONS: Dict[Role, FrozenSet[Permission]] = {
    Role.CONSTABLE: frozenset(
        {
            Permission.CASE_VIEW_ASSIGNED,
            Permission.EVIDENCE_UPLOAD,
        }
    ),
    Role.INVESTIGATOR: frozenset(
        {
            Permission.CASE_VIEW_ASSIGNED,
            Permission.EVIDENCE_UPLOAD,
            Permission.ENTITY_REVIEW,
            Permission.ANALYTICS_RUN,
            Permission.ASSISTANT_QUERY,
            Permission.BRIEF_DRAFT,
        }
    ),
    Role.SP: frozenset(Permission),
}


def permissions_for(role: str) -> FrozenSet[Permission]:
    try:
        return ROLE_PERMISSIONS[Role(role)]
    except (KeyError, ValueError):
        return frozenset()


def has_permission(role: str, permission: Permission) -> bool:
    return permission in permissions_for(role)

