"""OCSP/CRL and issuer connectors against local mock servers (httpx.MockTransport). No real CA/registry contacted."""
import base64, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import httpx, pytest
from cryptography import x509
from cryptography.x509 import ocsp
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app import trust  # noqa: E402

NOW = datetime.now(timezone.utc)


def _cert(subject, issuer, key, issuer_key, ca=False, serial=None):
    b = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject)]))
         .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, issuer)])).public_key(key.public_key())
         .serial_number(serial or x509.random_serial_number()).not_valid_before(NOW - timedelta(days=1))
         .not_valid_after(NOW + timedelta(days=30)).add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True))
    return b.sign(issuer_key, hashes.SHA256())


@pytest.fixture(scope="module")
def pki():
    ck = ec.generate_private_key(ec.SECP256R1()); lk = ec.generate_private_key(ec.SECP256R1())
    ca = _cert("Mock CA", "Mock CA", ck, ck, ca=True)
    good = _cert("Good Signer", "Mock CA", lk, ck, serial=1001)
    bad = _cert("Revoked Signer", "Mock CA", lk, ck, serial=1002)
    return ck, ca, good, bad


def responder(pki, calls):
    ck, ca, good, bad = pki
    def h(req: httpx.Request):
        calls.append(req.url.path)
        if req.url.path == "/ocsp":
            r = ocsp.load_der_ocsp_request(req.content)
            cert = good if r.serial_number == good.serial_number else bad
            st = ocsp.OCSPCertStatus.GOOD if cert is good else ocsp.OCSPCertStatus.REVOKED
            b = ocsp.OCSPResponseBuilder().add_response(cert=cert, issuer=ca, algorithm=hashes.SHA1(), cert_status=st,
                                                        this_update=NOW, next_update=NOW + timedelta(hours=1),
                                                        revocation_time=NOW - timedelta(hours=2) if cert is bad else None,
                                                        revocation_reason=None).responder_id(ocsp.OCSPResponderEncoding.HASH, ca)
            return httpx.Response(200, content=b.sign(ck, hashes.SHA256()).public_bytes(serialization.Encoding.DER))
        if req.url.path == "/crl":
            rc = x509.RevokedCertificateBuilder().serial_number(bad.serial_number).revocation_date(NOW - timedelta(hours=1)).build()
            crl = (x509.CertificateRevocationListBuilder().issuer_name(ca.subject).last_update(NOW).next_update(NOW + timedelta(days=1))
                   .add_revoked_certificate(rc).sign(ck, hashes.SHA256()))
            return httpx.Response(200, content=crl.public_bytes(serialization.Encoding.DER))
        if req.url.path == "/down":
            return httpx.Response(503)
        if req.url.path == "/registry":
            ref = req.url.params.get("ref")
            if ref == "OK-1":
                return httpx.Response(200, json={"status": "valid", "reference": ref})
            return httpx.Response(404)
        return httpx.Response(404)
    return httpx.MockTransport(h)


def der(c):
    return c.public_bytes(serialization.Encoding.DER)


def test_ocsp_good_revoked_and_cache(pki, tmp_path, monkeypatch):
    monkeypatch.setattr(trust.time, "sleep", lambda s: None)
    calls = []
    rc = trust.RevocationChecker(tmp_path / "c.json", transport=responder(pki, calls))
    _, ca, good, bad = pki
    assert rc.check(der(good), der(ca), ["http://ca.mock/ocsp"], [])["status"] == "good"
    assert rc.check(der(bad), der(ca), ["http://ca.mock/ocsp"], [])["status"] == "revoked"
    n = len(calls)
    again = trust.RevocationChecker(tmp_path / "c.json", transport=responder(pki, calls)).check(der(good), der(ca), ["http://ca.mock/ocsp"], [])
    assert again["cached"] and len(calls) == n  # disk cache honoured until nextUpdate


