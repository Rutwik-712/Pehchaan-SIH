# Phase 5 extraction and review jobs

## Durable visibility

Redis is the Celery broker and short-lived result backend. It is not the job system of record. PostgreSQL stores every processing job, current stage, stage status, attempt, timestamp, sanitized error, output summary, and retry count. This allows the React dashboard to display pipeline history even if Redis or Flower restarts.

Only opaque job identifiers are sent through Redis. A worker resolves case, evidence, and object-storage metadata from PostgreSQL and reads the original source through the backend's MinIO adapter.

## Durable extraction stages

1. `integrity_check` streams the stored object and verifies its SHA-256 and size.
2. `source_inspection` records non-content metadata needed to route later processing.
3. `text_extraction` reads UTF-8 text/CSV, embedded PDF text through PyMuPDF, or routes images and scanned PDFs to the optional local PaddleOCR adapter.
4. `language_detection` identifies the dominant Unicode script and stores the routing confidence.
5. `entity_extraction` combines spaCy with deterministic identifier and labelled-field rules.
6. `relation_extraction` uses the allowlisted local Qwen endpoint when enabled; otherwise it emits low-confidence co-occurrence candidates.
7. `schema_validation` rejects invalid entity types, relationship types, and dangling/self relationships.
8. `review_queue` reports the records requiring an investigator decision.

Every mention and relation retains its evidence, document, page, character span, source excerpt, method, and confidence. The extraction bundle excludes full raw text; the separate raw-text endpoint requires `entity.review`. The system extracts candidates and never labels a person guilty.

## API

- `POST /api/v1/cases/{case_id}/evidence/{evidence_id}/processing-jobs` creates or reuses the Phase 5 job.
- `GET /api/v1/cases/{case_id}/processing-jobs` lists visible jobs, optionally filtered by `evidence_id`.
- `GET /api/v1/cases/{case_id}/processing-jobs/{job_id}` returns the complete stage and attempt ledger.
- `POST /api/v1/cases/{case_id}/processing-jobs/{job_id}/retry` retries a failed job and requires analytical-run permission.

Every endpoint first enforces case assignment. Uploading new evidence automatically creates and dispatches its first job. Duplicate content is not reprocessed automatically.

Extraction and review endpoints:

- `GET /api/v1/cases/{case_id}/evidence/{evidence_id}/extractions` returns provenance-safe document metadata, mentions, and relations.
- `GET /api/v1/cases/{case_id}/evidence/{evidence_id}/extracted-text` returns raw extracted text to users with `entity.review`.
- `GET /api/v1/cases/{case_id}/review-queue` lists pending mentions and relations.
- `POST /api/v1/cases/{case_id}/mentions/{mention_id}/review` confirms, rejects, or corrects a mention.
- `POST /api/v1/cases/{case_id}/relations/{relation_id}/review` confirms, rejects, or corrects a relation.

Review events are append-only, audited, case-scoped, and cannot be submitted twice for a finalized target.

## Local services

```bash
docker compose up -d redis postgres minio

cd backend
.venv/bin/celery -A app.celery_app:celery_app worker --loglevel=INFO --concurrency=1
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 18000
```

The Compose Flower dashboard is published at `http://127.0.0.1:15555` and uses HTTP Basic authentication. The development default is `sih_flower` / `SIH1@2026`; replace it outside local demonstrations.

The worker runs at concurrency one for predictable laptop resource use. PostgreSQL advisory transaction locking serializes audit-chain appends across the API and worker; a dedicated audit writer or database-native immutable ledger remains a possible production evolution.

## Offline AI configuration

The Compose backend image installs spaCy, `en_core_web_sm`, PyMuPDF, PaddlePaddle 3.2.2, and PaddleOCR 3.3.3. `PADDLEOCR_LANGUAGE=en,hi,mr,ka` evaluates English, Hindi, Marathi, and Kannada OCR models and retains the strongest result using OCR confidence plus script coverage. Model files must be prefetched before taking the host offline with `docker compose run --rm worker python scripts/prefetch_ocr_models.py`.

Qwen is enabled in Compose through the local Ollama service. Load `qwen2.5:7b-instruct-q4_K_M` once and keep the endpoint host in `QWEN_ALLOWED_HOSTS`. Qwen receives a bounded evidence excerpt, a 4K context limit, and a JSON schema with temperature zero. Invalid or unavailable output still falls back to deterministic low-confidence relationships that require investigator review.

For multilingual FIRs, the Unicode router supports major Indian scripts. English uses the packaged statistical spaCy model; other languages use language tokenization plus the identifier/label rules, so their person and organization recall is intentionally weaker and should be manually reviewed.

## Reliability behavior

- Celery late acknowledgements and worker-lost rejection prevent a killed worker from silently treating a task as complete.
- A prefetch multiplier of one avoids reserving many long-running documents on one worker.
- Transient object-read failures retry up to twice with backoff.
- Task and worker failures are recorded in PostgreSQL with sanitized errors.
- Redis AOF is enabled for easier local recovery, although PostgreSQL remains authoritative.
