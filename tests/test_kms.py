"""KMS adapters: soft rotation, AWS KMS against moto, Vault Transit against a local mock HTTP server.
None of these touch real AWS or a real Vault."""
import base64, json, os, sys, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app import kms as K  # noqa: E402


def test_soft_rotation_rewrap(tmp_path):
    km = K.SoftKMS(str(tmp_path))
    b1 = km.encrypt(b"ABCDE1234F", b"PAN:1")
    assert b1["key_id"] == "local-kek-v1"
    assert km.rotate() == "local-kek-v2"
    assert km.decrypt(b1, b"PAN:1") == b"ABCDE1234F"  # old version still decrypts
    b2 = km.rewrap(b1)
    assert b2["key_id"] == "local-kek-v2" and b2["ciphertext"] == b1["ciphertext"]
    assert K.SoftKMS(str(tmp_path)).decrypt(b2, b"PAN:1") == b"ABCDE1234F"
    with pytest.raises(Exception):
        km.decrypt(b2, b"PAN:2")  # AAD bound


def test_aws_kms_moto(monkeypatch):
    moto = pytest.importorskip("moto")
    import boto3
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test"); monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    with moto.mock_aws():
        c = boto3.client("kms")
        kid = c.create_key(Description="sealcheck")["KeyMetadata"]["KeyId"]
        km = K.AwsKMS(kid, client=c)
        b = km.encrypt(b"secret", b"aad")
        assert b["key_id"].startswith("aws:")
        assert km.decrypt(b, b"aad") == b"secret"
        km.rotate()
        assert c.get_key_rotation_status(KeyId=kid)["KeyRotationEnabled"]
        assert km.decrypt(km.rewrap(b), b"aad") == b"secret"


class _Vault(BaseHTTPRequestHandler):
    keys = {1: os.urandom(32)}
    def log_message(self, *a): pass
    def _send(self, code, body):
        d = json.dumps(body).encode(); self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(d))); self.end_headers(); self.wfile.write(d)
    def do_POST(self):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        if self.headers.get("X-Vault-Token") != "root":
            return self._send(403, {"errors": ["permission denied"]})
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        cur = max(self.keys)
        def enc(pt):
            n = os.urandom(12); return f"vault:v{cur}:" + base64.b64encode(n + AESGCM(self.keys[cur]).encrypt(n, pt, None)).decode()
        def dec(ct):
            _, v, b = ct.split(":"); raw = base64.b64decode(b); return AESGCM(self.keys[int(v[1:])]).decrypt(raw[:12], raw[12:], None)
        p = self.path
        if p.endswith("/rotate"):
            self.keys[cur + 1] = os.urandom(32); return self._send(204, {})
        if "/encrypt/" in p:
            return self._send(200, {"data": {"ciphertext": enc(base64.b64decode(body["plaintext"]))}})
        if "/decrypt/" in p:
            return self._send(200, {"data": {"plaintext": base64.b64encode(dec(body["ciphertext"])).decode()}})
        if "/rewrap/" in p:
            return self._send(200, {"data": {"ciphertext": enc(dec(body["ciphertext"]))}})
        self._send(404, {})


def test_vault_transit_mock():
    srv = HTTPServer(("127.0.0.1", 0), _Vault); threading.Thread(target=srv.serve_forever, daemon=True).start()
    addr = f"http://127.0.0.1:{srv.server_port}"
    try:
        km = K.VaultTransitKMS(addr, "root", "sealcheck")
        b = km.encrypt(b"aadhaar", b"x")
        assert b["key_id"] == "vault:sealcheck:v1"
        km.rotate()
        b2 = km.rewrap(b)
        assert b2["key_id"] == "vault:sealcheck:v2" and km.decrypt(b2, b"x") == b"aadhaar"
        with pytest.raises(K.KMSUnavailable):
            K.VaultTransitKMS(addr, "wrong", "sealcheck").encrypt(b"x")
    finally:
        srv.shutdown()


def test_vault_unreachable_maps_to_unavailable(monkeypatch):
    monkeypatch.setattr(K.time, "sleep", lambda s: None)
    km = K.VaultTransitKMS("http://127.0.0.1:9", "root", "sealcheck", timeout=0.5)
    with pytest.raises(K.KMSUnavailable):
        km.encrypt(b"x")


def test_rewrap_all_db(tmp_path):
    from app.db import SessionLocal, PiiVault, init_db
    init_db()
    km = K.SoftKMS(str(tmp_path))
    with SessionLocal() as s:
        b = km.encrypt(b"ABCDE1234F", b"PAN:1")
        s.add(PiiVault(kind="PAN", ciphertext=b["ciphertext"], nonce=b["nonce"], wrapped_dek=b["wrapped_dek"], key_id=b["key_id"]))
        s.commit()
        rid = s.query(PiiVault).order_by(PiiVault.id.desc()).first().id
        km.rotate()
        assert K.rewrap_all(s, km, ids=[rid]) == 1
        r = s.get(PiiVault, rid)
        assert r.key_id == "local-kek-v2"
        assert km.decrypt({"ciphertext": r.ciphertext, "nonce": r.nonce, "wrapped_dek": r.wrapped_dek, "key_id": r.key_id}, b"PAN:1") == b"ABCDE1234F"
