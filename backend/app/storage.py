"""Write-once (WORM) storage for originals.

STORAGE_BACKEND = fs (default) | s3 | db

* fs - content-addressed files, chmod 0444, never overwritten. Tries `chattr +i`, which needs
       CAP_LINUX_IMMUTABLE, so it usually fails silently in containers. A user with write access
       to the directory can still delete files, so this is NOT real WORM.
* s3 - S3 Object Lock in COMPLIANCE mode (S3_BUCKET, S3_ENDPOINT_URL optional for MinIO,
       WORM_RETENTION_DAYS default 3650). The bucket must be created with Object Lock enabled.
       A local cache copy is still kept for the analysis pipeline. Tested with moto only,
       never against real AWS S3 or MinIO.
* db - originals AND derived artefacts (sanitised copies) as rows in the `blobs` table (Postgres bytea).
       Insert-only: a DB trigger rejects UPDATE/DELETE, rows are keyed by name and carry their SHA-256,
       which is re-checked on every read. Every serverless instance sees the same objects; the local
       directory is only a cache that is rebuilt on demand (`materialize`).
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


class DbWorm(FsWorm):
    name = "db"

    def _insert(self, key: str, data: bytes, sha: str):
        from .db import SessionLocal, Blob
        with SessionLocal() as s:
            if s.get(Blob, key) is None:
                s.add(Blob(key=key, sha256=sha, size=len(data), data=data))
                try:
                    s.commit()
                except Exception:  # noqa: BLE001  concurrent insert of the same object
                    s.rollback()

    def put(self, data, sha, ext):
        local = super().put(data, sha, ext)
        self._insert(f"{sha}.{ext}", data, sha)
        return local

    def save_artifact(self, path: str):
        p = Path(path)
        if p.exists():
            data = p.read_bytes()
            self._insert(blob_key(path), data, hashlib.sha256(data).hexdigest())

    def fetch(self, key: str) -> bytes | None:
        from .db import SessionLocal, Blob
        with SessionLocal() as s:
            b = s.get(Blob, key)
            if b is None:
                return None
            data = bytes(b.data)
            if hashlib.sha256(data).hexdigest() != b.sha256:
                raise RuntimeError(f"blob {key}: stored hash does not match content")
            return data

    def verify(self, key, sha):
        try:
            data = self.fetch(key)
        except RuntimeError:
            return False, "db hash mismatch"
        if data is None:
            return False, "missing in db"
        return (True, "ok (db)") if hashlib.sha256(data).hexdigest() == sha else (False, "db hash mismatch")


def blob_key(path: str) -> str:
    """Originals are keyed '<sha>.<ext>'; derived artifacts by their path under DATA_DIR (e.g. 'sanitized/doc7_v1.pdf')."""
    from .config import DATA_DIR, ORIGINALS_DIR
    p = Path(path)
    if p.parent == Path(ORIGINALS_DIR):
        return p.name
    try:
        return p.relative_to(DATA_DIR).as_posix()
    except ValueError:
        return p.name


def materialize(path: str | None) -> str | None:
    """Make sure a stored file exists in this instance's local cache (db backend); returns the path."""
    if not path or os.path.exists(path):
        return path
    st = get_store()
    if isinstance(st, DbWorm):
        data = st.fetch(blob_key(path))
        if data is not None:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            tmp = Path(path).with_suffix(".part")
            tmp.write_bytes(data); tmp.rename(path)
    return path


def save_artifact(path: str | None):
    st = get_store()
    if path and isinstance(st, DbWorm):
        st.save_artifact(path)


_store = None


def get_store():
    global _store
    if _store is None:
        from .config import ORIGINALS_DIR
        b = os.environ.get("STORAGE_BACKEND", "fs")
        _store = S3Worm(ORIGINALS_DIR) if b == "s3" else DbWorm(ORIGINALS_DIR) if b == "db" else FsWorm(ORIGINALS_DIR)
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
