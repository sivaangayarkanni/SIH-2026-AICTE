"""Minimal mock OpenID Connect provider for tests and screenshots ONLY (not a security product).
Implements: discovery, JWKS (RS256, rotatable), /authorize (login form + TOTP for staff), /token
(authorization_code + PKCE S256, refresh_token), /logout. Mirrors the claims Keycloak emits with the
realm in deploy/keycloak/sealcheck-realm.json (realm_access.roles, college_code, amr).
Run: python devtools/mock_oidc.py --port 9400"""
import base64, hashlib, hmac, html, secrets, struct, sys, time, threading
from urllib.parse import urlencode
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

TOTP_SECRET = "JBSWY3DPEHPK3PXP"  # demo secret (base32) — mock only
USERS = {
    "officer@sealcheck.demo": {"name": "Priya Raman", "roles": ["sealcheck-officer"], "totp": True},
    "senior@sealcheck.demo": {"name": "Dr. Arvind Menon", "roles": ["sealcheck-senior-officer"], "totp": True},
    "admin@sealcheck.demo": {"name": "Meera Iyer", "roles": ["sealcheck-admin"], "totp": True},
    "principal@svit.demo": {"name": "Dr. S. Krishnan", "roles": ["sealcheck-college"], "college_code": "SVIT", "totp": False},
    "nomfa.officer@sealcheck.demo": {"name": "No-MFA Officer", "roles": ["sealcheck-officer"], "totp": False},
}


OPEN_DOMAIN = "@gmail.test"  # any <name>@gmail.test signs in with password "google": stands in for Google accounts


def _open_user(email):
    return {"name": email.split("@")[0].replace(".", " ").title(), "roles": [], "totp": False}


