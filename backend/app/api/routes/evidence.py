from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Iterator, List
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.access import case_for_user
from app.audit import append_audit, verify_audit_chain
from app.config import get_settings
from app.database import get_db
from app.file_validation import detect_media_type, validate_filename
from app.jobs import create_processing_job, dispatch_processing_job
from app.models import AuditLog, EvidenceSource, User
from app.permissions import Permission
from app.schemas import AuditChainOut, AuditLogOut, EvidenceOut, IntegrityOut
from app.security import get_current_user, require_permission
from app.storage import ObjectNotFoundError, get_object_storage

router = APIRouter(prefix="/cases")
settings = get_settings()
UPLOAD_CHUNK_SIZE = 1024 * 1024


def _evidence_out(evidence: EvidenceSource, deduplicated: bool = False) -> EvidenceOut:
    result = EvidenceOut.model_validate(evidence)
    result.deduplicated = deduplicated
    return result


def _evidence_for_case(session: Session, case_id: str, evidence_id: str) -> EvidenceSource:
    evidence = session.scalar(
        select(EvidenceSource).where(
            EvidenceSource.id == evidence_id,
            EvidenceSource.case_id == case_id,
        )
    )
    if evidence is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evidence not found")
    return evidence


@router.post("/{case_id}/evidence", response_model=EvidenceOut, status_code=status.HTTP_201_CREATED)
async def upload_evidence(
    case_id: str,
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(require_permission(Permission.EVIDENCE_UPLOAD)),
    session: Session = Depends(get_db),
) -> EvidenceOut:
    case_for_user(session, case_id, current_user)
    filename, suffix = validate_filename(file.filename or "")
    temp_root = Path("data/tmp")
    temp_root.mkdir(parents=True, exist_ok=True)
    digest = sha256()
    total_size = 0
    header = b""
    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(prefix="evidence-", dir=temp_root, delete=False) as handle:
            temp_path = Path(handle.name)
            while True:
                chunk = await file.read(UPLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > settings.max_upload_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"Evidence exceeds {settings.max_upload_bytes} bytes",
                    )
                if len(header) < 4096:
                    header += chunk[: 4096 - len(header)]
                digest.update(chunk)
                handle.write(chunk)

        if total_size == 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Evidence file is empty")

        media_type = detect_media_type(suffix, header)
        content_hash = digest.hexdigest()
        existing = session.scalar(
            select(EvidenceSource).where(
                EvidenceSource.case_id == case_id,
                EvidenceSource.sha256 == content_hash,
            )
        )
        if existing is not None:
            append_audit(
                session,
                action="evidence.upload_duplicate",
                resource_type="evidence",
                resource_id=existing.id,
                case_id=case_id,
                user_id=current_user.id,
                request=request,
                details={"filename": filename, "sha256": content_hash},
            )
            session.commit()
            return _evidence_out(existing, deduplicated=True)

        evidence_id = str(uuid4())
        object_key = f"cases/{case_id}/evidence/{evidence_id}/{content_hash}{suffix}"
        storage = get_object_storage()
        stored = storage.put_file(
            object_key,
            temp_path,
            media_type,
            {"sha256": content_hash, "case-id": case_id, "evidence-id": evidence_id},
        )
        evidence = EvidenceSource(
            id=evidence_id,
            case_id=case_id,
            original_filename=filename,
            media_type=media_type,
            size_bytes=total_size,
            sha256=content_hash,
            object_key=object_key,
            storage_backend=storage.backend_name,
            object_etag=stored.etag,
            object_version_id=stored.version_id,
            uploaded_by_id=current_user.id,
        )
        session.add(evidence)
        append_audit(
            session,
            action="evidence.upload",
            resource_type="evidence",
            resource_id=evidence.id,
            case_id=case_id,
            user_id=current_user.id,
            request=request,
            details={
                "filename": filename,
                "media_type": media_type,
                "size_bytes": total_size,
                "sha256": content_hash,
                "storage_backend": storage.backend_name,
            },
        )
        session.commit()
        session.refresh(evidence)
        job, created = create_processing_job(
            session,
            evidence=evidence,
            requested_by_id=current_user.id,
            request=request,
        )
        session.commit()
        if created:
            dispatch_processing_job(job.id)
        return _evidence_out(evidence)
    finally:
        await file.close()
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


