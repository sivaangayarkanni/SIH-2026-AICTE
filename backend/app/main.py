"""SealCheck API (FastAPI). Zero-trust AI compliance platform prototype for AICTE (SIH26261)."""
import logging
import json, os, shutil, tempfile, time
from collections import defaultdict, deque
from datetime import datetime, timedelta
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import networkx as nx
from . import audit, service, reports, qa
from .config import AUTH_MODE, SESSION_IDLE_MIN, IS_PROD, ENV
from . import sandbox
from . import oidc
from . import storage, google_auth, accounts
from .config import FRONTEND_DIST, SAMPLES_DIR, TEMPLATES_DIR, BACKEND_DIR, JOB_TOKEN_TTL_S, LLM_API_KEY, DATA_DIR
from .db import (engine, SessionLocal, init_db, User, College, Application, Document, DocumentVersion, Job, Evidence, PiiVault, AuditLog, Override, Notification, UserProfile, now)
from .security import (issue_jwt, decode_jwt, issue_job_token, verify_job_token, TokenError, kms,
                       job_token_key)
from .events import notify_event
from .rules_bundle import load_rules, verify_bundle, RuleBundleError
from .pipeline import gateway, rule_engine, policy

from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(_app):
    import asyncio
    _app.state.draining = False
    init_db()
    accounts.bootstrap_from_env()
    if sandbox.active_backend() == "process":
        logging.getLogger("sealcheck").warning("SANDBOX: bubblewrap unavailable -> 'process' fallback (rlimits + Python socket guard only). "
                                           "Development only; ENV=production refuses this mode.")
    from . import notify
    notify.start_retry_loop(int(os.environ.get("NOTIFY_RETRY_S", "30")))
    service.resume_queued()
    task = None
    interval = int(os.environ.get("INTEGRITY_INTERVAL_S", "0"))
    if interval > 0:
        from .storage import integrity_check
        async def loop():
            while True:
                await asyncio.sleep(interval)
                def run():
                    with SessionLocal() as s2:
                        integrity_check(s2)
                await asyncio.to_thread(run)
        task = asyncio.create_task(loop())
    wf_task = None
    wf_interval = int(os.environ.get("WF_SCHEDULER_S", "0") or 0)
    if wf_interval > 0:   # dev scheduler loop (production uses Vercel Cron -> /api/cron/evaluate)
        from . import workflow
        async def wf_loop():
            while True:
                await asyncio.sleep(wf_interval)
                try:
                    await asyncio.to_thread(workflow.evaluate, None, "dev-loop")
                except Exception:
                    logging.getLogger("sealcheck").exception("workflow evaluation failed")
        wf_task = asyncio.create_task(wf_loop())
    yield
    if wf_task:
        wf_task.cancel()
    _app.state.draining = True  # graceful shutdown: readiness goes 503, then in-flight jobs finish
    if task:
        task.cancel()
    for _ in range(300):  # wait up to 30s for in-flight jobs (k8s terminationGracePeriodSeconds should exceed this)
        if not service._inflight:
            break
        await asyncio.sleep(0.1)


app = FastAPI(title="SealCheck API", version="1.0.0", lifespan=lifespan,
              description="Zero-Trust AI Compliance Platform for AICTE — SIH26261 prototype. All demo data is synthetic.")
from . import ops  # noqa: E402
ops.fail_fast_if_insecure(IS_PROD)
app.add_middleware(CORSMiddleware, allow_origins=[o for o in os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",") if o],
                   allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
                   allow_credentials=True, expose_headers=["X-Request-ID"])

ROLES = ["college", "officer", "senior_officer", "evc_member", "admin"]
ROLE_LABEL = {"pending": "Awaiting approval", "college": "College", "officer": "Scrutiny / Regional Officer", "senior_officer": "Senior / Bureau Officer",
              "evc_member": "EVC Member", "admin": "Administrator"}


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    if request.url.path.startswith(("/docs", "/redoc", "/openapi")):
        return resp
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Content-Security-Policy"] = ("default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
                                               "script-src 'self'; connect-src 'self'" + (f" {oidc.ISSUER}" if AUTH_MODE == "oidc" and oidc.ISSUER else "") + "; font-src 'self' data:; worker-src 'self' blob:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'" + (f" {oidc.ISSUER}" if AUTH_MODE == "oidc" and oidc.ISSUER else ""))
    return resp


ops.install(app, IS_PROD)


# ---------------- auth ----------------
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def current_user(request: Request, s=Depends(db)) -> User:
    h = request.headers.get("authorization", "")
    tok = h[7:] if h.lower().startswith("bearer ") else request.query_params.get("token")
    if not tok:
        raise HTTPException(401, "Please sign in.")
    if AUTH_MODE == "oidc":
        try:
            claims = oidc.validate(tok)
        except oidc.OIDCError as e:
            raise HTTPException(401, f"Sign-in rejected: {e}")
        return _oidc_user(s, claims)
    try:
        claims = decode_jwt(tok)
    except Exception:
        raise HTTPException(401, "Your session has expired. Please sign in again.")
    u = s.get(User, int(claims["sub"]))
    if not u:
        raise HTTPException(401, "Unknown user")
    c = s.get(accounts.UserCredential, u.id)
    if c is not None and int(claims.get("tv", 0)) != c.token_version:
        raise HTTPException(401, "You were signed out (password or role changed, or 'sign out everywhere'). Please sign in again.")
    if c is not None and c.must_change and request.url.path not in MUST_CHANGE_OK:
        raise HTTPException(403, "You must change your temporary password before continuing.")
    if u.role == "pending" and request.url.path not in PENDING_OK:
        raise HTTPException(403, "Your account is waiting for onboarding or administrator approval.")
    return u


MUST_CHANGE_OK = {"/api/auth/me", "/api/auth/logout", "/api/auth/password", "/api/auth/logout-all"}
PENDING_OK = {"/api/auth/password", "/api/auth/logout-all", "/api/auth/me", "/api/auth/logout", "/api/auth/profile", "/api/auth/onboarding", "/api/auth/onboarding/options"}


def _oidc_user(s, claims) -> User:
    """Just-in-time provisioning keyed on email; role is re-synced from the IdP on every request."""
    email = (claims.get("email") or "").lower()
    if not email or claims.get("email_verified") is False:
        raise HTTPException(401, "Sign-in rejected: verified email claim required")
    u = s.query(User).filter(User.email == email).first()
    cid = None
    if claims["_role"] == "college":
        code = claims.get(oidc.COLLEGE_CLAIM)
        c = s.query(College).filter(College.code == code).first() if code else None
        if not c:
            raise HTTPException(403, "Your account is not linked to an institution (college_code claim).")
        cid = c.id
    if not u:
        u = User(email=email, name=claims.get("name") or email, title="", role=claims["_role"], college_id=cid,
                 password_hash="!oidc", avatar_seed=email.split("@")[0])
        s.add(u); s.commit()
        audit.log("auth.oidc_provisioned", actor(u), u.role, f"user:{u.id}", {"sub": claims["sub"], "iss": claims["iss"]})
    elif u.role != claims["_role"] or (cid and u.college_id != cid):
        audit.log("auth.role_synced", actor(u), claims["_role"], f"user:{u.id}", {"from": u.role, "to": claims["_role"]})
        u.role, u.college_id = claims["_role"], cid or u.college_id
        s.commit()
    return u


def require(*roles):
    def dep(u: User = Depends(current_user)):
        if u.role not in roles:
            raise HTTPException(403, f"This action needs one of these roles: {', '.join(ROLE_LABEL[r] for r in roles)}.")
        return u
    return dep


def actor(u: User):
    return f"{u.name} <{u.email}>"


