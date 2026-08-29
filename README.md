# Criminal Network Analysis System

Offline-first investigation support system for processing evidence, reviewing extracted entities and relationships, and exploring source-backed network structures. The system assists investigators; it does not determine guilt.

## Current implementation status

Phases 1–8 provide FastAPI, Argon2-backed demo accounts, rotating JWT sessions, role permissions, case assignments, secure evidence registration, SHA-256 integrity verification, MinIO/PostgreSQL deployment, an append-only hash-chained audit trail, Redis/Celery execution, local text/PDF extraction, multilingual PaddleOCR routing, spaCy entity extraction, local Qwen relation and explanation adapters, investigator review APIs, conservative Splink entity resolution, a reviewed-only Neo4j/GDS graph, a fully API-connected React/Cytoscape workspace, a cited evidence assistant, immutable PDF case briefs with SP approval, and a 20-case/100-subject fictional demo package.

## Repository layout

```text
Project/
├── backend/          FastAPI application and backend tests
├── frontend/         React + Vite + Cytoscape prototype
├── docs/             Architecture and implementation notes
├── infra/            Infrastructure configuration added by later phases
├── tests/            Cross-service tests added by later phases
├── .env.example      Configuration contract for the complete stack
└── compose.yaml      Phase 1 development services
```

## Phase 1 local development

Backend:

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 18000
```

Frontend:

```bash
cd frontend
npm install
npm run dev -- --host 127.0.0.1
```

The direct-development frontend is available at `http://127.0.0.1:5173`. API documentation is available at `http://127.0.0.1:18000/docs`, and the health endpoint is `http://127.0.0.1:18000/api/v1/health`. The complete Compose frontend is published at `http://127.0.0.1:15173`.

## Configuration

Copy `.env.example` to `.env` for local development. Development defaults are safe for Phase 1, but every placeholder secret must be replaced before a shared or production deployment.

## Local AI and OCR startup

Docker Desktop should have at least 12 GB of memory available (16 GB is recommended for the complete stack). The first setup requires internet access to fetch the Qwen and PaddleOCR model files:

```bash
docker compose up -d ollama
docker compose exec ollama ollama pull qwen2.5:7b-instruct-q4_K_M
docker compose up -d --build backend worker flower frontend
docker compose run --rm worker python scripts/prefetch_ocr_models.py
```

Qwen data is retained in the `ollama_data` volume and OCR data in `paddle_models`. Once both caches are populated, inference and evidence processing remain on the local Docker network and do not require third-party APIs.

## Phase 2 demo sign-in

Use `constable.demo`, `investigator.demo`, or `sp.demo` with the shared local-demo password `SIH1@2026`. See [docs/RBAC.md](docs/RBAC.md) for the permission matrix and API contract.

Evidence custody behavior and Phase 3 endpoints are documented in [docs/CHAIN_OF_CUSTODY.md](docs/CHAIN_OF_CUSTODY.md).

Phase 5 extraction stages, local AI configuration, review APIs, retries, and Flower visibility are documented in [docs/PIPELINE_JOBS.md](docs/PIPELINE_JOBS.md).

Phase 6 entity resolution, reviewed-only Neo4j projection, GDS analytics, timeline, alerts, and evidence paths are documented in [docs/GRAPH_ANALYTICS.md](docs/GRAPH_ANALYTICS.md).

Phase 7 live React integration, role-aware behavior, screen-to-API mapping, and verification steps are documented in [docs/FRONTEND_INTEGRATION.md](docs/FRONTEND_INTEGRATION.md).

Phase 8 grounded assistant behavior, report versioning, local Qwen setup, and the synthetic data loader are documented in [docs/PHASE8_ASSISTANT_REPORTS.md](docs/PHASE8_ASSISTANT_REPORTS.md).

The Phase 8 security checks and residual dependency advisories are documented in [docs/PHASE8_SECURITY_EVALUATION.md](docs/PHASE8_SECURITY_EVALUATION.md). This remains a loopback-only fictional-data prototype and is not approved for operational records.

## Phase 1 verification

```bash
cd backend && .venv/bin/pytest
cd frontend && npm run build && npm run test:sites
```
