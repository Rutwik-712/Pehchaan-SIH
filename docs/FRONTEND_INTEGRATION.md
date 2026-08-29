# Phase 7 React integration

Phase 7 replaces the preserved prototype's simulated Phase 3–6 interactions with authorized FastAPI calls. The browser never talks directly to PostgreSQL, Redis, MinIO, Celery, or Neo4j.

## Live screens

- **Case overview** reconciles evidence, job, review, graph, ranking, alert, and optional SP-level audit-chain data for the active authorized case.
- **Evidence intake** uploads one or more supported files, polls durable Celery job status, shows all stage attempts, verifies SHA-256 integrity, retries failed jobs for permitted roles, and downloads originals through FastAPI.
- **Extraction review** confirms, corrects, or rejects mentions and relationships and records append-only review decisions. It runs Splink resolution and displays the actual values behind fuzzy-match candidates before a human merge decision.
- **Network graph** reads the reviewed-only Neo4j projection into Cytoscape, supports type and text filters, displays provenance, runs rebuild plus GDS analytics, highlights PageRank leaders, and queries reviewed shortest paths.
- **Event timeline** displays reviewed Neo4j relationships chronologically and exports the selected view as CSV.
- **Pattern alerts** displays rule explanations and evidence summaries, reruns GDS analytics, and records audited alert-review actions.

- **Evidence assistant** performs authorized reviewed-fact retrieval, displays persisted numbered citations, records feedback, and explicitly refuses unsupported questions.
- **Case brief** queues immutable PDF versions through Celery, displays snapshot metrics and cited links, downloads through the protected API, and exposes approval controls only to SP-level users.

## Access behavior

- All calls use the rotating bearer session and refresh cookie through the same-origin `/api/v1` reverse proxy.
- The frontend hides unauthorized workflow actions, while FastAPI remains the enforcement boundary.
- Constables can upload, inspect processing, read reviewed graphs, and view timelines. They cannot read extracted raw text, review entities, run analytics, or review alerts.
- Investigators and SP-level users can review facts, resolve identities, rebuild graphs, run analytics, and review alerts.
- SP-level users can switch across active cases and verify the tamper-evident audit chain.

## Runtime and verification

```bash
docker compose up -d --build backend worker flower frontend
curl --fail http://127.0.0.1:18000/api/v1/health

cd backend
.venv/bin/pytest -q

cd ../frontend
npm run build
npm run test:sites
```

Open `http://127.0.0.1:15173`, sign in with a demo account and `SIH1@2026`, and use case `KSP-CR-2048` for the populated synthetic workflow.

## Current limits

- PaddleOCR and local Qwen are enabled in Compose. A first-time online provisioning run must populate the persistent OCR and Ollama model volumes before offline operation.
- Graph data is a rebuildable projection; PostgreSQL remains authoritative.
- The local development stack is loopback-bound and does not configure production TLS.
