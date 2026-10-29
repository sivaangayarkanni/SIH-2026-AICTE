"""4A · PDF Forensics Engine.
DSC / ByteRange validation (pyHanko), certificate expiry, PDF object-tree summary, hidden-text & white-box
overlay detection, incremental-update / edit-history detection, metadata vs content cross-check, text/OCR."""
import re, shutil
from datetime import datetime, timezone
from pathlib import Path
import pikepdf
from pdfminer.high_level import extract_pages
from pdfminer.layout import LTTextContainer, LTTextLine, LTChar, LTRect, LAParams

EDIT_TOOLS = ("ilovepdf", "smallpdf", "sejda", "pdfescape", "foxit phantom", "nitro", "pdf-xchange", "pdfelement",
              "online pdf editor")


def _is_white(c):
    if c is None:
        return False
    if isinstance(c, (int, float)):
        return c >= 0.97
    try:
        vals = list(c)
    except TypeError:
        return False
    if len(vals) == 3:
        return all(v >= 0.97 for v in vals)
    if len(vals) == 4:  # CMYK white
        return all(v <= 0.03 for v in vals)
    if len(vals) == 1:
        return vals[0] >= 0.97
    return False


def extract_layout(path: str) -> dict:
    """Returns lines with page + bbox (PDF points, origin bottom-left) and page sizes; flags hidden text."""
    lines, pages, hidden, overlays = [], [], [], []
    for pno, layout in enumerate(extract_pages(path, laparams=LAParams()), start=1):
        w, h = layout.width, layout.height
        pages.append({"page": pno, "width": w, "height": h})
        white_rects, dark_rects = [], []
        page_lines = []
        for el in layout:  # pass 1: filled rectangles (backgrounds / masking boxes)
            if isinstance(el, LTRect) and el.fill and el.width > 20 and el.height > 6:
                (white_rects if _is_white(getattr(el, "non_stroking_color", None)) else dark_rects).append(el.bbox)
        for el in layout:  # pass 2: text
            if isinstance(el, LTTextContainer):
                for ln in el:
                    if not isinstance(ln, LTTextLine):
                        continue
                    text = ln.get_text().strip()
                    if not text:
                        continue
                    chars = [c for c in ln if isinstance(c, LTChar)]
                    white = sum(1 for c in chars if _is_white(c.graphicstate.ncolor))
                    tiny = sum(1 for c in chars if c.size < 2.0)
                    outside = ln.x0 > w or ln.x1 < 0 or ln.y0 > h or ln.y1 < 0
                    on_dark = any(_overlap(r, ln.bbox) > 0.8 for r in dark_rects)  # white text on a coloured band is visible
                    if on_dark:
                        white = 0
                    is_hidden = chars and (white / len(chars) > 0.6 or tiny / len(chars) > 0.6 or outside)
                    item = {"page": pno, "text": text, "bbox": [round(v, 1) for v in ln.bbox], "hidden": bool(is_hidden),
                            "reason": ("white-on-white text" if chars and white / len(chars) > 0.6 else
                                       "microscopic font" if chars and tiny / len(chars) > 0.6 else
                                       "outside page area" if outside else None)}
                    page_lines.append(item)
                    if is_hidden:
                        hidden.append(item)
        for r in white_rects:
            covered = [l for l in page_lines if not l["hidden"] and _overlap(r, l["bbox"]) > 0.5]
            if covered:
                overlays.append({"page": pno, "bbox": [round(v, 1) for v in r],
                                 "covers": [c["text"] for c in covered][:3]})
        page_lines = _merge_rows(page_lines)
        lines.extend(page_lines)
    return {"lines": lines, "pages": pages, "hidden_text": hidden, "overlays": overlays}


