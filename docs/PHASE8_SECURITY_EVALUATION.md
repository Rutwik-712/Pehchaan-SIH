# Phase 8 security evaluation

## Verified controls

- Assistant and report endpoints enforce permissions and case assignment in FastAPI; constable denials and hidden unassigned cases are covered by automated tests.
- Assistant retrieval includes only confirmed/corrected facts, persists citations, refuses unsupported questions, and rejects unsafe or uncited local-Qwen output.
- Report PDFs are immutable versions, classification-watermarked, SHA-256 recorded, MinIO-backed, audited, and SP-approved.
- The audit chain remained valid after the complete demo workflow (2,213 entries at the final scripted verification).
- The frontend package-lock audit completed offline with zero known npm vulnerabilities.
- Uploaded originals remain MIME-validated, hashed, access-controlled, and never passed directly from the browser to MinIO.

## Residual dependency advisories

`pip-audit --local` reported advisories for the current development environment. Most published fix versions in the advisory feed are not available from the configured package index at the time of Phase 8 verification: examples include `python-multipart 0.0.31` while the index exposes only `0.0.20`, `PyMuPDF 1.26.7` while it exposes `1.26.5`, and Starlette 1.x while it exposes `0.49.3`. The audit also includes development/build tooling (`pip`, `setuptools`, `pytest`, and `python-dotenv`) that is not an application endpoint.

These are unresolved release blockers for any shared or production deployment, even though the functional prototype remains loopback-only. Before a pilot:

1. Re-run audits against an index containing the published patched versions.
2. Upgrade FastAPI/Starlette, `python-multipart`, PyMuPDF, Requests, and their transitive packages as a tested set.
3. Rebuild images from pinned hashes/SBOM, rerun all authorization and evidence tests, and conduct a focused upload/parser penetration test.
4. Replace all demo secrets, enable TLS, disable demo seeding, and use a supported Python toolchain (the Compose runtime is Python 3.12; the current host virtualenv is Python 3.9 and is end-of-life).

Phase 8 is therefore accepted as a local fictional-data prototype, not cleared for operational criminal/intelligence records.