def totp(secret_b32, t=None, step=30, digits=6):
    key = base64.b32decode(secret_b32)
    c = int((t or time.time()) // step)
    h = hmac.new(key, struct.pack(">Q", c), hashlib.sha1).digest()
    o = h[-1] & 15
    return str((struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % 10 ** digits).zfill(digits)


def totp_ok(code):
    return any(hmac.compare_digest(code, totp(TOTP_SECRET, time.time() + d)) for d in (-30, 0, 30))


def create_app(issuer: str, access_ttl=300):
    app = FastAPI()
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    st = {"key": rsa.generate_private_key(public_exponent=65537, key_size=2048), "kid": secrets.token_hex(4),
          "codes": {}, "refresh": {}, "access_ttl": access_ttl}
    app.state.mock = st

    def jwk():
        n = st["key"].public_key().public_numbers()
        b = lambda i: base64.urlsafe_b64encode(i.to_bytes((i.bit_length() + 7) // 8, "big")).decode().rstrip("=")
        return {"kty": "RSA", "kid": st["kid"], "use": "sig", "alg": "RS256", "n": b(n.n), "e": b(n.e)}

    def mint(email, client_id, nonce=None, mfa=False):
        u = USERS.get(email) or _open_user(email); now = int(time.time())
        base = {"iss": issuer, "sub": hashlib.sha256(email.encode()).hexdigest()[:24], "iat": now, "email": email,
                "email_verified": True, "name": u["name"], "azp": client_id}
        if u.get("college_code"):
            base["college_code"] = u["college_code"]
        at = {**base, "aud": ["sealcheck-api", "account"], "exp": now + st["access_ttl"], "typ": "Bearer",
              "realm_access": {"roles": u["roles"]}, "amr": ["pwd", "otp"] if mfa else ["pwd"], "acr": "2" if mfa else "1"}
        idt = {**base, "aud": client_id, "exp": now + 3600, **({"nonce": nonce} if nonce else {})}
        h = {"kid": st["kid"]}
        rt = secrets.token_urlsafe(32); st["refresh"][rt] = (email, client_id, mfa)
        return {"access_token": jwt.encode(at, st["key"], "RS256", headers=h), "id_token": jwt.encode(idt, st["key"], "RS256", headers=h),
                "refresh_token": rt, "token_type": "Bearer", "expires_in": st["access_ttl"]}
    app.state.mint = mint

    @app.get("/.well-known/openid-configuration")
    def disc():
        return {"issuer": issuer, "authorization_endpoint": f"{issuer}/authorize", "token_endpoint": f"{issuer}/token",
                "jwks_uri": f"{issuer}/jwks", "end_session_endpoint": f"{issuer}/logout",
                "code_challenge_methods_supported": ["S256"], "response_types_supported": ["code"],
                "id_token_signing_alg_values_supported": ["RS256"], "grant_types_supported": ["authorization_code", "refresh_token"]}

    @app.get("/jwks")
    def jwks():
        return {"keys": [jwk()]}

    @app.post("/rotate")
    def rotate():
        st["key"] = rsa.generate_private_key(public_exponent=65537, key_size=2048); st["kid"] = secrets.token_hex(4)
        return {"kid": st["kid"]}

    @app.get("/authorize", response_class=HTMLResponse)
    def authorize(response_type: str, client_id: str, redirect_uri: str, code_challenge: str, code_challenge_method: str,
                  state: str = "", nonce: str = "", scope: str = "openid", error: str = ""):
        if response_type != "code" or code_challenge_method != "S256":
            raise HTTPException(400, "only code + PKCE S256")
        hidden = "".join(f'<input type="hidden" name="{k}" value="{html.escape(v)}">' for k, v in
                         dict(client_id=client_id, redirect_uri=redirect_uri, code_challenge=code_challenge, state=state, nonce=nonce).items())
        opts = "".join(f'<option value="{e}">{e}</option>' for e in USERS)
        return f"""<!doctype html><html><head><title>Mock Keycloak · SealCheck realm</title><style>
body{{font-family:system-ui;background:#f1f5f9;display:grid;place-items:center;height:100vh;margin:0}}
form{{background:#fff;padding:32px;border-radius:14px;width:360px;box-shadow:0 10px 30px #0001}}
label{{display:block;font-size:13px;margin:14px 0 4px;color:#334155}} input,select{{width:100%;padding:9px;border:1px solid #cbd5e1;border-radius:8px;box-sizing:border-box}}
button{{margin-top:18px;width:100%;padding:10px;border:0;border-radius:8px;background:#1d4ed8;color:#fff;font-weight:600}}
.b{{font-size:11px;background:#fef3c7;color:#92400e;padding:6px 8px;border-radius:6px}} .e{{color:#b91c1c;font-size:13px}}</style></head>
<body><form method="post" action="{issuer}/authorize"><div class="b">MOCK identity provider for tests — not Keycloak</div>
<h2 style="margin:12px 0 0">Sign in to SealCheck</h2><p style="color:#64748b;font-size:13px;margin:4px 0">Realm: sealcheck · PKCE S256</p>
{f'<p class="e">{html.escape(error)}</p>' if error else ''}{hidden}
<label>Account</label><select name="email" id="email">{opts}</select>
<label>Password</label><input name="password" type="password" value="Demo@2026" id="password">
<label>One-time code (TOTP, staff accounts)</label><input name="otp" id="otp" inputmode="numeric" placeholder="6 digits">
<button id="kc-login">Sign in</button></form></body></html>"""

    @app.post("/authorize")
    def authorize_post(client_id: str = Form(), redirect_uri: str = Form(), code_challenge: str = Form(), state: str = Form(""),
                       nonce: str = Form(""), email: str = Form(), password: str = Form(), otp: str = Form("")):
        u = USERS.get(email) or (_open_user(email) if email.endswith(OPEN_DOMAIN) and password == "google" else None)
        q = dict(response_type="code", client_id=client_id, redirect_uri=redirect_uri, code_challenge=code_challenge,
                 code_challenge_method="S256", state=state, nonce=nonce)
        if not u or (email in USERS and password != "Demo@2026"):
            return RedirectResponse(f"{issuer}/authorize?{urlencode({**q, 'error': 'Invalid credentials'})}", 303)
        mfa = False
        if u["totp"]:
            if not totp_ok(otp.strip()):
                return RedirectResponse(f"{issuer}/authorize?{urlencode({**q, 'error': 'Invalid one-time code'})}", 303)
            mfa = True
        code = secrets.token_urlsafe(24)
        st["codes"][code] = dict(email=email, client_id=client_id, redirect_uri=redirect_uri, challenge=code_challenge,
                                 nonce=nonce, mfa=mfa, exp=time.time() + 60)
        return RedirectResponse(f"{redirect_uri}?{urlencode({'code': code, 'state': state})}", 303)

    @app.post("/token")
    def token(grant_type: str = Form(), client_id: str = Form(), code: str = Form(""), redirect_uri: str = Form(""),
              code_verifier: str = Form(""), refresh_token: str = Form("")):
        if grant_type == "authorization_code":
            c = st["codes"].pop(code, None)
            if not c or c["exp"] < time.time() or c["client_id"] != client_id or c["redirect_uri"] != redirect_uri:
                return JSONResponse({"error": "invalid_grant"}, 400)
            chal = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).decode().rstrip("=")
            if not hmac.compare_digest(chal, c["challenge"]):
                return JSONResponse({"error": "invalid_grant", "error_description": "PKCE verification failed"}, 400)
            return mint(c["email"], client_id, c["nonce"], c["mfa"])
        if grant_type == "refresh_token":
            r = st["refresh"].pop(refresh_token, None)  # rotation: one-time use
            if not r or r[1] != client_id:
                return JSONResponse({"error": "invalid_grant"}, 400)
            return mint(r[0], client_id, None, r[2])
        return JSONResponse({"error": "unsupported_grant_type"}, 400)

    @app.get("/logout")
    def logout(post_logout_redirect_uri: str = "/", id_token_hint: str = ""):
        st["refresh"].clear()
        return RedirectResponse(post_logout_redirect_uri, 303)

    return app


def serve_in_thread(port):
    import uvicorn
    issuer = f"http://127.0.0.1:{port}"
    app = create_app(issuer)
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=srv.run, daemon=True); t.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    return issuer, app, srv


if __name__ == "__main__":
    import uvicorn
    port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 9400
    uvicorn.run(create_app(f"http://127.0.0.1:{port}"), host="127.0.0.1", port=port)
