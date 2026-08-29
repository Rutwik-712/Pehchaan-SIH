# Architecture baseline

## System boundary

The application is offline-first. FastAPI is the only browser-facing data API. Evidence access, authorization, audit logging, and case isolation will be enforced at the backend rather than trusted to the React interface.

## Planned runtime

```text
React + Cytoscape.js
        |
     FastAPI
        |
  PostgreSQL + MinIO
        |
 Redis + Celery + Flower
        |
PaddleOCR + spaCy + Qwen2.5 + Splink
        |
      Neo4j
```

PostgreSQL is the durable system of record for cases, users, assignments, jobs, stage history, review decisions, resolution runs, graph snapshots, alerts, and audit events. Redis transports small task messages and transient results only. MinIO stores original evidence. Neo4j stores a rebuildable projection containing reviewed case facts only.

## Phase gates

1. Project foundation and health contract.
2. Authentication, RBAC, and case assignments.
3. Evidence persistence, integrity, and chain of custody.
4. Celery execution, durable stage history, and Flower visibility.
5. OCR/NLP/Qwen extraction and human review.
6. Entity resolution, graph projection, analytics, timeline, and alerts.
7. Complete React API integration. **Implemented.**
8. Assistant, reports, synthetic data, complete Compose stack, and final verification. **Implemented.**

Each phase is independently verified before work begins on the next phase.