def scoped_app(s, app_id: int, u: User) -> Application:
    a = s.get(Application, app_id)
    if not a:
        raise HTTPException(404, "Application not found")
    if u.role == "college" and a.college_id != u.college_id:   # row-level security (ABAC)
        audit.log("access.denied", actor(u), u.role, f"application:{app_id}", {"reason": "row-level scope"})
        raise HTTPException(404, "Application not found")
    if u.role == "evc_member":   # EVC members: read-only, only applications whose visit they are assigned to
        from .workflow import EvcVisit
        if not any(u.id in (v.members_json or []) for v in s.query(EvcVisit).filter(EvcVisit.application_id == a.id).all()):
            raise HTTPException(404, "Application not found")
    return a


def scoped_doc(s, doc_id: int, u: User) -> Document:
    d = s.get(Document, doc_id)
    if not d:
        raise HTTPException(404, "Document not found")
    scoped_app(s, d.application_id, u)
    return d


_attempts = defaultdict(deque)
_signups = defaultdict(deque)


class LoginIn(BaseModel):
    username: str = Field("", max_length=200)   # username or email
    email: str = Field("", max_length=200)      # kept for older clients
    password: str = Field(max_length=256)


def user_out(u: User):
    return {"id": u.id, "email": u.email, "name": u.name, "title": u.title, "role": u.role, "role_label": ROLE_LABEL[u.role],
            "college_id": u.college_id, "college": u.college.name if u.college else None, "avatar_seed": u.avatar_seed,
            "access_status": (u.profile.status if getattr(u, "profile", None) else None)} | _cred_out(u)


def _cred_out(u: User) -> dict:
    from sqlalchemy.orm import object_session
    s = object_session(u)
    c = s.get(accounts.UserCredential, u.id) if s is not None else None
    return {"username": c.username if c else None, "must_change_password": bool(c and c.must_change)}


@app.get("/api/auth/config")
def auth_config():
    return {"mode": AUTH_MODE, "idle_timeout_min": SESSION_IDLE_MIN,
            "oidc": oidc.public_config() if AUTH_MODE == "oidc" else None, "demo_accounts": DEMO_LOGIN,
            "password_login": AUTH_MODE in ("local", "password"), "signup": AUTH_MODE in ("local", "password"), "env": ENV,
            "google": {"enabled": google_auth.configured(),
                       "notice": None if google_auth.configured() else "Google sign-in is not configured yet (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET missing)."},
            "demo_notice": (os.environ.get("SEALCHECK_DEMO_NOTICE") or None) if not IS_PROD else None}


DEMO_LOGIN = ENV == "development" and AUTH_MODE == "local"
PASSWORD_AUTH = AUTH_MODE in ("local", "password")
app.include_router(google_auth.router)


@app.get("/api/auth/onboarding/options")
def onboarding_options(u: User = Depends(current_user)):
    return {"states": google_auth.INDIAN_STATES, "email": u.email, "name": u.name,
            "roles": [{"value": "college", "label": "College / institution representative"},
                      {"value": "officer", "label": "AICTE officer (requires administrator approval)"},
                      {"value": "evc_member", "label": "Expert Visit Committee member (requires administrator approval)"}]}


@app.get("/api/auth/profile")
def get_profile(u: User = Depends(current_user), s=Depends(db)):
    return {"user": user_out(u), "profile": google_auth.profile_out(s.get(UserProfile, u.id))}


@app.post("/api/auth/onboarding")
def onboarding(body: google_auth.OnboardingIn, u: User = Depends(current_user), s=Depends(db)):
    out = google_auth.submit_onboarding(s, u, body)
    s.refresh(u)
    return out | {"user": user_out(u)}



@app.post("/api/auth/login")
def login(body: LoginIn, request: Request, s=Depends(db)):
    if not PASSWORD_AUTH:
        raise HTTPException(403, "Password sign-in is disabled; use single sign-on.")
    ip = request.client.host if request.client else "-"
    q = _attempts[ip]
    while q and q[0] < time.time() - 60:
        q.popleft()
    if len(q) >= 10:
        raise HTTPException(429, "Too many failed sign-in attempts. Wait a minute and try again.")
    try:
        u, c = accounts.password_login(s, body.username or body.email, body.password, ip)
    except HTTPException:
        q.append(time.time())
        raise
    audit.log("auth.login", actor(u), u.role, f"user:{u.id}", {"method": "password", "username": c.username}, ip=ip)
    return {"token": issue_jwt(u, c.token_version), "user": user_out(u), "must_change_password": c.must_change}


@app.post("/api/auth/signup")
def signup(body: accounts.SignupIn, request: Request):
    if not PASSWORD_AUTH:
        raise HTTPException(403, "Sign-up is handled by single sign-on on this server.")
    ip = request.client.host if request.client else "-"
    q = _signups[ip]
    while q and q[0] < time.time() - 3600:
        q.popleft()
    if len(q) >= 10:
        raise HTTPException(429, "Too many sign-ups from this network. Try again later.")
    q.append(time.time())
    return accounts.signup(body, ip)


@app.get("/api/auth/signup/options")
def signup_options(s=Depends(db)):
    from .workflow import active_config
    return {"roles": [{"value": k, "label": v, "needs_approval": k != "college"} for k, v in accounts.SIGNUP_ROLES.items()],
            "states": google_auth.INDIAN_STATES, "regions": [{"code": r["code"], "name": r["name"]} for r in active_config(s)["regions"]],
            "policy": {"min_length": 10, "classes": 3, "breach_check": os.environ.get("PASSWORD_BREACH_CHECK", "off").lower() == "hibp"}}


class PwCheckIn(BaseModel):
    password: str = Field(max_length=256)
    username: str = Field("", max_length=32)
    email: str = Field("", max_length=200)


@app.post("/api/auth/password/check")
def password_check(body: PwCheckIn):
    return {"problems": accounts.password_problems(body.password, body.username, body.email)}


@app.post("/api/auth/password")
def password_change(body: accounts.PasswordChangeIn, u: User = Depends(current_user), s=Depends(db)):
    return {"token": accounts.change_password(s, u, body), "user": user_out(u)}


@app.post("/api/auth/logout-all")
def logout_all(u: User = Depends(current_user), s=Depends(db)):
    accounts.sign_out_everywhere(s, u)
    return {"ok": True}


@app.get("/api/auth/setup")
def setup_status(s=Depends(db)):
    return {"needed": PASSWORD_AUTH and accounts.admin_count(s) == 0}


@app.post("/api/auth/setup")
def setup(body: accounts.SetupIn, request: Request):
    if not PASSWORD_AUTH:
        raise HTTPException(403, "Not available")
    return accounts.first_run_setup(body, request.client.host if request.client else "-")


@app.post("/api/admin/users/{user_id}/reset-password")
def admin_reset_password(user_id: int, u: User = Depends(require("admin")), s=Depends(db)):
    return accounts.admin_reset(s, u, user_id)


class RoleIn(BaseModel):
    role: str
    note: str = Field("", max_length=300)


@app.post("/api/admin/users/{user_id}/role")
def admin_set_role(user_id: int, body: RoleIn, u: User = Depends(require("admin")), s=Depends(db)):
    t = s.get(User, user_id)
    if not t:
        raise HTTPException(404, "User not found")
    if t.id == u.id:
        raise HTTPException(403, "You cannot change your own role.")
    if body.role not in ("officer", "senior_officer", "evc_member", "admin", "pending") and not (body.role == "college" and t.college_id):
        raise HTTPException(422, "Unknown role (college needs a linked institution; approve it from Access requests).")
    prev = t.role
    t.role = body.role
    c = accounts.cred_for(s, t); c.token_version += 1
    s.commit()
    audit.log("access.role_changed", actor(u), u.role, f"user:{t.id}", {"from": prev, "to": body.role, "note": body.note})
    return user_out(t)


