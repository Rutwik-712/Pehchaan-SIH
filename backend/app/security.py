from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Callable, Optional, Tuple
from uuid import uuid4

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import RefreshSession, User
from app.permissions import Permission, has_permission

settings = get_settings()
password_hasher = PasswordHash.recommended()
bearer_scheme = HTTPBearer(auto_error=False)
ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return password_hasher.verify(password, password_hash)


def authenticate_user(session: Session, username: str, password: str) -> Optional[User]:
    user = session.scalar(select(User).where(User.username == username.strip().lower()))
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        return None
    return user


def _encode_token(user: User, token_type: str, lifetime: timedelta, token_id: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": user.id,
            "username": user.username,
            "role": user.role,
            "type": token_type,
            "jti": token_id,
            "iat": now,
            "exp": now + lifetime,
        },
        settings.jwt_secret,
        algorithm=ALGORITHM,
    )


def _token_hash(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def create_token_pair(session: Session, user: User) -> Tuple[str, str, int]:
    access_id = str(uuid4())
    refresh_id = str(uuid4())
    access_lifetime = timedelta(minutes=settings.access_token_minutes)
    refresh_lifetime = timedelta(days=settings.refresh_token_days)
    access_token = _encode_token(user, "access", access_lifetime, access_id)
    refresh_token = _encode_token(user, "refresh", refresh_lifetime, refresh_id)
    session.add(
        RefreshSession(
            id=refresh_id,
            user_id=user.id,
            token_hash=_token_hash(refresh_token),
            expires_at=datetime.now(timezone.utc) + refresh_lifetime,
        )
    )
    session.commit()
    return access_token, refresh_token, int(access_lifetime.total_seconds())


def decode_token(token: str, expected_type: str) -> dict:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    if payload.get("type") != expected_type or not payload.get("sub") or not payload.get("jti"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token type",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    session: Session = Depends(get_db),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(credentials.credentials, "access")
    user = session.get(User, payload["sub"])
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive or unknown user")
    return user


def require_permission(permission: Permission) -> Callable:
    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if not has_permission(current_user.role, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: {permission.value}",
            )
        return current_user

    return dependency


def rotate_refresh_token(session: Session, token: str) -> Tuple[str, str, int]:
    payload = decode_token(token, "refresh")
    refresh_session = session.get(RefreshSession, payload["jti"])
    if (
        refresh_session is None
        or refresh_session.revoked_at is not None
        or refresh_session.token_hash != _token_hash(token)
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token is revoked")
    expires_at = refresh_session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token is expired")
    user = session.get(User, payload["sub"])
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive or unknown user")
    refresh_session.revoked_at = datetime.now(timezone.utc)
    session.commit()
    return create_token_pair(session, user)


def revoke_refresh_token(session: Session, token: str) -> None:
    payload = decode_token(token, "refresh")
    refresh_session = session.get(RefreshSession, payload["jti"])
    if refresh_session and refresh_session.token_hash == _token_hash(token):
        refresh_session.revoked_at = datetime.now(timezone.utc)
        session.commit()

