"""Trust store, OCSP/CRL revocation checks and issuer-registry connectors. These run host-side, after the sandbox.

TRUST_STORE_DIR       directory of trusted root certs (*.pem, *.crt, *.cer, plus an intermediates/ subdir).
                      The default is the synthetic demo PKI. Production must supply the CCA India root and the licensed CA chains.
REVOCATION_CHECK      off (dev default) | soft | hard
                        soft: revoked -> Mismatch; responder unreachable -> warning, the status is not changed
                        hard: responder unreachable -> Source Unavailable
REVOCATION_CACHE_S    default cache TTL when the response has no nextUpdate (3600)
ISSUER_CONNECTORS_FILE YAML list: [{name, match, url, token_env, timeout_s}]. GET {url}?ref=..&issuer=..&sha256=..
                       must return {"status": "valid"|"invalid"|"not_found", "reference": ...}
Every network call has a timeout, retries, and a per-host circuit breaker. On failure the result is "unavailable",
which maps to Source Unavailable. It is never reported as Verified.
Tested only against local mock OCSP, CRL and registry servers. No real CA responder or issuer API was contacted.
"""
from __future__ import annotations
import base64, json, os, threading, time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.x509 import ocsp


def trust_dir(default: Path) -> Path:
    return Path(os.environ.get("TRUST_STORE_DIR") or default)


class CircuitBreaker:
    def __init__(self, threshold=3, cooldown_s=60):
        self.threshold, self.cooldown = threshold, cooldown_s
        self.fail, self.opened = {}, {}
        self.lock = threading.Lock()

    def allow(self, key):
        with self.lock:
            t = self.opened.get(key)
            if t and time.time() - t < self.cooldown:
                return False
            if t:
                self.opened.pop(key, None); self.fail[key] = self.threshold - 1  # half-open: one trial
            return True

    def record(self, key, ok):
        with self.lock:
            if ok:
                self.fail[key] = 0; self.opened.pop(key, None)
            else:
                self.fail[key] = self.fail.get(key, 0) + 1
                if self.fail[key] >= self.threshold:
                    self.opened[key] = time.time()

    def state(self, key):
        return "open" if key in self.opened and time.time() - self.opened[key] < self.cooldown else "closed"


BREAKER = CircuitBreaker(int(os.environ.get("CB_THRESHOLD", "3")), int(os.environ.get("CB_COOLDOWN_S", "60")))


def _host(url):
    return httpx.URL(url).host


def _request(method, url, retries=2, timeout=5.0, transport=None, **kw):
    key = _host(url)
    if not BREAKER.allow(key):
        raise ConnectionError(f"circuit open for {key}")
    last = None
    with httpx.Client(timeout=timeout, transport=transport) as h:
        for i in range(retries + 1):
            try:
                r = h.request(method, url, **kw)
                if r.status_code >= 500:
                    raise httpx.HTTPStatusError(f"{r.status_code}", request=r.request, response=r)
                BREAKER.record(key, True)
                return r
            except (httpx.TransportError, httpx.HTTPStatusError) as e:
                last = e
                time.sleep(0.2 * (i + 1))
    BREAKER.record(key, False)
    raise ConnectionError(f"{key}: {type(last).__name__}: {last}")


