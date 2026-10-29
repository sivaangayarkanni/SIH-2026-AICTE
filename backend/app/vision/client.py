"""Vision backend selector + out-of-process model worker.

VISION_BACKEND=classic (default, dev): pHash + ORB + Hough cues, computed inside the sandbox worker.
VISION_BACKEND=remote: the same models behind vision_service/ (HTTP, token-authenticated), see vision/remote.py.
VISION_BACKEND=models: DINOv2-small / DISK+LightGlue / RT-DETR run in ONE long-lived separate process
(ProcessPoolExecutor, spawn) so the API process never imports torch and models load once (lazily).
Any failure (torch missing, weights not downloadable, timeout) -> caller falls back to classic and records why.
"""
import multiprocessing as mp
import os
import threading
from concurrent.futures import ProcessPoolExecutor

BACKEND = os.getenv("VISION_BACKEND", "classic").lower()
TIMEOUT_S = float(os.getenv("VISION_TIMEOUT_S", "180"))
DUP_COSINE = float(os.getenv("VISION_DUP_COSINE", "0.70"))
DUP_INLIERS = int(os.getenv("VISION_DUP_INLIERS", "150"))
SUSPECT_COSINE = float(os.getenv("VISION_SUSPECT_COSINE", "0.85"))
CANDIDATE_MIN_COS = float(os.getenv("VISION_CANDIDATE_MIN_COS", "0.75"))
_pool = None
_plock = threading.Lock()


def _get_pool():
    global _pool
    with _plock:
        if _pool is None:
            _pool = ProcessPoolExecutor(max_workers=1, mp_context=mp.get_context("spawn"))
        return _pool


def _call(fn, *args):
    global _pool
    try:
        return _get_pool().submit(fn, *args).result(timeout=TIMEOUT_S)
    except Exception:
        with _plock:  # broken/hung worker: discard so the next call respawns
            if _pool is not None:
                _pool.shutdown(wait=False, cancel_futures=True)
            _pool = None
        raise


def _describe(path):
    from app.vision import models
    return models.describe(path)


def _verify(path, cands, lh):
    from app.vision import models
    return models.verify(path, cands, lh)


def available():
    try:
        import importlib.util
        return all(importlib.util.find_spec(m) for m in ("torch", "transformers", "kornia"))
    except Exception:
        return False


def is_duplicate(m):
    return bool(m.get("cosine", 0) >= DUP_COSINE and (m.get("local") or {}).get("inliers", 0) >= DUP_INLIERS)


def analyze_with_models(path, find_candidates):
    """find_candidates(embedding) -> [{document_id, college_id, path, similarity, layout_hash}] (pgvector kNN).
    VISION_BACKEND=models runs the local worker process; VISION_BACKEND=remote calls vision_service over HTTPS."""
    if BACKEND == "remote":
        from . import remote
        d = remote.describe(path)
        cands = [c for c in find_candidates(d["embedding"]) if c["similarity"] >= CANDIDATE_MIN_COS and c.get("path")]
        d["matches"] = remote.verify(path, cands[:5], d["layout_hash"]) if cands else []
        d["backend"] = "remote"
    else:
        d = _call(_describe, path)
        cands = [c for c in find_candidates(d["embedding"]) if c["similarity"] >= CANDIDATE_MIN_COS and c.get("path")]
        d["matches"] = _call(_verify, path, cands[:5], d["layout_hash"]) if cands else []
    d["thresholds"] = {"dup_cosine": DUP_COSINE, "dup_inliers": DUP_INLIERS, "suspect_cosine": SUSPECT_COSINE}
    return d


def shutdown():
    global _pool
    if _pool is not None:
        _pool.shutdown(wait=False, cancel_futures=True)
        _pool = None
