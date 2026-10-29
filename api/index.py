"""Vercel serverless entry for SealCheck.

ENV=production (set in the Vercel project): shared Neon Postgres (DATABASE_URL from the Neon integration),
document blobs stored insert-only in Postgres (STORAGE_BACKEND=db), keys derived from SEALCHECK_MASTER_KEY,
Google sign-in (AUTH_MODE=google), jobs run inline in the request, no demo data. The schema is created
idempotently under a Postgres advisory lock; nothing is reseeded per instance.

ENV=development (local `vercel dev` only): synthetic demo data is generated and seeded into /tmp."""
import fcntl
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.setdefault("SEALCHECK_DATA_DIR", "/tmp/sealcheck"))
DATA.mkdir(parents=True, exist_ok=True)
for k, v in {
    "ENV": "production", "AUTH_MODE": "google", "QUEUE_BACKEND": "inline", "SANDBOX_BACKEND": "process",
    "SEALCHECK_ACCEPT_PROCESS_SANDBOX": "1", "STORAGE_BACKEND": "db", "VISION_BACKEND": "classic", "RATE_LIMIT": "on",
    "SEALCHECK_FRONTEND_DIST": str(ROOT / "frontend" / "dist-not-served-by-function"),
}.items():
    os.environ.setdefault(k, v)
if not os.environ.get("DATABASE_URL") and os.environ.get("POSTGRES_URL"):
    os.environ["DATABASE_URL"] = os.environ["POSTGRES_URL"]
sys.path.insert(0, str(ROOT / "backend"))
# child processes (sandbox worker) need the runtime's vendored dependency paths
os.environ["SEALCHECK_WORKER_SYSPATH"] = os.pathsep.join(p for p in sys.path if p and os.path.isdir(p))


def _dev_seed():
    os.environ.setdefault("SEALCHECK_SAMPLES_DIR", str(DATA / "samples"))
    os.environ.setdefault("SEALCHECK_TEMPLATES_DIR", str(DATA / "templates"))
    with open(DATA / ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if (DATA / ".seeded").exists():
            return
        import runpy
        for script in (["seed/generate_samples.py"], ["seed/seed_db.py", "--force"]):
            argv, sys.argv = sys.argv, [str(ROOT / script[0]), *script[1:]]
            try:
                runpy.run_path(str(ROOT / script[0]), run_name="__main__")
            finally:
                sys.argv = argv
        (DATA / ".seeded").touch()


if os.environ["ENV"] == "development":
    _dev_seed()
from app.db import init_db  # noqa: E402
init_db()  # idempotent; advisory-locked on Postgres so concurrent cold starts are safe
from app.main import app  # noqa: E402,F401
