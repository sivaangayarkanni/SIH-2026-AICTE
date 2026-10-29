"""SYNTHETIC evaluation + threshold calibration for SealCheck's detectors.

  .venv/bin/python ml/eval/synth_eval.py [--scenes 40] [--docs 30] [--no-models]

Everything here is generated: procedural 'lab rooms' (scenes.py) and ReportLab PDFs from seed/generate_samples.py.
Numbers measure behaviour on this synthetic set only. They say NOTHING about accuracy on real AICTE submissions;
that needs real, labelled, consented data which this project does not have.

Split: scenes/documents with even index -> calibration, odd -> held-out test. Thresholds are chosen on the
calibration split only (maximise F1 subject to precision >= 0.97), then reported on the test split."""
import argparse, json, os, sys, tempfile, time
from pathlib import Path
import numpy as np
import cv2

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
TMP = Path(tempfile.mkdtemp(prefix="sealcheck-eval-"))
os.environ.setdefault("SEALCHECK_DATA_DIR", str(TMP / "data"))
os.environ.setdefault("SEALCHECK_SAMPLES_DIR", str(TMP / "samples"))
os.environ["SEALCHECK_DB_URL"] = f"sqlite:///{TMP}/eval.db"; os.environ.pop("DATABASE_URL", None)
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "seed"), str(HERE)]
import scenes  # noqa: E402


def prf(y, p):
    y, p = np.asarray(y, bool), np.asarray(p, bool)
    tp, fp, fn, tn = int((y & p).sum()), int((~y & p).sum()), int((y & ~p).sum()), int((~y & ~p).sum())
    P = tp / (tp + fp) if tp + fp else 1.0; R = tp / (tp + fn) if tp + fn else 1.0
    return {"precision": round(P, 3), "recall": round(R, 3), "f1": round(2 * P * R / (P + R), 3) if P + R else 0.0,
            "tp": tp, "fp": fp, "fn": fn, "tn": tn, "n": len(y)}


def calibrate(rows, grid, decide, min_precision=0.97):
    cal = [r for r in rows if r["split"] == "cal"]
    best = None
    for params in grid:
        m = prf([r["label"] for r in cal], [decide(r, params) for r in cal])
        key = (m["precision"] >= min_precision, m["f1"], m["precision"])
        if best is None or key > best[0]:
            best = (key, params, m)
    return best[1], best[2]


def report(rows, decide, params):
    out = {}
    for split in ("cal", "test"):
        rs = [r for r in rows if r["split"] == split]
        out[split] = prf([r["label"] for r in rs], [decide(r, params) for r in rs])
        out[split]["by_kind"] = {k: prf([r["label"] for r in rs if r["kind"] == k], [decide(r, params) for r in rs if r["kind"] == k])
                                 for k in sorted({r["kind"] for r in rs})}
    return out


# ---------------------------------------------------------------- photos
def build_photo_pairs(n_scenes, d: Path):
    d.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(7)
    pairs = []
    def save(img, name):
        p = d / name; cv2.imwrite(str(p), img, [cv2.IMWRITE_JPEG_QUALITY, 92]); return str(p)
    base = {i: save(scenes.scene(i, i), f"s{i}.jpg") for i in range(n_scenes)}
    for i in range(n_scenes):
        split = "cal" if i % 2 == 0 else "test"
        img = cv2.imread(base[i])
        for k in range(2):
            pairs.append({"a": base[i], "b": save(scenes.reuse_variant(img, 100 * i + k), f"s{i}_reuse{k}.jpg"), "label": True, "kind": "reuse (crop/scale/rotate/recompress)", "split": split})
        pairs.append({"a": base[i], "b": save(scenes.reuse_variant(img, 100 * i + 9, flip=True), f"s{i}_flip.jpg"), "label": True, "kind": "reuse, mirrored", "split": split})
        pairs.append({"a": base[i], "b": save(scenes.scene(i, 500 + i), f"s{i}_sibling.jpg"), "label": False, "kind": "sibling room (same plan, different lab)", "split": split})
        for _ in range(3):
            j = int(rng.integers(0, n_scenes))
            while j % 2 != i % 2 or j == i:
                j = int(rng.integers(0, n_scenes))
            pairs.append({"a": base[i], "b": base[j], "label": False, "kind": "unrelated room", "split": split})
    return pairs


