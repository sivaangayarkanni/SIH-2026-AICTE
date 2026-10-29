"""AUTH_MODE=google against the local MOCK OpenID provider (devtools/mock_oidc.py stands in for Google).
This exercises our code path (PKCE, state cookie, JWKS signature, nonce, email_verified, onboarding,
approvals); it is NOT a test against Google's real service."""
import socket, sys, time
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import httpx, jwt, pytest
from fastapi.testclient import TestClient
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "devtools"))
import mock_oidc  # noqa: E402

FORM = {"full_name": "Dr. Kavya Nair", "requested_role": "college", "institution_name": "Nila Institute of Technology",
        "aicte_id": "1-4455667788", "state": "Kerala", "designation": "Principal", "phone": "+91 98470 12345", "consent": True}


def _port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


@pytest.fixture(scope="module")
def env():
    mp = pytest.MonkeyPatch()
    issuer, mapp, srv = mock_oidc.serve_in_thread(_port())
    import app.main as M
    from app import google_auth
    from app.db import init_db
    init_db()
    mp.setattr(M, "AUTH_MODE", "google"); mp.setattr(M, "DEMO_LOGIN", False)
    mp.setenv("GOOGLE_CLIENT_ID", "test-client.apps.googleusercontent.com")
    mp.setenv("GOOGLE_CLIENT_SECRET", "test-secret"); mp.setenv("GOOGLE_ISSUER", issuer)
    mp.setenv("SEALCHECK_BOOTSTRAP_ADMIN_EMAIL", "boss@gmail.test")
    google_auth._disc.clear(); google_auth._jwks.clear()
    with TestClient(M.app) as c:
        yield c, issuer, mapp
    srv.should_exit = True; mp.undo()


def google_login(c, issuer, email, tamper_state=False):
    c.cookies.clear()
    r = c.get("/api/auth/google/start", params={"return_to": "/"}, follow_redirects=False)
    assert r.status_code == 302, r.text
    q = {k: v[0] for k, v in parse_qs(urlparse(r.headers["location"]).query).items()}
    assert q["code_challenge_method"] == "S256" and q["scope"] == "openid email profile" and q["nonce"]
    r2 = httpx.post(f"{issuer}/authorize", data={"client_id": q["client_id"], "redirect_uri": q["redirect_uri"],
                    "code_challenge": q["code_challenge"], "state": q["state"], "nonce": q["nonce"],
                    "email": email, "password": "google"}, follow_redirects=False)
    cb = {k: v[0] for k, v in parse_qs(urlparse(r2.headers["location"]).query).items()}
    if tamper_state:
        cb["state"] = "x" + cb["state"]
    r3 = c.get("/api/auth/google/callback", params=cb, follow_redirects=False)
    assert r3.status_code == 302
    loc = r3.headers["location"]
    if not loc.startswith("/auth/google#"):
        return None, loc
    return parse_qs(loc.split("#", 1)[1])["token"][0], loc


def H(t):
    return {"Authorization": f"Bearer {t}"}


def test_config_and_no_demo(env):
    c, *_ = env
    cfg = c.get("/api/auth/config").json()
    assert cfg["mode"] == "google" and cfg["google"]["enabled"] and not cfg["demo_accounts"]
    assert c.get("/api/auth/demo-accounts").status_code == 404
    assert c.post("/api/auth/login", json={"email": "a@b.c", "password": "x"}).status_code == 403


def test_signup_new_institution_gets_college_access(env):
    c, issuer, _ = env
    tok, _ = google_login(c, issuer, "kavya.nair@gmail.test")
    me = c.get("/api/auth/me", headers=H(tok)).json()
    assert me["role"] == "pending" and me["access_status"] == "new"
    assert c.get("/api/applications", headers=H(tok)).status_code == 403   # no access before onboarding
    opts = c.get("/api/auth/onboarding/options", headers=H(tok)).json()
    assert "Kerala" in opts["states"] and opts["email"] == "kavya.nair@gmail.test"
    r = c.post("/api/auth/onboarding", headers=H(tok), json=FORM)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "approved" and out["role"] == "college" and out["user"]["college"] == FORM["institution_name"]
    assert out["profile"]["phone"] == "9847012345" and out["profile"]["official_email"] == "kavya.nair@gmail.test"
    assert c.get("/api/applications", headers=H(tok)).status_code == 200
    # signing in again keeps the same account (keyed on Google 'sub')
    tok2, _ = google_login(c, issuer, "kavya.nair@gmail.test")
    assert c.get("/api/auth/me", headers=H(tok2)).json()["role"] == "college"


