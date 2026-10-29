"""VISION_BACKEND=models tests on the SYNTHETIC sample photos only (no real-world accuracy claim)."""
import json, pytest
from conftest import SAMPLES
from app.vision import client as vc

pytestmark = pytest.mark.skipif(not vc.available(), reason="torch/transformers/kornia not installed")
SCORES = {}


@pytest.fixture(scope="module")
def M():
    from app.vision import models
    return models


def test_reused_photo_matches_unrelated_does_not(M):
    a, b, c = (str(SAMPLES / f) for f in ("svit_lab_cse.jpg", "diem_lab_reused.jpg", "gvce_lab_ece.jpg"))
    ea, eb, ec = M.embed(a), M.embed(b), M.embed(c)
    reused = {"cosine": M.cosine(ea, eb), "local": M.local_match(a, b)}
    unrel = {"cosine": M.cosine(ea, ec), "local": M.local_match(a, c)}
    SCORES.update(reused={"cosine": round(reused["cosine"], 4), "inliers": reused["local"]["inliers"]},
                  unrelated={"cosine": round(unrel["cosine"], 4), "inliers": unrel["local"]["inliers"]})
    print("\nSYNTHETIC vision scores:", json.dumps(SCORES))
    assert vc.is_duplicate(reused), reused
    assert not vc.is_duplicate(unrel), unrel
    assert unrel["cosine"] < vc.SUSPECT_COSINE


def test_out_of_process_pipeline_and_detector(M):
    a, b, c = (str(SAMPLES / f) for f in ("svit_lab_cse.jpg", "diem_lab_reused.jpg", "gvce_lab_ece.jpg"))
    idx = [{"document_id": 1, "college_id": 1, "path": a, "emb": M.embed(a), "layout_hash": M.layout_hash(a)[0]},
           {"document_id": 2, "college_id": 2, "path": c, "emb": M.embed(c), "layout_hash": M.layout_hash(c)[0]}]
    def kNN(e):
        return sorted([{**i, "similarity": M.cosine(e, i["emb"])} for i in idx], key=lambda x: -x["similarity"])
    r = vc.analyze_with_models(b, kNN)  # runs in the spawned vision worker
    assert len(r["embedding"]) == 384
    dups = [m for m in r["matches"] if vc.is_duplicate(m)]
    assert [m["document_id"] for m in dups] == [1]
    assert all(m["document_id"] != 2 for m in r["matches"])  # unrelated filtered by candidate threshold
    labels = {d["label"] for d in r["detections"]}
    assert labels & {"tvmonitor", "tv", "keyboard", "chair", "laptop", "mouse"}, labels
    vc.shutdown()
