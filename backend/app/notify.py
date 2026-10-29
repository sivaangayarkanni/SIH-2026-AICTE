"""Notification fan-out with a persistent retry outbox.

NOTIFY_CHANNELS (comma list): inapp (always on), email, sms, webhook, slack, siem
* email   - SMTP via aiosmtplib: SMTP_HOST, SMTP_PORT (587), SMTP_USER, SMTP_PASSWORD, SMTP_STARTTLS (1), SMTP_FROM, ALERT_EMAIL_TO
* sms     - SMS_PROVIDER=http (POST JSON to SMS_URL with bearer SMS_TOKEN) | twilio (TWILIO_SID, TWILIO_TOKEN, TWILIO_FROM); ALERT_SMS_TO
* webhook - WEBHOOK_URL, signed with HMAC-SHA256 (WEBHOOK_SECRET) in X-SealCheck-Signature
* slack   - SLACK_WEBHOOK_URL (incoming webhook)
* siem    - SIEM_FORMAT=jsonl|cef|syslog; SIEM_FILE (JSONL/CEF lines appended) and/or SIEM_SYSLOG=host:port (UDP, RFC 5424)
Tested here against a local SMTP server (aiosmtpd), local HTTP mocks and a local UDP socket. Not tested with
any real provider (no Twilio, Slack or mail relay accounts were used).
"""
from __future__ import annotations
import hashlib, hmac, json, logging, os, socket, threading, time
from datetime import datetime, timedelta, timezone

log = logging.getLogger("sealcheck.notify")
MAX_ATTEMPTS = int(os.environ.get("NOTIFY_MAX_ATTEMPTS", "5"))

TEMPLATES = {  # kind -> (severity, subject, body)
    "pii_reveal": ("high", "PII revealed: {kind} by {actor}", "{actor} revealed a {kind} value for college {college_id}. Justification: {justification}"),
    "integrity_failure": ("critical", "WORM integrity failure ({n} objects)", "Integrity check found {n} original(s) whose hash no longer matches. Details: {failed}"),
    "override_requested": ("medium", "Override awaiting approval", "{actor} requested an override on {target}."),
    "decision": ("info", "Decision recorded: {ref}", "{ref}: {decision}"),
    "sandbox_violation": ("high", "Sandbox violation", "{detail}"),
}
SEV_CEF = {"info": 3, "medium": 5, "high": 8, "critical": 10}


def render(kind: str, data: dict) -> dict:
    sev, subj, body = TEMPLATES.get(kind, ("info", kind, "{data}"))
    ctx = {"data": json.dumps(data, default=str)[:500], "n": len(data.get("failed", [])) if isinstance(data.get("failed"), list) else 0, **data}

    class D(dict):
        def __missing__(self, k): return "?"
    return {"kind": kind, "severity": sev, "subject": subj.format_map(D(ctx))[:200], "body": body.format_map(D(ctx))[:2000],
            "data": data, "ts": datetime.now(timezone.utc).isoformat()}


def channels() -> list[str]:
    return [c.strip() for c in os.environ.get("NOTIFY_CHANNELS", "inapp").split(",") if c.strip()]


# ---------------- channel senders (raise on failure -> retried) ----------------
def send_email(msg: dict):
    import asyncio
    import aiosmtplib
    from email.message import EmailMessage
    m = EmailMessage()
    m["From"] = os.environ.get("SMTP_FROM", "sealcheck@localhost")
    m["To"] = os.environ["ALERT_EMAIL_TO"]
    m["Subject"] = f"[SealCheck {msg['severity'].upper()}] {msg['subject']}"
    m.set_content(msg["body"])
    asyncio.run(aiosmtplib.send(m, hostname=os.environ.get("SMTP_HOST", "localhost"), port=int(os.environ.get("SMTP_PORT", "587")),
                                username=os.environ.get("SMTP_USER") or None, password=os.environ.get("SMTP_PASSWORD") or None,
                                start_tls=os.environ.get("SMTP_STARTTLS", "1") == "1", timeout=10))


def _http():
    import httpx
    return httpx.Client(timeout=httpx.Timeout(5.0, connect=3.0))


def send_sms(msg: dict):
    text = f"SealCheck {msg['severity'].upper()}: {msg['subject']}"[:160]
    to = os.environ["ALERT_SMS_TO"]
    with _http() as h:
        if os.environ.get("SMS_PROVIDER", "http") == "twilio":
            sid = os.environ["TWILIO_SID"]
            base = os.environ.get("TWILIO_BASE_URL", "https://api.twilio.com")
            r = h.post(f"{base}/2010-04-01/Accounts/{sid}/Messages.json", auth=(sid, os.environ["TWILIO_TOKEN"]),
                       data={"From": os.environ["TWILIO_FROM"], "To": to, "Body": text})
        else:
            tok = os.environ.get("SMS_TOKEN")
            r = h.post(os.environ["SMS_URL"], headers={"Authorization": f"Bearer {tok}"} if tok else {}, json={"to": to, "text": text})
        r.raise_for_status()


