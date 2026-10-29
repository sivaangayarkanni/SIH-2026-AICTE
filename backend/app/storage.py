"""Write-once (WORM) storage for originals.

STORAGE_BACKEND = fs (default) | s3

* fs - content-addressed files, chmod 0444, never overwritten. Tries `chattr +i`, which needs
       CAP_LINUX_IMMUTABLE, so it usually fails silently in containers. A user with write access
       to the directory can still delete files, so this is NOT real WORM.
* s3 - S3 Object Lock in COMPLIANCE mode (S3_BUCKET, S3_ENDPOINT_URL optional for MinIO,
       WORM_RETENTION_DAYS default 3650). The bucket must be created with Object Lock enabled.
       A local cache copy is still kept for the analysis pipeline. Tested with moto only,
       never against real AWS S3 or MinIO.
"""
from __future__ import annotations
import base64, hashlib, os, subprocess, time
from datetime import datetime, timedelta, timezone
from pathlib import Path


class FsWorm:
    name = "fs"

    def __init__(self, root: Path):
        self.root = Path(root)

    def put(self, data: bytes, sha: str, ext: str) -> str:
        p = self.root / f"{sha}.{ext}"
        if not p.exists():
            tmp = p.with_suffix(".tmp")
            tmp.write_bytes(data)
            os.chmod(tmp, 0o444)
            tmp.rename(p)
            try:
                subprocess.run(["chattr", "+i", str(p)], capture_output=True, timeout=5)
            except Exception:  # noqa: BLE001
                pass
        return str(p)

    def verify(self, key: str, sha: str) -> tuple[bool, str]:
        p = self.root / key
        if not p.exists():
            return False, "missing"
        ok = hashlib.sha256(p.read_bytes()).hexdigest() == sha
        return ok, "ok" if ok else "hash mismatch"


class S3Worm(FsWorm):
    name = "s3"

    def __init__(self, root: Path, bucket: str | None = None, client=None, retention_days: int | None = None):
        super().__init__(root)
        import boto3
        from botocore.config import Config
        self.bucket = bucket or os.environ["S3_BUCKET"]
        self.days = retention_days or int(os.environ.get("WORM_RETENTION_DAYS", "3650"))
        self.c = client or boto3.client("s3", endpoint_url=os.environ.get("S3_ENDPOINT_URL") or None,
                                        config=Config(connect_timeout=3, read_timeout=10,
                                                      retries={"max_attempts": 3, "mode": "standard"}))

    def put(self, data, sha, ext):
        local = super().put(data, sha, ext)
        key = f"originals/{sha}.{ext}"
        try:
            self.c.head_object(Bucket=self.bucket, Key=key)
            return local  # already stored: never overwrite
        except Exception:  # noqa: BLE001
            pass
        self.c.put_object(Bucket=self.bucket, Key=key, Body=data, ChecksumAlgorithm="SHA256",
                          ContentMD5=base64.b64encode(hashlib.md5(data).digest()).decode(),
                          ChecksumSHA256=base64.b64encode(bytes.fromhex(sha)).decode(),
                          ObjectLockMode="COMPLIANCE",
                          ObjectLockRetainUntilDate=datetime.now(timezone.utc) + timedelta(days=self.days),
                          Metadata={"sha256": sha})
        return local

    def verify(self, key, sha):
        ok, why = super().verify(key, sha)
        try:
            body = self.c.get_object(Bucket=self.bucket, Key=f"originals/{key}")["Body"].read()
        except Exception as e:  # noqa: BLE001
            return False, f"s3 unavailable: {type(e).__name__}"
        if hashlib.sha256(body).hexdigest() != sha:
            return False, "s3 hash mismatch"
        return ok, why if not ok else "ok (local + s3)"


_store = None


def get_store():
    global _store
    if _store is None:
        from .config import ORIGINALS_DIR
        _store = S3Worm(ORIGINALS_DIR) if os.environ.get("STORAGE_BACKEND", "fs") == "s3" else FsWorm(ORIGINALS_DIR)
    return _store


def integrity_check(session, store=None) -> dict:
    """Re-hash every original. Failures are written to the audit log and raised as an alert event."""
    from .db import DocumentVersion
    from . import audit
    from .events import notify_event
    store = store or get_store()
    t0 = time.time()
    bad = []
    rows = session.query(DocumentVersion).all()
    for v in rows:
        ok, why = store.verify(Path(v.stored_path).name, v.sha256)
        if not ok:
            bad.append({"version_id": v.id, "document_id": v.document_id, "reason": why})
    res = {"checked": len(rows), "failed": bad, "backend": store.name, "duration_ms": int((time.time() - t0) * 1000)}
    audit.log("integrity.check", target="storage", details={"checked": len(rows), "failed": len(bad), "backend": store.name})
    if bad:
        notify_event("integrity_failure", res)
    return res
