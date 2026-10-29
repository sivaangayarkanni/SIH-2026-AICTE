"""Cross-document consistency engine (deterministic).

Reuses the text the analysis pipeline already extracted (Document.analysis_json["lines"], each with page and bbox)
plus the values the institution declared in the submission wizard and the registered institution profile. Core fields
are normalised and compared pairwise: numbers/areas/dates exactly after normalisation, names/addresses with a fuzzy
similarity (difflib) threshold from the workflow config. Every disagreement becomes a mismatch with the field, the
values, and the document/page each value came from. It flags; it never decides."""
from __future__ import annotations
import re
from datetime import date
from difflib import SequenceMatcher

FIELDS = {
    "institution_name": {"label": "Institution name", "kind": "text", "keys": ["institution name", "name of institution", "name of the institution", "institution"]},
    "trust_name": {"label": "Trust / society (applicant)", "kind": "text", "keys": ["lessee", "trust", "society", "name of trust", "applicant", "trust / society"]},
    "address": {"label": "Address", "kind": "text", "keys": ["address", "site address", "location", "address of institution"]},
    "survey_no": {"label": "Survey / land details", "kind": "id", "keys": ["survey no", "survey number", "khasra no", "plot no", "survey no."]},
    "land_area": {"label": "Land area (acres)", "kind": "area", "keys": ["area", "land area", "total land area"]},
    "lease_start": {"label": "Lease start date", "kind": "date", "keys": ["lease start", "lease from"]},
    "lease_end": {"label": "Lease end / valid until", "kind": "date", "keys": ["lease end", "lease until", "lease valid until"]},
    "lease_term": {"label": "Lease term (years)", "kind": "number", "keys": ["lease term", "lease period", "term of lease"]},
    "signatory": {"label": "Authorised signatory", "kind": "text", "keys": ["deponent", "signatory", "authorised signatory", "authorized signatory", "signed by"]},
}
DECLARED_KEYS = list(FIELDS)
KEY_RE = re.compile(r"^\s*([A-Za-z][A-Za-z /.&-]{1,40}?)\s*:\s+(.+)$")


def _norm_text(v: str) -> str:
    v = re.sub(r"\((synthetic|demo)\)", "", v, flags=re.I)
    v = re.sub(r"[^a-z0-9 ]", " ", v.lower())
    v = re.sub(r"\b(the|of|and|dr|m s|ms|pvt|ltd)\b", " ", v)
    return " ".join(v.split())


def _norm_id(v: str) -> str:
    return re.sub(r"[^a-z0-9/]", "", v.lower().split(",")[0])


def _areas(v: str) -> list[float]:
    out = []
    for num, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(acres?|acre|ha|hectares?|sq\.?\s?m)?", v.replace(",", ""), flags=re.I):
        x = float(num)
        u = (unit or "acres").lower()
        if u.startswith("ha") or u.startswith("hect"):
            x *= 2.47105
        elif u.startswith("sq"):
            x /= 4046.86
        out.append(round(x, 2))
    return out


