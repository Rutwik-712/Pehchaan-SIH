from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import get_settings

router = APIRouter()


class HealthResponse(BaseModel):
    status: Literal["healthy"]
    service: str
    environment: str
    version: str
    timestamp: datetime


@router.get("/health", response_model=HealthResponse, summary="API health check")
def health_check() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="healthy",
        service=settings.app_name,
        environment=settings.app_env,
        version=settings.build_version,
        timestamp=datetime.now(timezone.utc),
    )
