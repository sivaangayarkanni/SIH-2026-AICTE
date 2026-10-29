"""Procedural SYNTHETIC 'lab room' images for evaluating photo-reuse detection. Not real photographs.

layout_seed fixes the room geometry (desk rows, monitor and poster positions); texture_seed fixes colours and
surface textures. Two images with the same layout_seed and different texture_seed are 'sibling rooms' built to
the same standard plan: the hard-negative case (similar-looking but different labs)."""
import cv2
import numpy as np

W, H = 1024, 768


def _texture(rng, h, w, base):
    noise = rng.normal(0, 1, (h // 8 + 1, w // 8 + 1, 1)).astype(np.float32)
    noise = cv2.resize(noise, (w, h), interpolation=cv2.INTER_CUBIC)[..., None] if noise.ndim == 3 else noise
    fine = rng.normal(0, 1, (h, w, 1)).astype(np.float32)
    t = np.clip(np.array(base, np.float32) + 18 * noise.reshape(h, w, 1) + 6 * fine, 0, 255)
    return t.astype(np.uint8)


def _paste(img, patch, y, x, h, w):
    y0, x0, y1, x1 = max(0, y), max(0, x), min(H, y + h), min(W, x + w)
    if y1 > y0 and x1 > x0:
        img[y0:y1, x0:x1] = cv2.resize(patch, (x1 - x0, y1 - y0), interpolation=cv2.INTER_NEAREST)


def scene(layout_seed: int, texture_seed: int) -> np.ndarray:
    L, T = np.random.default_rng(layout_seed), np.random.default_rng(10_000 + texture_seed)
    img = np.zeros((H, W, 3), np.uint8)
    horizon = int(H * L.uniform(0.38, 0.5))
    wall = T.integers(150, 235, 3); floor = T.integers(60, 160, 3)
    img[:horizon] = _texture(T, horizon, W, wall)
    img[horizon:] = _texture(T, H - horizon, W, floor)
    for _ in range(L.integers(1, 3)):  # windows
        x = int(L.uniform(0.05, 0.75) * W); w = int(L.uniform(0.12, 0.2) * W); y = int(L.uniform(0.05, 0.12) * H)
        cv2.rectangle(img, (x, y), (x + w, y + int(0.22 * H)), tuple(int(v) for v in T.integers(190, 255, 3)), -1)
        cv2.line(img, (x + w // 2, y), (x + w // 2, y + int(0.22 * H)), (90, 90, 90), 4)
    for _ in range(L.integers(1, 4)):  # posters / charts with random high-frequency content (keypoints)
        x = int(L.uniform(0.02, 0.85) * W); y = int(L.uniform(0.06, 0.25) * H); w = int(L.uniform(0.06, 0.12) * W)
        h = int(w * L.uniform(1.0, 1.4))
        patch = (T.random((h // 6 + 1, w // 6 + 1, 3)) * 255).astype(np.uint8)
        _paste(img, patch, y, x, h, w)
    rows = L.integers(2, 5)
    for r in range(rows):  # desk rows in perspective, each with monitors
        t = (r + 1) / (rows + 1)
        y = int(horizon + t * (H - horizon) * 0.9)
        half = int((0.25 + 0.7 * t) * W / 2); cx = W // 2 + int(L.uniform(-0.05, 0.05) * W)
        dh = int(10 + 30 * t)
        desk = tuple(int(v) for v in T.integers(80, 200, 3))
        cv2.rectangle(img, (cx - half, y), (cx + half, y + dh), desk, -1)
        n = L.integers(3, 8)
        for k in range(n):
            mx = cx - half + int((k + 0.5) * 2 * half / n); mw = int(18 + 50 * t); mh = int(mw * 0.7)
            cv2.rectangle(img, (mx - mw // 2, y - mh), (mx + mw // 2, y - 2), (25, 25, 30), -1)
            scr = (T.random((4, 6, 3)) * 255).astype(np.uint8)
            _paste(img, scr, y - mh + 3, mx - mw // 2 + 3, mh - 8, mw - 6)
            cv2.rectangle(img, (mx - 3, y - 2), (mx + 3, y + 2), (40, 40, 40), -1)
    return cv2.GaussianBlur(img, (3, 3), 0)


def reuse_variant(img: np.ndarray, seed: int, flip: bool = False) -> np.ndarray:
    """What a college might do to a copied photo: crop, rescale, slight rotation, colour shift, noise, recompress."""
    r = np.random.default_rng(seed)
    h, w = img.shape[:2]
    cf = r.uniform(0.72, 0.95); ch, cw = int(h * cf), int(w * cf)
    y0, x0 = r.integers(0, h - ch + 1), r.integers(0, w - cw + 1)
    out = img[y0:y0 + ch, x0:x0 + cw]
    M = cv2.getRotationMatrix2D((cw / 2, ch / 2), r.uniform(-4, 4), r.uniform(1.0, 1.06))
    out = cv2.warpAffine(out, M, (cw, ch), borderMode=cv2.BORDER_REFLECT)
    s = r.uniform(0.6, 1.0); out = cv2.resize(out, (int(cw * s), int(ch * s)), interpolation=cv2.INTER_AREA)
    out = np.clip(out.astype(np.float32) * r.uniform(0.8, 1.2) + r.uniform(-20, 20) + r.normal(0, 3, out.shape), 0, 255).astype(np.uint8)
    if flip:
        out = out[:, ::-1].copy()
    ok, enc = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, int(r.integers(45, 86))])
    return cv2.imdecode(enc, cv2.IMREAD_COLOR)