def test_validation(env):
    c, issuer, _ = env
    tok, _ = google_login(c, issuer, "val.user@gmail.test")
    for bad in ({"phone": "12345"}, {"consent": False}, {"requested_role": "admin"}, {"state": "Atlantis"},
                {"aicte_id": "<script>"}, {"full_name": "<b>x</b>"}):
        assert c.post("/api/auth/onboarding", headers=H(tok), json={**FORM, **bad}).status_code == 422, bad


def test_officer_request_needs_admin_and_bootstrap_admin(env):
    c, issuer, _ = env
    off, _ = google_login(c, issuer, "ravi.officer@gmail.test")
    r = c.post("/api/auth/onboarding", headers=H(off), json={**FORM, "requested_role": "officer", "aicte_id": "AICTE-SRO",
                                                            "institution_name": "AICTE Southern Regional Office"})
    assert r.json()["status"] == "pending" and r.json()["role"] == "pending"
    assert c.get("/api/admin/access-requests", headers=H(off)).status_code == 403
    # second representative of an existing institution also waits for an admin
    dup, _ = google_login(c, issuer, "second.rep@gmail.test")
    assert c.post("/api/auth/onboarding", headers=H(dup), json=FORM).json()["status"] == "pending"

    adm, _ = google_login(c, issuer, "boss@gmail.test")
    me = c.get("/api/auth/me", headers=H(adm)).json()
    assert me["role"] == "admin"
    reqs = c.get("/api/admin/access-requests", headers=H(adm)).json()
    ids = {x["email"]: x["user_id"] for x in reqs}
    assert {"ravi.officer@gmail.test", "second.rep@gmail.test"} <= set(ids)
    assert c.post(f"/api/admin/access-requests/{ids['ravi.officer@gmail.test']}/approve", headers=H(adm),
                  json={"role": "officer", "note": "verified by phone"}).json()["role"] == "officer"
    assert c.get("/api/auth/me", headers=H(off)).json()["role"] == "officer"
    assert c.get("/api/applications", headers=H(off)).status_code == 200
    assert c.post(f"/api/admin/access-requests/{ids['second.rep@gmail.test']}/reject", headers=H(adm),
                  json={"note": "not known to the institution"}).json()["status"] == "rejected"
    assert c.get("/api/applications", headers=H(dup)).status_code == 403
    assert c.post(f"/api/admin/access-requests/{ids['second.rep@gmail.test']}/approve", headers=H(adm), json={}).status_code == 409


def test_tampered_state_rejected(env):
    c, issuer, _ = env
    tok, loc = google_login(c, issuer, "mallory@gmail.test", tamper_state=True)
    assert tok is None and loc.startswith("/login?error=")


def test_id_token_checks(env):
    _, issuer, mapp = env
    from app import google_auth
    st = mapp.state.mock; cfg = google_auth.cfg(); now = int(time.time())
    base = {"iss": issuer, "sub": "s1", "aud": cfg["client_id"], "iat": now, "exp": now + 600, "email": "x@gmail.test",
            "email_verified": True, "nonce": "n1"}
    sign = lambda c: jwt.encode(c, st["key"], "RS256", headers={"kid": st["kid"]})
    assert google_auth.verify_id_token(cfg, sign(base), "n1")["email"] == "x@gmail.test"
    for bad, nonce in (({"email_verified": False}, "n1"), ({}, "other"), ({"aud": "someone-else"}, "n1"),
                       ({"iss": "https://evil.example"}, "n1"), ({"exp": now - 3600}, "n1")):
        with pytest.raises(Exception):
            google_auth.verify_id_token(cfg, sign({**base, **bad}), nonce)


def test_not_configured(env, monkeypatch):
    c, *_ = env
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET")
    assert c.get("/api/auth/google/start", follow_redirects=False).status_code == 503
    assert c.get("/api/auth/config").json()["google"]["enabled"] is False


def test_production_config_accepts_google_db(monkeypatch):
    from app.ops import validate_production_config
    good = {"SEALCHECK_JWT_SECRET": "x" * 40, "AUTH_MODE": "google", "PUBLIC_BASE_URL": "https://sealcheck-nu.vercel.app",
            "DATABASE_URL": "postgresql://u:p@h/db", "SEALCHECK_MASTER_KEY": "m" * 48, "STORAGE_BACKEND": "db",
            "SANDBOX_BACKEND": "process", "SEALCHECK_ACCEPT_PROCESS_SANDBOX": "1", "QUEUE_BACKEND": "inline"}
    assert validate_production_config(good) == []
    assert validate_production_config({**good, "AUTH_MODE": "local"})
    assert validate_production_config({**good, "SEALCHECK_MASTER_KEY": ""})