def test_crl_fallback_when_ocsp_down(pki, monkeypatch):
    monkeypatch.setattr(trust.time, "sleep", lambda s: None)
    trust.BREAKER.fail.clear(); trust.BREAKER.opened.clear()
    _, ca, good, bad = pki
    rc = trust.RevocationChecker(None, transport=responder(pki, []))
    r = rc.check(der(bad), der(ca), ["http://ocsp-down.mock/down"], ["http://ca.mock/crl"])
    assert r["status"] == "revoked" and r["source"] == "crl"
    assert trust.RevocationChecker(None, transport=responder(pki, [])).check(der(good), der(ca), [], ["http://ca.mock/crl"])["status"] == "good"


def test_unreachable_maps_to_source_unavailable_in_hard_mode(pki, monkeypatch):
    monkeypatch.setattr(trust.time, "sleep", lambda s: None)
    monkeypatch.setenv("REVOCATION_CHECK", "hard")
    trust.BREAKER.fail.clear(); trust.BREAKER.opened.clear()
    _, ca, good, _ = pki
    sig = {"signer": "Good", "cert_der": base64.b64encode(der(good)).decode(), "issuer_der": base64.b64encode(der(ca)).decode(),
           "ocsp_urls": ["http://dead.mock/down"], "crl_urls": []}
    out = trust.enrich([], [sig], {}, None, transport=responder(pki, []))
    f = next(f for f in out if f["rule_id"] == "F-DSC-05")
    assert f["source_unavailable"] and f["outcome"] == "warn"
    from app.pipeline import policy
    assert policy.decide(out)["status"] == "Source Unavailable"


def test_revoked_cert_becomes_mismatch(pki, monkeypatch):
    monkeypatch.setenv("REVOCATION_CHECK", "soft")
    _, ca, _, bad = pki
    sig = {"signer": "Bad", "cert_der": base64.b64encode(der(bad)).decode(), "issuer_der": base64.b64encode(der(ca)).decode(),
           "ocsp_urls": ["http://ca.mock/ocsp"], "crl_urls": []}
    from app.pipeline import policy
    assert policy.decide(trust.enrich([], [sig], {}, None, transport=responder(pki, [])))["status"] == "Mismatch Detected"


def test_issuer_connector_and_circuit_breaker(pki, tmp_path, monkeypatch):
    monkeypatch.setattr(trust.time, "sleep", lambda s: None)
    trust.BREAKER.fail.clear(); trust.BREAKER.opened.clear()
    cfg = tmp_path / "conn.yaml"
    cfg.write_text("- {name: Fire NOC registry (mock), match: Fire, url: 'http://registry.mock/registry'}\n"
                   "- {name: Dead registry, match: Municipal, url: 'http://dead-reg.mock/down'}\n")
    monkeypatch.setenv("ISSUER_CONNECTORS_FILE", str(cfg)); monkeypatch.setenv("REVOCATION_CHECK", "off")
    src = lambda: [{"rule_id": "R-FIRE-SRC", "outcome": "warn", "source_unavailable": True, "title": "x"}]  # noqa: E731
    t = responder(pki, [])
    ok = trust.enrich(src(), [], {"issuer": "Directorate of Fire and Rescue", "reference": "OK-1"}, "ab", transport=t)
    assert ok[0]["outcome"] == "pass" and not ok[0]["source_unavailable"]
    nf = trust.enrich(src(), [], {"issuer": "Directorate of Fire and Rescue", "reference": "FAKE"}, "ab", transport=t)
    assert nf[0]["outcome"] == "fail" and nf[0]["forgery"]
    for _ in range(3):
        un = trust.enrich(src(), [], {"issuer": "Municipal Corporation"}, "ab", transport=t)
        assert un[0]["source_unavailable"]
    assert trust.BREAKER.state("dead-reg.mock") == "open"
    un = trust.enrich(src(), [], {"issuer": "Municipal Corporation"}, "ab", transport=t)
    assert "circuit open" in un[0]["connector"]["error"]


def test_worker_returns_cert_material(tmp_path):
    from conftest import SAMPLES
    from app.pipeline.forensics import signatures
    from app.service import TRUST_DIR
    s = signatures(str(SAMPLES / "svit_application_form.pdf"), str(TRUST_DIR))[0]
    assert s["cert_der"] and s["issuer_der"] and "ltv_dss" in s and s["trusted"]
