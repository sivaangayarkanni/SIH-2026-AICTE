import os
"""4C · Infrastructure / Lab Photo Inspector (local equivalent of the GPU pipeline).
EXIF geotag extraction, perceptual hash + OpenCV ORB keypoint matching for reused photos, and simple
room-structure cues (straight-line/edge statistics). Production plugs DINOv2/LightGlue + a permissive-licence
object detector into `PhotoMatcher`/`RoomAnalyzer`."""
import math
import numpy as np
import cv2
try:
    import imagehash
except ImportError:  # slim serverless install: identical pHash computed with numpy below
    imagehash = None
from PIL import Image, ExifTags


def _ratio(v):
    try:
        return float(v)
    except Exception:
        return float(v[0]) / float(v[1])


def exif_info(path: str) -> dict:
    with Image.open(path) as im:
        ex = im.getexif()
        base = {ExifTags.TAGS.get(k, str(k)): v for k, v in ex.items()}
        gps = ex.get_ifd(0x8825) if ex else {}
        lat = lon = None
        if gps and 2 in gps and 4 in gps:
            def dms(t):
                return _ratio(t[0]) + _ratio(t[1]) / 60 + _ratio(t[2]) / 3600
            lat = dms(gps[2]) * (-1 if gps.get(1) in ("S", b"S") else 1)
            lon = dms(gps[4]) * (-1 if gps.get(3) in ("W", b"W") else 1)
        return {"width": im.width, "height": im.height, "make": str(base.get("Make", "")) or None,
                "model": str(base.get("Model", "")) or None, "datetime": str(base.get("DateTime", "")) or None,
                "software": str(base.get("Software", "")) or None,
                "gps": {"lat": round(lat, 6), "lon": round(lon, 6)} if lat is not None else None}


_N = 32
_DCT = 2 * np.cos(np.pi * np.outer(np.arange(_N), 2 * np.arange(_N) + 1) / (2 * _N))  # scipy DCT-II (unnormalised)


def _phash_np(im) -> str:
    """Same algorithm as imagehash.phash(hash_size=8, highfreq_factor=4)."""
    px = np.asarray(im.convert("L").resize((_N, _N), Image.Resampling.LANCZOS), dtype=np.float64)
    low = (_DCT @ px @ _DCT.T)[:8, :8]
    bits = (low > np.median(low)).flatten()
    return "".join(f"{int(''.join('1' if b else '0' for b in bits[i:i + 4]), 2):x}" for i in range(0, 64, 4))


def phash(path: str) -> str:
    with Image.open(path) as im:
        im = im.convert("RGB")
        return str(imagehash.phash(im)) if imagehash else _phash_np(im)


def phash_distance(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def _gray(path, maxdim=900):
    img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    s = maxdim / max(img.shape)
    return cv2.resize(img, None, fx=s, fy=s) if s < 1 else img


def orb_match(a: str, b: str) -> dict:
    """ORB keypoints + ratio test + RANSAC homography. Many geometric inliers => same physical scene/photo."""
    orb = cv2.ORB_create(nfeatures=1500)
    ga, gb = _gray(a), _gray(b)
    ka, da = orb.detectAndCompute(ga, None)
    kb, db = orb.detectAndCompute(gb, None)
    if da is None or db is None:
        return {"good": 0, "inliers": 0, "inlier_ratio": 0.0}
    bf = cv2.BFMatcher(cv2.NORM_HAMMING)
    good = []
    for m in bf.knnMatch(da, db, k=2):
        if len(m) == 2 and m[0].distance < 0.75 * m[1].distance:
            good.append(m[0])
    inliers = 0
    if len(good) >= 8:
        src = np.float32([ka[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
        dst = np.float32([kb[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
        _, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
        inliers = int(mask.sum()) if mask is not None else 0
    return {"good": len(good), "inliers": inliers, "inlier_ratio": round(inliers / max(1, len(good)), 3),
            "keypoints": [len(ka), len(kb)]}


def room_cues(path: str) -> dict:
    g = _gray(path, 800)
    edges = cv2.Canny(g, 60, 160)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 80, minLineLength=60, maxLineGap=8)
    horiz = vert = 0
    for x1, y1, x2, y2 in (lines.reshape(-1, 4) if lines is not None else []):
        ang = abs(math.degrees(math.atan2(y2 - y1, x2 - x1)))
        if ang < 12 or ang > 168:
            horiz += 1
        elif 78 < ang < 102:
            vert += 1
    density = float(edges.mean() / 255)
    return {"straight_lines": int(0 if lines is None else len(lines)), "horizontal": horiz, "vertical": vert,
            "edge_density": round(density, 4), "brightness": round(float(g.mean()), 1),
            "indoor_structure_likely": horiz + vert >= 10,
            "method": "Canny + probabilistic Hough (local stand-in for room-structure model)"}


def haversine_km(a, b):
    R = 6371
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


# Thresholds calibrated on the SYNTHETIC eval set (ml/eval/REPORT.md); held-out synthetic precision 1.00 / recall 0.67
# vs 0.86 / 0.40 for the previous hand-set values (8, 40, 22). Not validated on real lab photos; override via env.
PHASH_DUP = int(os.getenv("PHOTO_PHASH_DUP", "2"))
ORB_DUP_INLIERS = int(os.getenv("PHOTO_ORB_INLIERS", "15"))
ORB_GATE_PHASH = int(os.getenv("PHOTO_ORB_GATE_PHASH", "64"))


def analyze_photo(path: str, candidates: list[dict]) -> dict:
    ph = phash(path)
    matches = []
    for c in candidates:
        try:
            d = phash_distance(ph, c["phash"]) if c.get("phash") else 64
            orb = orb_match(path, c["path"]) if d <= ORB_GATE_PHASH else {"good": 0, "inliers": 0, "inlier_ratio": 0}
            dup = d <= PHASH_DUP or (d <= ORB_GATE_PHASH and orb["inliers"] >= ORB_DUP_INLIERS)
            if dup or d <= 14:
                matches.append({"document_id": c["document_id"], "college_id": c["college_id"], "phash_distance": d,
                                "orb": orb, "duplicate": dup})
        except Exception:
            continue
    return {"exif": exif_info(path), "phash": ph, "matches": matches, "room": room_cues(path)}
