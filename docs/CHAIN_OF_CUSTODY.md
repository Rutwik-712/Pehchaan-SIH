# Evidence chain of custody

## Upload boundary

Evidence enters through the authenticated FastAPI multipart endpoint. The API verifies case assignment and the `evidence:upload` permission before reading the file. It rejects path-like filenames, unsupported extensions, empty files, content/extension mismatches, and files exceeding the configured size limit.

The service streams the upload into a temporary file while calculating SHA-256. It then creates a server-generated object key and stores the original bytes without transformation. User-provided filenames never become storage paths.

## Storage modes

- `OBJECT_STORAGE_BACKEND=local` supports direct developer execution and stores objects beneath a non-public directory.
- `OBJECT_STORAGE_BACKEND=minio` is used by Compose and stores evidence in the private `evidence` bucket.

The development Compose stack exposes its PostgreSQL port as `127.0.0.1:55432` to avoid colliding with a workstation PostgreSQL installation. Containers continue to use the standard internal port `5432`.

To remain isolated from other local projects, the Compose API is published at `127.0.0.1:18000`, the frontend at `127.0.0.1:15173`, and MinIO API/console at `127.0.0.1:19000` and `127.0.0.1:19001`. Container-to-container traffic still uses ports `8000`, `80`, `9000`, and `9001`.

FastAPI is the only evidence access boundary. The browser is never given a direct MinIO URL. Metadata view, listing, integrity verification, and download all re-check the user’s case access.

## Integrity

PostgreSQL stores the original filename, detected media type, byte count, SHA-256 digest, uploader, object key, backend, ETag/version metadata, and timestamp. Re-uploading identical bytes in the same case returns the existing immutable source record and produces a duplicate-upload audit event.

The integrity endpoint reads the stored object again, recalculates its size and SHA-256, and records the result.

## Audit trail

Audit rows record the user, action, resource, case, timestamp, request ID, client address, outcome, and limited non-secret details. Each entry includes the previous entry’s hash and its own SHA-256 hash. The application rejects updates and deletes of audit rows.

SP-level users can list case audit events and verify the audit hash chain. Application-level hash chaining detects modification but is not a substitute for external timestamping, write-once database storage, or independent log replication in a production evidentiary environment.

## Phase 3 endpoints

- `POST /api/v1/cases/{case_id}/evidence`
- `GET /api/v1/cases/{case_id}/evidence`
- `GET /api/v1/cases/{case_id}/evidence/{evidence_id}`
- `GET /api/v1/cases/{case_id}/evidence/{evidence_id}/download`
- `POST /api/v1/cases/{case_id}/evidence/{evidence_id}/verify-integrity`
- `GET /api/v1/cases/{case_id}/audit-logs`
- `GET /api/v1/cases/{case_id}/audit-chain/verify`
