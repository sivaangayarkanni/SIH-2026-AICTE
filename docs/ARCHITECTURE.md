# Architecture

## Components
| Layer | Implementation |
|---|---|
| UI | React 18 + TypeScript + Vite + Tailwind PWA in `frontend/`. Four themes plus dark mode (saved in localStorage), an IndexedDB offline upload queue, and a service worker (`/sw.js`). Fonts are bundled via @fontsource. |
| API | FastAPI (`backend/app/main.py`), which also serves the built SPA on port 8000 |
| Data | SQLAlchemy on SQLite (`backend/data/`); set `SEALCHECK_DB_URL` to use Postgres |
| Worker | `backend/app/worker.py`, run as a separate `python -I` process per job |
| Pipeline | `backend/app/pipeline/`: gateway (type/size checks) → cdr → forensics (4A) → rule_engine (4B) → photo (4C) → policy |
| Cross-document | `backend/app/main.py` (collusion graph 4D via networkx) , which also holds the priority score; `backend/app/service.py` orchestrates the pipeline |
| Explanations | `backend/app/agents.py` (Compliance, Forensics and Guidance agents), `backend/app/qa.py` (grounded Q&A over findings) |
| Reports | `backend/app/reports.py`: evidence packet, decision and rejection PDFs (reportlab) |
| Audit | `backend/app/audit.py`: SHA-256 hash chain and verify |

## Document lifecycle
1. **Upload.** The college uploads a file, or the PWA queues it while offline and syncs it later. The API checks size and type, stores the original as AES-GCM envelope-encrypted WORM (0444), and creates a job.
2. **Sandbox.** The worker receives a 60-second HMAC job token. It runs with CPU and memory rlimits, has outbound sockets blocked, and works only on its copy of the file.
3. **CDR.** pikepdf rebuilds the PDF and removes JavaScript, OpenAction/Launch actions and embedded files. Anything removed is recorded as a module-3 finding.
4. **4A forensics.** Checks for hidden or white text, masking overlays, incremental updates and metadata anomalies, and validates the DSC with pyHanko.
5. **4B rules.** The Ed25519 signature of the YAML bundle is verified before any rule loads. The engine checks required fields, validity windows and issuer allow-lists.
6. **4C photos.** Checks EXIF data, the geofence against the campus coordinates, and pHash plus ORB matches against all other colleges' photos.
7. **4D collusion.** Faculty PANs are matched across colleges by an HMAC blind index. Shared hashes and photos become graph edges.
8. **Policy.** Rules P1–P6 map the findings to exactly one status: Verified, Mismatch Detected, Expired, Verification Pending, Source Unavailable or Manual Review Required. The checks are deterministic and run in order.
9. **Queue and decision.** Applications are ranked by priority = 0.5·risk + 0.3·deadline urgency + 0.2·waiting time. Only officers decide. A flagged document blocks approval until an override has been requested by one officer and approved by a *different* senior officer.

## Extension seams
- `worker.py`: swap the subprocess for a gVisor or Firecracker runner.
- `security.py` `SoftKMS`: replace with a cloud KMS or HSM client.
- The issuer allow-list in `rules/aicte_rules.yaml`: replace with registry API adapters (unknown issuers currently become Source Unavailable).

## Frontend structure
- Routes are code-split with `React.lazy`, and vendor chunks are split into react, charts (recharts), graph (@xyflow) and fonts. No chunk is above 500 kB.
- `components/Tour.tsx` is the in-browser guided demo tour. Its state lives in localStorage, and it targets elements by `data-tour` attributes.
- Modals render through a portal, so they always sit above sticky panels.
