from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.config import get_settings, validate_security_settings
from app.database import create_schema
from app.seed import seed_phase2_data

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_security_settings(settings)
    create_schema()
    if settings.seed_demo_data:
        seed_phase2_data()
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.build_version,
    description=(
        "Offline-first, source-backed criminal network analysis support API. "
        "The system does not determine guilt."
    ),
    debug=settings.app_debug,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)


@app.middleware("http")
async def attach_request_id(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid4()))
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    return {
        "service": settings.app_name,
        "health": f"{settings.api_v1_prefix}/health",
        "docs": "/docs",
    }
