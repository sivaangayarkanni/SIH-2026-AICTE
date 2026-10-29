"""Notifications: SMTP to a local aiosmtpd server, SMS/webhook/Slack to local HTTP mocks, SIEM to file + UDP,
retry/backoff to dead-letter. No real providers are contacted."""
import json, socket, sys, threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app import notify  # noqa: E402
from app.db import SessionLocal, NotificationOutbox, Notification, init_db  # noqa: E402

GOT = []


class H(BaseHTTPRequestHandler):
    fail = 0
    def log_message(self, *a): pass
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if H.fail > 0:
            H.fail -= 1; self.send_response(503); self.end_headers(); return
        GOT.append((self.path, dict(self.headers), body))
        self.send_response(201); self.send_header("Content-Length", "2"); self.end_headers(); self.wfile.write(b"{}")


@pytest.fixture(scope="module")
def http():
    srv = HTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


@pytest.fixture()
def env(monkeypatch, http, tmp_path):
    init_db()
    with SessionLocal() as s:
        s.query(NotificationOutbox).delete(); s.commit()
    GOT.clear()
    monkeypatch.setenv("SMS_URL", http + "/sms"); monkeypatch.setenv("ALERT_SMS_TO", "+911234567890")
    monkeypatch.setenv("WEBHOOK_URL", http + "/hook"); monkeypatch.setenv("WEBHOOK_SECRET", "k")
    monkeypatch.setenv("SLACK_WEBHOOK_URL", http + "/slack")
    monkeypatch.setenv("SIEM_FILE", str(tmp_path / "siem.log"))
    return tmp_path


def test_templates_and_siem_formats():
    m = notify.render("pii_reveal", {"kind": "PAN", "actor": "a@b", "college_id": 3, "justification": "audit case 12"})
    assert m["severity"] == "high" and "PAN" in m["subject"]
    cef = notify.siem_line(m, "cef")
    assert cef.startswith("CEF:0|SealCheck|SealCheck|1.0|pii_reveal|") and "|8|" in cef
    assert notify.siem_line(m, "syslog").startswith("<107>1 ")
    assert json.loads(notify.siem_line(m, "jsonl"))["kind"] == "pii_reveal"


def test_smtp_local_server(monkeypatch):
    from aiosmtpd.controller import Controller
    msgs = []
    class Handler:
        async def handle_DATA(self, server, session, envelope):
            msgs.append(envelope.content.decode()); return "250 OK"
    sk = socket.socket(); sk.bind(("127.0.0.1", 0)); port = sk.getsockname()[1]; sk.close()
    c = Controller(Handler(), hostname="127.0.0.1", port=port); c.start()
    try:
        monkeypatch.setenv("SMTP_HOST", "127.0.0.1"); monkeypatch.setenv("SMTP_PORT", str(port))
        monkeypatch.setenv("SMTP_STARTTLS", "0"); monkeypatch.setenv("ALERT_EMAIL_TO", "soc@aicte.example")
        notify.send_email(notify.render("integrity_failure", {"failed": [{"version_id": 1}]}))
    finally:
        c.stop()
    assert msgs and "WORM integrity failure (1 objects)" in msgs[0] and "soc@aicte.example" in msgs[0]


def test_dispatch_all_http_channels_and_siem(env, monkeypatch):
    monkeypatch.setenv("NOTIFY_CHANNELS", "inapp,sms,webhook,slack,siem")
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); udp.bind(("127.0.0.1", 0)); udp.settimeout(3)
    monkeypatch.setenv("SIEM_SYSLOG", f"127.0.0.1:{udp.getsockname()[1]}")
    notify.dispatch("sandbox_violation", {"detail": "socket() attempted"}, background=False)
    paths = sorted(p for p, _, _ in GOT)
    assert paths == ["/hook", "/slack", "/sms"]
    hook = next(g for g in GOT if g[0] == "/hook")
    import hashlib, hmac
    assert hook[1]["X-SealCheck-Signature"] == "sha256=" + hmac.new(b"k", hook[2], hashlib.sha256).hexdigest()
    assert "socket() attempted" in (env / "siem.log").read_text()
    assert b"sandbox_violation" in udp.recv(9000)
    with SessionLocal() as s:
        assert {r.status for r in s.query(NotificationOutbox).all()} == {"sent"}
        assert s.query(Notification).filter_by(kind="sandbox_violation").count() >= 1


def test_retry_then_dead_letter(env, monkeypatch):
    monkeypatch.setenv("NOTIFY_CHANNELS", "webhook")
    H.fail = 1
    notify.dispatch("decision", {"ref": "X", "decision": "ok"}, background=False)
    with SessionLocal() as s:
        r = s.query(NotificationOutbox).one(); assert r.status == "pending" and r.attempts == 1 and "503" in r.last_error
    notify.deliver_pending(now=datetime.utcnow() + timedelta(hours=1))
    with SessionLocal() as s:
        assert s.query(NotificationOutbox).one().status == "sent"
    monkeypatch.setenv("WEBHOOK_URL", "http://127.0.0.1:9/none")
    notify.dispatch("decision", {"ref": "Y", "decision": "ok"}, background=False)
    for i in range(notify.MAX_ATTEMPTS):
        notify.deliver_pending(now=datetime.utcnow() + timedelta(days=i + 1))
    with SessionLocal() as s:
        assert s.query(NotificationOutbox).filter_by(status="dead").count() == 1


def test_twilio_style_sms(env, monkeypatch, http):
    monkeypatch.setenv("SMS_PROVIDER", "twilio"); monkeypatch.setenv("TWILIO_SID", "AC1"); monkeypatch.setenv("TWILIO_TOKEN", "t")
    monkeypatch.setenv("TWILIO_FROM", "+100"); monkeypatch.setenv("TWILIO_BASE_URL", http)
    notify.send_sms(notify.render("decision", {"ref": "R", "decision": "d"}))
    p, h, b = GOT[-1]
    assert p == "/2010-04-01/Accounts/AC1/Messages.json" and h["Authorization"].startswith("Basic ") and b"To=%2B911234567890" in b
