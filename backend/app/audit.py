from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Dict, Optional, Tuple
from uuid import uuid4

from fastapi import Request
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import AuditLog

GENESIS_HASH = "0" * 64
AUDIT_CHAIN_LOCK_ID = 84202601


def _time_value(value: datetime) -> str:
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.isoformat(timespec="microseconds")


def _canonical_payload(
    *,
    log_id: str,
    occurred_at: datetime,
    user_id: Optional[str],
    action: str,
    resource_type: str,
    resource_id: Optional[str],
    case_id: Optional[str],
    outcome: str,
    request_id: Optional[str],
    client_ip: Optional[str],
    details: Dict[str, Any],
) -> str:
    return json.dumps(
        {
            "id": log_id,
            "occurred_at": _time_value(occurred_at),
            "user_id": user_id,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "case_id": case_id,
            "outcome": outcome,
            "request_id": request_id,
            "client_ip": client_ip,
            "details": details,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def request_identity(request: Optional[Request]) -> Tuple[Optional[str], Optional[str]]:
    if request is None:
        return None, None
    request_id = getattr(request.state, "request_id", None)
    client_ip = request.client.host if request.client else None
    return request_id, client_ip


def append_audit(
    session: Session,
    *,
    action: str,
    resource_type: str,
    user_id: Optional[str] = None,
    resource_id: Optional[str] = None,
    case_id: Optional[str] = None,
    outcome: str = "success",
    request: Optional[Request] = None,
    details: Optional[Dict[str, Any]] = None,
) -> AuditLog:
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"),
            {"lock_id": AUDIT_CHAIN_LOCK_ID},
        )
    pending_entries = [item for item in session.new if isinstance(item, AuditLog)]
    if pending_entries:
        previous_hash = max(
            pending_entries,
            key=lambda item: (item.occurred_at, item.id),
        ).entry_hash
    else:
        previous_hash = session.scalar(
            select(AuditLog.entry_hash)
            .order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc())
            .limit(1)
        ) or GENESIS_HASH
    log_id = str(uuid4())
    occurred_at = datetime.now(timezone.utc)
    request_id, client_ip = request_identity(request)
    safe_details = details or {}
    canonical = _canonical_payload(
        log_id=log_id,
        occurred_at=occurred_at,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        case_id=case_id,
        outcome=outcome,
        request_id=request_id,
        client_ip=client_ip,
        details=safe_details,
    )
    entry_hash = sha256(f"{previous_hash}:{canonical}".encode("utf-8")).hexdigest()
    entry = AuditLog(
        id=log_id,
        occurred_at=occurred_at,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        case_id=case_id,
        outcome=outcome,
        request_id=request_id,
        client_ip=client_ip,
        details=safe_details,
        previous_hash=previous_hash,
        entry_hash=entry_hash,
    )
    session.add(entry)
    return entry


def verify_audit_chain(session: Session) -> Tuple[bool, int, Optional[str]]:
    entries = session.scalars(
        select(AuditLog).order_by(AuditLog.occurred_at.asc(), AuditLog.id.asc())
    ).all()
    previous_hash = GENESIS_HASH
    for entry in entries:
        canonical = _canonical_payload(
            log_id=entry.id,
            occurred_at=entry.occurred_at,
            user_id=entry.user_id,
            action=entry.action,
            resource_type=entry.resource_type,
            resource_id=entry.resource_id,
            case_id=entry.case_id,
            outcome=entry.outcome,
            request_id=entry.request_id,
            client_ip=entry.client_ip,
            details=entry.details or {},
        )
        expected = sha256(f"{previous_hash}:{canonical}".encode("utf-8")).hexdigest()
        if entry.previous_hash != previous_hash or entry.entry_hash != expected:
            return False, len(entries), entry.id
        previous_hash = entry.entry_hash
    return True, len(entries), None
