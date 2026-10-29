# SealCheck: production deployment guide

This guide says what has to be set, and what has to be supplied by an operator, before SealCheck can process real AICTE submissions.
**Read the "Verification status" column carefully.** Many production backends were written and then tested only against local mocks
(moto, fakeredis, mock HTTP servers, a mock OIDC provider). None of them has been run against the real cloud service, Keycloak,
an HSM, a real CA's OCSP responder or a government registry.

## 1. What ENV=production enforces

`ops.validate_production_config` refuses to start the API when any of the following is true:
- `SEALCHECK_JWT_SECRET` is shorter than 32 characters;
- `AUTH_MODE` is not `oidc`, or `OIDC_ISSUER` is not set;
- `DATABASE_URL` is not PostgreSQL;
- `KMS_BACKEND=soft`;
- `STORAGE_BACKEND` is not `s3`;
- `SANDBOX_BACKEND=process`;
- `SEALCHECK_ALLOW_SEED=1`;
- `CORS_ORIGINS` contains `*`.

Production mode also turns on HSTS.

## 2. Backends and their verification status

| Concern | Variable | Dev default | Production choice | Verification status |
|---|---|---|---|---|
| Database | `DATABASE_URL` | SQLite file | PostgreSQL 16 + pgvector | **Tested here** on a real local PG16 (full test suite + Alembic up/down) |
| Login | `AUTH_MODE`, `OIDC_*` | `local` | `oidc` (Keycloak realm in `deploy/keycloak/`) | **Mock-tested only** (`devtools/mock_oidc.py`); Keycloak itself not run here (no Java/Docker) |
| Sandbox | `SANDBOX_BACKEND` | `namespace` when bubblewrap exists, else `process` | `namespace` or `docker` (+`SANDBOX_DOCKER_RUNTIME=runsc`) | `namespace` **tested here** (bwrap + seccomp, escape tests); `docker`/gVisor **argv-tested only** |
| KMS | `KMS_BACKEND` = soft, aws, vault or pkcs11 | `soft` | `aws` (`KMS_AWS_KEY_ID`) / `vault` (`VAULT_ADDR`, `VAULT_TOKEN`, `KMS_VAULT_KEY`) / `pkcs11` | soft **tested**; aws **moto-tested**; vault **mock-HTTP-tested**; pkcs11 **untested** (no SoftHSM on box) |
| WORM storage | `STORAGE_BACKEND`, `S3_BUCKET`, `S3_ENDPOINT_URL`, `WORM_RETENTION_DAYS` | `fs` (chmod 0444) | `s3` with Object Lock COMPLIANCE | fs **tested**; S3 **moto-tested only** |
| Job queue | `QUEUE_BACKEND`, `REDIS_URL` | `thread` | `rq` (Redis) or `db` (PG `SKIP LOCKED`) | `db` **tested on PG**; `rq` **fakeredis-tested only** |
| Rate limits | `RATE_LIMIT`, `RATE_*_PER_MIN`, `REDIS_URL` | in-memory | Redis | in-memory **tested**; Redis **fakeredis-tested** |
| Photo vision | `VISION_BACKEND`, `VISION_*` | `classic` (pHash+ORB) | `models` (DINOv2-small, RT-DETR r18vd, DISK+LightGlue; `requirements-vision.txt`) | **Run here** on SYNTHETIC photos only; thresholds not calibrated on real data |
| LLM wording | `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` | off (rule-based) | openai / anthropic / ollama | **Mock-tested only**; it can never change a status |
| Alerts | `NOTIFY_CHANNELS`, `SMTP_*`, `ALERT_EMAIL_TO`, `SMS_*`/`TWILIO_*`, `ALERT_SMS_TO`, `WEBHOOK_URL`, `WEBHOOK_SECRET`, `SLACK_WEBHOOK_URL`, `SIEM_FILE`, `SIEM_FORMAT`, `SIEM_SYSLOG`, `NOTIFY_MAX_ATTEMPTS`, `NOTIFY_RETRY_S` | in-app only | email + SMS + SIEM | SMTP tested against local aiosmtpd; SMS/webhook/Slack **mock-HTTP-tested**; SIEM file/UDP tested locally |
| DSC trust | `TRUST_STORE_DIR` (+`intermediates/`) | demo root from the seed | CCA India roots + intermediates | **Operator must supply** the real roots |
| Revocation | `REVOCATION_CHECK` = off, soft or hard; `REVOCATION_CACHE_S`, `CB_THRESHOLD`, `CB_COOLDOWN_S` | `off` | `hard` | **Mock-tested** with locally built OCSP/CRL responses; no real CA responder contacted |
| Issuer registries | `ISSUER_CONNECTORS_FILE` (see `deploy/issuer-connectors.example.yaml`) | none, so the check reports *Source Unavailable* | real registry APIs | **Mock-tested only**; no real registry API is known or integrated |
| Integrity sweep | `INTEGRITY_INTERVAL_S` | 0 (manual endpoint) | e.g. 3600 | **Tested here** |
| Observability | `LOG_FORMAT=json`, `LOG_LEVEL`, `METRICS_TOKEN` | plain | json + scraped `/metrics` | **Tested here** (`/healthz`, `/readyz`, `/metrics`) |
| DB pool | `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT_S`, `DB_STATEMENT_TIMEOUT_MS` | defaults | tune | tested on PG |
| Misc | `SEALCHECK_JWT_SECRET`, `SEALCHECK_JWT_TTL_MIN`, `SESSION_IDLE_MIN`, `SEALCHECK_JOB_TOKEN_TTL_S`, `SEALCHECK_MAX_UPLOAD_MB`, `SEALCHECK_WORKER_CPU_S`, `SEALCHECK_WORKER_MEM_MB`, `CORS_ORIGINS`, `SEALCHECK_DATA_DIR` | dev values | set explicitly | n/a |