def score_classic(pairs):
    from app.pipeline import photo
    for r in pairs:
        r["phash_d"] = photo.phash_distance(photo.phash(r["a"]), photo.phash(r["b"]))
        r["orb_inliers"] = photo.orb_match(r["b"], r["a"])["inliers"]


def classic_decide(r, p):
    ph, inl, gate = p
    return r["phash_d"] <= ph or (r["phash_d"] <= gate and r["orb_inliers"] >= inl)


def score_models(pairs):
    from app.vision import models as M
    emb = {}
    def e(p):
        if p not in emb:
            emb[p] = M.embed(p)
        return emb[p]
    for i, r in enumerate(pairs):
        r["cosine"] = round(M.cosine(e(r["a"]), e(r["b"])), 4)
        r["lg_inliers"] = M.local_match(r["b"], r["a"])["inliers"]
        if i % 25 == 0:
            print(f"  models {i}/{len(pairs)}", flush=True)


def models_decide(r, p):
    cos, inl = p
    return r["cosine"] >= cos and r["lg_inliers"] >= inl


# ---------------------------------------------------------------- documents
def build_docs(n, d: Path):
    import generate_samples as G
    G.make_pki() if not (G.PKI / "valid.key").exists() else None
    from reportlab.lib.units import mm
    d.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(11)
    docs = []
    kinds = [("clean, signed", False), ("clean, unsigned", False), ("clean, decorative white box (covers nothing)", False),
             ("hidden white text", True), ("white-box overlay over text", True), ("edited after signing", True),
             ("hidden text, tiny 1pt black", True), ("overlay in near-white (#FAFAFA)", True)]
    for i in range(n):
        split = "cal" if i % 2 == 0 else "test"
        acres = int(rng.integers(2, 40)); reg = f"REG/{rng.integers(1000, 9999)}/{rng.integers(2019, 2026)}"
        fields = [("Registration No.", reg), ("Survey No.", f"{rng.integers(10, 999)}/{rng.integers(1, 9)}"),
                  ("Extent", f"{acres} acres"), ("Valid until", f"{rng.integers(2027, 2031)}-0{rng.integers(1, 9)}-15")]
        for kind, label in kinds:
            kw = {}
            if kind == "hidden white text":
                kw["hidden"] = [f"Extent revised to {acres + 10} acres"]
            if kind == "white-box overlay over text":
                kw["overlay"] = (70 * mm - 2, 297 * mm - 62 * mm - 18 * mm - 3, 40 * mm, 5.5 * mm, f"{acres + 12} acres")
            if kind == "overlay in near-white (#FAFAFA)":
                kw["overlay"] = (70 * mm - 2, 297 * mm - 62 * mm - 18 * mm - 3, 40 * mm, 5.5 * mm, f"{acres + 12} acres")
            if kind == "clean, decorative white box (covers nothing)":
                kw["overlay"] = (140 * mm, 30 * mm, 40 * mm, 6 * mm, "Office copy")
            data = G.doc_pdf(f"Land Lease Deed {i}", "Sub-Registrar Office (synthetic)", fields, **kw)
            if kind == "overlay in near-white (#FAFAFA)":
                data = data.replace(b"1 1 1 rg", b".98 .98 .98 rg")
            if kind == "hidden text, tiny 1pt black":
                data = _tiny_text(data, f"Extent revised to {acres + 10} acres")
            if kind in ("clean, signed", "edited after signing"):
                data = G.sign(data, "valid")
            if kind == "edited after signing":
                data = G.tamper_after_signing(data, f"{acres + 15} acres")
            p = d / f"doc{i}_{kinds.index((kind, label))}.pdf"; p.write_bytes(data)
            docs.append({"path": str(p), "label": label, "kind": kind, "split": split})
    return docs


def _tiny_text(data, text):
    import io, pikepdf
    pdf = pikepdf.open(io.BytesIO(data)); pg = pdf.pages[0]
    pg.contents_add(pikepdf.Stream(pdf, f"BT /F1 1 Tf 60 120 Td ({text}) Tj ET".encode()), prepend=False)
    out = io.BytesIO(); pdf.save(out); return out.getvalue()


