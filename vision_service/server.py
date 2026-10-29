"""SealCheck vision service: DINOv2-small embeddings, RT-DETR (COCO) detection, DISK+LightGlue matching.

Runs where PyTorch fits (Hugging Face Space, any Docker host), NOT on Vercel. The SealCheck API calls it with
VISION_BACKEND=remote, VISION_REMOTE_URL and VISION_REMOTE_TOKEN; if it is down, SealCheck falls back to the
classic pHash+ORB checks and says so in the findings.

Auth: every /v1/* request needs `X-SealCheck-Token: $VISION_SERVICE_TOKEN` (or `Authorization: Bearer ...`) (startup fails without a token).
Limits: images <= 10 MB, <= 5 candidates per /v1/match. Images are decoded with Pillow and re-encoded before use;
nothing is stored after the request."""
import hmac, io, json, os, tempfile
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from PIL import Image

import models as M

TOKEN = os.environ.get("VISION_SERVICE_TOKEN", "")
if len(TOKEN) < 24 and os.environ.get("VISION_SERVICE_ALLOW_NO_TOKEN") != "1":
    raise SystemExit("Set VISION_SERVICE_TOKEN (>= 24 random characters) before starting the vision service.")
MAX_BYTES = int(os.environ.get("VISION_MAX_BYTES", str(10 * 1024 * 1024)))
MAX_CANDS = 5
Image.MAX_IMAGE_PIXELS = 40_000_000
app = FastAPI(title="SealCheck vision service", version="1.0.0", docs_url=None, redoc_url=None)


def auth(x_sealcheck_token: str = Header(""), authorization: str = Header("")):
    # X-SealCheck-Token is preferred so that `Authorization` stays free for a private Hugging Face Space's HF token
    given = x_sealcheck_token or (authorization[7:] if authorization.lower().startswith("bearer ") else "")
    if TOKEN and not hmac.compare_digest(given.encode(), TOKEN.encode()):
        raise HTTPException(401, "bad or missing service token")


async def _img(f: UploadFile, d: str, name: str) -> str:
    data = await f.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, f"{f.filename}: image larger than {MAX_BYTES} bytes")
    try:
        im = Image.open(io.BytesIO(data)); im.load(); im = im.convert("RGB")
    except Exception:
        raise HTTPException(415, f"{f.filename}: not a decodable image")
    p = str(Path(d) / f"{name}.jpg"); im.save(p, "JPEG", quality=95)
    return p


@app.get("/healthz")
def healthz():
    return {"ok": True, "models": {"global": M.DINO_ID, "detector": M.DETR_ID, "local": "kornia DISK+LightGlue"},
            "loaded": sorted(M._M), "auth": bool(TOKEN)}


@app.post("/v1/embed", dependencies=[Depends(auth)])
async def embed(image: UploadFile = File(...)):
    with tempfile.TemporaryDirectory() as d:
        return {"embedding": M.embed(await _img(image, d, "q")), "model": M.DINO_ID}


@app.post("/v1/detect", dependencies=[Depends(auth)])
async def detect(image: UploadFile = File(...)):
    with tempfile.TemporaryDirectory() as d:
        return {"detections": M.detect(await _img(image, d, "q")), "model": M.DETR_ID,
                "note": "COCO-80 classes only; not trained on laboratory equipment."}


@app.post("/v1/describe", dependencies=[Depends(auth)])
async def describe(image: UploadFile = File(...)):
    with tempfile.TemporaryDirectory() as d:
        return M.describe(await _img(image, d, "q"))


@app.post("/v1/match", dependencies=[Depends(auth)])
async def match(image: UploadFile = File(...), candidates: list[UploadFile] = File(...), meta: str = Form("[]"),
                layout_hash: str = Form("")):
    """meta: JSON list aligned with `candidates`: [{document_id, college_id, similarity, layout_hash}]"""
    try:
        info = json.loads(meta)
    except ValueError:
        raise HTTPException(422, "meta must be JSON")
    if len(candidates) > MAX_CANDS or len(info) != len(candidates):
        raise HTTPException(422, f"1..{MAX_CANDS} candidates with one meta entry each")
    with tempfile.TemporaryDirectory() as d:
        q = await _img(image, d, "q")
        cands = [{**m, "path": await _img(c, d, f"c{i}")} for i, (c, m) in enumerate(zip(candidates, info))]
        return {"matches": M.verify(q, cands, layout_hash or None)}
