"""WORM storage: fs fallback and S3 Object Lock (COMPLIANCE) against moto. Never tested on real S3/MinIO."""
import hashlib, os, sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app import storage  # noqa: E402


def test_fs_worm_readonly_and_verify(tmp_path):
    st = storage.FsWorm(tmp_path)
    data = b"%PDF-1.4 original"
    sha = hashlib.sha256(data).hexdigest()
    p = Path(st.put(data, sha, "pdf"))
    assert not os.access(p, os.W_OK) or os.geteuid() == 0
    assert st.verify(p.name, sha) == (True, "ok")
    os.chmod(p, 0o644); p.write_bytes(b"tampered")
    assert st.verify(p.name, sha)[0] is False


def test_s3_object_lock_moto(tmp_path, monkeypatch):
    moto = pytest.importorskip("moto")
    import boto3
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "t"); monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "t")
    with moto.mock_aws():
        c = boto3.client("s3")
        c.create_bucket(Bucket="worm", ObjectLockEnabledForBucket=True)
        st = storage.S3Worm(tmp_path, bucket="worm", client=c, retention_days=1)
        data = b"original bytes"
        sha = hashlib.sha256(data).hexdigest()
        st.put(data, sha, "pdf")
        st.put(data, sha, "pdf")  # idempotent, no overwrite
        h = c.head_object(Bucket="worm", Key=f"originals/{sha}.pdf")
        assert h["ObjectLockMode"] == "COMPLIANCE"  # (moto's GetObjectRetention 500s, so read via HEAD)
        vid = h["VersionId"]
        with pytest.raises(Exception):
            c.delete_object(Bucket="worm", Key=f"originals/{sha}.pdf", VersionId=vid)
        assert st.verify(f"{sha}.pdf", sha) == (True, "ok (local + s3)")
        ok, why = storage.S3Worm(tmp_path, bucket="missing", client=c).verify(f"{sha}.pdf", sha)
        assert not ok and why.startswith("s3 unavailable")


def test_integrity_job_detects_tamper(tmp_path):
    from app.db import SessionLocal, DocumentVersion, init_db
    init_db()
    with SessionLocal() as s:
        v = s.query(DocumentVersion).first()
        if v is None:
            pytest.skip("no seeded versions")
        res = storage.integrity_check(s)
        assert res["checked"] >= 1 and res["failed"] == []
        class Bad(storage.FsWorm):
            def verify(self, key, sha): return False, "hash mismatch"
        res = storage.integrity_check(s, Bad(tmp_path))
        assert len(res["failed"]) == res["checked"]
