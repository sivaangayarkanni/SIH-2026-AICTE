"""Google sign-in (OpenID Connect, authorization code + PKCE, confidential client) and first-login onboarding.

Flow: /api/auth/google/start -> Google -> /api/auth/google/callback. The server keeps state, nonce and the
PKCE verifier in a short-lived HMAC-signed HttpOnly cookie, exchanges the code with the client secret,
verifies the id_token signature against Google's JWKS (iss, aud, exp, nonce) and requires email_verified.
New accounts start with role 'pending' and must complete the onboarding form. Officer/admin access is
never self-assigned: an administrator approves it. The first administrator is bootstrapped by
SEALCHECK_BOOTSTRAP_ADMIN_EMAIL. Configuration: GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, PUBLIC_BASE_URL
(redirect URI = PUBLIC_BASE_URL + /api/auth/google/callback). GOOGLE_ISSUER is only overridden in tests."""
from __future__ import annotations
import base64, hashlib, hmac, json, os, re, secrets, time
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, field_validator

from . import audit
from .db import SessionLocal, User, College, UserProfile, now
from .security import hash_password, issue_jwt, _jwt_key

router = APIRouter()
COOKIE = "sc_google"
ISSUERS = {"https://accounts.google.com", "accounts.google.com"}
_disc: dict = {}
_jwks: dict = {}

INDIAN_STATES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat", "Haryana",
    "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur",
    "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana",
    "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal", "Andaman and Nicobar Islands", "Chandigarh",
    "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Jammu and Kashmir", "Ladakh", "Lakshadweep", "Puducherry"]


def cfg() -> dict:
    return {"client_id": os.environ.get("GOOGLE_CLIENT_ID", ""), "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET", ""),
            "issuer": os.environ.get("GOOGLE_ISSUER", "https://accounts.google.com").rstrip("/"),
            "base": os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")}


def configured() -> bool:
    c = cfg()
    return bool(c["client_id"] and c["client_secret"])


def bootstrap_admin() -> str:
    return os.environ.get("SEALCHECK_BOOTSTRAP_ADMIN_EMAIL", "").strip().lower()


def _issuers(c):
    return ISSUERS if c["issuer"] == "https://accounts.google.com" else {c["issuer"]}


def discovery(c) -> dict:
    if c["issuer"] not in _disc:
        r = httpx.get(c["issuer"] + "/.well-known/openid-configuration", timeout=10); r.raise_for_status()
        _disc[c["issuer"]] = r.json()
    return _disc[c["issuer"]]


def _signing_key(c, token):
    uri = discovery(c)["jwks_uri"]
    if uri not in _jwks:
        _jwks[uri] = jwt.PyJWKClient(uri, cache_keys=True, timeout=10)
    return _jwks[uri].get_signing_key_from_jwt(token).key


def verify_id_token(c, token: str, nonce: str) -> dict:
    claims = jwt.decode(token, _signing_key(c, token), algorithms=["RS256"], audience=c["client_id"],
                        options={"require": ["iss", "aud", "exp", "iat", "sub"]}, leeway=60)
    if claims.get("iss") not in _issuers(c):
        raise ValueError("unexpected issuer")
    if not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
        raise ValueError("nonce mismatch")
    if claims.get("email_verified") not in (True, "true"):
        raise ValueError("Google account email is not verified")
    if not claims.get("email"):
        raise ValueError("no email in id_token")
    return claims


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _sign(d: dict) -> str:
    body = _b64(json.dumps(d, separators=(",", ":")).encode())
    return body + "." + _b64(hmac.new(_jwt_key(), body.encode(), hashlib.sha256).digest())


def _unsign(v: str) -> dict:
    body, _, sig = (v or "").partition(".")
    if not body or not hmac.compare_digest(sig, _b64(hmac.new(_jwt_key(), body.encode(), hashlib.sha256).digest())):
        raise ValueError("bad state cookie")
    d = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    if d.get("exp", 0) < time.time():
        raise ValueError("sign-in attempt expired, please try again")
    return d


def _redirect_uri(c, request: Request) -> str:
    base = c["base"] or str(request.base_url).rstrip("/")
    return base + "/api/auth/google/callback"


def _safe_return(p: str) -> str:
    return p if p.startswith("/") and not p.startswith("//") else "/"