@app.get("/api/admin/users")
def admin_users(u: User = Depends(require("admin")), s=Depends(db)):
    creds = {c.user_id: c for c in s.query(accounts.UserCredential).all()}
    t = now()
    return [user_out(x) | {"username": creds[x.id].username if x.id in creds else None,
                           "locked": bool(x.id in creds and creds[x.id].locked_until and creds[x.id].locked_until > t),
                           "last_login_at": creds[x.id].last_login_at.isoformat() if x.id in creds and creds[x.id].last_login_at else None}
            for x in s.query(User).order_by(User.id).all()]


@app.get("/api/auth/me")
def me(u: User = Depends(current_user)):
    return user_out(u)


@app.post("/api/auth/logout")
def logout(request: Request, u: User = Depends(current_user)):
    audit.log("auth.logout", actor(u), u.role, f"user:{u.id}", ip=request.client.host if request.client else "-")
    return {"ok": True, "end_session_endpoint": (oidc.discovery().get("end_session_endpoint") if AUTH_MODE == "oidc" else None)}


@app.get("/api/auth/demo-accounts")
def demo_accounts(s=Depends(db)):
    if not DEMO_LOGIN:
        raise HTTPException(404, "Not available")
    return {"password": "Demo@2026", "note": "Seeded demo accounts for the prototype only.",
            "accounts": [user_out(u) for u in s.query(User).order_by(User.id).all()]}


@app.get("/api/admin/access-requests")
def access_requests(status: str = "pending", u: User = Depends(require("admin")), s=Depends(db)):
    q = s.query(UserProfile)
    if status != "all":
        q = q.filter(UserProfile.status == status)
    return [{"user_id": p.user_id, "email": p.user.email, "role": p.user.role, "created_at": p.created_at.isoformat() if p.created_at else None,
             "decided_by": p.decided_by, **google_auth.profile_out(p)} for p in q.order_by(UserProfile.created_at.desc()).limit(500)]


@app.post("/api/admin/access-requests/{user_id}/approve")
def approve_access(user_id: int, body: google_auth.DecisionIn, u: User = Depends(require("admin")), s=Depends(db)):
    return google_auth.decide(s, u, user_id, True, body)


@app.post("/api/admin/access-requests/{user_id}/reject")
def reject_access(user_id: int, body: google_auth.DecisionIn, u: User = Depends(require("admin")), s=Depends(db)):
    return google_auth.decide(s, u, user_id, False, body)


def _vision_status(vclient):
    b = vclient.BACKEND
    if b == "remote":
        from .vision import remote
        return "remote" if remote.configured() else "remote (VISION_REMOTE_URL/TOKEN missing -> classic)"
    if b == "models":
        return "models" if vclient.available() else "models (unavailable -> classic)"
    return "classic"


# ---------------- meta ----------------
@app.get("/api/health")
def health():
    v = verify_bundle()
    return {"status": "ok", "service": "SealCheck", "version": app.version, "rules_bundle_valid": v["valid"],
            "time": datetime.utcnow().isoformat() + "Z"}


@app.get("/api/meta")
def meta():
    r = load_rules()
    return {"categories": r["categories"], "doc_types": {k: {"label": v["label"], "clause": v["clause"],
                                                             "photo": v.get("photo", False)} for k, v in r["document_types"].items()},
            "statuses": policy.STATUSES, "policy_table": policy.POLICY_TABLE, "stages": service.STAGES,
            "llm_enabled": bool(LLM_API_KEY)}


# ---------------- applications ----------------
def priority(a: Application, ref=None):
    ref = ref or now()
    risk = a.risk_score or 0
    days = (a.deadline - ref).days if a.deadline else 30
    urgency = 100 if days <= 0 else max(0, 100 - days * 100 / 30)
    waited_h = ((ref - a.submitted_at).total_seconds() / 3600) if a.submitted_at else 0
    waiting = min(100, waited_h * 100 / 72)
    score = round(0.5 * risk + 0.3 * urgency + 0.2 * waiting, 1)
    return {"score": score, "risk": risk, "deadline_urgency": round(urgency), "waiting": round(waiting),
            "days_to_deadline": days, "waiting_hours": round(waited_h, 1),
            "formula": "0.5×risk + 0.3×deadline urgency + 0.2×waiting time"}


def readiness(s, a: Application, rules=None):
    rules = rules or load_rules()
    comp = rule_engine.completeness(a.category, [d.doc_type for d in a.documents], rules)
    pts = {"Verified": 1.0, "Verification Pending": 0.5, "Source Unavailable": 0.5, "Manual Review Required": 0.4,
           "Expired": 0.1, "Mismatch Detected": 0.0}
    items, total = [], 0
    for dt in comp["required"]:
        docs = [d for d in a.documents if d.doc_type == dt]
        label = rules["document_types"][dt]["label"]
        if not docs:
            items.append({"doc_type": dt, "label": label, "state": "missing", "message": f"{label} is missing. Upload it to continue."})
            continue
        best = max(docs, key=lambda d: pts.get(d.status, 0))
        total += pts.get(best.status, 0)
        msg = {"Verified": "Verified — no action needed.", "Expired": "Expired — upload a renewed copy.",
               "Mismatch Detected": "Problems found — see highlighted evidence.",
               "Verification Pending": "Being analysed…", "Source Unavailable": "Issuer could not be confirmed — attach issuer reference.",
               "Manual Review Required": "Needs officer review — check findings."}.get(best.status, best.status)
        items.append({"doc_type": dt, "label": label, "state": best.status, "message": msg, "document_id": best.id})
    score = round(100 * total / max(1, len(comp["required"])))
    return {"score": score, "items": items, "missing": comp["missing"], "complete": comp["complete"],
            "explanation": f"{sum(1 for i in items if i['state']=='Verified')} of {len(items)} required documents verified; "
                           f"{len(comp['missing'])} missing. Score = verified 100% · pending 50% · review 40% · expired 10% · mismatch 0%."}


def app_out(s, a: Application, detail=False):
    d = {"id": a.id, "ref": a.ref, "college_id": a.college_id, "college": a.college.name, "college_city": a.college.city,
         "category": a.category, "category_label": next((c["label"] for c in load_rules()["categories"] if c["id"] == a.category), a.category),
         "title": a.title, "academic_year": a.academic_year, "status": a.status, "risk_score": a.risk_score,
         "deadline": a.deadline.isoformat() if a.deadline else None, "created_at": a.created_at.isoformat(),
         "submitted_at": a.submitted_at.isoformat() if a.submitted_at else None, "decision": a.decision,
         "decision_reason": a.decision_reason, "decided_at": a.decided_at.isoformat() if a.decided_at else None,
         "documents_count": len(a.documents), "priority": priority(a)}
    if detail:
        d["documents"] = [doc_out(s, x) for x in a.documents]
        d["readiness"] = readiness(s, a)
        d["overrides"] = [ov_out(s, o) for o in s.query(Override).filter_by(application_id=a.id).order_by(Override.id.desc())]
        d["guidance"] = a.guidance_json
        d["decision_by"] = user_out(s.get(User, a.decision_by)) if a.decision_by else None
    return d


def doc_out(s, d: Document, full=False):
    job = s.query(Job).filter_by(document_id=d.id).order_by(Job.id.desc()).first()
    an = d.analysis_json or {}
    o = {"id": d.id, "application_id": d.application_id, "doc_type": d.doc_type, "label": an.get("label") or d.doc_type,
         "filename": d.filename, "mime": d.mime, "size": d.size, "sha256": d.sha256, "status": d.status,
         "risk_score": d.risk_score, "lab_type": d.lab_type, "created_at": d.created_at.isoformat(),
         "job": {"id": job.id, "status": job.status, "stage": job.stage, "progress": job.progress_json, "error": job.error,
                 "duration_ms": job.duration_ms, "token_jti": job.token_jti} if job else None,
         "decision": an.get("decision"), "findings_count": len([f for f in an.get("findings", []) if f.get("outcome") != "pass"])}
    if full:
        o.update({"findings": an.get("findings", []), "agents": an.get("agents", []), "modules": an.get("modules", {}),
                  "pages": an.get("pages", []), "facts": an.get("facts", {}), "pii_masked": an.get("pii_masked", []),
                  "error": an.get("error"),
                  "versions": [{"version": v.version_no, "sha256": v.sha256, "size": v.size, "created_at": v.created_at.isoformat(),
                                "worm": not os.access(v.stored_path, os.W_OK)} for v in d.versions]})
    return o


