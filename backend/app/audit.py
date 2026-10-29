"""Append-only, hash-linked audit log (tamper-evident). Each entry's hash covers the previous hash."""
import hashlib, json, threading
from datetime import datetime, timezone
from .db import AuditLog, SessionLocal

GENESIS = "0" * 64
_lock = threading.Lock()


def _entry_hash(prev: str, e: dict) -> str:
    canon = json.dumps(e, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256((prev + canon).encode()).hexdigest()


def _fields(row) -> dict:
    return {"ts": row.ts, "actor": row.actor, "role": row.role, "action": row.action,
            "target": row.target, "ip": row.ip, "details": row.details}


def log(action: str, actor: str = "system", role: str = "system", target: str = "", details=None, ip: str = ""):
    with _lock:
        s = SessionLocal()
        try:
            last = s.query(AuditLog).order_by(AuditLog.id.desc()).first()
            prev = last.hash if last else GENESIS
            row = AuditLog(ts=datetime.now(timezone.utc).isoformat(timespec="milliseconds"), actor=actor, role=role,
                           action=action, target=target, ip=ip or "",
                           details=json.dumps(details or {}, sort_keys=True, default=str))
            row.prev_hash = prev
            row.hash = _entry_hash(prev, _fields(row))
            s.add(row)
            s.commit()
            return row.hash
        finally:
            s.close()


def verify_chain(session=None) -> dict:
    s = session or SessionLocal()
    try:
        prev = GENESIS
        n = 0
        for row in s.query(AuditLog).order_by(AuditLog.id.asc()).yield_per(500):
            n += 1
            if row.prev_hash != prev:
                return {"valid": False, "entries": n, "broken_at": row.id, "reason": "prev_hash link broken"}
            if _entry_hash(prev, _fields(row)) != row.hash:
                return {"valid": False, "entries": n, "broken_at": row.id, "reason": "entry content altered"}
            prev = row.hash
        return {"valid": True, "entries": n, "head": prev}
    finally:
        if session is None:
            s.close()
