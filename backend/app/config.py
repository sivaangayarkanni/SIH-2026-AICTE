"""Central configuration. All values can be overridden with environment variables (see .env.example)."""
import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BACKEND_DIR.parent
DATA_DIR = Path(os.getenv("SEALCHECK_DATA_DIR", BACKEND_DIR / "data"))
ORIGINALS_DIR = DATA_DIR / "originals"      # write-once (WORM) originals
SANITIZED_DIR = DATA_DIR / "sanitized"      # CDR output
EVIDENCE_DIR = DATA_DIR / "evidence"        # rendered highlight images
KEYS_DIR = DATA_DIR / "keys"
JOBS_DIR = DATA_DIR / "jobs"
RULES_DIR = Path(__file__).resolve().parent / "rules"
FRONTEND_DIST = Path(os.getenv("SEALCHECK_FRONTEND_DIST", ROOT_DIR / "frontend" / "dist"))
SAMPLES_DIR = Path(os.getenv("SEALCHECK_SAMPLES_DIR", ROOT_DIR / "seed" / "samples"))
TEMPLATES_DIR = Path(os.getenv("SEALCHECK_TEMPLATES_DIR", ROOT_DIR / "seed" / "templates"))

ENV = os.getenv("ENV", "development").lower()
IS_PROD = ENV == "production"
DB_URL = os.getenv("DATABASE_URL") or os.getenv("SEALCHECK_DB_URL") or f"sqlite:///{DATA_DIR / 'sealcheck.db'}"
if DB_URL.startswith("postgres://") or DB_URL.startswith("postgresql://"):
    DB_URL = "postgresql+psycopg://" + DB_URL.split("://", 1)[1]
AUTH_MODE = os.getenv("AUTH_MODE", "local").lower()  # local (dev demo login) | oidc (Keycloak)
SESSION_IDLE_MIN = int(os.getenv("SESSION_IDLE_MIN", "15"))
DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "10"))
DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "20"))
DB_POOL_TIMEOUT_S = int(os.getenv("DB_POOL_TIMEOUT_S", "10"))
DB_STATEMENT_TIMEOUT_MS = int(os.getenv("DB_STATEMENT_TIMEOUT_MS", "30000"))
JWT_SECRET = os.getenv("SEALCHECK_JWT_SECRET", "")
JWT_TTL_MIN = int(os.getenv("SEALCHECK_JWT_TTL_MIN", "480"))
JOB_TOKEN_TTL_S = int(os.getenv("SEALCHECK_JOB_TOKEN_TTL_S", "60"))
MAX_UPLOAD_MB = int(os.getenv("SEALCHECK_MAX_UPLOAD_MB", "15"))
WORKER_CPU_SECONDS = int(os.getenv("SEALCHECK_WORKER_CPU_S", "45"))
WORKER_MEMORY_MB = int(os.getenv("SEALCHECK_WORKER_MEM_MB", "1536"))
# Optional artificial delay per pipeline stage so a live audience can follow the progress UI (0 = off; adds to timings)
DEMO_PACE_MS = int(os.getenv("SEALCHECK_DEMO_PACE_MS", "0"))
LLM_API_KEY = os.getenv("OPENAI_API_KEY", "")
LLM_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
LLM_MODEL = os.getenv("SEALCHECK_LLM_MODEL", "gpt-4o-mini")

for d in (DATA_DIR, ORIGINALS_DIR, SANITIZED_DIR, EVIDENCE_DIR, KEYS_DIR, JOBS_DIR):
    d.mkdir(parents=True, exist_ok=True)


def secret(name: str, nbytes: int = 32) -> bytes:
    """Load (or create once) a local secret file under data/keys. Production: fetched from KMS/HSM."""
    if os.environ.get("SEALCHECK_MASTER_KEY"):
        return derive_key(name, nbytes)
    p = KEYS_DIR / name
    if not p.exists():
        p.write_bytes(os.urandom(nbytes))
        os.chmod(p, 0o600)
    return p.read_bytes()


def derive_key(label: str, nbytes: int = 32) -> bytes:
    """HKDF-SHA256 sub-key of SEALCHECK_MASTER_KEY, so every serverless instance derives identical keys."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    mk = os.environ["SEALCHECK_MASTER_KEY"].encode()
    return HKDF(algorithm=hashes.SHA256(), length=nbytes, salt=b"sealcheck-v1", info=label.encode()).derive(mk)
