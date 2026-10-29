"""Username + password accounts with roles (AUTH_MODE=password in production, also used by AUTH_MODE=local in dev).

* Hashing: bcrypt (cost 12) over a SHA-256 prehash, see security.py. Legacy PBKDF2 hashes are upgraded on login.
* Policy: 10-128 characters, at least 3 of 4 character classes, not in the built-in common-password list, must not
  contain the username / email name. Optional breach check (PASSWORD_BREACH_CHECK=hibp): k-anonymity range query,
  only the first 5 hex characters of the SHA-1 leave the server.
* Roles are never self-granted. College representatives of a new institution get access at signup; every other
  role (Regional officer, Bureau officer, EVC member) and a second representative of an existing institution are
  'pending' until an administrator approves them.
* Lockout: per-account progressive lockout (5 failures -> 1 min, doubling to 60 min) on top of the per-IP limiter.
  Every failure returns the same generic message and takes the same time.
* Sessions: Bearer JWT (no cookies, so no CSRF surface) with a token version; password change, admin reset and
  'sign out everywhere' bump the version, which invalidates every earlier token.
* First admin: SEALCHECK_BOOTSTRAP_ADMIN_USERNAME + SEALCHECK_BOOTSTRAP_ADMIN_PASSWORD, or the one-time setup
  form, which works only while there are zero administrators."""
from __future__ import annotations
import hashlib, os, re, secrets, string
from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Boolean

from . import audit
from .db import Base, College, SessionLocal, User, UserProfile, now
from .security import hash_password, verify_password, burn_password_check, needs_rehash, issue_jwt

router = APIRouter()
USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")
EMAIL = re.compile(r"^[^@\s<>]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24}$")
SIGNUP_ROLES = {"college": "College / institution representative", "evc_member": "Expert Visit Committee member",
                "officer": "Regional officer (scrutiny)", "senior_officer": "Bureau officer (senior)"}
LOCK_AFTER, LOCK_MAX_MIN = 5, 60
GENERIC_FAIL = "Sign-in failed. Check your username and password. After repeated failures sign-in is paused for a few minutes."
_COMMON: set[str] = set()


class UserCredential(Base):
    __tablename__ = "user_credentials"
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    username = Column(String(32), unique=True, nullable=False)
    failed_count = Column(Integer, default=0, nullable=False)
    locked_until = Column(DateTime)
    token_version = Column(Integer, default=0, nullable=False)
    must_change = Column(Boolean, default=False, nullable=False)
    requested_region = Column(String(16))
    pw_changed_at = Column(DateTime)
    last_login_at = Column(DateTime)
    created_at = Column(DateTime, default=lambda: now())


def common_passwords() -> set[str]:
    if not _COMMON:
        p = Path(__file__).parent / "rules" / "common_passwords.txt"
        _COMMON.update(x.strip().lower() for x in p.read_text().splitlines() if x.strip() and not x.startswith("#"))
    return _COMMON


def _breached(pw: str) -> bool | None:
    if os.environ.get("PASSWORD_BREACH_CHECK", "off").lower() != "hibp":
        return None
    import httpx
    h = hashlib.sha1(pw.encode()).hexdigest().upper()
    try:
        r = httpx.get(f"https://api.pwnedpasswords.com/range/{h[:5]}", headers={"Add-Padding": "true"}, timeout=4)
        r.raise_for_status()
    except Exception:
        return None  # fail open: the local policy still applies; logged by the caller
    return any(line.split(":")[0] == h[5:] and int(line.split(":")[1] or 0) > 0 for line in r.text.splitlines())


def password_problems(pw: str, username: str = "", email: str = "") -> list[str]:
    p = []
    if len(pw) < 10:
        p.append("Use at least 10 characters.")
    if len(pw) > 128:
        p.append("Use at most 128 characters.")
    classes = sum(bool(re.search(r, pw)) for r in (r"[a-z]", r"[A-Z]", r"\d", r"[^A-Za-z0-9]"))
    if classes < 3:
        p.append("Mix at least three of: lower-case, upper-case, digits, symbols.")
    low = pw.lower()
    stem = re.sub(r"[\d\W_]+$", "", low)
    if low in common_passwords() or stem in common_passwords() or re.fullmatch(r"(.)\1{5,}", low):
        p.append("This password is too common.")
    for part in {username.lower(), email.lower().split("@")[0]} - {""}:
        if len(part) >= 3 and part in low:
            p.append("Do not include your username or email name.")
            break
    if not p and _breached(pw):
        p.append("This password appears in known data breaches. Choose a different one.")
    return p