def ov_out(s, o: Override):
    rq, ap = s.get(User, o.requested_by), s.get(User, o.approved_by) if o.approved_by else None
    d = s.get(Document, o.document_id)
    return {"id": o.id, "application_id": o.application_id, "document_id": o.document_id,
            "document": (d.analysis_json or {}).get("label", d.doc_type) if d else None, "proposed_status": o.proposed_status,
            "justification": o.justification, "status": o.status, "requested_by": user_out(rq),
            "approved_by": user_out(ap) if ap else None, "approver_note": o.approver_note,
            "created_at": o.created_at.isoformat(), "decided_at": o.decided_at.isoformat() if o.decided_at else None}


@app.get("/api/applications")
def list_apps(u: User = Depends(current_user), s=Depends(db)):
    q = s.query(Application)
    if u.role == "college":
        q = q.filter(Application.college_id == u.college_id)
    if u.role == "evc_member":
        from .workflow import EvcVisit
        ids = [v.application_id for v in s.query(EvcVisit).all() if u.id in (v.members_json or [])]
        q = q.filter(Application.id.in_(ids or [0]))
    return [app_out(s, a) for a in q.order_by(Application.id.desc()).all()]


class AppIn(BaseModel):
    category: str
    title: str | None = None


@app.post("/api/applications")
def create_app(body: AppIn, u: User = Depends(require("college")), s=Depends(db)):
    cats = {c["id"]: c for c in load_rules()["categories"]}
    if body.category not in cats:
        raise HTTPException(400, "Unknown application category")
    n = s.query(Application).count() + 1
    a = Application(ref=f"AICTE-26-{u.college.code}-{n:04d}", college_id=u.college_id, category=body.category,
                    title=body.title or cats[body.category]["label"], status="Draft", deadline=now() + timedelta(days=21))
    s.add(a); s.commit()
    audit.log("application.created", actor(u), u.role, f"application:{a.id}", {"category": body.category})
    return app_out(s, a, True)


@app.get("/api/applications/{app_id}")
def get_app(app_id: int, u: User = Depends(current_user), s=Depends(db)):
    return app_out(s, scoped_app(s, app_id, u), True)


@app.post("/api/applications/{app_id}/submit")
def submit_app(app_id: int, u: User = Depends(require("college")), s=Depends(db)):
    a = scoped_app(s, app_id, u)
    if not a.documents:
        raise HTTPException(400, "Upload at least one document before submitting.")
    a.submitted_at = a.submitted_at or now()
    service.refresh_application(s, a.id)
    audit.log("application.submitted", actor(u), u.role, f"application:{a.id}")
    s.add(Notification(role="officer", message=f"New submission {a.ref} from {a.college.name}", link=f"/applications/{a.id}"))
    s.commit()
    from . import workflow
    workflow.route_application(s, a, actor(u), u.role)
    from .wf_api import notify_mismatches
    notify_mismatches(s, a, "system (cross-document check on submit)", "system")
    s.refresh(a)
    return app_out(s, a, True)


@app.post("/api/applications/{app_id}/documents")
async def upload(app_id: int, request: Request, file: UploadFile = File(...), doc_type: str = Form(...),
                 lab_type: str | None = Form(None), u: User = Depends(require("college")), s=Depends(db)):
    a = scoped_app(s, app_id, u)
    if a.decision:
        raise HTTPException(409, "A decision has been recorded; uploads are closed for this application.")
    rules = load_rules()
    if doc_type not in rules["document_types"]:
        raise HTTPException(400, "Unknown document type")
    data = await file.read()
    try:
        g = gateway.inspect_upload(data, file.filename or "upload")
    except gateway.GatewayReject as e:
        audit.log("upload.blocked", actor(u), u.role, f"application:{a.id}", {"reason": e.message, "file": file.filename})
        raise HTTPException(e.code, e.message)
    is_photo = rules["document_types"][doc_type].get("photo", False)
    if is_photo and g["mime"] == "application/pdf" or (not is_photo and g["mime"] != "application/pdf"):
        raise HTTPException(415, "Lab photos must be JPEG/PNG; all other documents must be PDF.")
    ext = {"application/pdf": "pdf", "image/jpeg": "jpg", "image/png": "png"}[g["mime"]]
    path = service.store_original(data, g["sha256"], ext)
    d = Document(application_id=a.id, doc_type=doc_type, filename=os.path.basename(file.filename or f"upload.{ext}")[:200],
                 mime=g["mime"], size=g["size"], sha256=g["sha256"], status="Verification Pending", lab_type=lab_type)
    s.add(d); s.flush()
    s.add(DocumentVersion(document_id=d.id, version_no=1, sha256=g["sha256"], stored_path=path, size=g["size"]))
    if a.status == "Draft":
        a.status = "Verification Pending"
    s.commit()
    audit.log("document.uploaded", actor(u), u.role, f"document:{d.id}",
              {"sha256": g["sha256"], "mime": g["mime"], "size": g["size"], "scan": g["malware_scan"]["engine"]},
              ip=request.client.host if request.client else "")
    jid = service.enqueue(d.id)
    return {"document": doc_out(s, d), "gateway": g, "job_id": jid}


@app.get("/api/documents/{doc_id}")
def get_doc(doc_id: int, u: User = Depends(current_user), s=Depends(db)):
    return doc_out(s, scoped_doc(s, doc_id, u), full=True)


@app.post("/api/documents/{doc_id}/reanalyze")
def reanalyze(doc_id: int, u: User = Depends(require("officer", "senior_officer", "admin")), s=Depends(db)):
    d = scoped_doc(s, doc_id, u)
    audit.log("document.reanalyze", actor(u), u.role, f"document:{d.id}")
    return {"job_id": service.enqueue(d.id)}


@app.get("/api/documents/{doc_id}/page/{page}")
def page_image(doc_id: int, page: int, u: User = Depends(current_user), s=Depends(db)):
    d = scoped_doc(s, doc_id, u)
    san = storage.materialize((d.analysis_json or {}).get("sanitized_path"))
    if not san or not Path(san).exists():
        raise HTTPException(404, "Page not available yet")
    if d.mime != "application/pdf":
        return FileResponse(san, media_type=d.mime)
    return FileResponse(reports.page_png(san, page, d.id), media_type="image/png")


class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=400)


@app.post("/api/documents/{doc_id}/ask")
def ask(doc_id: int, body: AskIn, u: User = Depends(require("officer", "senior_officer", "admin")), s=Depends(db)):
    d = scoped_doc(s, doc_id, u)
    an = d.analysis_json or {}
    res = qa.answer(body.question, an.get("lines", []), an.get("facts", {}), an.get("label", d.doc_type), an.get("findings", []), d.status)
    audit.log("assistant.question", actor(u), u.role, f"document:{d.id}", {"q": body.question[:200]})
    return res


def _audit_for(s, targets):
    return s.query(AuditLog).filter(AuditLog.target.in_(targets)).order_by(AuditLog.id).all()


@app.get("/api/documents/{doc_id}/evidence-packet.pdf")
def evidence_packet(doc_id: int, u: User = Depends(current_user), s=Depends(db)):
    d = scoped_doc(s, doc_id, u)
    an = d.analysis_json or {}
    rows = _audit_for(s, [f"document:{d.id}", f"application:{d.application_id}"])
    pdf = reports.evidence_packet(d, d.application, an, rows, storage.materialize(an.get("sanitized_path")) if d.mime == "application/pdf" else None)
    audit.log("evidence.downloaded", actor(u), u.role, f"document:{d.id}")
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="evidence_packet_doc{d.id}.pdf"'})


