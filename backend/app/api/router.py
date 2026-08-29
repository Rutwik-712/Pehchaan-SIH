from fastapi import APIRouter

from app.api.routes.auth import router as auth_router
from app.api.routes.cases import router as cases_router
from app.api.routes.evidence import router as evidence_router
from app.api.routes.extractions import router as extractions_router
from app.api.routes.health import router as health_router
from app.api.routes.jobs import router as jobs_router
from app.api.routes.graph import router as graph_router
from app.api.routes.assistant import router as assistant_router
from app.api.routes.reports import router as reports_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["system"])
api_router.include_router(auth_router, tags=["authentication"])
api_router.include_router(cases_router, tags=["cases", "rbac"])
api_router.include_router(evidence_router, tags=["evidence", "chain-of-custody"])
api_router.include_router(jobs_router, tags=["processing", "pipeline"])
api_router.include_router(extractions_router, tags=["extraction", "human-review"])
api_router.include_router(graph_router, tags=["entity-resolution", "graph-analytics"])
api_router.include_router(assistant_router, tags=["assistant", "citations"])
api_router.include_router(reports_router, tags=["reports", "approval"])