def cred_for(s, u: User) -> UserCredential:
    c = s.get(UserCredential, u.id)
    if c is None:  # accounts created before usernames existed (seeded demo users): username = email name
        base = re.sub(r"[^a-z0-9._-]", "", u.email.split("@")[0].lower())[:28] or f"user{u.id}"
        name, i = base if len(base) >= 3 else f"{base}{u.id:03d}", 1
        while s.query(UserCredential).filter_by(username=name).first():
            i += 1; name = f"{base}{i}"
        c = UserCredential(user_id=u.id, username=name, failed_count=0, token_version=0, must_change=False)
        s.add(c); s.flush()
    return c


def token_for(s, u: User) -> str:
    return issue_jwt(u, cred_for(s, u).token_version)


# ------------------------------------------------------------------ login (called from main.login)
def password_login(s, ident: str, pw: str, ip: str) -> tuple[User, UserCredential]:
    ident = ident.strip().lower()
    c = s.query(UserCredential).filter_by(username=ident).first()
    u = s.get(User, c.user_id) if c else s.query(User).filter(User.email == ident).first()
    if u is None or u.password_hash.startswith("!"):
        burn_password_check(pw)
        audit.log("auth.failed", ident[:80], "-", "auth", {"reason": "unknown account"}, ip=ip)
        raise HTTPException(401, GENERIC_FAIL)
    c = c or cred_for(s, u)
    t = now()
    if c.locked_until and c.locked_until > t:
        burn_password_check(pw)
        audit.log("auth.locked_attempt", ident[:80], u.role, f"user:{u.id}", {"until": c.locked_until.isoformat()}, ip=ip)
        raise HTTPException(401, GENERIC_FAIL)
    if not verify_password(pw, u.password_hash):
        c.failed_count = (c.failed_count or 0) + 1
        if c.failed_count >= LOCK_AFTER:
            c.locked_until = t + timedelta(minutes=min(LOCK_MAX_MIN, 2 ** (c.failed_count - LOCK_AFTER)))
        s.commit()
        audit.log("auth.failed", ident[:80], u.role, f"user:{u.id}", {"failures": c.failed_count,
                  "locked_until": c.locked_until.isoformat() if c.locked_until and c.locked_until > t else None}, ip=ip)
        raise HTTPException(401, GENERIC_FAIL)
    c.failed_count, c.locked_until, c.last_login_at = 0, None, t
    if needs_rehash(u.password_hash):
        u.password_hash = hash_password(pw)
    s.commit()
    return u, c


# ------------------------------------------------------------------ signup
class SignupIn(BaseModel):
    full_name: str = Field(max_length=120)
    username: str = Field(max_length=64)
    email: str = Field(max_length=200)
    phone: str = Field(max_length=20)
    password: str = Field(max_length=256)
    confirm: str = Field(max_length=256)
    role: str
    institution_name: str = Field("", max_length=200)
    aicte_id: str = Field("", max_length=20)
    state: str = Field("", max_length=80)
    designation: str = Field("", max_length=120)
    region: str = Field("", max_length=16)
    consent: bool = False


def _clean(v: str) -> str:
    v = " ".join((v or "").split())
    if re.search(r"[<>{}]", v):
        raise HTTPException(422, "Remove the characters < > { }.")
    return v


def validate_signup(b: SignupIn) -> dict:
    from .google_auth import INDIAN_STATES, PHONE, AICTE_ID
    errs: dict[str, str] = {}
    un, em = b.username.strip().lower(), b.email.strip().lower()
    if not USERNAME.match(un):
        errs["username"] = "3-32 characters: lower-case letters, digits, '.', '_' or '-' (start with a letter or digit)."
    if not EMAIL.match(em):
        errs["email"] = "Enter a valid email address."
    ph = re.sub(r"[\s-]", "", b.phone.strip())
    if not PHONE.match(ph):
        errs["phone"] = "Enter a 10-digit Indian mobile number (optionally starting +91)."
    if b.role not in SIGNUP_ROLES:
        errs["role"] = "Choose a role."
    if b.password != b.confirm:
        errs["confirm"] = "The two passwords do not match."
    pp = password_problems(b.password, un, em)
    if pp:
        errs["password"] = " ".join(pp)
    if len(" ".join(b.full_name.split())) < 3:
        errs["full_name"] = "Enter your full name."
    if not b.consent:
        errs["consent"] = "You must agree to the data-use terms."
    d = {"full_name": _clean(b.full_name), "designation": _clean(b.designation) or SIGNUP_ROLES.get(b.role, ""),
         "institution_name": _clean(b.institution_name), "aicte_id": b.aicte_id.strip().upper(), "state": b.state, "region": b.region.strip()}
    if b.role == "college":
        if len(d["institution_name"]) < 3:
            errs["institution_name"] = "Enter the institution name."
        if not AICTE_ID.match(d["aicte_id"]):
            errs["aicte_id"] = "AICTE institution / application ID: 4-20 letters, digits, '-' or '/'."
        if b.state not in INDIAN_STATES:
            errs["state"] = "Choose a state or union territory."
        if len(d["designation"]) < 2:
            errs["designation"] = "Enter your designation."
    elif b.role in ("officer", "senior_officer"):
        from .workflow import active_config
        with SessionLocal() as s:
            codes = {r["code"] for r in active_config(s)["regions"]}
        if b.role == "officer" and d["region"] not in codes:
            errs["region"] = "Choose your region."
        if d["region"] and d["region"] not in codes:
            errs["region"] = "Unknown region."
    if errs:
        raise HTTPException(422, {"message": "Please correct the highlighted fields.", "fields": errs})
    return d | {"username": un, "email": em, "phone": ph[-10:]}