The Security centre has an **Active backends** card, and `GET /api/security/overview` returns a `backends` field. Both show what a running server is actually using.

## 3. Inputs only an operator can provide

1. **Identity:** a Keycloak (or other OIDC) realm, client IDs, an MFA policy for staff, and the mapping from college codes to users.
2. **DSC trust:** the CCA India root and intermediate certificates, placed in `TRUST_STORE_DIR`.
3. **Registries:** the issuer-registry APIs (fire department, land registry, DigiLocker and others), with their credentials. Put them in `ISSUER_CONNECTORS_FILE`.
4. **KMS:** an AWS KMS key ARN, or a Vault transit key, or an HSM with its PKCS#11 library and PIN.
5. **Storage:** an S3 bucket created **with Object Lock enabled**, and a retention period agreed with AICTE legal.
6. **Rules:** the Ed25519 signing key for rule bundles. It is held by the AICTE rule authority and is not the demo key.
7. **Alerts:** SMTP relay, SMS gateway and SIEM endpoints, plus the alert recipients.
8. **Data:** real-world labelled documents and photos, needed to calibrate the vision thresholds (`VISION_DUP_*`) and to measure false-positive rates.
9. **Infrastructure:** TLS certificates and a domain; the nginx config is in `deploy/nginx/`.

## 4. Deploying

- `docker-compose.prod.yml` brings up postgres+pgvector, redis, minio (Object Lock), keycloak, a migration job, the api, a worker and nginx.
- `deploy/k8s/sealcheck.yaml` holds the equivalent Kubernetes manifests.
- **Neither has been run.** Docker is not available on the build box, so both have only been syntax-checked.

Steps:
1. `alembic upgrade head`. This is run by the `migrate` service.
2. Start the API (`uvicorn app.main:app`) and the workers (`python -m app.queue_worker`).
3. Point your probes at `/healthz` (liveness) and `/readyz` (readiness; returns 503 while draining).

## 5. Operations

- **Key rotation:**
  - `python -m app.kms rotate`, then `python -m app.kms rewrap`. Check with `python -m app.kms status`.
- **Integrity:**
  - Run `POST /api/admin/integrity-check`, or set `INTEGRITY_INTERVAL_S`.
  - A failure writes to the audit log and raises an `integrity_failure` alert.
- **Backups:**
  - Use `pg_dump` together with a bucket replica.
  - A restore was rehearsed into the `sealcheck_restore` database.
- **Alert retries:**
  - Failed alerts retry with exponential backoff and go to `dead` after `NOTIFY_MAX_ATTEMPTS`.
  - Inspect them in the Notification centre (admin), or via `GET /api/notifications/outbox`.