def _merge_rows(lines):
    """Join visible text fragments that sit on the same baseline (e.g. 'Issued By:' + value) into one row."""
    vis = sorted([l for l in lines if not l["hidden"]], key=lambda l: (-round(l["bbox"][1]), l["bbox"][0]))
    rows = []
    for l in vis:
        cy = (l["bbox"][1] + l["bbox"][3]) / 2
        r = next((r for r in rows if abs(r["_cy"] - cy) < 3), None)
        if r:
            r["parts"].append(l)
        else:
            rows.append({"_cy": cy, "parts": [l]})
    out = []
    for r in rows:
        ps = sorted(r["parts"], key=lambda p: p["bbox"][0])
        bb = [min(p["bbox"][0] for p in ps), min(p["bbox"][1] for p in ps), max(p["bbox"][2] for p in ps), max(p["bbox"][3] for p in ps)]
        out.append({"page": ps[0]["page"], "text": "  ".join(p["text"] for p in ps), "bbox": bb, "hidden": False, "reason": None})
    return out + [l for l in lines if l["hidden"]]


def _overlap(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    area_b = max(1e-6, (b[2] - b[0]) * (b[3] - b[1]))
    return ix * iy / area_b


def ocr_pdf(path: str, max_pages=3) -> dict:
    """OCR scanned pages (no text layer) with Tesseract when available."""
    if not shutil.which("tesseract"):
        return {"engine": None, "text": ""}
    try:
        import pypdfium2 as pdfium, pytesseract
        doc = pdfium.PdfDocument(path)
        out = []
        for i in range(min(len(doc), max_pages)):
            img = doc[i].render(scale=2).to_pil()
            out.append(pytesseract.image_to_string(img))
        return {"engine": "Tesseract " + str(pytesseract.get_tesseract_version()), "text": "\n".join(out)}
    except Exception as e:
        return {"engine": "Tesseract", "text": "", "error": str(e)}


def edit_history(raw: bytes) -> dict:
    eof = len(re.findall(rb"%%EOF", raw))
    prev = len(re.findall(rb"/Prev\s+\d+", raw))
    startxref = len(re.findall(rb"startxref", raw))
    return {"eof_markers": eof, "prev_pointers": prev, "startxref": startxref,
            "incremental_updates": max(0, eof - 1), "edited_after_creation": eof > 1}


def object_tree(path: str) -> dict:
    with pikepdf.open(path) as pdf:
        fonts, images, annots = set(), 0, 0
        for p in pdf.pages:
            res = p.obj.get("/Resources", {})
            for f in (res.get("/Font", {}) or {}).keys():
                fonts.add(str(res.Font[f].get("/BaseFont", f)))
            for x in (res.get("/XObject", {}) or {}).values():
                if x.get("/Subtype") == "/Image":
                    images += 1
            annots += len(p.obj.get("/Annots", []) or [])
        meta = {}
        try:
            for k, v in pdf.docinfo.items():
                meta[str(k).strip("/")] = str(v)
        except Exception:
            pass
        return {"pdf_version": pdf.pdf_version, "objects": len(pdf.objects), "pages": len(pdf.pages),
                "fonts": sorted(fonts)[:12], "images": images, "annotations": annots,
                "has_acroform": "/AcroForm" in pdf.Root, "encrypted": pdf.is_encrypted, "metadata": meta}


def _pdf_date(s: str | None):
    if not s:
        return None
    m = re.match(r"D:(\d{4})(\d{2})(\d{2})(\d{2})?(\d{2})?", s)
    if not m:
        return None
    return datetime(int(m[1]), int(m[2]), int(m[3]), int(m[4] or 0), int(m[5] or 0))


def signatures(path: str, trust_dir: str | None) -> list[dict]:
    out = []
    try:
        from pyhanko.pdf_utils.reader import PdfFileReader
        from pyhanko.sign.validation import validate_pdf_signature
        from pyhanko_certvalidator import ValidationContext
        from pyhanko.keys import load_cert_from_pemder
    except Exception as e:
        return [{"error": f"pyHanko unavailable: {e}"}]
    roots, inter = [], []
    if trust_dir and Path(trust_dir).exists():
        for ext in ("*.pem", "*.crt", "*.cer"):
            roots += [load_cert_from_pemder(str(p)) for p in Path(trust_dir).glob(ext)]
        if (Path(trust_dir) / "intermediates").exists():
            inter = [load_cert_from_pemder(str(p)) for p in (Path(trust_dir) / "intermediates").glob("*.*")]
    import base64 as _b64m
    raw_all = Path(path).read_bytes()
    has_dss = b"/DSS" in raw_all
    with open(path, "rb") as f:
        r = PdfFileReader(f, strict=False)
        for sig in r.embedded_signatures:
            item = {"field": sig.field_name}
            try:
                cert = sig.signer_cert
                validity = cert["tbs_certificate"]["validity"]
                na = validity["not_after"].native
                nb = validity["not_before"].native
                item.update({"signer": cert.subject.human_friendly, "issuer": cert.issuer.human_friendly,
                             "not_before": nb.date().isoformat(), "not_after": na.date().isoformat(),
                             "cert_expired": na < datetime.now(timezone.utc)})
                issuer_cert = next((c.chosen for c in sig.signed_data["certificates"]
                                    if getattr(c, "chosen", None) is not None and c.name == "certificate"
                                    and c.chosen.subject == cert.issuer), None)
                if issuer_cert is None:
                    issuer_cert = next((r for r in roots + inter if r.subject == cert.issuer), None)
                item.update({"cert_der": _b64m.b64encode(cert.dump()).decode(),
                             "issuer_der": _b64m.b64encode(issuer_cert.dump()).decode() if issuer_cert is not None else None,
                             "ocsp_urls": list(cert.ocsp_urls), "crl_urls": [u for dp in (cert.crl_distribution_points or [])
                                                                              for u in (dp.url and [dp.url] or [])],
                             "ltv_dss": has_dss})
                # The sandbox has no network: revocation is checked host-side (app/trust.py) from the cert we return.
                vc = ValidationContext(trust_roots=roots, other_certs=inter, allow_fetching=False, revocation_mode="soft-fail")
                st = validate_pdf_signature(sig, vc)
                cov = str(st.coverage).split(".")[-1] if st.coverage is not None else None
                ml = str(st.modification_level).split(".")[-1] if getattr(st, "modification_level", None) is not None else None
                item.update({"intact": bool(st.intact), "valid": bool(st.valid), "trusted": bool(st.trusted),
                             "coverage": cov, "modification_level": ml,
                             "covers_whole_file": cov == "ENTIRE_FILE",
                             "signing_time": st.signer_reported_dt.isoformat() if st.signer_reported_dt else None,
                             "byte_range_ok": bool(st.intact)})
            except Exception as e:
                item.update({"error": str(e)[:200], "intact": False, "valid": False})
            out.append(item)
    return out


def analyze_pdf(original: str, sanitized: str, trust_dir: str | None) -> dict:
    raw = Path(original).read_bytes()
    layout = extract_layout(sanitized)
    text = "\n".join(l["text"] for l in layout["lines"] if not l["hidden"])
    ocr = {"engine": None}
    if len(text.strip()) < 20:
        ocr = ocr_pdf(sanitized)
        text = ocr.get("text", "")
    tree = object_tree(original)
    hist = edit_history(raw)
    sigs = signatures(original, trust_dir)
    meta = tree["metadata"]
    # metadata vs content cross-check
    producer = (meta.get("Producer", "") + " " + meta.get("Creator", "")).lower()
    tool = next((t for t in EDIT_TOOLS if t in producer), None)
    cd, md = _pdf_date(meta.get("CreationDate")), _pdf_date(meta.get("ModDate"))
    title = meta.get("Title", "")
    return {
        "text": text, "lines": layout["lines"], "pages": layout["pages"], "hidden_text": layout["hidden_text"],
        "overlays": layout["overlays"], "ocr": ocr, "object_tree": tree, "edit_history": hist, "signatures": sigs,
        "metadata_check": {"producer": meta.get("Producer"), "creator": meta.get("Creator"), "title": title,
                           "creation_date": cd.isoformat() if cd else None, "mod_date": md.isoformat() if md else None,
                           "editing_tool": tool, "modified_later_days": (md - cd).days if cd and md else 0},
    }