def signup(b: SignupIn, ip: str) -> dict:
    d = validate_signup(b)
    with SessionLocal() as s:
        if s.query(UserCredential).filter_by(username=d["username"]).first() or s.query(User).filter(User.email == d["email"]).first():
            audit.log("auth.signup_rejected", d["username"], "-", "auth", {"reason": "username or email already registered"}, ip=ip)
            raise HTTPException(409, {"message": "That username or email cannot be used. Choose another, or sign in.",
                                      "fields": {"username": "Not available.", "email": "Not available."}})
        u = User(email=d["email"], name=d["full_name"], title=d["designation"], role="pending",
                 password_hash=hash_password(b.password), avatar_seed=d["username"][:12])
        s.add(u); s.flush()
        s.add(UserCredential(user_id=u.id, username=d["username"], failed_count=0, token_version=0, must_change=False,
                             requested_region=d["region"] or None, pw_changed_at=now()))
        prof = UserProfile(user_id=u.id, full_name=d["full_name"], requested_role=b.role, official_email=d["email"], phone=d["phone"],
                           designation=d["designation"], consent_at=now(),
                           institution_name=d["institution_name"] or "AICTE", aicte_id=d["aicte_id"] or None, state=d["state"] or None)
        s.add(prof)
        if b.role == "college":
            col = s.query(College).filter(College.code == d["aicte_id"]).first()
            if col is None:
                col = College(code=d["aicte_id"], name=d["institution_name"], state=d["state"]); s.add(col); s.flush()
                u.role, u.college_id, prof.status = "college", col.id, "approved"
                prof.decided_by, prof.decided_at = "auto: first representative of a new institution", now()
            else:
                prof.status = "pending"
        else:
            prof.status = "pending"
        s.commit(); s.refresh(u)
        audit.log("auth.signup", f"{u.name} <{u.email}>", u.role, f"user:{u.id}",
                  {"username": d["username"], "requested_role": b.role, "status": prof.status, "region": d["region"] or None}, ip=ip)
        tok = token_for(s, u)
        from .main import user_out
        return {"token": tok, "status": prof.status, "user": user_out(u)}


# ------------------------------------------------------------------ password change / reset / sign out everywhere
class PasswordChangeIn(BaseModel):
    current: str = Field(min_length=1, max_length=256)
    new: str = Field(max_length=256)
    confirm: str = Field(max_length=256)


def change_password(s, u: User, b: PasswordChangeIn) -> str:
    c = cred_for(s, u)
    if not verify_password(b.current, u.password_hash):
        audit.log("auth.password_change_failed", f"{u.name} <{u.email}>", u.role, f"user:{u.id}")
        raise HTTPException(400, {"message": "Your current password is not correct.", "fields": {"current": "Not correct."}})
    if b.new != b.confirm:
        raise HTTPException(422, {"message": "The two passwords do not match.", "fields": {"confirm": "Does not match."}})
    pp = password_problems(b.new, c.username, u.email)
    if b.new == b.current:
        pp.append("Choose a password you have not just used.")
    if pp:
        raise HTTPException(422, {"message": " ".join(pp), "fields": {"new": " ".join(pp)}})
    u.password_hash = hash_password(b.new)
    c.token_version += 1; c.must_change = False; c.pw_changed_at = now()
    s.commit()
    audit.log("auth.password_changed", f"{u.name} <{u.email}>", u.role, f"user:{u.id}", {"other_sessions": "signed out"})
    return issue_jwt(u, c.token_version)


def temp_password() -> str:
    a = string.ascii_letters + string.digits
    while True:
        p = "".join(secrets.choice(a) for _ in range(14)) + secrets.choice("!@#%*-") + secrets.choice(string.digits)
        if not password_problems(p):
            return p


