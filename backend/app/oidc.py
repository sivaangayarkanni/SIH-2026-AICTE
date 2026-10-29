"""OIDC (Keycloak) resource-server validation. AUTH_MODE=oidc.

Frontend does Authorization Code + PKCE (S256) directly with the IdP (public client); the API only validates
bearer access tokens: signature via the issuer's JWKS (cached, key-rotation aware), iss, aud/azp, exp/nbf, and
maps realm/client roles to SealCheck roles. Staff roles must present an MFA (TOTP) authentication: we require
`amr` to contain "otp"/"mfa" or `acr` in OIDC_MFA_ACR_VALUES (configure Keycloak's ACR→LoA mapping + OTP flow).
Tested here against a mock OIDC provider only (tests/mock_oidc.py); NOT verified against a real Keycloak."""
import os, threading, time
import httpx
import jwt

ISSUER = os.getenv("OIDC_ISSUER", "").rstrip("/")
CLIENT_ID = os.getenv("OIDC_CLIENT_ID", "sealcheck-web")
AUDIENCE = os.getenv("OIDC_AUDIENCE", "sealcheck-api")
ROLE_CLAIM = os.getenv("OIDC_ROLE_CLAIM", "realm_access.roles")
COLLEGE_CLAIM = os.getenv("OIDC_COLLEGE_CLAIM", "college_code")
MFA_ROLES = set(filter(None, os.getenv("OIDC_MFA_ROLES", "officer,senior_officer,admin").split(",")))
MFA_ACR = set(filter(None, os.getenv("OIDC_MFA_ACR_VALUES", "2,mfa,urn:sealcheck:loa:mfa").split(",")))
ALGS = ["RS256", "PS256", "ES256"]
# IdP role name -> SealCheck role (highest wins)
ROLE_MAP = {"sealcheck-admin": "admin", "sealcheck-senior-officer": "senior_officer", "sealcheck-officer": "officer", "sealcheck-college": "college"}
ROLE_ORDER = ["admin", "senior_officer", "officer", "college"]
_disc = {"t": 0, "doc": None}
_lock = threading.Lock()
_jwks = {}


class OIDCError(Exception):
    pass


def discovery(force=False):
    with _lock:
        if force or not _disc["doc"] or time.time() - _disc["t"] > 3600:
            if not ISSUER:
                raise OIDCError("OIDC_ISSUER not configured")
            last = None
            for attempt in range(3):
                try:
                    r = httpx.get(f"{ISSUER}/.well-known/openid-configuration", timeout=5)
                    r.raise_for_status()
                    doc = r.json()
                    if doc.get("issuer", "").rstrip("/") != ISSUER:
                        raise OIDCError("issuer mismatch in discovery document")
                    _disc.update(t=time.time(), doc=doc)
                    break
                except (httpx.HTTPError, ValueError) as e:
                    last = e; time.sleep(0.2 * (attempt + 1))
            else:
                raise OIDCError(f"IdP unreachable: {last}")
        return _disc["doc"]


JWKS_TTL_S = int(os.getenv("OIDC_JWKS_TTL_S", "600"))
JWKS_MIN_REFRESH_S = float(os.getenv("OIDC_JWKS_MIN_REFRESH_S", "1"))


def _signing_key(token):
    """kid -> key from a cached JWKS; an unknown kid triggers one (rate-limited) refetch to follow key rotation."""
    kid = jwt.get_unverified_header(token).get("kid")
    uri = discovery()["jwks_uri"]
    ent = _jwks.get(uri)

    def fetch():
        r = httpx.get(uri, timeout=5); r.raise_for_status()
        keys = {k["kid"]: jwt.PyJWK(k).key for k in r.json()["keys"] if k.get("use", "sig") == "sig"}
        _jwks[uri] = {"keys": keys, "t": time.time()}
        return _jwks[uri]
    with _lock:
        if not ent or time.time() - ent["t"] > JWKS_TTL_S:
            ent = fetch()
        if kid not in ent["keys"] and time.time() - ent["t"] >= JWKS_MIN_REFRESH_S:
            ent = fetch()
    if kid not in ent["keys"]:
        raise OIDCError(f"signing key {kid!r} not in issuer JWKS")
    return ent["keys"][kid]


def _claim(claims, path):
    cur = claims
    for p in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur


def map_role(claims):
    roles = set(_claim(claims, ROLE_CLAIM) or [])
    for c in (claims.get("resource_access") or {}).values():
        roles |= set(c.get("roles", []))
    mapped = {ROLE_MAP[r] for r in roles if r in ROLE_MAP}
    for r in ROLE_ORDER:
        if r in mapped:
            return r
    return None


def has_mfa(claims):
    amr = claims.get("amr") or []
    return bool({"otp", "mfa", "totp"} & set(map(str.lower, amr))) or str(claims.get("acr", "")) in MFA_ACR


def validate(token: str) -> dict:
    try:
        key = _signing_key(token)
        claims = jwt.decode(token, key, algorithms=ALGS, issuer=ISSUER, audience=[AUDIENCE, CLIENT_ID],
                            options={"require": ["exp", "iat", "iss", "sub"]}, leeway=30)
    except httpx.HTTPError as e:
        raise OIDCError(f"IdP JWKS unreachable: {e}")
    except jwt.InvalidTokenError as e:
        raise OIDCError(str(e))
    role = map_role(claims)
    if not role:
        raise OIDCError("no SealCheck role assigned in the IdP")
    if role in MFA_ROLES and not has_mfa(claims):
        raise OIDCError("MFA (TOTP) required for staff roles")
    claims["_role"] = role
    return claims


def public_config():
    return {"issuer": ISSUER, "client_id": CLIENT_ID, "scope": "openid profile email", "audience": AUDIENCE}