# ---------------- officer ----------------
@app.get("/api/officer/queue")
def queue(u: User = Depends(require("officer", "senior_officer", "admin")), s=Depends(db)):
    apps = s.query(Application).filter(Application.submitted_at.isnot(None)).all()
    out = [app_out(s, a) for a in apps]
    out.sort(key=lambda x: (x["decision"] is not None, -x["priority"]["score"]))
    return out


class DecisionIn(BaseModel):
    decision: str  # approve | reject | request_changes
    reason: str = Field(min_length=5, max_length=4000)


@app.post("/api/applications/{app_id}/decision")
def decide(app_id: int, body: DecisionIn, u: User = Depends(require("officer", "senior_officer")), s=Depends(db)):
    a = scoped_app(s, app_id, u)
    if body.decision not in ("approve", "reject", "request_changes"):
        raise HTTPException(400, "Unknown decision")
    if a.decision in ("Approved", "Rejected"):
        raise HTTPException(409, "A final decision already exists.")
    if not a.submitted_at:
        raise HTTPException(409, "This application is still a draft; the college has not submitted it yet.")
    if any(d.status == "Verification Pending" for d in a.documents):
        raise HTTPException(409, "Some documents are still being analysed.")
    flagged = [d for d in a.documents if d.status == "Mismatch Detected"]
    if body.decision == "approve" and flagged:
        ok = s.query(Override).filter(Override.application_id == a.id, Override.status == "approved").all()
        cleared = {o.document_id for o in ok}
        pending = [d for d in flagged if d.id not in cleared]
        if pending:
            audit.log("decision.blocked", actor(u), u.role, f"application:{a.id}", {"reason": "two-person override required"})
            raise HTTPException(409, "This application has documents flagged as possible forgeries. Approval needs a "
                                     "two-person security override (Officer + a different Senior Officer).")
    from . import workflow
    w = s.get(workflow.AppWorkflow, a.id)
    if w and body.decision in ("approve", "reject") and w.state != "awaiting_decision":
        audit.log("decision.blocked", actor(u), u.role, f"application:{a.id}", {"reason": "workflow stage", "stage": w.current_stage, "state": w.state})
        raise HTTPException(409, f"The workflow is at '{workflow.stage_label(workflow.active_config(s), w.current_stage)}' ({w.state}). "
                                 "Complete the configured stages before the final decision.")
    a.decision = {"approve": "Approved", "reject": "Rejected", "request_changes": "Changes Requested"}[body.decision]
    a.decision_reason, a.decision_by, a.decided_at = body.reason, u.id, now()
    s.commit()
    audit.log("decision.recorded", actor(u), u.role, f"application:{a.id}", {"decision": a.decision, "reason": body.reason[:300]})
    workflow.on_decision(s, a, actor(u), u.role)
    s.add(Notification(college_id=a.college_id, message=f"{a.ref}: {a.decision}", link=f"/applications/{a.id}"))
    s.commit()
    return app_out(s, a, True)


@app.post("/api/applications/{app_id}/reopen")
def reopen(app_id: int, u: User = Depends(require("college")), s=Depends(db)):
    a = scoped_app(s, app_id, u)
    if a.decision != "Changes Requested":
        raise HTTPException(409, "Only applications with requested changes can be reopened.")
    a.decision = None; a.decided_at = None
    s.commit(); service.refresh_application(s, a.id)
    audit.log("application.reopened", actor(u), u.role, f"application:{a.id}")
    return app_out(s, a, True)


GUIDE = {
    "F-HID": "Remove all hidden / invisible text. Re-export the document directly from the issuing authority's original file.",
    "F-OVL": "Do not cover text with white boxes. Obtain a correct copy from the issuer instead of editing the PDF.",
    "F-DSC-01": "The signed file was altered. Download the original DSC-signed file again and upload it without changes.",
    "F-DSC-02": "Content was added after signing. Upload the signed original; any correction must be re-signed by the issuer.",
    "F-DSC-03": "The signing certificate has expired. Ask the issuer to re-sign with a valid Digital Signature Certificate (DSC).",
    "F-DSC-04": "Use a certificate from a recognised Certifying Authority.",
    "F-EDT": "The document was edited after creation. Upload the unedited original.",
    "F-MET": "Upload the authority-issued original rather than a copy saved by an editing tool.",
    "R-": "Provide the missing field / renewed certificate cited by the rule.",
    "S-CDR": "Remove scripts, attachments and auto-run actions from the PDF before uploading.",
    "I-DUP": "Upload original, recent, geotagged photos of your own laboratory.",
    "I-GEO": "Enable location on the camera so photos carry campus GPS coordinates.",
    "C-PAN": "Confirm the faculty member works only at your institution; remove them otherwise.",
    "C-HASH": "Upload your institution's own document, not a copy of another institution's file.",
    "C-IMG": "Replace photos that also appear in another institution's submission.",
}


def _guidance(rule_id: str, f: dict):
    if rule_id.startswith("R-") and f.get("expired"):
        return "This document has expired. Upload a renewed copy with a future validity date."
    for k, v in GUIDE.items():
        if rule_id.startswith(k):
            return v
    return "Review the highlighted area and upload a corrected document."


class RejectIn(BaseModel):
    reason: str = Field(min_length=10, max_length=4000)


@app.post("/api/applications/{app_id}/rejection-helper")
def rejection_helper(app_id: int, body: RejectIn, u: User = Depends(require("officer", "senior_officer")), s=Depends(db)):
    a = scoped_app(s, app_id, u)
    items = []
    for d in a.documents:
        for f in (d.analysis_json or {}).get("findings", []):
            if f.get("outcome") in ("fail", "warn"):
                items.append({"document_id": d.id, "document": (d.analysis_json or {}).get("label", d.doc_type),
                              "rule_id": f.get("rule_id"), "issue": f["title"], "action": _guidance(f.get("rule_id", ""), f),
                              "page": f.get("page"), "severity": f.get("severity")})
    for m in readiness(s, a)["missing"]:
        items.append({"document_id": None, "document": load_rules()["document_types"][m]["label"], "rule_id": "R-COMPLETE",
                      "issue": "Missing document", "action": f"Upload the {load_rules()['document_types'][m]['label']}.",
                      "page": None, "severity": "medium"})
    a.guidance_json = {"reason": body.reason, "items": items, "by": u.name, "at": now().isoformat(),
                       "engine": "rule-based guidance"}
    s.commit()
    audit.log("rejection_helper.generated", actor(u), u.role, f"application:{a.id}", {"items": len(items)})
    return a.guidance_json


@app.get("/api/applications/{app_id}/rejection.pdf")
def rejection_pdf(app_id: int, u: User = Depends(current_user), s=Depends(db)):
    a = scoped_app(s, app_id, u)
    g = a.guidance_json
    if not g:
        raise HTTPException(404, "No correction guidance has been generated yet.")
    docs = []
    for d in a.documents:
        an = d.analysis_json or {}
        fs = [{**f, "guidance": _guidance(f.get("rule_id", ""), f)} for f in an.get("findings", [])
              if f.get("outcome") in ("fail", "warn") and f.get("page")]
        if fs and d.mime == "application/pdf":
            docs.append((d, storage.materialize(an.get("sanitized_path")), fs))
    pdf = reports.rejection_pdf(a, g["items"], g["reason"], docs)
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="corrections_{a.ref}.pdf"'})


