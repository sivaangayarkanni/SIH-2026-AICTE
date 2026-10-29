# 3-minute judge demo

Setup: run `RESEED=1 ./run.sh` and open http://localhost:8000. Every password is `Demo@2026`, and you can click a demo card on the login page instead of typing.

**Guided option:** officer dashboard → **Start 3-minute demo tour**. The callouts follow the same steps as the table below.

| Time | Do | Say |
|---|---|---|
| 0:00 | Click the **Scrutiny Officer** card (officer@). | "AICTE officers get a queue ranked by risk, deadline and waiting time. The formula is shown, not hidden." |
| 0:20 | Open **AICTE-26-GVCE-0002**, then click *gvce_land_lease_forged.pdf*. | "Every file went through the sandbox and CDR first. Here 4A found hidden white text and a masking overlay, highlighted right on the page." |
| 0:50 | Open the **Agents** tab, then **Ask** (try the mic). | "The agents explain the finding in plain language. They cannot change the status; the deterministic policy engine sets it (rule P1)." |
| 1:10 | Click **Approve**. | "It's blocked. A suspected forgery needs a two-person override." |
| 1:20 | **Request override** with a justification. Sign out and sign in as **Senior Officer** (senior@). Go to **Security overrides** → approve. | "The requester can't approve their own override. Both steps go into the audit chain." |
| 1:50 | Open **Collusion graph**. | "4D: the same faculty PAN appears at two colleges. It is matched by blind index, so we never compare plain PANs. DIEM also reused another college's lab photo (pHash + ORB)." |
| 2:15 | Open **Security center**: token countdown, KMS demo, **Verify chain**. | "Job tokens expire in 60 seconds, originals are envelope-encrypted and read-only, and the audit log is hash-chained and verifiable." |
| 2:35 | Sign in as **principal.gvce**. Open **Readiness** and run the pre-check; open the rejection helper. Settings → switch theme / dark mode. | "Colleges get a pre-check and fix-it guidance before they submit. Uploads queue offline on poor connections." |
| 2:55 | Close on the README's real-vs-simulated table. | "What's real, what's simulated, and where production adapters plug in. No invented accuracy numbers." |

Fallback: if live clicking fails, `python scripts/smoke.py` exercises the same flows from the terminal, and `/workspace/sealcheck/screenshots` contains stills.