class RevocationChecker:
    def __init__(self, cache_file: Path | None = None, transport=None):
        self.cache_file = cache_file
        self.transport = transport
        self.cache = {}
        if cache_file and cache_file.exists():
            try:
                self.cache = json.loads(cache_file.read_text())
            except Exception:  # noqa: BLE001
                self.cache = {}

    def _save(self):
        if self.cache_file:
            tmp = self.cache_file.with_suffix(".tmp"); tmp.write_text(json.dumps(self.cache)); tmp.replace(self.cache_file)

    def check(self, cert_der: bytes, issuer_der: bytes | None, ocsp_urls: list[str], crl_urls: list[str]) -> dict:
        cert = x509.load_der_x509_certificate(cert_der)
        key = f"{cert.issuer.rfc4514_string()}#{cert.serial_number}"
        c = self.cache.get(key)
        if c and c["expires"] > time.time():
            return {**c["result"], "cached": True}
        res, ttl = None, int(os.environ.get("REVOCATION_CACHE_S", "3600"))
        errors = []
        issuer = x509.load_der_x509_certificate(issuer_der) if issuer_der else None
        for url in ocsp_urls if issuer is not None else []:
            try:
                req = ocsp.OCSPRequestBuilder().add_certificate(cert, issuer, hashes.SHA1()).build()
                r = _request("POST", url, content=req.public_bytes(serialization.Encoding.DER),
                             headers={"Content-Type": "application/ocsp-request"}, transport=self.transport)
                o = ocsp.load_der_ocsp_response(r.content)
                if o.response_status != ocsp.OCSPResponseStatus.SUCCESSFUL:
                    errors.append(f"ocsp {o.response_status.name}"); continue
                if o.certificates:
                    _verify_delegated(o, issuer)
                else:
                    issuer.public_key().verify(o.signature, o.tbs_response_bytes, *_sig_args(issuer, o))
                st = {ocsp.OCSPCertStatus.GOOD: "good", ocsp.OCSPCertStatus.REVOKED: "revoked"}.get(o.certificate_status, "unknown")
                res = {"status": st, "source": "ocsp", "url": url,
                       "revoked_at": o.revocation_time_utc.isoformat() if st == "revoked" else None}
                if o.next_update_utc:
                    ttl = max(60, int(o.next_update_utc.timestamp() - time.time()))
                break
            except Exception as e:  # noqa: BLE001
                errors.append(f"ocsp {url}: {str(e)[:120]}")
        if res is None:
            for url in crl_urls:
                try:
                    r = _request("GET", url, transport=self.transport)
                    crl = x509.load_der_x509_crl(r.content) if not r.content.startswith(b"-----") else x509.load_pem_x509_crl(r.content)
                    if issuer is not None and not crl.is_signature_valid(issuer.public_key()):
                        errors.append(f"crl {url}: bad signature"); continue
                    rev = crl.get_revoked_certificate_by_serial_number(cert.serial_number)
                    res = {"status": "revoked" if rev else "good", "source": "crl", "url": url,
                           "revoked_at": rev.revocation_date_utc.isoformat() if rev else None}
                    if crl.next_update_utc:
                        ttl = max(60, int(crl.next_update_utc.timestamp() - time.time()))
                    break
                except Exception as e:  # noqa: BLE001
                    errors.append(f"crl {url}: {str(e)[:120]}")
        if res is None:
            res = {"status": "unavailable" if (ocsp_urls or crl_urls) else "no_endpoint", "errors": errors}
            return res  # never cached
        res["checked_at"] = datetime.now(timezone.utc).isoformat()
        self.cache[key] = {"expires": time.time() + ttl, "result": res}
        self._save()
        return res


def _sig_args(issuer, o):
    from cryptography.hazmat.primitives.asymmetric import padding, ec
    pk = issuer.public_key()
    if isinstance(pk, ec.EllipticCurvePublicKey):
        return (ec.ECDSA(o.signature_hash_algorithm),)
    return (padding.PKCS1v15(), o.signature_hash_algorithm)


def _verify_delegated(o, issuer):
    r = o.certificates[0]
    issuer.public_key().verify(r.signature, r.tbs_certificate_bytes, *_sig_args(issuer, r))
    r.public_key().verify(o.signature, o.tbs_response_bytes, *_sig_args(r, o))


# ---------------- issuer connectors ----------------
def load_connectors() -> list[dict]:
    f = os.environ.get("ISSUER_CONNECTORS_FILE")
    if not f or not Path(f).exists():
        return []
    import yaml
    return yaml.safe_load(Path(f).read_text()) or []


