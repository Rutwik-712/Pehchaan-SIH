# Phase 6 entity resolution and graph analytics

## Trust boundary

PostgreSQL remains the system of record. Neo4j is a rebuildable, case-scoped projection containing only mentions and relations whose review status is `confirmed` or `corrected`. Records that are pending review, rejected, or merely auto-validated never enter the graph.

Graph centrality, communities, paths, alerts, and priority levels describe reviewed network structure. They do not determine guilt, intent, causation, or criminal responsibility.

## Entity resolution

Splink 4 runs locally with DuckDB:

- Exact normalized values of the same entity type merge deterministically.
- Fuzzy matching is limited to people, organizations, and locations.
- Splink matches above `RESOLUTION_CANDIDATE_THRESHOLD` become review candidates.
- Fuzzy candidates never merge automatically. An investigator must confirm or reject each candidate.
- Candidate decisions create append-only `review_decisions` records and audit events.
- Re-running resolution applies confirmed candidates and recreates the derived `resolved_entities` and `resolved_mentions` projection.

This conservative approach prefers duplicate nodes over unsafe identity merges. Phone numbers, vehicle numbers, and email addresses merge only on exact normalized values.

## Neo4j projection

The Compose stack runs Neo4j Community 5.26.12 with Graph Data Science 2.13.7. Each projected node contains its case ID, entity type, canonical value, reviewed aliases, mention/evidence counts, and resolution method. Each relationship contains:

- relation and case identifiers;
- source and target resolved entity identifiers;
- evidence and extracted-document identifiers;
- page number and source excerpt;
- extraction method and confidence;
- observation timestamp derived from evidence registration.

All Cypher data values are passed as parameters. The shortest-path hop bound is validated to the fixed range 1–8 before being inserted into the query shape.

## Analytics

The case projection runs locally through Neo4j GDS:

- PageRank for structural prominence;
- betweenness with a sampling size of 100 for potential bridges;
- Louvain for community assignment;
- Cypher degree counting for reviewed connectivity.

Analytics are written back to PostgreSQL and Neo4j. The human-facing priority score combines normalized PageRank, betweenness, degree, and evidence-source count. Extraction confidence is deliberately excluded from priority: low confidence means “review this fact,” not “low investigative importance.”

Rule-based alerts currently cover reviewed high connectivity, potential bridging nodes, and entities observed in multiple evidence sources. Alerts are leads for human review and are never accusations.

## API

- `POST /api/v1/cases/{case_id}/resolution/run`
- `GET /api/v1/cases/{case_id}/resolution/candidates`
- `POST /api/v1/cases/{case_id}/resolution/candidates/{candidate_id}/review`
- `POST /api/v1/cases/{case_id}/graph/rebuild`
- `GET /api/v1/cases/{case_id}/graph`
- `POST /api/v1/cases/{case_id}/graph/analytics`
- `GET /api/v1/cases/{case_id}/graph/analytics`
- `GET /api/v1/cases/{case_id}/graph/timeline`
- `GET /api/v1/cases/{case_id}/graph/path?source_id=...&target_id=...`

Resolution, graph rebuilds, and analytics require `analytics:run`. Candidate review requires `entity:review`. Read endpoints still enforce case assignment. Every operation is audited in PostgreSQL.

## Local services

- Neo4j Browser: `http://127.0.0.1:17474`
- Bolt: `bolt://127.0.0.1:17687`
- Development credentials: `neo4j` / `SIH1@2026`

The GDS plugin is downloaded into the persistent `neo4j_plugins` volume during the first connected startup. For a truly air-gapped first deployment, prepackage the matching plugin JAR in a custom Neo4j image and export both images with `docker save` before transfer.

## Current limitations

- The current GDS version still supports `gds.graph.project.cypher` but reports it as deprecated. The pinned stack is functional; migrate to the aggregation-function projection before a future GDS major upgrade.
- Graph replacement spans PostgreSQL and Neo4j, so it is not a distributed ACID transaction. Neo4j is derived and can be safely rebuilt from reviewed PostgreSQL records if projection is interrupted.
- Development Bolt/HTTP traffic is loopback-bound but not TLS-encrypted. Configure Neo4j TLS and encrypted driver schemes for shared or production infrastructure.
- Schema creation currently uses SQLAlchemy `create_all`; production upgrades require Alembic migrations.
- Phase 7 connects these APIs to the case-scoped React and Cytoscape workspace. The local explanatory assistant and report workflow remain Phase 8 scope.
