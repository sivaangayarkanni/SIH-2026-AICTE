"""Officer voice/text assistant: answers questions about a document from extracted evidence with citations.
Deterministic retrieval (intent + keyword overlap) by default; never invents facts not present in the text."""
import re
from datetime import date
from .pipeline.rule_engine import parse_date

STOP = set("the a an of is was does do when what who which this that for to in on by and or it be are has have how much many".split())
INTENTS = [
    (r"expir|valid|until|lapse|renew", r"valid until|valid upto|valid up to|expiry|expires|valid till"),
    (r"issu|who (signed|gave)|authority", r"issued by|authority|signed by"),
    (r"area|acre|land|extent", r"area|extent|acre|survey"),
    (r"intake|seats|students", r"intake|seats"),
    (r"amount|fdr|money|rupee|deposit", r"amount|rs\.|inr|fdr"),
    (r"date of issue|issued on|when.*issued", r"date of issue|issued on|dated"),
]


def answer(question: str, lines: list[dict], facts: dict, doc_label: str, findings: list | None = None, status: str | None = None) -> dict:
    q = question.lower().strip()
    if findings is not None and re.search(r"why|flag|status|problem|issue|wrong|reject|forg|suspic", q):
        bad = [f for f in findings if f.get("outcome") != "pass"]
        bad.sort(key=lambda f: ["critical", "high", "medium", "low", "info"].index(f.get("severity", "info")) if f.get("severity") in ("critical", "high", "medium", "low", "info") else 9)
        if not bad:
            return {"answer": f"Nothing was flagged: every check on this {doc_label} passed, so its status is {status or 'Verified'}.",
                    "citation": None, "confidence": "high", "method": "findings summary (no generation)"}
        top = bad[0]
        more = f" There are {len(bad) - 1} other issue(s) listed in the Evidence tab." if len(bad) > 1 else ""
        cit = {"page": top["page"], "bbox": top["bbox"], "text": top.get("title", "")} if top.get("page") and top.get("bbox") else None
        return {"answer": f"Status is {status or 'flagged'} mainly because of rule {top.get('rule_id')}: {top.get('title')}. {top.get('detail', '')}{more}".strip(),
                "citation": cit, "confidence": "high", "method": "findings summary (no generation)"}
    visible = [l for l in lines if not l.get("hidden")]
    cands = []
    for qi, li in INTENTS:
        if re.search(qi, q):
            cands = [l for l in visible if re.search(li, l["text"], re.I)]
            if cands:
                break
    if not cands:
        words = {w for w in re.findall(r"[a-z0-9]+", q) if w not in STOP and len(w) > 2}
        scored = sorted(((sum(1 for w in words if w in l["text"].lower()), l) for l in visible), key=lambda x: -x[0])
        cands = [l for s, l in scored if s > 0][:1]
    if not cands:
        return {"answer": f"I could not find that in the {doc_label}. Try asking about validity, issuer, area, intake or amount.",
                "citation": None, "confidence": "none"}
    best = cands[0]
    text = best["text"]
    ans = f"The {doc_label} says: “{text}” (page {best['page']})."
    if re.search(r"expir|valid|until", q):
        d = parse_date(text)
        if d:
            days = (d - date.today()).days
            ans = (f"This document {'expired' if days < 0 else 'expires'} on {d:%d %B %Y}"
                   f" ({abs(days)} days {'ago' if days < 0 else 'from today'}). Source: page {best['page']}.")
    return {"answer": ans, "citation": {"page": best["page"], "bbox": best["bbox"], "text": text},
            "confidence": "high" if len(cands) >= 1 else "low", "method": "evidence retrieval (no generation)"}
