# Phase 8 assistant, reports, and demo package

## Grounded assistant

The assistant searches only extraction records with `confirmed` or `corrected` human-review status. It ranks matching reviewed facts locally, persists each exact evidence citation, and returns an explicit insufficiency response when no meaningful fact matches. When `QWEN_ENABLED=true`, local Qwen2.5 may explain the already-retrieved evidence packet; its output is accepted only when it contains valid citation markers and no prohibited culpability/enforcement language. Any failure falls back to deterministic cited output.

Endpoints require `assistant:query` plus case assignment:

- `POST /api/v1/cases/{case_id}/assistant/query`
- `GET /api/v1/cases/{case_id}/assistant/queries`
- `GET /api/v1/assistant/queries/{query_id}`
- `POST /api/v1/assistant/queries/{query_id}/feedback`

## Immutable report versions

Investigators and SP users can queue a versioned case brief. Celery builds a fixed snapshot of current sources, resolved entities, reviewed relationships, citations, pending-review counts, and limitations. The resulting restricted PDF is stored in MinIO/local object storage with SHA-256 metadata. There is no report-content update API: later case changes require a new version. Only SP users can approve or reject a completed version.

- `POST /api/v1/cases/{case_id}/reports`
- `GET /api/v1/cases/{case_id}/reports`
- `GET /api/v1/reports/{report_id}`
- `GET /api/v1/reports/{report_id}/download`
- `POST /api/v1/reports/{report_id}/decision`

Every query, feedback action, report generation, approval/rejection, and download appends a hash-chained audit event.

## Local Qwen with Compose

The normal Compose stack includes Ollama, while deterministic grounding remains available if the model is temporarily unavailable. Provision the model once with:

```bash
docker compose up -d ollama
docker compose exec ollama ollama pull qwen2.5:7b-instruct-q4_K_M
docker compose up -d --build backend worker
```

Compose sets `QWEN_ENABLED=true`, `QWEN_BASE_URL=http://ollama:11434`, and a 4K context limit. Model download is a one-time network-dependent preparation step; inference remains local afterward and retrieved citations are still validated before an answer is accepted.

## Demo data

`datasets/synthetic` contains 20 cases, 100 fictional subjects, and 20 multilingual FIR-style text files. Run the opt-in Compose loader with:

```bash
docker compose --profile demo-data run --rm demo-data-loader
```

The loader uploads through FastAPI, waits for Celery, confirms only the explicitly fictional records, and rebuilds the reviewed Neo4j projection. Operational data must always use manual review.
