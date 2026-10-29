"""Model-based vision backend (VISION_BACKEND=models). Loaded lazily, once per vision-worker process.

* Global descriptor: DINOv2-small (facebook/dinov2-small, Apache-2.0) CLS embedding, 384-d, L2-normalised,
  stored in pgvector (photo_index.embedding) for nearest-neighbour candidate retrieval.
* Local verification: DISK keypoints + LightGlue matcher (kornia, Apache-2.0) + RANSAC fundamental-matrix inliers.
  SuperPoint was NOT used: its official weights are under Magic Leap's non-commercial licence.
* Detection: RT-DETR r18vd (PekingU/rtdetr_r18vd, Apache-2.0) trained on COCO-80. It detects COCO classes only
  (person, chair, dining table, tv, laptop, keyboard, mouse, monitor-like 'tv', bottle, ...). It does NOT know
  lab-specific equipment (oscilloscopes, lathes, fume hoods). We report raw COCO detections; we do not claim more.
* Room-structure layout hash: 8x8 grid of dominant edge orientation (Sobel, 4 bins) + detected-object grid occupancy,
  packed into a hex digest. It is a coarse layout fingerprint, not a learned room-layout model.
All weights download from Hugging Face on first use (HF_HOME cache); offline deployments must pre-seed the cache.
"""
import hashlib, os, threading
import numpy as np

_lock = threading.Lock()
_M = {}
DINO_ID = os.getenv("VISION_DINO_MODEL", "facebook/dinov2-small")
DETR_ID = os.getenv("VISION_DETR_MODEL", "PekingU/rtdetr_r18vd")
DET_THRESHOLD = float(os.getenv("VISION_DET_THRESHOLD", "0.5"))


def _torch():
    import torch
    torch.set_num_threads(int(os.getenv("VISION_THREADS", "2")))
    return torch


def _load(name):
    with _lock:
        if name in _M:
            return _M[name]
        _torch()
        if name == "dino":
            from transformers import AutoModel, AutoImageProcessor
            _M[name] = (AutoImageProcessor.from_pretrained(DINO_ID), AutoModel.from_pretrained(DINO_ID).eval())
        elif name == "detr":
            from transformers import RTDetrForObjectDetection, AutoImageProcessor
            _M[name] = (AutoImageProcessor.from_pretrained(DETR_ID), RTDetrForObjectDetection.from_pretrained(DETR_ID).eval())
        elif name == "lg":
            import kornia.feature as KF
            _M[name] = (KF.DISK.from_pretrained("depth").eval(), KF.LightGlueMatcher("disk").eval())
        return _M[name]


def _rgb(path, maxdim=None):
    from PIL import Image
    im = Image.open(path).convert("RGB")
    if maxdim and max(im.size) > maxdim:
        im.thumbnail((maxdim, maxdim))
    return im


def embed(path):
    torch = _torch()
    proc, model = _load("dino")
    with torch.inference_mode():
        out = model(**proc(images=_rgb(path), return_tensors="pt"))
    v = out.last_hidden_state[:, 0][0].numpy().astype(float)
    return (v / (np.linalg.norm(v) or 1)).tolist()