def send_webhook(msg: dict):
    body = json.dumps(msg, default=str).encode()
    sig = hmac.new(os.environ.get("WEBHOOK_SECRET", "").encode(), body, hashlib.sha256).hexdigest()
    with _http() as h:
        h.post(os.environ["WEBHOOK_URL"], content=body, headers={"Content-Type": "application/json",
                                                                 "X-SealCheck-Signature": f"sha256={sig}"}).raise_for_status()


def send_slack(msg: dict):
    with _http() as h:
        h.post(os.environ["SLACK_WEBHOOK_URL"], json={"text": f"*{msg['severity'].upper()}* {msg['subject']}\n{msg['body']}"}).raise_for_status()


def _cef_escape(s: str) -> str:
    return str(s).replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def siem_line(msg: dict, fmt: str) -> str:
    if fmt == "cef":
        ext = " ".join(f"{k}={str(v).replace('=', chr(92) + '=')[:200]}" for k, v in
                       {"rt": msg["ts"], "msg": msg["body"][:500], "cs1Label": "kind", "cs1": msg["kind"]}.items())
        return f"CEF:0|SealCheck|SealCheck|1.0|{_cef_escape(msg['kind'])}|{_cef_escape(msg['subject'])}|{SEV_CEF.get(msg['severity'], 3)}|{ext}"
    if fmt == "syslog":
        pri = 8 * 13 + {"info": 6, "medium": 5, "high": 3, "critical": 2}.get(msg["severity"], 6)  # facility 13 = log audit
        return f"<{pri}>1 {msg['ts']} {socket.gethostname()} sealcheck - {msg['kind']} - {json.dumps({'subject': msg['subject'], 'data': msg['data']}, default=str)}"
    return json.dumps(msg, default=str)


def send_siem(msg: dict):
    fmt = os.environ.get("SIEM_FORMAT", "jsonl")
    line = siem_line(msg, fmt)
    if os.environ.get("SIEM_FILE"):
        with open(os.environ["SIEM_FILE"], "a") as f:
            f.write(line + "\n")
    if os.environ.get("SIEM_SYSLOG"):
        host, port = os.environ["SIEM_SYSLOG"].rsplit(":", 1)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.sendto((line if fmt == "syslog" else siem_line(msg, "syslog")).encode()[:8000], (host, int(port)))
        finally:
            s.close()


SENDERS = {"email": send_email, "sms": send_sms, "webhook": send_webhook, "slack": send_slack, "siem": send_siem}


# ---------------- outbox ----------------
def dispatch(kind: str, data: dict, background: bool = True):
    from .db import SessionLocal, Notification, NotificationOutbox
    msg = render(kind, data)
    with SessionLocal() as s:
        s.add(Notification(role="admin", message=msg["subject"], link="/notifications", kind=kind, severity=msg["severity"]))
        for ch in channels():
            if ch in SENDERS:
                s.add(NotificationOutbox(channel=ch, kind=kind, payload=json.dumps(msg, default=str), status="pending", attempts=0))
        s.commit()
    if background:
        threading.Thread(target=deliver_pending, daemon=True).start()
    else:
        deliver_pending()


_deliver_lock = threading.Lock()


def deliver_pending(now: datetime | None = None) -> dict:
    from .db import SessionLocal, NotificationOutbox
    stats = {"sent": 0, "retry": 0, "dead": 0}
    with _deliver_lock, SessionLocal() as s:
        t = now or datetime.utcnow()
        rows = s.query(NotificationOutbox).filter(NotificationOutbox.status == "pending").all()
        for r in rows:
            if r.next_at and r.next_at > t:
                continue
            try:
                SENDERS[r.channel](json.loads(r.payload))
                r.status, r.sent_at, r.last_error = "sent", t, None
                stats["sent"] += 1
            except Exception as e:  # noqa: BLE001
                r.attempts += 1
                r.last_error = f"{type(e).__name__}: {e}"[:300]
                if r.attempts >= MAX_ATTEMPTS:
                    r.status = "dead"; stats["dead"] += 1
                else:
                    r.next_at = t + timedelta(seconds=min(3600, 5 * 2 ** r.attempts)); stats["retry"] += 1
                log.warning("notify %s failed (%s/%s): %s", r.channel, r.attempts, MAX_ATTEMPTS, r.last_error)
            r.attempts = r.attempts if r.status != "sent" else r.attempts + 1
        s.commit()
    return stats


def start_retry_loop(interval_s: int = 30):
    def loop():
        while True:
            time.sleep(interval_s)
            try:
                deliver_pending()
            except Exception:  # noqa: BLE001
                log.exception("outbox retry loop")
    threading.Thread(target=loop, daemon=True, name="sealcheck-notify-retry").start()
