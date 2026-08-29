# Authentication and RBAC

## Demo accounts

All Phase 2 demonstration accounts use the password `SIH1@2026`. This shared password is for local synthetic-data demonstrations only and must never be used in a shared or production deployment.

Demo seeding is controlled by `SEED_DEMO_DATA`. Production startup rejects enabled demo seeding and rejects the default development JWT secret.

| Username | Role | Case visibility |
|---|---|---|
| `constable.demo` | Constable | Assigned cases only |
| `investigator.demo` | Investigator | Assigned cases only |
| `sp.demo` | SP-level | All active cases |

Passwords are stored in the database as salted Argon2 hashes. Access tokens are short-lived signed JWTs and held only for the browser tab. Refresh tokens are delivered through `HttpOnly`, `SameSite=Strict` cookies, persisted only as SHA-256 hashes, rotated after use, and revocable on logout.

## Permission matrix

| Permission | Constable | Investigator | SP-level |
|---|---:|---:|---:|
| View assigned cases | Yes | Yes | Yes |
| View all cases | No | No | Yes |
| Upload evidence | Yes | Yes | Yes |
| Review extracted entities | No | Yes | Yes |
| Run analytics | No | Yes | Yes |
| Query evidence assistant | No | Yes | Yes |
| Draft case brief | No | Yes | Yes |
| Approve case brief | No | No | Yes |
| Assign cases | No | No | Yes |
| View audit trail | No | No | Yes |

The React interface hides unavailable workflows for clarity. FastAPI independently enforces every permission and case assignment; hiding a control is never treated as authorization.

## Phase 2 API

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`
- `GET /api/v1/cases`
- `GET /api/v1/cases/{case_id}`
- `POST /api/v1/cases/{case_id}/assignments`
- `POST /api/v1/cases/{case_id}/review-access`
- `POST /api/v1/cases/{case_id}/approve-access`

An unassigned case returns `404` rather than revealing its existence. Inactive or invalid sessions return `401`; authenticated users lacking an action permission receive `403`.