@router.get("/api/auth/google/start")
def start(request: Request, return_to: str = "/"):
    c = cfg()
    if not configured():
        raise HTTPException(503, "Google sign-in is not configured on this server yet.")
    state, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    q = {"client_id": c["client_id"], "redirect_uri": _redirect_uri(c, request), "response_type": "code",
         "scope": "openid email profile", "state": state, "nonce": nonce, "prompt": "select_account",
         "code_challenge": _b64(hashlib.sha256(verifier.encode()).digest()), "code_challenge_method": "S256"}
    r = RedirectResponse(discovery(c)["authorization_endpoint"] + "?" + urlencode(q), 302)
    r.set_cookie(COOKIE, _sign({"s": state, "n": nonce, "v": verifier, "r": _safe_return(return_to), "exp": time.time() + 600}),
                 max_age=600, httponly=True, secure=request.url.scheme == "https", samesite="lax", path="/api/auth/google")
    return r


def _fail(msg: str):
    r = RedirectResponse("/login?" + urlencode({"error": msg}), 302)
    r.delete_cookie(COOKIE, path="/api/auth/google")
    return r


@router.get("/api/auth/google/callback")
def callback(request: Request, code: str = "", state: str = "", error: str = ""):
    c = cfg()
    if error:
        return _fail(f"Google sign-in was cancelled ({error}).")
    try:
        ck = _unsign(request.cookies.get(COOKIE, ""))
        if not hmac.compare_digest(ck["s"], state):
            raise ValueError("state mismatch")
        tr = httpx.post(discovery(c)["token_endpoint"], timeout=15, data={
            "grant_type": "authorization_code", "code": code, "redirect_uri": _redirect_uri(c, request),
            "client_id": c["client_id"], "client_secret": c["client_secret"], "code_verifier": ck["v"]})
        if tr.status_code != 200:
            raise ValueError(f"token exchange failed ({tr.status_code})")
        claims = verify_id_token(c, tr.json()["id_token"], ck["n"])
    except Exception as e:  # noqa: BLE001
        audit.log("auth.google_failed", "-", "-", "auth", {"reason": str(e)[:200]})
        return _fail(f"Google sign-in failed: {str(e)[:160]}")
    u, new = upsert_google_user(claims)
    audit.log("auth.login", f"{u.name} <{u.email}>", u.role, f"user:{u.id}", {"method": "google", "new_account": new})
    r = RedirectResponse(f"/auth/google#{urlencode({'token': issue_jwt(u), 'return_to': ck['r']})}", 302)
    r.delete_cookie(COOKIE, path="/api/auth/google")
    return r


def upsert_google_user(claims: dict) -> tuple[User, bool]:
    email, sub = claims["email"].strip().lower(), str(claims["sub"])
    with SessionLocal() as s:
        prof = s.query(UserProfile).filter_by(google_sub=sub).first()
        u = prof.user if prof else s.query(User).filter(User.email == email).first()
        new = u is None
        if new:
            u = User(email=email, name=(claims.get("name") or email.split("@")[0])[:120], role="pending",
                     password_hash=hash_password(secrets.token_urlsafe(32)), avatar_seed=sub[:12])
            s.add(u); s.flush()
        if not prof:
            prof = s.get(UserProfile, u.id) or UserProfile(user_id=u.id, status="new")
            prof.google_sub, prof.official_email = sub, email
            s.add(prof)
        if bootstrap_admin() and email == bootstrap_admin() and u.role != "admin":
            u.role = "admin"; prof.status = "approved"; prof.decided_by = "bootstrap (SEALCHECK_BOOTSTRAP_ADMIN_EMAIL)"
            prof.decided_at = now(); boot = True
        else:
            boot = False
        s.commit(); s.refresh(u)
        if boot:
            audit.log("access.bootstrap_admin", "system", "system", f"user:{u.id}", {"email": email})
        s.expunge(u)
        return u, new


PHONE = re.compile(r"^(?:\+91[\s-]?)?[6-9]\d{9}$")
AICTE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9/\-]{3,19}$")


class OnboardingIn(BaseModel):
    full_name: str = Field(min_length=3, max_length=120)
    requested_role: str
    institution_name: str = Field(min_length=3, max_length=200)
    aicte_id: str
    state: str
    designation: str = Field(min_length=2, max_length=120)
    phone: str
    consent: bool

    @field_validator("requested_role")
    @classmethod
    def _role(cls, v):
        if v not in ("college", "officer", "evc_member"):
            raise ValueError("Choose 'college representative', 'AICTE officer (needs approval)' or 'EVC member (needs approval)'.")
        return v

    @field_validator("aicte_id")
    @classmethod
    def _aid(cls, v):
        v = v.strip().upper()
        if not AICTE_ID.match(v):
            raise ValueError("AICTE institution / application ID: 4-20 letters, digits, '-' or '/'.")
        return v

    @field_validator("state")
    @classmethod
    def _state(cls, v):
        if v not in INDIAN_STATES:
            raise ValueError("Choose a state or union territory from the list.")
        return v

    @field_validator("phone")
    @classmethod
    def _phone(cls, v):
        v = re.sub(r"[\s-]", "", v.strip())
        if not PHONE.match(v):
            raise ValueError("Enter a 10-digit Indian mobile number (optionally starting +91).")
        return v[-10:]

    @field_validator("consent")
    @classmethod
    def _consent(cls, v):
        if v is not True:
            raise ValueError("You must agree to the data-use terms to continue.")
        return v

    @field_validator("full_name", "institution_name", "designation")
    @classmethod
    def _strip(cls, v):
        v = " ".join(v.split())
        if re.search(r"[<>{}]", v):
            raise ValueError("Remove the characters < > { }.")
        return v