def _date(v: str) -> str | None:
    m = re.search(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", v)
    if m:
        try:
            return date(int(m[3]), int(m[2]), int(m[1])).isoformat()
        except ValueError:
            return None
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", v)
    return m.group(0) if m else None


def normalise(field: str, raw: str) -> list:
    kind = FIELDS[field]["kind"]
    if kind == "area":
        return _areas(raw)
    if kind == "date":
        d = _date(raw); return [d] if d else []
    if kind == "number":
        m = re.search(r"\d+(?:\.\d+)?", raw); return [float(m.group(0))] if m else []
    if kind == "id":
        return [_norm_id(raw)] if raw.strip() else []
    return [_norm_text(raw)] if raw.strip() else []


def _field_for_key(key: str, doc_type: str | None) -> str | None:
    k = key.strip().lower().rstrip(".")
    if k == "valid until" and doc_type == "land_document":
        return "lease_end"
    if k == "date of issue" and doc_type == "land_document":
        return "lease_start"
    if k in ("built-up area", "built up area"):
        return None
    for f, spec in FIELDS.items():
        if k in spec["keys"]:
            return f
    return None


def extract(doc) -> list[dict]:
    """Field observations from one analysed document: [{field, raw, values, page, bbox, hidden}]."""
    obs = []
    for ln in (doc.analysis_json or {}).get("lines") or []:
        m = KEY_RE.match(ln.get("text") or "")
        if not m:
            continue
        f = _field_for_key(m[1], doc.doc_type)
        if not f:
            continue
        vals = normalise(f, m[2])
        if vals:
            obs.append({"field": f, "raw": m[2].strip(), "values": vals, "page": ln.get("page"), "bbox": ln.get("bbox"), "hidden": bool(ln.get("hidden"))})
    return obs


def _same(field, a, b, thr) -> bool:
    kind = FIELDS[field]["kind"]
    if kind == "area":
        return abs(a - b) <= 0.05
    if kind == "number":
        return abs(a - b) < 1e-6
    if kind == "text":
        if a == b or (len(a) > 6 and (a in b or b in a)):
            return True
        return SequenceMatcher(None, " ".join(sorted(a.split())), " ".join(sorted(b.split()))).ratio() >= thr
    return a == b


def crosscheck(s, a, threshold: float | None = None) -> dict:
    from .workflow import active_config, WizardDraft
    thr = threshold if threshold is not None else float((active_config(s).get("crosscheck") or {}).get("fuzzy_threshold", 0.88))
    sources = []   # (source dict, observations)
    if a.college:
        sources.append(({"kind": "profile", "label": "Registered institution profile", "document_id": None},
                        [{"field": "institution_name", "raw": a.college.name, "values": normalise("institution_name", a.college.name), "page": None, "bbox": None, "hidden": False}]))
    dr = s.get(WizardDraft, a.id)
    declared = ((dr.data_json or {}).get("institution") or {}) if dr else {}
    dobs = []
    for f in DECLARED_KEYS:
        v = str(declared.get(f) or "").strip()
        if v:
            dobs.append({"field": f, "raw": v, "values": normalise(f, v), "page": None, "bbox": None, "hidden": False})
    if dobs:
        sources.append(({"kind": "declared", "label": "Declared in the application form (wizard)", "document_id": None}, dobs))
    for d in a.documents:
        if d.status in ("Verification Pending",) or not d.analysis_json:
            continue
        sources.append(({"kind": "document", "label": d.filename, "document_id": d.id, "doc_type": d.doc_type}, extract(d)))
    table: dict[str, list] = {f: [] for f in FIELDS}
    for src, obs in sources:
        for o in obs:
            for v in o["values"]:
                table[o["field"]].append({**src, "raw": o["raw"], "value": v, "page": o["page"], "bbox": o["bbox"], "hidden": o["hidden"]})
    mismatches = []
    for f, vals in table.items():
        seen = set()
        for i in range(len(vals)):
            for j in range(i + 1, len(vals)):
                x, y = vals[i], vals[j]
                if _same(f, x["value"], y["value"], thr):
                    continue
                key = (f, str(x["value"]), str(y["value"]))
                if key in seen:
                    continue
                seen.add(key)
                same_doc = x.get("document_id") and x.get("document_id") == y.get("document_id")
                mismatches.append({
                    "field": f, "field_label": FIELDS[f]["label"],
                    "a": {"value": x["raw"], "source": x["label"], "document_id": x.get("document_id"), "page": x["page"], "bbox": x["bbox"], "hidden": x["hidden"]},
                    "b": {"value": y["raw"], "source": y["label"], "document_id": y.get("document_id"), "page": y["page"], "bbox": y["bbox"], "hidden": y["hidden"]},
                    "within_document": bool(same_doc),
                    "action": "To be corrected / re-uploaded by the institution",
                })
    fields = [{"field": f, "label": FIELDS[f]["label"], "observations": [{"value": v["raw"], "source": v["label"], "document_id": v.get("document_id"), "page": v["page"]} for v in vals]}
              for f, vals in table.items() if vals]
    return {"application_id": a.id, "threshold": thr, "fields": fields, "mismatches": mismatches,
            "sources": [src["label"] for src, _ in sources],
            "note": "Deterministic comparison of extracted text. A mismatch is a prompt for correction or officer review, not a finding of fraud."}
