"""Passwords, JWT sessions, 60-second scoped job tokens, and a local software KMS (envelope encryption)."""
import base64, hashlib, hmac, json, os, time, uuid
import jwt
from .config import secret, JWT_SECRET, JWT_TTL_MIN, JOB_TOKEN_TTL_S

# ---------- passwords (PBKDF2-SHA256, 200k iterations) ----------
def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 200_000)
    return f"pbkdf2_sha256$200000${salt.hex()}${dk.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, it, salt, h = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), int(it))
        return hmac.compare_digest(dk.hex(), h)
    except Exception:
        return False


# ---------- JWT ----------
def _jwt_key() -> bytes:
    return JWT_SECRET.encode() if JWT_SECRET else secret("jwt.key")


def issue_jwt(user) -> str:
    payload = {"sub": str(user.id), "role": user.role, "cid": user.college_id,
               "iat": int(time.time()), "exp": int(time.time()) + JWT_TTL_MIN * 60}
    return jwt.encode(payload, _jwt_key(), algorithm="HS256")


def decode_jwt(token: str) -> dict:
    return jwt.decode(token, _jwt_key(), algorithms=["HS256"])


# ---------- 60-second scoped job tokens (HMAC-SHA256) ----------
def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def job_token_key() -> bytes:
    return secret("job_token.key")


def issue_job_token(job_id: int, document_id: int, ttl: int = JOB_TOKEN_TTL_S, key: bytes | None = None) -> tuple[str, dict]:
    claims = {"jti": uuid.uuid4().hex[:16], "job": job_id, "doc": document_id, "scope": "analyze:read-only",
              "exp": int(time.time()) + ttl}
    body = _b64(json.dumps(claims, separators=(",", ":"), sort_keys=True).encode())
    sig = _b64(hmac.new(key or job_token_key(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}", claims


class TokenError(Exception):
    pass


def verify_job_token(token: str, job_id: int, document_id: int, key: bytes | None = None, now: float | None = None) -> dict:
    try:
        body, sig = token.split(".")
    except ValueError:
        raise TokenError("malformed token")
    expect = _b64(hmac.new(key or job_token_key(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(expect, sig):
        raise TokenError("bad signature")
    claims = json.loads(_unb64(body))
    if (now or time.time()) > claims["exp"]:
        raise TokenError("token expired")
    if claims["job"] != job_id or claims["doc"] != document_id:
        raise TokenError("token scope mismatch")
    if claims.get("scope") != "analyze:read-only":
        raise TokenError("wrong scope")
    return claims


# ---------- KMS (adapter chosen by KMS_BACKEND; see app/kms.py) ----------
from .kms import get_kms  # noqa: E402

kms = get_kms()


def blind_index(value: str) -> str:
    return hmac.new(secret("blind_index.key"), value.upper().strip().encode(), hashlib.sha256).hexdigest()


def mask_pan(pan: str) -> str:
    """Last-4 masking (e.g. XXXXXX821Q)."""
    return "XXXXXX" + pan.strip()[-4:] if len(pan.strip()) == 10 else "XXXX"


def mask_aadhaar(a: str) -> str:
    d = "".join(c for c in a if c.isdigit())
    return "XXXX XXXX " + d[-4:]