def cosine(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    return float(a @ b / ((np.linalg.norm(a) * np.linalg.norm(b)) or 1))


def local_match(a, b, maxdim=640):
    """DISK + LightGlue; returns matches and RANSAC (fundamental) inliers."""
    torch = _torch()
    import kornia as K
    import cv2
    disk, lg = _load("lg")

    def feats(p):
        t = K.image_to_tensor(np.asarray(_rgb(p, maxdim)), keepdim=False).float() / 255.0
        h, w = t.shape[-2:]
        t = t[..., : h // 16 * 16, : w // 16 * 16]
        with torch.inference_mode():
            f = disk(t, n=2048, pad_if_not_divisible=True)[0]
        return f, t.shape[-2:]

    (fa, sa), (fb, sb) = feats(a), feats(b)
    import kornia.feature as KF
    with torch.inference_mode():
        lafa = KF.laf_from_center_scale_ori(fa.keypoints[None], torch.ones(1, len(fa.keypoints), 1, 1))
        lafb = KF.laf_from_center_scale_ori(fb.keypoints[None], torch.ones(1, len(fb.keypoints), 1, 1))
        dists, idx = lg(fa.descriptors, fb.descriptors, lafa, lafb,
                        hw1=torch.tensor(sa), hw2=torch.tensor(sb))
    n = int(idx.shape[0])
    inl = 0
    if n >= 8:
        pa = fa.keypoints[idx[:, 0]].numpy(); pb = fb.keypoints[idx[:, 1]].numpy()
        _, mask = cv2.findFundamentalMat(pa, pb, cv2.USAC_MAGSAC, 1.0, 0.999, 10000)
        inl = int(mask.sum()) if mask is not None else 0
    return {"matches": n, "inliers": inl, "keypoints": [len(fa.keypoints), len(fb.keypoints)],
            "method": "DISK + LightGlue (kornia) + MAGSAC fundamental"}


def detect(path):
    torch = _torch()
    proc, model = _load("detr")
    im = _rgb(path, 800)
    with torch.inference_mode():
        out = model(**proc(images=im, return_tensors="pt"))
    res = proc.post_process_object_detection(out, target_sizes=torch.tensor([im.size[::-1]]), threshold=DET_THRESHOLD)[0]
    dets = []
    for s, l, b in zip(res["scores"], res["labels"], res["boxes"]):
        x0, y0, x1, y1 = [float(v) for v in b]
        dets.append({"label": model.config.id2label[int(l)], "score": round(float(s), 3),
                     "box": [round(x0 / im.width, 3), round(y0 / im.height, 3), round(x1 / im.width, 3), round(y1 / im.height, 3)]})
    return dets


def layout_hash(path, dets=()):
    import cv2
    g = np.asarray(_rgb(path, 512).convert("L"), dtype=np.float32)
    gx, gy = cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1)
    mag, ang = cv2.magnitude(gx, gy), (np.degrees(np.arctan2(gy, gx)) % 180)
    H, W = g.shape
    bits = []
    for i in range(8):
        for j in range(8):
            sl = (slice(i * H // 8, (i + 1) * H // 8), slice(j * W // 8, (j + 1) * W // 8))
            hist = np.histogram(ang[sl], bins=4, range=(0, 180), weights=mag[sl])[0]
            k = int(hist.argmax()); bits += [k >> 1 & 1, k & 1]
    occ = np.zeros((4, 4), int)
    for d in dets:
        cx, cy = (d["box"][0] + d["box"][2]) / 2, (d["box"][1] + d["box"][3]) / 2
        occ[min(3, int(cy * 4)), min(3, int(cx * 4))] = 1
    bits += occ.flatten().tolist()
    n = int("".join(map(str, bits)), 2)
    return f"{n:036x}", hashlib.sha256(str(n).encode()).hexdigest()[:16]


def layout_distance(a, b):
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def analyze(path, candidates):
    """candidates: [{document_id, college_id, path, similarity}] pre-selected by pgvector kNN."""
    emb = embed(path)
    dets = detect(path)
    lh, _ = layout_hash(path, dets)
    matches = []
    for c in candidates:
        try:
            sim = c.get("similarity")
            if sim is None and c.get("embedding") is not None:
                sim = cosine(emb, c["embedding"])
            lm = local_match(path, c["path"])
            matches.append({"document_id": c["document_id"], "college_id": c["college_id"], "cosine": round(sim or 0, 4),
                            "local": lm, "layout_distance": layout_distance(lh, c["layout_hash"]) if c.get("layout_hash") else None})
        except Exception as e:  # noqa: BLE001
            matches.append({"document_id": c.get("document_id"), "error": str(e)[:200]})
    return {"embedding": emb, "detections": dets, "layout_hash": lh, "matches": matches,
            "models": {"global": DINO_ID, "local": "kornia DISK+LightGlue", "detector": DETR_ID}}


def describe(path):
    dets = detect(path)
    lh, _ = layout_hash(path, dets)
    return {"embedding": embed(path), "detections": dets, "layout_hash": lh}


def verify(path, candidates, layout_hash_q=None):
    out = []
    for c in candidates:
        try:
            out.append({"document_id": c["document_id"], "college_id": c["college_id"], "cosine": round(c["similarity"], 4),
                        "local": local_match(path, c["path"]),
                        "layout_distance": layout_distance(layout_hash_q, c["layout_hash"]) if layout_hash_q and c.get("layout_hash") else None})
        except Exception as e:  # noqa: BLE001
            out.append({"document_id": c.get("document_id"), "college_id": c.get("college_id"), "error": str(e)[:200]})
    return out