@app.get("/api/applications/{app_id}/decision.pdf")
def decision_pdf(app_id: int, u: User = Depends(current_user), s=Depends(db)):
    a = scoped_app(s, app_id, u)
    if not a.decision:
        raise HTTPException(404, "No decision yet.")
    ov = s.query(Override).filter_by(application_id=a.id, status="approved").first()
    head = audit.verify_chain(s).get("head", "-")
    pdf = reports.decision_letter(a, s.get(User, a.decision_by), head, ov)
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="decision_{a.ref}.pdf"'})


# ---------------- two-person override ----------------
class OverrideIn(BaseModel):
    document_id: int
    justification: str
    proposed_status: str = "Verified"


@app.post("/api/applications/{app_id}/overrides")
def request_override(app_id: int, body: OverrideIn, u: User = Depends(require("officer", "senior_officer")), s=Depends(db)):
    a = scoped_app(s, app_id, u)
    d = s.get(Document, body.document_id)
    if not d or d.application_id != a.id:
        raise HTTPException(404, "Document not in this application")
    if d.status != "Mismatch Detected":
        raise HTTPException(400, "Overrides apply only to documents flagged as possible forgeries (Mismatch Detected).")
    if len(body.justification.strip()) < 20:
        raise HTTPException(422, "Justification must be at least 20 characters.")
    if s.query(Override).filter_by(document_id=d.id, status="pending").first():
        raise HTTPException(409, "An override request is already pending for this document.")
    o = Override(application_id=a.id, document_id=d.id, requested_by=u.id, justification=body.justification.strip(),
                 proposed_status=body.proposed_status)
    s.add(o); s.commit()
    audit.log("override.requested", actor(u), u.role, f"application:{a.id}", {"override": o.id, "document": d.id,
                                                                           "justification": o.justification})
    s.add(Notification(role="senior_officer", message=f"Override #{o.id} awaits your approval ({a.ref})", link="/overrides"))
    notify_event("override_requested", {"actor": actor(u), "target": f"{a.ref} override #{o.id}"})
    s.commit()
    return ov_out(s, o)


@app.get("/api/overrides")
def list_overrides(u: User = Depends(require("officer", "senior_officer", "admin")), s=Depends(db)):
    return [ov_out(s, o) for o in s.query(Override).order_by(Override.id.desc()).all()]


class ApproveIn(BaseModel):
    note: str = Field(min_length=5, max_length=2000)


def _decide_override(oid, body, u, s, approve: bool):
    o = s.get(Override, oid)
    if not o:
        raise HTTPException(404, "Override not found")
    if o.status != "pending":
        raise HTTPException(409, "This override has already been decided.")
    if o.requested_by == u.id:
        audit.log("override.self_approval_blocked", actor(u), u.role, f"application:{o.application_id}", {"override": o.id})
        raise HTTPException(403, "Separation of duties: the officer who requested an override cannot approve it.")
    o.status = "approved" if approve else "rejected"
    o.approved_by, o.approver_note, o.decided_at = u.id, body.note, now()
    if approve:
        d = s.get(Document, o.document_id)
        an = dict(d.analysis_json or {})
        an["override"] = {"id": o.id, "original_status": d.status, "by": [o.requested_by, u.id]}
        d.analysis_json = an
        d.status = o.proposed_status
    s.commit()
    service.refresh_application(s, o.application_id)
    audit.log("override." + o.status, actor(u), u.role, f"application:{o.application_id}", {"override": o.id, "note": body.note})
    return ov_out(s, o)


@app.post("/api/overrides/{oid}/approve")
def approve_override(oid: int, body: ApproveIn, u: User = Depends(require("senior_officer")), s=Depends(db)):
    return _decide_override(oid, body, u, s, True)


@app.post("/api/overrides/{oid}/reject")
def reject_override(oid: int, body: ApproveIn, u: User = Depends(require("senior_officer")), s=Depends(db)):
    return _decide_override(oid, body, u, s, False)


# ---------------- 3A readiness: pre-check (file NOT stored) ----------------
@app.post("/api/readiness/precheck")
async def precheck(file: UploadFile = File(...), doc_type: str = Form(...), u: User = Depends(current_user)):
    data = await file.read()
    try:
        g = gateway.inspect_upload(data, file.filename or "x")
    except gateway.GatewayReject as e:
        raise HTTPException(e.code, e.message)
    rules = load_rules()
    if doc_type not in rules["document_types"]:
        raise HTTPException(400, "Unknown document type")
    tmp = tempfile.mkdtemp(prefix="precheck-")
    try:
        ext = "pdf" if g["mime"] == "application/pdf" else "jpg"
        src = os.path.join(tmp, f"in.{ext}")
        Path(src).write_bytes(data)
        token, _ = issue_job_token(0, 0)
        spec = {"token": token, "token_key": job_token_key().hex(), "job_id": 0, "document_id": 0, "file_path": src,
                "sanitized_path": os.path.join(tmp, f"san.{ext}"), "mime": g["mime"], "doc_type": doc_type,
                "trust_dir": str(service.TRUST_DIR), "backend_dir": str(BACKEND_DIR), "candidates": []}
        from . import sandbox
        env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(BACKEND_DIR), "HOME": tmp, "LANG": "C.UTF-8",
               "SEALCHECK_SANDBOX": sandbox.active_backend()}
        env.update({k: os.environ[k] for k in ("SEALCHECK_WORKER_SYSPATH", "SEALCHECK_DATA_DIR") if os.environ.get(k)})
        p = sandbox.popen({"scratch": tmp, "ro": [str(service.TRUST_DIR)], "rw_files": []}, env)
        out, _err = p.communicate(json.dumps(spec), timeout=90)
        msgs = [json.loads(l) for l in out.splitlines() if l.startswith("{")]
        final = next((m for m in msgs if m["stage"] == "final"), None)
        if not final:
            raise HTTPException(500, "Pre-check failed: " + (next((m.get("error") for m in msgs if m.get("error")), "worker error")))
        ext_msg = next((m for m in msgs if m["stage"] == "extract"), {})
        a4 = next((m for m in msgs if m["stage"] == "4A" and m["status"] == "done"), {}).get("result") or {}
        findings = final["findings"]
        dec = policy.decide(findings)
        sigs = [x for x in a4.get("signatures", []) if x.get("signer")]
        guard = None
        if sigs and any(not x.get("covers_whole_file") for x in sigs):
            guard = "This file is digitally signed but was modified after signing. Do not edit signed files — upload the original you received from the issuer."
        elif sigs:
            guard = "Signed file detected. Upload it exactly as received; any edit will break the digital signature."
        return {"stored": False, "note": "Pre-check only — this file was analysed in a temporary sandbox folder and deleted immediately.",
                "gateway": {k: g[k] for k in ("mime", "size", "sha256")}, "predicted_status": dec["status"],
                "risk_score": dec["risk_score"], "findings": findings, "facts": ext_msg.get("facts", {}),
                "text_preview": (ext_msg.get("text") or "")[:1500], "signed_file_guard": guard,
                "tips": [_guidance(f["rule_id"], f) for f in findings if f.get("outcome") in ("fail", "warn")][:6]}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@app.get("/api/templates")
def templates():
    return [{"name": p.name, "size": p.stat().st_size} for p in sorted(TEMPLATES_DIR.glob("*")) if p.is_file()]


@app.get("/api/templates/{name}")
def template_file(name: str):
    p = TEMPLATES_DIR / os.path.basename(name)
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, filename=p.name)


@app.get("/api/samples")
def samples():
    if IS_PROD:
        return []  # synthetic sample files are a development aid only
    man = SAMPLES_DIR / "manifest.json"
    return json.loads(man.read_text()) if man.exists() else []


@app.get("/api/samples/{name}")
def sample_file(name: str):
    if IS_PROD:
        raise HTTPException(404, "Not available")
    p = SAMPLES_DIR / os.path.basename(name)
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, filename=p.name)


