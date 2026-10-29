"""VISION_BACKEND=remote: HTTP client for vision_service/ (Hugging Face Space or any Docker host).

Same contract as the in-process model worker (describe / verify). Any error (timeout, 5xx, bad token, sleeping
Space) raises, and service.model_photo_findings falls back to the classic checks and records why."""
import json, os
import httpx

URL = os.getenv("VISION_REMOTE_URL", "").rstrip("/")
TIMEOUT_S = float(os.getenv("VISION_REMOTE_TIMEOUT_S", "60"))


def _headers():
    h = {"X-SealCheck-Token": os.getenv("VISION_REMOTE_TOKEN", "")}
    if os.getenv("VISION_REMOTE_HF_TOKEN"):           # private HF Space
        h["Authorization"] = f"Bearer {os.environ['VISION_REMOTE_HF_TOKEN']}"
    return h


def configured() -> bool:
    return bool(URL and os.getenv("VISION_REMOTE_TOKEN"))


def _post(path, files, data=None, client=None):
    if not configured():
        raise RuntimeError("VISION_REMOTE_URL / VISION_REMOTE_TOKEN not set")
    c = client or httpx
    r = c.post(f"{URL}{path}", files=files, data=data or {}, headers=_headers(), timeout=TIMEOUT_S)
    if r.status_code != 200:
        raise RuntimeError(f"vision service {path} -> HTTP {r.status_code}: {r.text[:200]}")
    return r.json()


def describe(path, client=None):
    with open(path, "rb") as f:
        return _post("/v1/describe", {"image": ("q.jpg", f, "image/jpeg")}, client=client)


def verify(path, candidates, layout_hash_q=None, client=None):
    from ..storage import materialize
    cands = [c for c in candidates if materialize(c.get("path")) and os.path.exists(c["path"])]
    if not cands:
        return []
    fh = [open(c["path"], "rb") for c in cands]
    try:
        with open(path, "rb") as q:
            files = [("image", ("q.jpg", q, "image/jpeg"))] + [("candidates", (f"c{i}.jpg", f, "image/jpeg")) for i, f in enumerate(fh)]
            meta = [{"document_id": c["document_id"], "college_id": c["college_id"], "similarity": c["similarity"],
                     "layout_hash": c.get("layout_hash")} for c in cands]
            return _post("/v1/match", files, {"meta": json.dumps(meta), "layout_hash": layout_hash_q or ""}, client=client)["matches"]
    finally:
        for f in fh:
            f.close()


def health(client=None) -> dict:
    r = (client or httpx).get(f"{URL}/healthz", headers=_headers(), timeout=10)
    return r.json()