def query_issuer(conn: dict, issuer: str, ref: str | None, sha: str | None, transport=None) -> dict:
    headers = {}
    if conn.get("token_env") and os.environ.get(conn["token_env"]):
        headers["Authorization"] = f"Bearer {os.environ[conn['token_env']]}"
    try:
        r = _request("GET", conn["url"], params={"ref": ref or "", "issuer": issuer, "sha256": sha or ""},
                     headers=headers, timeout=float(conn.get("timeout_s", 5)), transport=transport)
        if r.status_code == 404:
            return {"status": "not_found", "connector": conn["name"]}
        r.raise_for_status()
        st = r.json().get("status")
        return {"status": {"valid": "confirmed", "invalid": "invalid", "not_found": "not_found"}.get(st, "unavailable"),
                "connector": conn["name"], "reference": r.json().get("reference")}
    except Exception as e:  # noqa: BLE001
        return {"status": "unavailable", "connector": conn["name"], "error": str(e)[:160]}


# ---------------- enrichment of sandbox findings ----------------
def enrich(findings: list[dict], sigs: list[dict], facts: dict, sha: str | None, cache_file: Path | None = None,
           transport=None) -> list[dict]:
    mode = os.environ.get("REVOCATION_CHECK", "off")
    out = list(findings)
    if mode != "off":
        rc = RevocationChecker(cache_file, transport=transport)
        for s in sigs or []:
            if not s.get("cert_der"):
                continue
            r = rc.check(base64.b64decode(s["cert_der"]), base64.b64decode(s["issuer_der"]) if s.get("issuer_der") else None,
                         s.get("ocsp_urls") or [], s.get("crl_urls") or [])
            s["revocation"] = r
            base = {"module": "4A", "clause": "Forensics · Certificate revocation (OCSP/CRL)"}
            if r["status"] == "revoked":
                out.append({**base, "rule_id": "F-DSC-05", "outcome": "fail", "severity": "critical", "forgery": True,
                            "title": "Signing certificate is revoked",
                            "detail": f"{r['source'].upper()} reports the certificate of {s.get('signer')} revoked at {r.get('revoked_at')}."})
            elif r["status"] == "good":
                out.append({**base, "rule_id": "F-DSC-05", "outcome": "pass", "severity": "info",
                            "title": "Certificate not revoked", "detail": f"Checked via {r['source'].upper()} ({r.get('url')})."
                            + (" Document embeds LTV data (DSS)." if s.get("ltv_dss") else "")})
            else:
                out.append({**base, "rule_id": "F-DSC-05", "outcome": "warn", "severity": "medium",
                            "source_unavailable": mode == "hard", "manual_review": mode != "hard",
                            "title": "Revocation status could not be checked",
                            "detail": "No OCSP/CRL endpoint in certificate." if r["status"] == "no_endpoint" else
                                      "OCSP/CRL responders unreachable: " + "; ".join(r.get("errors", []))[:300]})
    conns = load_connectors()
    issuer = facts.get("issuer")
    if conns and issuer:
        conn = next((c for c in conns if c.get("match", "").lower() in issuer.lower()), None)
        if conn:
            r = query_issuer(conn, issuer, facts.get("reference") or facts.get("ref_no"), sha, transport=transport)
            for f in out:
                if str(f.get("rule_id", "")).endswith("-SRC"):
                    if r["status"] == "confirmed":
                        f.update(outcome="pass", severity="info", source_unavailable=False,
                                 title=f"Issuer confirmed by {r['connector']}", detail=f"Reference {r.get('reference')} confirmed at source.")
                    elif r["status"] in ("invalid", "not_found"):
                        f.update(outcome="fail", severity="critical", forgery=True, source_unavailable=False,
                                 title=f"Issuer registry ({r['connector']}) does not recognise this document",
                                 detail=f"Registry answered '{r['status']}'.")
                    else:
                        f.update(outcome="warn", severity="medium", source_unavailable=True,
                                 title="Issuer registry unavailable",
                                 detail=f"{r['connector']} could not be reached ({r.get('error', '')}). Reported as Source Unavailable.")
                    f["connector"] = r
    return out