@router.get("/{case_id}/evidence", response_model=List[EvidenceOut])
def list_evidence(
    case_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> List[EvidenceOut]:
    case_for_user(session, case_id, current_user)
    evidence = session.scalars(
        select(EvidenceSource)
        .where(EvidenceSource.case_id == case_id)
        .order_by(EvidenceSource.created_at.desc())
    ).all()
    append_audit(
        session,
        action="evidence.list",
        resource_type="case",
        resource_id=case_id,
        case_id=case_id,
        user_id=current_user.id,
        request=request,
        details={"result_count": len(evidence)},
    )
    session.commit()
    return [_evidence_out(item) for item in evidence]


@router.get("/{case_id}/evidence/{evidence_id}", response_model=EvidenceOut)
def get_evidence_metadata(
    case_id: str,
    evidence_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> EvidenceOut:
    case_for_user(session, case_id, current_user)
    evidence = _evidence_for_case(session, case_id, evidence_id)
    append_audit(
        session,
        action="evidence.view",
        resource_type="evidence",
        resource_id=evidence.id,
        case_id=case_id,
        user_id=current_user.id,
        request=request,
    )
    session.commit()
    return _evidence_out(evidence)


@router.get("/{case_id}/evidence/{evidence_id}/download")
def download_evidence(
    case_id: str,
    evidence_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> StreamingResponse:
    case_for_user(session, case_id, current_user)
    evidence = _evidence_for_case(session, case_id, evidence_id)
    storage = get_object_storage()
    iterator = iter(storage.iter_bytes(evidence.object_key))
    try:
        first_chunk = next(iterator)
    except (StopIteration, ObjectNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Evidence object unavailable") from exc

    append_audit(
        session,
        action="evidence.download",
        resource_type="evidence",
        resource_id=evidence.id,
        case_id=case_id,
        user_id=current_user.id,
        request=request,
        details={"sha256": evidence.sha256, "size_bytes": evidence.size_bytes},
    )
    session.commit()

    def stream() -> Iterator[bytes]:
        yield first_chunk
        yield from iterator

    encoded_name = quote(evidence.original_filename)
    return StreamingResponse(
        stream(),
        media_type=evidence.media_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}",
            "Content-Length": str(evidence.size_bytes),
            "X-Content-SHA256": evidence.sha256,
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/{case_id}/evidence/{evidence_id}/verify-integrity", response_model=IntegrityOut)
def verify_evidence_integrity(
    case_id: str,
    evidence_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> IntegrityOut:
    case_for_user(session, case_id, current_user)
    evidence = _evidence_for_case(session, case_id, evidence_id)
    digest = sha256()
    size = 0
    try:
        for chunk in get_object_storage().iter_bytes(evidence.object_key):
            digest.update(chunk)
            size += len(chunk)
    except ObjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Evidence object unavailable") from exc
    actual_hash = digest.hexdigest()
    valid = actual_hash == evidence.sha256 and size == evidence.size_bytes
    verified_at = datetime.now(timezone.utc)
    evidence.integrity_verified_at = verified_at
    evidence.status = "registered" if valid else "integrity_mismatch"
    append_audit(
        session,
        action="evidence.integrity_verify",
        resource_type="evidence",
        resource_id=evidence.id,
        case_id=case_id,
        user_id=current_user.id,
        request=request,
        outcome="success" if valid else "integrity_mismatch",
        details={"expected_sha256": evidence.sha256, "actual_sha256": actual_hash, "actual_size": size},
    )
    session.commit()
    return IntegrityOut(
        evidence_id=evidence.id,
        valid=valid,
        expected_sha256=evidence.sha256,
        actual_sha256=actual_hash,
        expected_size=evidence.size_bytes,
        actual_size=size,
        verified_at=verified_at,
    )


@router.get("/{case_id}/audit-logs", response_model=List[AuditLogOut])
def list_audit_logs(
    case_id: str,
    request: Request,
    current_user: User = Depends(require_permission(Permission.AUDIT_VIEW)),
    session: Session = Depends(get_db),
) -> List[AuditLog]:
    case_for_user(session, case_id, current_user)
    entries = session.scalars(
        select(AuditLog)
        .where(AuditLog.case_id == case_id)
        .order_by(AuditLog.occurred_at.desc())
        .limit(500)
    ).all()
    append_audit(
        session,
        action="audit.list",
        resource_type="case",
        resource_id=case_id,
        case_id=case_id,
        user_id=current_user.id,
        request=request,
        details={"result_count": len(entries)},
    )
    session.commit()
    return list(entries)


@router.get("/{case_id}/audit-chain/verify", response_model=AuditChainOut)
def verify_case_audit_chain(
    case_id: str,
    request: Request,
    current_user: User = Depends(require_permission(Permission.AUDIT_VIEW)),
    session: Session = Depends(get_db),
) -> AuditChainOut:
    case_for_user(session, case_id, current_user)
    valid, count, invalid_id = verify_audit_chain(session)
    append_audit(
        session,
        action="audit.chain_verify",
        resource_type="case",
        resource_id=case_id,
        case_id=case_id,
        user_id=current_user.id,
        request=request,
        outcome="success" if valid else "integrity_mismatch",
        details={"entries_checked": count, "first_invalid_entry_id": invalid_id},
    )
    session.commit()
    return AuditChainOut(valid=valid, entries_checked=count, first_invalid_entry_id=invalid_id)
