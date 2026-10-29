"""AUTH_MODE=oidc against the local MOCK provider (devtools/mock_oidc.py). Not a test of real Keycloak."""
import base64, hashlib, secrets, socket, sys, time
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import httpx, jwt, pytest
from fastapi.testclient import TestClient
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "devtools"))
import mock_oidc  # noqa: E402


def _port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


@pytest.fixture(scope="module")
def env(monkeypatch_module):
    issuer, mapp, srv = mock_oidc.serve_in_thread(_port())
    import app.main as M
    from app import oidc
    from app.db import SessionLocal, College, init_db
    init_db(); s = SessionLocal()
    if not s.query(College).count():
        import seed_db; sys.argv = ["seed", "--force"]; seed_db.main()
    s.close()
    monkeypatch_module.setattr(M, "AUTH_MODE", "oidc")
    monkeypatch_module.setattr(oidc, "ISSUER", issuer)
    oidc._disc.update(t=0, doc=None); oidc._jwks.clear()
    with TestClient(M.app) as c:
        yield c, issuer, mapp
    srv.should_exit = True


@pytest.fixture(scope="module")
def monkeypatch_module():
    mp = pytest.MonkeyPatch(); yield mp; mp.undo()


def pkce_login(issuer, email, otp=None, tamper_verifier=False):
    ver = secrets.token_urlsafe(48)
    chal = base64.urlsafe_b64encode(hashlib.sha256(ver.encode()).digest()).decode().rstrip("=")
    redirect = "http://localhost:8000/auth/callback"
    h = httpx.Client(base_url=issuer, follow_redirects=False, timeout=5)
    q = dict(response_type="code", client_id="sealcheck-web", redirect_uri=redirect, code_challenge=chal,
             code_challenge_method="S256", state="st1", nonce="n1", scope="openid")
    assert h.get("/authorize", params=q).status_code == 200
    r = h.post("/authorize", data=dict(client_id="sealcheck-web", redirect_uri=redirect, code_challenge=chal, state="st1",
                                       nonce="n1", email=email, password="Demo@2026", otp=otp or ""))
    loc = urlparse(r.headers["location"]); qs = parse_qs(loc.query)
    if "code" not in qs:
        return None
    assert qs["state"] == ["st1"]
    tr = h.post("/token", data=dict(grant_type="authorization_code", client_id="sealcheck-web", code=qs["code"][0],
                                    redirect_uri=redirect, code_verifier=ver + ("x" if tamper_verifier else "")))
    return tr.json() if tr.status_code == 200 else {"error": tr.json()}


def me(c, tok):
    return c.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"})


def test_pkce_flow_with_totp_maps_officer(env):
    c, iss, _ = env
    assert pkce_login(iss, "officer@sealcheck.demo", otp="000000") is None  # wrong TOTP -> back to login form
    t = pkce_login(iss, "officer@sealcheck.demo", otp=mock_oidc.totp(mock_oidc.TOTP_SECRET))
    r = me(c, t["access_token"]); assert r.status_code == 200 and r.json()["role"] == "officer"
    assert c.get("/api/auth/config").json()["mode"] == "oidc"
    assert c.post("/api/auth/login", json={"email": "officer@sealcheck.demo", "password": "Demo@2026"}).status_code == 403


def test_pkce_verifier_mismatch_rejected(env):
    _, iss, _ = env
    t = pkce_login(iss, "principal@svit.demo", tamper_verifier=True)
    assert t["error"]["error"] == "invalid_grant"


def test_college_role_and_scope(env):
    c, iss, _ = env
    t = pkce_login(iss, "principal@svit.demo")
    u = me(c, t["access_token"]).json()
    assert u["role"] == "college" and "Venkateswara" in (u["college"] or "")


def test_staff_without_mfa_rejected(env):
    c, iss, _ = env
    t = pkce_login(iss, "nomfa.officer@sealcheck.demo")
    r = me(c, t["access_token"]); assert r.status_code == 401 and "MFA" in r.json()["detail"]


def test_tampered_expired_and_foreign_tokens_rejected(env):
    c, iss, mapp = env
    t = pkce_login(iss, "senior@sealcheck.demo", otp=mock_oidc.totp(mock_oidc.TOTP_SECRET))
    a = t["access_token"]; head, body, sig = a.split(".")
    claims = jwt.decode(a, options={"verify_signature": False}); claims["realm_access"]["roles"] = ["sealcheck-admin"]
    forged = head + "." + base64.urlsafe_b64encode(__import__("json").dumps(claims).encode()).decode().rstrip("=") + "." + sig
    assert me(c, forged).status_code == 401
    st = mapp.state.mock
    exp = jwt.encode({**claims, "exp": int(time.time()) - 120}, st["key"], "RS256", headers={"kid": st["kid"]})
    assert me(c, exp).status_code == 401
    from cryptography.hazmat.primitives.asymmetric import rsa
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert me(c, jwt.encode(claims, other, "RS256", headers={"kid": st["kid"]})).status_code == 401
    wrong_iss = jwt.encode({**claims, "iss": "http://evil"}, st["key"], "RS256", headers={"kid": st["kid"]})
    assert me(c, wrong_iss).status_code == 401


def test_refresh_rotation_and_key_rotation(env):
    c, iss, _ = env
    t = pkce_login(iss, "admin@sealcheck.demo", otp=mock_oidc.totp(mock_oidc.TOTP_SECRET))
    h = httpx.Client(base_url=iss)
    r1 = h.post("/token", data=dict(grant_type="refresh_token", client_id="sealcheck-web", refresh_token=t["refresh_token"]))
    assert r1.status_code == 200
    assert h.post("/token", data=dict(grant_type="refresh_token", client_id="sealcheck-web",
                                      refresh_token=t["refresh_token"])).status_code == 400  # reuse refused
    time.sleep(1.1); h.post("/rotate")  # IdP rotates signing key -> API must fetch new JWKS by kid
    t2 = pkce_login(iss, "admin@sealcheck.demo", otp=mock_oidc.totp(mock_oidc.TOTP_SECRET))
    r2 = me(c, t2["access_token"]); assert r2.status_code == 200, r2.text
    assert r2.json()["role"] == "admin"
    lo = c.post("/api/auth/logout", headers={"Authorization": f"Bearer {t2['access_token']}"}).json()
    assert lo["end_session_endpoint"].endswith("/logout")