def admin_reset(s, admin: User, user_id: int) -> dict:
    u = s.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    if u.id == admin.id:
        raise HTTPException(403, "Use 'Change password' for your own account.")
    c = cred_for(s, u)
    pw = temp_password()
    u.password_hash = hash_password(pw)
    c.token_version += 1; c.must_change = True; c.failed_count = 0; c.locked_until = None
    s.commit()
    audit.log("auth.password_reset_by_admin", f"{admin.name} <{admin.email}>", admin.role, f"user:{u.id}", {"username": c.username})
    return {"user_id": u.id, "username": c.username, "temporary_password": pw,
            "note": "Shown once. Give it to the person over a trusted channel; they must change it at first sign-in."}


def sign_out_everywhere(s, u: User) -> None:
    c = cred_for(s, u); c.token_version += 1; s.commit()
    audit.log("auth.signout_everywhere", f"{u.name} <{u.email}>", u.role, f"user:{u.id}")


# ------------------------------------------------------------------ first administrator
def admin_count(s) -> int:
    return s.query(User).filter(User.role == "admin").count()


def bootstrap_from_env() -> None:
    un = os.environ.get("SEALCHECK_BOOTSTRAP_ADMIN_USERNAME", "").strip().lower()
    pw = os.environ.get("SEALCHECK_BOOTSTRAP_ADMIN_PASSWORD", "")
    if not un or not pw:
        return
    with SessionLocal() as s:
        if s.query(UserCredential).filter_by(username=un).first():
            return  # never overwrite an existing account's password from the environment
        if not USERNAME.match(un) or password_problems(pw, un):
            audit.log("access.bootstrap_admin_refused", "system", "system", "auth", {"reason": "username or password fails policy"})
            return
        email = os.environ.get("SEALCHECK_BOOTSTRAP_ADMIN_EMAIL", "").strip().lower() or f"{un}@admin.invalid"
        if s.query(User).filter(User.email == email).first():
            email = f"{un}+{secrets.token_hex(3)}@admin.invalid"
        u = User(email=email, name="Administrator", title="System administrator", role="admin", password_hash=hash_password(pw), avatar_seed=un)
        s.add(u); s.flush()
        s.add(UserCredential(user_id=u.id, username=un, failed_count=0, token_version=0, must_change=False, pw_changed_at=now()))
        s.add(UserProfile(user_id=u.id, full_name="Administrator", requested_role="admin", status="approved",
                          decided_by="bootstrap (SEALCHECK_BOOTSTRAP_ADMIN_USERNAME)", decided_at=now()))
        try:
            s.commit()
        except Exception:  # another cold start won the race
            s.rollback(); return
        audit.log("access.bootstrap_admin", "system", "system", f"user:{u.id}", {"username": un})


class SetupIn(BaseModel):
    full_name: str = Field(min_length=3, max_length=120)
    username: str = Field(min_length=3, max_length=32)
    email: str = Field(min_length=5, max_length=200)
    password: str = Field(max_length=256)
    confirm: str = Field(max_length=256)


def first_run_setup(b: SetupIn, ip: str) -> dict:
    un, em = b.username.strip().lower(), b.email.strip().lower()
    errs = {}
    if not USERNAME.match(un):
        errs["username"] = "3-32 characters: lower-case letters, digits, '.', '_' or '-'."
    if not EMAIL.match(em):
        errs["email"] = "Enter a valid email address."
    if b.password != b.confirm:
        errs["confirm"] = "The two passwords do not match."
    pp = password_problems(b.password, un, em)
    if pp:
        errs["password"] = " ".join(pp)
    if errs:
        raise HTTPException(422, {"message": "Please correct the highlighted fields.", "fields": errs})
    with SessionLocal() as s:
        from .db import IS_PG
        from sqlalchemy import text
        if IS_PG:
            s.execute(text("SELECT pg_advisory_xact_lock(726356)"))
        if admin_count(s):
            raise HTTPException(409, "Setup is already complete. Sign in instead.")
        if s.query(UserCredential).filter_by(username=un).first() or s.query(User).filter(User.email == em).first():
            raise HTTPException(409, "That username or email cannot be used.")
        u = User(email=em, name=_clean(b.full_name), title="System administrator", role="admin", password_hash=hash_password(b.password), avatar_seed=un)
        s.add(u); s.flush()
        s.add(UserCredential(user_id=u.id, username=un, failed_count=0, token_version=0, must_change=False, pw_changed_at=now()))
        s.add(UserProfile(user_id=u.id, full_name=u.name, requested_role="admin", status="approved", decided_by="first-run setup", decided_at=now()))
        s.commit(); s.refresh(u)
        audit.log("access.first_run_admin", f"{u.name} <{u.email}>", "admin", f"user:{u.id}", {"username": un}, ip=ip)
        from .main import user_out
        return {"token": token_for(s, u), "user": user_out(u)}