# ---------------- 4D collusion graph ----------------
@app.get("/api/collusion/graph")
def collusion_graph(u: User = Depends(require("officer", "senior_officer", "admin")), s=Depends(db)):
    G = nx.Graph()
    for c in s.query(College).all():
        G.add_node(f"college:{c.id}", kind="college", label=c.name, city=c.city)
    for d in s.query(Document).all():
        an = d.analysis_json or {}
        cid = d.application.college_id
        for f in an.get("findings", []):
            if f.get("rule_id") in ("I-DUP-01", "I-DUP-02") and f.get("match"):
                m = f["match"]
                lbl = (f"Same lab photo (pHash Δ{m['phash_distance']}, {m['orb']['inliers']} inliers)" if "orb" in m else
                       f"Same scene (DINOv2 cos {m['cosine']:.2f}, {m['local']['inliers']} LightGlue inliers)")
                G.add_edge(f"college:{cid}", f"college:{m['college_id']}", kind="photo", label=lbl, docs=[d.id, m["document_id"]])
    by_bi = defaultdict(set)
    masked = {}
    for p in s.query(PiiVault).filter_by(kind="PAN").all():
        by_bi[p.blind_index].add(p.college_id); masked[p.blind_index] = p.masked
    for bi, cs in by_bi.items():
        if len(cs) > 1:
            n = f"pan:{bi[:10]}"
            G.add_node(n, kind="faculty", label=f"Faculty PAN {masked[bi]}")
            for c in cs:
                G.add_edge(n, f"college:{c}", kind="pan", label="Listed as faculty")
    by_hash = defaultdict(set)
    for d in s.query(Document).all():
        by_hash[d.sha256].add(d.application.college_id)
    for h, cs in by_hash.items():
        if len(cs) > 1:
            n = f"file:{h[:10]}"
            G.add_node(n, kind="file", label=f"Identical file {h[:10]}…")
            for c in cs:
                G.add_edge(n, f"college:{c}", kind="file", label="Submitted")
    comps = [sorted(c) for c in nx.connected_components(G) if len(c) > 1]
    deg = nx.degree_centrality(G) if G.number_of_nodes() else {}
    return {"nodes": [{"id": n, **a, "centrality": round(deg.get(n, 0), 3)} for n, a in G.nodes(data=True)],
            "edges": [{"source": a, "target": b, **e} for a, b, e in G.edges(data=True)],
            "clusters": comps, "summary": {"colleges": sum(1 for _, a in G.nodes(data=True) if a["kind"] == "college"),
                                           "links": G.number_of_edges(), "suspicious_clusters": len(comps)}}


# ---------------- security center ----------------
RBAC = {
    "Create application / upload": ["college"],
    "View own college's applications": ["college"],
    "View all applications": ["officer", "senior_officer", "admin"],
    "Ask document assistant": ["officer", "senior_officer", "admin"],
    "Record decision": ["officer", "senior_officer"],
    "Request security override": ["officer", "senior_officer"],
    "Approve security override (not own)": ["senior_officer"],
    "View collusion graph": ["officer", "senior_officer", "admin"],
    "View audit log": ["officer", "senior_officer", "admin"],
    "Reveal PII (audited)": ["admin"],
    "View rule bundles / system health": ["officer", "senior_officer", "admin"],
}


def active_backends() -> dict:
    from . import notify, storage
    from .llm import LLMClient
    from .vision import client as vclient
    c = LLMClient()
    return {"database": engine.dialect.name + (" + pgvector" if engine.dialect.name == "postgresql" else ""),
            "auth": AUTH_MODE, "sandbox": sandbox.active_backend(), "kms": kms.name, "storage": storage.get_store().name,
            "queue": service.QUEUE_BACKEND, "vision": _vision_status(vclient),
            "llm": c.provider if c.provider != "none" else "off (rule-based)", "notify": ",".join(notify.channels()),
            "revocation": os.environ.get("REVOCATION_CHECK", "off"),
            "issuer_connectors": len(__import__("app.trust", fromlist=["x"]).load_connectors()), "env": ENV}


@app.get("/api/security/overview")
def security_overview(u: User = Depends(current_user), s=Depends(db)):
    jobs = s.query(Job).order_by(Job.id.desc()).limit(8).all()
    return {
        "backends": active_backends(),
        "sandbox": {"mode": {"namespace": "bubblewrap namespaces (no network, read-only root, cap-drop ALL) + seccomp + rlimits",
                             "docker": "Docker --network none --read-only (optionally gVisor runsc)",
                             "process": "Separate OS process (python -I), rlimits, Python socket guard only (dev fallback)"}[sandbox.active_backend()],
                    "backend": sandbox.active_backend(),
                    "cpu_limit_s": sandbox.WORKER_CPU_SECONDS, "memory_limit_mb": sandbox.WORKER_MEMORY_MB,
                    "egress": {"namespace": "No network interfaces in the job's namespace; seccomp blocks non-AF_UNIX socket().",
                               "docker": "Container started with --network none.",
                               "process": "Blocked only at the Python socket layer (weak; dev fallback)."}[sandbox.active_backend()],
                    "recent_jobs": [{"id": j.id, "document_id": j.document_id, "status": j.status, "duration_ms": j.duration_ms,
                                     "token_jti": j.token_jti} for j in jobs]},
        "token_ttl_s": JOB_TOKEN_TTL_S, "rules_bundle": verify_bundle(), "audit_chain": audit.verify_chain(s),
        "rbac": {"roles": [ROLE_LABEL[r] for r in ROLES], "matrix": {k: [ROLE_LABEL[r] for r in v] for k, v in RBAC.items()}},
        "kms": {"provider": {"soft": "Local software KMS (dev only, AES-256-GCM envelope)", "aws": "AWS KMS",
                             "vault": "HashiCorp Vault Transit", "pkcs11": "PKCS#11 HSM"}[kms.name],
                "backend": kms.name, "key_id": kms.key_id,
                "pii_records": s.query(PiiVault).count()},
        "worm": {"originals": s.query(DocumentVersion).count(),
                 "read_only": sum(1 for v in s.query(DocumentVersion).all() if not os.access(v.stored_path, os.W_OK))},
        "malware_engine": "ClamAV" if shutil.which("clamscan") else "Heuristic scanner (ClamAV not installed on this host)",
        "you": {"role": ROLE_LABEL[u.role], "row_scope": f"college #{u.college_id} only" if u.role == "college" else "all colleges"},
    }


class TokenDemoIn(BaseModel):
    ttl: int = Field(default=60, ge=1, le=60)


@app.post("/api/security/token-demo")
def token_demo(body: TokenDemoIn, u: User = Depends(current_user)):
    tok, claims = issue_job_token(999999, 999999, ttl=body.ttl)
    return {"token": tok, "claims": claims}


class TokenVerifyIn(BaseModel):
    token: str


@app.post("/api/security/token-verify")
def token_verify(body: TokenVerifyIn, u: User = Depends(current_user)):
    try:
        c = verify_job_token(body.token, 999999, 999999)
        return {"valid": True, "claims": c, "seconds_left": c["exp"] - int(time.time())}
    except TokenError as e:
        return {"valid": False, "reason": str(e)}


class KmsIn(BaseModel):
    plaintext: str = Field(min_length=1, max_length=500)


@app.post("/api/security/kms-demo")
def kms_demo(body: KmsIn, u: User = Depends(current_user)):
    blob = kms.encrypt(body.plaintext.encode(), b"demo")
    return {"plaintext": body.plaintext, "envelope": blob, "decrypted": kms.decrypt(blob, b"demo").decode(),
            "explanation": "A fresh 256-bit data key (DEK) encrypts the value with AES-GCM; the DEK itself is encrypted (wrapped) "
                           "by the KMS master key (KEK). Only the wrapped DEK is stored."}


