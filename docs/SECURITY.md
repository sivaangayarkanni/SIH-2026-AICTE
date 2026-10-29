# Security model

| Threat | Control | Where |
|---|---|---|
| Malicious PDF (JS, launch actions, embedded payloads) | Sandbox subprocess (`python -I`, CPU/memory/file rlimits, socket egress guard) + pikepdf CDR | `worker.py`, `pipeline/cdr.py` |
| Replay or forged worker jobs | HMAC job token bound to the job and document, 60-second lifetime | `security.py` |
| Tampering with stored originals | Original encrypted with AES-GCM under a per-file DEK, the DEK wrapped by the KMS key; file set to 0444; SHA-256 recorded | `security.py` |
| Forged or tampered documents | 4A forensics, DSC validation, 4B rules, 4C photo reuse, 4D collusion | `pipeline/` |
| Rule tampering | Ed25519-signed YAML bundle, verified at load time; the UI shows the fingerprint | `rules_bundle.py` |
| PII exposure | PANs encrypted at rest and matched by blind index; reveal is admin-only and audited | `security.py`, `main.py` |
| Insider approval of a forgery | Two-person override: requester ≠ approver, approver must be a senior officer, justification of at least 20 characters | `main.py` |
| AI overreach | The policy engine sets the status deterministically; agents and LLMs only explain and cannot change it | `pipeline/policy.py`, `agents.py` |
| Log tampering | SHA-256 hash chain; `/api/audit/verify` recomputes it | `audit.py` |
| Credential stuffing | PBKDF2-SHA256 (200k iterations) password hashes; 10 failures per minute per IP gives 429 | `main.py` |
| Cross-tenant access | RBAC + `scoped_app` (colleges see only their own data) | `main.py` |

## Prototype limits (honest)
- The KMS master key is software-held (a file under `backend/data/keys`). Production needs an HSM or cloud KMS.
- The sandbox is OS-process isolation, not a VM. Production should use gVisor or Firecracker.
- The DSC trust root is a demo CA created by the seed, not the CCA India root.
- WORM is enforced only by file mode. Production should use object-lock storage.
- SQLite with a single node; there is no HA.
