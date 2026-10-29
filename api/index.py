"""Vercel serverless entry for the SealCheck public demo.

Demo-safe defaults: synthetic data only, local demo login, SQLite in /tmp seeded on cold start (~10 s),
jobs run inline in the request, sandbox falls back to a plain process (no bubblewrap on Vercel),
classic vision (no ML models), no Postgres/Redis/S3/Vault/SMTP. Data resets whenever the instance recycles."""
import fcntl
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.setdefault("SEALCHECK_DATA_DIR", "/tmp/sealcheck"))
for k, v in {
    "ENV": "demo", "AUTH_MODE": "local", "QUEUE_BACKEND": "inline", "SANDBOX_BACKEND": "process",
    "VISION_BACKEND": "classic", "RATE_LIMIT": "on",
    "SEALCHECK_SAMPLES_DIR": str(DATA / "samples"), "SEALCHECK_TEMPLATES_DIR": str(DATA / "templates"),
    "SEALCHECK_FRONTEND_DIST": str(ROOT / "frontend" / "dist-not-served-by-function"),
    "SEALCHECK_DEMO_NOTICE": "public prototype on Vercel with synthetic data. Data resets periodically; "
                             "ML vision models, Postgres, background workers and the bubblewrap sandbox are switched off.",
}.items():
    os.environ.setdefault(k, v)
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, str(ROOT / "backend"))
# child processes (seed scripts, sandbox worker) need the runtime's vendored dependency paths
_extra = os.pathsep.join(p for p in sys.path if p and os.path.isdir(p))
os.environ["SEALCHECK_WORKER_SYSPATH"] = _extra


def _seed():
    DATA.mkdir(parents=True, exist_ok=True)
    with open(DATA / ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if (DATA / ".seeded").exists():
            return
        import runpy  # in-process: avoids two extra interpreter start-ups on a cold start
        for script in (["seed/generate_samples.py"], ["seed/seed_db.py", "--force"]):
            argv, sys.argv = sys.argv, [str(ROOT / script[0]), *script[1:]]
            try:
                runpy.run_path(str(ROOT / script[0]), run_name="__main__")
            finally:
                sys.argv = argv
        (DATA / ".seeded").touch()


_seed()
from app.main import app  # noqa: E402,F401