@app.get("/api/security/pii")
def pii_list(u: User = Depends(require("officer", "senior_officer", "admin")), s=Depends(db)):
    audit.log("pii.listed_masked", actor(u), u.role, "pii_vault", {"fields": "masked only"})
    return [{"id": p.id, "college": s.get(College, p.college_id).name, "kind": p.kind, "masked": p.masked,
             "ciphertext": p.ciphertext[:32] + "…", "key_id": p.key_id, "document_id": p.document_id}
            for p in s.query(PiiVault).order_by(PiiVault.id).all()]


class RevealIn(BaseModel):
    justification: str = Field(min_length=20, max_length=500)


@app.post("/api/security/pii/{pid}/reveal")
def pii_reveal(pid: int, body: RevealIn, u: User = Depends(require("admin")), s=Depends(db)):
    p = s.get(PiiVault, pid)
    if not p:
        raise HTTPException(404)
    if len(set(body.justification.lower().split())) < 4:
        raise HTTPException(422, "Give a specific reason (case/application reference) for revealing this value.")
    val = kms.decrypt({"ciphertext": p.ciphertext, "nonce": p.nonce, "wrapped_dek": p.wrapped_dek}, f"{p.kind}:{p.college_id}".encode())
    audit.log("pii.revealed", actor(u), u.role, f"pii:{p.id}", {"kind": p.kind, "justification": body.justification})
    notify_event("pii.revealed", {"pii_id": p.id, "kind": p.kind, "by": u.email, "justification": body.justification})
    return {"id": p.id, "value": val.decode()}


# ---------------- audit / rules / admin / notifications ----------------
@app.get("/api/audit")
def audit_list(limit: int = 200, u: User = Depends(require("officer", "senior_officer", "admin")), s=Depends(db)):
    rows = s.query(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 1000)).all()
    return [{"id": r.id, "ts": r.ts, "actor": r.actor, "role": r.role, "action": r.action, "target": r.target,
             "details": json.loads(r.details or "{}"), "prev_hash": r.prev_hash, "hash": r.hash} for r in rows]


@app.get("/api/audit/verify")
def audit_verify(u: User = Depends(current_user), s=Depends(db)):
    return audit.verify_chain(s)


@app.get("/api/rules")
def rules(u: User = Depends(current_user)):
    try:
        r = load_rules()
    except RuleBundleError as e:
        return {"valid": False, "error": str(e), "verification": verify_bundle()}
    from .rules_bundle import BUNDLE
    return {"valid": True, "verification": r.pop("_verification"), "bundle": r, "yaml": BUNDLE.read_text()}


@app.post("/api/admin/integrity-check")
def run_integrity_check(u: User = Depends(require("admin")), s=Depends(db)):
    from .storage import integrity_check
    return integrity_check(s)


@app.get("/api/admin/health")
def admin_health(u: User = Depends(require("officer", "senior_officer", "admin")), s=Depends(db)):
    jobs = s.query(Job).all()
    durs = [j.duration_ms for j in jobs if j.duration_ms]
    import platform
    return {"database": {"url": engine.url.render_as_string(hide_password=True), "dialect": engine.dialect.name, "tables": {t: s.query(m).count() for t, m in
                         [("users", User), ("colleges", College), ("applications", Application), ("documents", Document),
                          ("document_versions", DocumentVersion), ("evidence", Evidence), ("pii_vault", PiiVault),
                          ("jobs", Job), ("audit_log", AuditLog), ("overrides", Override)]}},
            "jobs": {"total": len(jobs), "done": sum(j.status == "done" for j in jobs), "failed": sum(j.status == "failed" for j in jobs),
                     "queued": sum(j.status in ("queued", "running") for j in jobs),
                     "measured_avg_ms": round(sum(durs) / len(durs)) if durs else None, "measured_max_ms": max(durs) if durs else None},
            "components": {"pyhanko": _ver("pyhanko"), "pikepdf": _ver("pikepdf"), "opencv": _ver("cv2"), "pdfminer": _ver("pdfminer"),
                           "pypdfium2": _ver("pypdfium2"), "tesseract": bool(shutil.which("tesseract")),
                           "clamav": bool(shutil.which("clamscan")), "llm": bool(LLM_API_KEY)},
            "python": platform.python_version(), "disk_data_mb": round(sum(f.stat().st_size for f in DATA_DIR.rglob("*") if f.is_file()) / 1e6, 1)}


def _ver(mod):
    try:
        m = __import__(mod)
        return getattr(m, "__version__", "installed")
    except Exception:
        return None


@app.get("/api/notifications")
def notifications(u: User = Depends(current_user), s=Depends(db)):
    q = s.query(Notification)
    if u.role == "college":
        q = q.filter(Notification.college_id == u.college_id)
    elif u.role == "evc_member":
        q = q.filter(Notification.user_id == u.id)
    else:
        roles = {"officer": ["officer"], "senior_officer": ["officer", "senior_officer"], "admin": ["officer", "senior_officer", "admin"]}[u.role]
        q = q.filter(Notification.role.in_(roles), (Notification.user_id.is_(None)) | (Notification.user_id == u.id))
    return [{"id": n.id, "message": n.message, "link": n.link, "read": n.read, "created_at": n.created_at.isoformat(),
             "kind": n.kind, "severity": n.severity or "info"}
            for n in q.order_by(Notification.id.desc()).limit(30)]


@app.get("/api/notifications/outbox")
def notifications_outbox(u: User = Depends(require("admin")), s=Depends(db)):
    from .db import NotificationOutbox
    from . import notify
    rows = s.query(NotificationOutbox).order_by(NotificationOutbox.id.desc()).limit(100).all()
    return {"channels": notify.channels(),
            "configured": {c: c in notify.channels() for c in ["inapp", "email", "sms", "webhook", "slack", "siem"]},
            "items": [{"id": r.id, "channel": r.channel, "kind": r.kind, "status": r.status, "attempts": r.attempts,
                       "last_error": r.last_error, "created_at": r.created_at.isoformat(),
                       "subject": json.loads(r.payload).get("subject")} for r in rows]}


class TestAlert(BaseModel):
    kind: str = "sandbox_violation"


@app.post("/api/notifications/test")
def notifications_test(body: TestAlert, u: User = Depends(require("admin"))):
    notify_event(body.kind if body.kind in ("sandbox_violation", "integrity_failure") else "sandbox_violation",
                 {"detail": f"Test alert sent by {actor(u)}", "failed": []})
    audit.log("notify.test", actor(u), u.role, body.kind)
    return {"ok": True}


@app.post("/api/notifications/read")
def notifications_read(u: User = Depends(current_user), s=Depends(db)):
    for n in notifications(u, s):
        s.get(Notification, n["id"]).read = True
    s.commit()
    return {"ok": True}


@app.get("/api/stats")
def stats(u: User = Depends(current_user), s=Depends(db)):
    q = s.query(Application)
    if u.role == "college":
        q = q.filter(Application.college_id == u.college_id)
    apps = q.all()
    docs = [d for a in apps for d in a.documents]
    by = defaultdict(int)
    for d in docs:
        by[d.status] += 1
    return {"applications": len(apps), "documents": len(docs), "by_status": dict(by),
            "pending_review": sum(1 for a in apps if a.submitted_at and not a.decision),
            "overrides_pending": s.query(Override).filter_by(status="pending").count() if u.role != "college" else 0,
            "avg_risk": round(sum(a.risk_score or 0 for a in apps) / len(apps)) if apps else 0,
            "by_category": {a.category: sum(1 for b in apps if b.category == a.category) for a in apps}}


# ---------------- frontend ----------------
from . import wf_api  # noqa: E402  (workflow module; imports the auth dependencies defined above)
app.include_router(wf_api.router)

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        f = FRONTEND_DIST / path
        if path and f.is_file():
            return FileResponse(f)
        return FileResponse(FRONTEND_DIST / "index.html")
