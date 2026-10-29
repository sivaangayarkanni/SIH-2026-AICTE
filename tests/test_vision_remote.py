"""VISION_BACKEND=remote: contract test of vision_service/server.py with the model functions stubbed (fast, no torch),
plus the SealCheck client and its classic fallback. The real models are exercised in test_vision.py."""
import importlib, sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from conftest import SAMPLES

VS = Path(__file__).resolve().parent.parent / "vision_service"
TOKEN = "t" * 32


@pytest.fixture()
def svc(monkeypatch):
    monkeypatch.setenv("VISION_SERVICE_TOKEN", TOKEN)
    monkeypatch.syspath_prepend(str(VS))
    for m in ("server", "models"):
        sys.modules.pop(m, None)
    vs = importlib.import_module("server")
    M = vs.M
    monkeypatch.setattr(M, "describe", lambda p: {"embedding": [0.1] * 384, "detections": [{"label": "tv", "score": 0.9, "box": [0, 0, 1, 1]}], "layout_hash": "ab"})
    monkeypatch.setattr(M, "verify", lambda p, c, lh=None: [{"document_id": x["document_id"], "college_id": x["college_id"], "cosine": 0.97,
                                                             "local": {"inliers": 400}, "layout_distance": 1} for x in c])
    monkeypatch.setattr(M, "embed", lambda p: [0.0] * 384)
    yield TestClient(vs.app)
    for m in ("server", "models"):
        sys.modules.pop(m, None)


def test_service_requires_token(svc):
    img = (SAMPLES / "svit_lab_cse.jpg").read_bytes()
    assert svc.get("/healthz").json()["auth"] is True
    assert svc.post("/v1/embed", files={"image": ("a.jpg", img)}).status_code == 401
    assert svc.post("/v1/embed", files={"image": ("a.jpg", img)}, headers={"X-SealCheck-Token": "wrong" * 8}).status_code == 401
    r = svc.post("/v1/embed", files={"image": ("a.jpg", img)}, headers={"X-SealCheck-Token": TOKEN})
    assert r.status_code == 200 and len(r.json()["embedding"]) == 384
    assert svc.post("/v1/detect", files={"image": ("a.jpg", b"not an image")}, headers={"X-SealCheck-Token": TOKEN}).status_code == 415


def test_client_roundtrip_and_fallback(svc, monkeypatch):
    from app.vision import remote, client as vc
    import app.service as service
    monkeypatch.setattr(remote, "URL", "http://testserver"); monkeypatch.setenv("VISION_REMOTE_TOKEN", TOKEN)
    monkeypatch.setattr(remote, "httpx", svc)          # route the client's HTTP calls into the service app
    monkeypatch.setattr(vc, "BACKEND", "remote")
    q, c = str(SAMPLES / "diem_lab_reused.jpg"), str(SAMPLES / "svit_lab_cse.jpg")
    r = vc.analyze_with_models(q, lambda e: [{"document_id": 7, "college_id": 1, "path": c, "similarity": 0.95, "layout_hash": "ab"}])
    assert r["backend"] == "remote" and r["matches"][0]["document_id"] == 7 and vc.is_duplicate(r["matches"][0])

    class Down:
        def post(self, *a, **k):
            raise ConnectionError("space is sleeping")
    monkeypatch.setattr(remote, "httpx", Down())
    import app.db as db
    monkeypatch.setattr(db, "similar_photos", lambda *a, **k: [])
    photo_res = {}
    out = service.model_photo_findings(None, photo_res, q, 1)
    assert photo_res["vision_backend"] == "classic (remote failed)" and out[0]["rule_id"] == "I-VIS-00"


def test_service_models_in_sync_with_backend():
    a = (VS / "models.py").read_text(); b = (VS.parent / "backend" / "app" / "vision" / "models.py").read_text()
    assert a == b, "copy backend/app/vision/models.py to vision_service/models.py"