def profile_out(p: UserProfile | None) -> dict | None:
    if not p:
        return None
    return {k: getattr(p, k) for k in ("full_name", "requested_role", "institution_name", "aicte_id", "state", "designation",
                                       "phone", "official_email", "status", "decision_note")} | {
        "consent_at": p.consent_at.isoformat() if p.consent_at else None}


def submit_onboarding(s, u: User, body: OnboardingIn) -> dict:
    prof = s.get(UserProfile, u.id)
    if not prof:
        prof = UserProfile(user_id=u.id, official_email=u.email, status="new"); s.add(prof)
    if prof.status == "approved" and u.role != "admin":
        raise HTTPException(409, "Your account is already approved. Contact an administrator to change your details.")
    for k in ("full_name", "requested_role", "institution_name", "aicte_id", "state", "designation", "phone"):
        setattr(prof, k, getattr(body, k))
    prof.official_email, prof.consent_at = u.email, datetime.now(timezone.utc).replace(tzinfo=None)
    u.name, u.title = body.full_name, body.designation
    if u.role == "admin":
        prof.status = "approved"
    elif body.requested_role == "college":
        col = s.query(College).filter(College.code == body.aicte_id).first()
        if col is None:   # first representative of a new institution: access to that institution only
            col = College(code=body.aicte_id, name=body.institution_name, state=body.state); s.add(col); s.flush()
            u.role, u.college_id, prof.status = "college", col.id, "approved"
            prof.decided_by, prof.decided_at = "auto: first representative of a new institution", now()
        else:             # institution already claimed: an administrator must confirm this person
            u.role, u.college_id, prof.status = "pending", None, "pending"
    else:
        u.role, prof.status = "pending", "pending"
    s.commit()
    audit.log("access.onboarding", f"{u.name} <{u.email}>", u.role, f"user:{u.id}",
              {"requested_role": body.requested_role, "aicte_id": body.aicte_id, "status": prof.status})
    return {"status": prof.status, "role": u.role, "profile": profile_out(prof)}


class DecisionIn(BaseModel):
    role: str | None = None
    note: str = Field(default="", max_length=500)


def decide(s, admin: User, user_id: int, approve: bool, body: DecisionIn) -> dict:
    prof = s.get(UserProfile, user_id)
    u = s.get(User, user_id)
    if not prof or not u:
        raise HTTPException(404, "Request not found")
    if prof.status != "pending":
        raise HTTPException(409, f"This request is already {prof.status}.")
    if u.id == admin.id:
        raise HTTPException(403, "You cannot approve your own access.")
    if approve:
        role = body.role or (prof.requested_role if prof.requested_role in ("college", "evc_member", "officer", "senior_officer") else "officer")
        if role not in ("college", "officer", "senior_officer", "evc_member", "admin"):
            raise HTTPException(422, "Unknown role")
        if role == "college":
            col = s.query(College).filter(College.code == prof.aicte_id).first()
            if col is None:
                col = College(code=prof.aicte_id, name=prof.institution_name, state=prof.state); s.add(col); s.flush()
            u.college_id = col.id
        prev = u.role
        u.role, prof.status = role, "approved"
        from .accounts import UserCredential
        c = s.get(UserCredential, u.id)
        if role == "officer" and c and c.requested_region:
            from .workflow import UserRegion
            r = s.get(UserRegion, u.id)
            if r:
                r.region_code = c.requested_region
            else:
                s.add(UserRegion(user_id=u.id, region_code=c.requested_region))
        if c and prev != role:
            c.token_version += 1   # role change: earlier sessions must sign in again
    else:
        prof.status = "rejected"
    prof.decided_by, prof.decided_at, prof.decision_note = f"{admin.name} <{admin.email}>", now(), body.note or None
    s.commit()
    audit.log("access.approved" if approve else "access.rejected", f"{admin.name} <{admin.email}>", admin.role,
              f"user:{u.id}", {"role": u.role, "note": body.note})
    return {"user_id": u.id, "status": prof.status, "role": u.role}