def score_docs(docs):
    from app.pipeline import cdr, forensics
    from app.worker import pdf_findings
    from app.service import TRUST_DIR
    for r in docs:
        san = r["path"] + ".san.pdf"
        cdr.disarm_pdf(r["path"], san)
        f = pdf_findings(forensics.analyze_pdf(r["path"], san, str(TRUST_DIR)))
        r["forgery_rules"] = sorted({x["rule_id"] for x in f if x.get("forgery")})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenes", type=int, default=40); ap.add_argument("--docs", type=int, default=30)
    ap.add_argument("--no-models", action="store_true")
    a = ap.parse_args()
    t0 = time.time(); res = {"warning": "SYNTHETIC DATA ONLY. Not a measure of real-world accuracy.", "generated_at": time.strftime("%Y-%m-%d %H:%M %Z")}
    import generate_samples
    generate_samples.main()   # synthetic PKI + trust roots for the signature checks

    pairs = build_photo_pairs(a.scenes, TMP / "photos")
    print(f"photo pairs: {len(pairs)}", flush=True)
    score_classic(pairs)
    current = (8, 40, 22)
    grid = [(ph, inl, g) for ph in range(2, 17, 2) for inl in (10, 15, 20, 25, 30, 40, 60, 80) for g in (14, 18, 22, 26, 30, 64)]
    best, cal_m = calibrate(pairs, grid, classic_decide)
    res["photo_classic"] = {"method": "pHash Hamming + ORB/RANSAC homography inliers",
                            "current_thresholds": {"phash_dup": 8, "orb_inliers": 40, "orb_gate_phash": 22}, "current": report(pairs, classic_decide, current),
                            "calibrated_thresholds": {"phash_dup": best[0], "orb_inliers": best[1], "orb_gate_phash": best[2]},
                            "calibrated": report(pairs, classic_decide, best)}
    from app.vision import client as vc
    if not a.no_models and vc.available():
        score_models(pairs)
        cur = (vc.DUP_COSINE, vc.DUP_INLIERS)
        grid = [(c / 100, i) for c in range(70, 99) for i in (10, 20, 30, 50, 75, 100, 150, 200, 300)]
        bm, _ = calibrate(pairs, grid, models_decide)
        res["photo_models"] = {"method": "DINOv2-small cosine AND DISK+LightGlue MAGSAC inliers",
                               "current_thresholds": {"dup_cosine": cur[0], "dup_inliers": cur[1]}, "current": report(pairs, models_decide, cur),
                               "calibrated_thresholds": {"dup_cosine": bm[0], "dup_inliers": bm[1]}, "calibrated": report(pairs, models_decide, bm)}
    else:
        res["photo_models"] = {"skipped": "torch/transformers/kornia not installed (or --no-models)"}

    docs = build_docs(a.docs, TMP / "docs")
    print(f"documents: {len(docs)}", flush=True)
    score_docs(docs)
    res["documents"] = {"method": "CDR + PDF forensics (hidden text, white-box overlay, DSC ByteRange/coverage); 'detected' = any forgery finding",
                        "result": report(docs, lambda r, _: bool(r["forgery_rules"]), None),
                        "rules_fired_by_kind": {k: sorted({x for r in docs if r["kind"] == k for x in r["forgery_rules"]}) for k in sorted({r["kind"] for r in docs})}}
    res["sizes"] = {"photo_pairs": len(pairs), "documents": len(docs), "scenes": a.scenes}
    res["runtime_s"] = round(time.time() - t0, 1)
    out = HERE / "results"; out.mkdir(exist_ok=True)
    (out / "synthetic_eval.json").write_text(json.dumps(res, indent=2))
    (out / "pairs.json").write_text(json.dumps([{k: (Path(v).name if k in ("a", "b") else v) for k, v in r.items()} for r in pairs], indent=1))
    print(json.dumps({k: v for k, v in res.items()}, indent=1)[:6000])


if __name__ == "__main__":
    main()
