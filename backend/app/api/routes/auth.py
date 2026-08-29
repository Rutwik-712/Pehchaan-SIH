from typing import Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.audit import append_audit
from app.models import User
from app.permissions import permissions_for
from app.config import get_settings
from app.schemas import LoginRequest, TokenPair, UserOut
from app.security import authenticate_user, create_token_pair, decode_token, get_current_user, revoke_refresh_token, rotate_refresh_token

router = APIRouter(prefix="/auth")
settings = get_settings()
REFRESH_COOKIE = "threadline_refresh"


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=token,
        max_age=settings.refresh_token_days * 24 * 60 * 60,
        httponly=True,
        secure=settings.app_env.lower() == "production",
        samesite="strict",
        path="/api/v1/auth",
    )


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        permissions=sorted(permission.value for permission in permissions_for(user.role)),
    )


@router.post("/login", response_model=TokenPair)
def login(
    payload: LoginRequest,
    response: Response,
    request: Request,
    session: Session = Depends(get_db),
) -> TokenPair:
    user = authenticate_user(session, payload.username, payload.password)
    if user is None:
        append_audit(
            session,
            action="auth.login",
            resource_type="session",
            outcome="denied",
            request=request,
            details={"username": payload.username.strip().lower()},
        )
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token, refresh_token, expires_in = create_token_pair(session, user)
    _set_refresh_cookie(response, refresh_token)
    refresh_payload = decode_token(refresh_token, "refresh")
    append_audit(
        session,
        action="auth.login",
        resource_type="session",
        resource_id=refresh_payload["jti"],
        user_id=user.id,
        request=request,
    )
    session.commit()
    return TokenPair(access_token=access_token, expires_in=expires_in)


@router.post("/refresh", response_model=TokenPair)
def refresh(
    response: Response,
    request: Request,
    refresh_token: Optional[str] = Cookie(default=None, alias=REFRESH_COOKIE),
    session: Session = Depends(get_db),
) -> TokenPair:
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh session required")
    refresh_payload = decode_token(refresh_token, "refresh")
    access_token, next_refresh_token, expires_in = rotate_refresh_token(session, refresh_token)
    _set_refresh_cookie(response, next_refresh_token)
    append_audit(
        session,
        action="auth.refresh",
        resource_type="session",
        resource_id=refresh_payload["jti"],
        user_id=refresh_payload["sub"],
        request=request,
    )
    session.commit()
    return TokenPair(access_token=access_token, expires_in=expires_in)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    request: Request,
    refresh_token: Optional[str] = Cookie(default=None, alias=REFRESH_COOKIE),
    session: Session = Depends(get_db),
) -> None:
    if refresh_token:
        try:
            refresh_payload = decode_token(refresh_token, "refresh")
        except HTTPException:
            refresh_payload = None
        if refresh_payload:
            revoke_refresh_token(session, refresh_token)
            append_audit(
                session,
                action="auth.logout",
                resource_type="session",
                resource_id=refresh_payload["jti"],
                user_id=refresh_payload["sub"],
                request=request,
            )
            session.commit()
    response.delete_cookie(key=REFRESH_COOKIE, path="/api/v1/auth", samesite="strict")


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)) -> UserOut:
    return _user_out(current_user)
