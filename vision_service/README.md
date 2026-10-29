---
title: SealCheck Vision
emoji: 🔎
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
license: apache-2.0
---

# SealCheck vision service

Model-based photo checks for SealCheck: **DINOv2-small** global embeddings (Apache-2.0), **DISK + LightGlue**
geometric matching (kornia, Apache-2.0) and **RT-DETR r18vd** object detection (Apache-2.0, COCO-80 classes only).
No AGPL code (no Ultralytics YOLO), no SuperPoint (non-commercial weights).

It exists because PyTorch does not fit in a Vercel function. SealCheck calls it with `VISION_BACKEND=remote`.
If it is unreachable, SealCheck falls back to its built-in pHash + ORB checks and records that in the findings.

## Endpoints (all `/v1/*` need the header `X-SealCheck-Token: $VISION_SERVICE_TOKEN`)

| Method | Path | Body (multipart) | Returns |
|---|---|---|---|
| GET | `/healthz` | – | models, which are loaded |
| POST | `/v1/embed` | `image` | 384-d L2-normalised DINOv2 embedding |
| POST | `/v1/detect` | `image` | COCO detections (label, score, normalised box) |
| POST | `/v1/describe` | `image` | embedding + detections + layout hash |
| POST | `/v1/match` | `image`, `candidates` (1–5 files), `meta` (JSON list), `layout_hash` | cosine, LightGlue inliers, layout distance per candidate |

## Host it on a free Hugging Face Space (you create the account; nothing here does it for you)

1. Sign in at https://huggingface.co and choose **New Space**. Pick **Docker** as the SDK, the free **CPU basic** hardware, and
   **Private** visibility if you prefer.
2. Upload the contents of this folder (`server.py`, `models.py`, `prefetch.py`, `requirements.txt`, `Dockerfile`, `README.md`) to the Space
   repository (web upload, or `git clone https://huggingface.co/spaces/<you>/<space>` then copy and push).
3. In the Space **Settings → Variables and secrets**, add a secret `VISION_SERVICE_TOKEN` with a long random value
   (for example the output of `python -c "import secrets; print(secrets.token_urlsafe(32))"`).
4. Wait for the build (about 10–15 minutes the first time), then open `https://<you>-<space>.hf.space/healthz`.
5. In the SealCheck Vercel project set:
   `VISION_BACKEND=remote`, `VISION_REMOTE_URL=https://<you>-<space>.hf.space`, `VISION_REMOTE_TOKEN=<the same token>`, and redeploy.

Free CPU Spaces sleep after inactivity; the first request after a sleep can take a minute, and SealCheck's
client times out after `VISION_REMOTE_TIMEOUT_S` (default 60 s) and then uses the classic checks for that document.
A private Space also needs `VISION_REMOTE_HF_TOKEN` (a read token) so SealCheck can reach it.

## Run it anywhere else

```bash
docker build -t sealcheck-vision .
docker run -p 7860:7860 -e VISION_SERVICE_TOKEN=$(python -c "import secrets;print(secrets.token_urlsafe(32))") sealcheck-vision
```

## Honest limits
- RT-DETR knows COCO classes (person, chair, tv/monitor, laptop, keyboard, …), not oscilloscopes, lathes or fume hoods.
  Fine-tuning it for lab equipment needs real labelled AICTE inspection photos, which this project does not have.
- Thresholds were calibrated on a synthetic set (see `ml/eval/REPORT.md` in the SealCheck repo). That is not real-world accuracy.
