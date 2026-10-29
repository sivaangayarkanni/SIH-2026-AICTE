"""Production plumbing: probes, metrics, request IDs, headers, rate limiter, prod fail-fast, queues."""
import os, sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from fastapi.testclient import TestClient  # noqa: E402
from app import ops  # noqa: E402


@pytest.fixture(scope="module")
def client():
    from app.main import app
    with TestClient(app) as c:
        yield c


def test_probes_metrics_request_id(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    r = client.get("/readyz"); assert r.status_code == 200 and r.json()["checks"]["db"] == "ok"
    r = client.get("/api/auth/config", headers={"X-Request-ID": "abc-123"})
    assert r.headers["X-Request-ID"] == "abc-123"
    assert r.headers["X-Content-Type-Options"] == "nosniff" and "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert client.get("/api/auth/config", headers={"X-Request-ID": "bad id<script>"}).headers["X-Request-ID"] != "bad id<script>"
    m = client.get("/metrics").text
    assert "sealcheck_http_requests_total" in m and 'route="/api/auth/config"' in m


def test_rate_limiter_memory_and_redis():
    rl = ops.RateLimiter()
    assert all(rl.hit("k", 3, 60) for _ in range(3)) and not rl.hit("k", 3, 60)
    fakeredis = pytest.importorskip("fakeredis")
    r = ops.RateLimiter(fakeredis.FakeRedis())
    assert all(r.hit("k", 2, 60) for _ in range(2)) and not r.hit("k", 2, 60)


def test_rate_limit_middleware(client, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT", "on")
    client.app.state.rate_limiter.mem.clear()
    codes = [client.post("/api/auth/login", json={"email": "x@y.z", "password": "bad"}).status_code for _ in range(12)]
    assert 429 in codes and codes.index(429) >= 8 and codes[-1] == 429
    client.app.state.rate_limiter.mem.clear()


def test_production_fail_fast():
    probs = ops.validate_production_config({})
    assert any("JWT" in p for p in probs) and any("PostgreSQL" in p for p in probs) and any("KMS" in p for p in probs)
    good = {"SEALCHECK_JWT_SECRET": "x" * 40, "AUTH_MODE": "oidc", "OIDC_ISSUER": "https://idp", "DATABASE_URL": "postgresql://h/db",
            "KMS_BACKEND": "aws", "STORAGE_BACKEND": "s3", "SANDBOX_BACKEND": "namespace", "QUEUE_BACKEND": "rq",
            "CORS_ORIGINS": "https://sealcheck.example"}
    assert ops.validate_production_config(good) == []
    import subprocess
    env = {**os.environ, "ENV": "production", "AUTH_MODE": "local"}
    r = subprocess.run([sys.executable, "-c", "import app.main"], cwd=str(Path(__file__).resolve().parents[1] / "backend"),
                       env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode != 0 and "Refusing to start in ENV=production" in r.stderr


def test_rq_queue_fakeredis(monkeypatch):
    fakeredis = pytest.importorskip("fakeredis")
    from rq import SimpleWorker
    from app import queue_worker, service
    conn = fakeredis.FakeRedis()
    ran = []
    monkeypatch.setattr(service, "run_job", lambda jid: ran.append(jid))
    q = queue_worker.rq_queue(conn)
    q.enqueue(service.run_job_task, 4242)
    SimpleWorker([q], connection=conn).work(burst=True)
    assert ran == [4242]


def test_db_queue_claim():
    from app.db import SessionLocal, Job, Document, init_db
    from app import queue_worker
    init_db()
    with SessionLocal() as s:
        d = s.query(Document).first()
        if d is None:
            pytest.skip("no seeded document")
        j = Job(document_id=d.id, status="queued", progress_json=[]); s.add(j); s.commit(); jid = j.id
        got = []
        while (c := queue_worker.claim_next(s)) is not None:
            got.append(c)
        assert jid in got
        s.expire_all()
        assert s.get(Job, jid).status == "running"
        s.get(Job, jid).status = "done"; s.commit()
