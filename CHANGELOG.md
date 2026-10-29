# Changelog

All commits are local. Nothing has been pushed to any remote.

## Acceptance pass, AICTE Portal theme, and the rename to SealCheck

### Rename to SealCheck
- Renamed everywhere: UI, docs, package names, service, metric and log names, JWT issuer and audience, localStorage keys, PWA manifest, Docker, compose, k8s and Keycloak files, and DB defaults.
- Environment variables: the prefix is now `SEALCHECK_*` (`.env.example` is updated).
- Demo accounts: now **`@sealcheck.demo`** (the old domain is gone). The password is still `Demo@2026`.
- The rule bundle was re-signed (Ed25519, same public key).

### AICTE Portal theme
- New default theme. The palette was sampled from aicte.gov.in.
- Adds a government top bar with a Hindi line, a tricolour strip, and a utility bar:
  - skip link;
  - A-/A/A+;
  - English or Hindi nav labels;
  - high contrast;
  - dark mode.
- Also adds a portal nav with dropdowns, breadcrumbs, and a government-style footer.
- Our own generic shield mark is used; no AICTE or GoI logo or emblem.
- The labels "Prototype - not an official AICTE system" appear in the header and footer.

### Acceptance pass
- `run.sh` now checks for Python 3.11+ and Node 18+. It reports missing optional packages (bubblewrap, tesseract, ClamAV) along with the fallback each one triggers.
- The server logs a visible warning when the sandbox falls back to `process`.
- README covers zip users and adds macOS and Windows (WSL2) notes.
- `scripts/clickthrough.py` is a headless click-through of every role and flow. It produces a PASS/FAIL table.
- `render.yaml` adds a demo Blueprint. Docker was not available on the build box, so the image is untested.

## Phase 3: production hardening

Status labels:
- **tested**: exercised against the real thing on the build box.
- **mock-tested**: exercised against a local stand-in.
- **untested**: neither.

### Stages
- **A: PostgreSQL 16 + pgvector.**
  - `DATABASE_URL`, Alembic 0001, HNSW indexes, append-only audit triggers, pooling.
  - Backup and restore rehearsal. Tested on PG16.
- **B: `VISION_BACKEND=models`.**
  - DINOv2-small embeddings in pgvector, DISK+LightGlue verification, RT-DETR COCO detections and a layout hash, all out of process.
  - Run on synthetic photos only.
- **G: OIDC.**
  - PKCE SPA, JWKS validation and rotation, role and college mapping, staff MFA enforcement, refresh, logout and idle timeout.
  - Keycloak realm export included.
  - Mock-tested with `devtools/mock_oidc.py`.
- **C: sandbox.**
  - bubblewrap namespaces with no network, plus a seccomp BPF filter (AF_UNIX-only sockets, dangerous syscalls denied) and rlimits.
  - Escape probes tested.
  - Docker/gVisor backend: argv only.
  - Fixed documents getting stuck at Manual Review (EBUSY on bind-mounted output) and signatures failing (socketpair blocked).
- **D: KMS adapters.**
  - Soft (versioned) and AWS KMS (moto), Vault Transit (mock HTTP), PKCS#11 (untested).
  - Rotate/rewrap CLI added.
- **E: WORM storage.**
  - fs, plus S3 Object Lock COMPLIANCE (moto).
  - Integrity-check endpoint and periodic job, with audit and alert.
- **J: operations.**
  - Request IDs, JSON logs, Prometheus `/metrics`, `/healthz` and `/readyz` with drain, rate limiting (memory or Redis), and production fail-fast config validation.
  - RQ and DB (`SKIP LOCKED`) queue workers.
  - Pinned requirements and lock file, ruff, CI workflow, pre-commit.
  - Dockerfile, compose and k8s manifests (not run: no Docker).
- **H: notifications.**
  - SMTP, SMS (HTTP/Twilio-style), HMAC-signed webhook, Slack, and SIEM (jsonl/CEF/syslog).
  - Outbox with exponential-backoff retry and dead-letter; migration 0002.
- **I: guarded LLM client.**
  - OpenAI-compatible, Anthropic and Ollama.
  - Evidence minimisation, prompt-injection scrub, schema validation and a status lock, so the LLM can never change a decision.
  - Mock-tested.
- **F: DSC trust.**
  - Configurable trust store with intermediates.
  - Host-side OCSP-then-CRL checks with a disk cache and circuit breaker; LTV/DSS flag.
  - Issuer-registry connectors mapped to the *Source Unavailable* status.
  - Mock-tested.
- **K: UI.**
  - Long checklist names now wrap instead of being cut off. Document tabs wrap instead of scrolling sideways. The policy summary row no longer squeezes.
  - New **Notification centre** page: inbox, external-channel status, delivery outbox and a test-alert button.
  - Security centre now has an **Active backends** card.
  - Fixed a crash in `/api/security/overview`: it referenced a constant that had moved, which broke the Security page. A regression test now covers it.
  - ESLint `no-explicit-any` turned off deliberately, because API payloads are untyped JSON. Lint has 0 errors.
  - Screenshots re-taken (42), including OIDC, vision models and backends.
- **L: docs.**
  - `docs/PRODUCTION.md`, an honest real-vs-simulated table in the README, and this changelog.

## Phase 2: polish
- Sticky evidence layout, demo tour, code-split bundle, portal modals, QA flag answers and screenshots.

## Phase 1: prototype
- Zero-trust compliance prototype: CDR, PDF forensics, DSC checks, signed rule bundle, photo checks, collusion graph, agents and audit chain.
