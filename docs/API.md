# API

Live OpenAPI/Swagger docs are served at `http://localhost:8000/docs`. All endpoints except login, health and demo-accounts need `Authorization: Bearer <JWT>`.

| Area | Endpoints |
|---|---|
| Auth | `POST /api/auth/login`, `GET /api/auth/me`, `GET /api/auth/demo-accounts` |
| Meta | `GET /api/health`, `GET /api/meta`, `GET /api/stats`, `GET /api/notifications`, `POST /api/notifications/read` |
| Applications | `GET/POST /api/applications`, `GET /api/applications/{id}`, `POST /api/applications/{id}/submit`, `POST /api/applications/{id}/reopen` |
| Documents | `POST /api/applications/{id}/documents` (multipart: `file`, `doc_type`, optional `lab_type`), `GET /api/documents/{id}`, `POST /api/documents/{id}/reanalyze`, `GET /api/documents/{id}/page/{n}`, `POST /api/documents/{id}/ask`, `GET /api/documents/{id}/evidence-packet.pdf` |
| Decisions | `GET /api/officer/queue`, `POST /api/applications/{id}/decision` `{decision: approve\|reject\|request_changes, reason}`, `GET /api/applications/{id}/decision.pdf`, `POST /api/applications/{id}/rejection-helper`, `GET /api/applications/{id}/rejection.pdf` |
| Overrides | `POST /api/applications/{id}/overrides` `{document_id, justification (min 20 chars), proposed_status}`, `GET /api/overrides`, `POST /api/overrides/{id}/approve` and `/reject` `{note}` |
| Readiness | `POST /api/readiness/precheck`, `GET /api/templates`, `GET /api/templates/{name}`, `GET /api/samples`, `GET /api/samples/{name}` |
| 4D | `GET /api/collusion/graph` |
| Security | `GET /api/security/overview`, `POST /api/security/token-demo`, `POST /api/security/token-verify`, `POST /api/security/kms-demo`, `GET /api/security/pii`, `POST /api/security/pii/{id}/reveal` (admin) |
| Audit & rules | `GET /api/audit`, `GET /api/audit/verify`, `GET /api/rules`, `GET /api/admin/health` |

Error codes: 401 (not signed in or session expired), 403 (role or self-approval), 409 (blocked by policy: flagged document, draft application, final decision exists, analysis still running), 422 (validation), 429 (sign-in rate limit).
