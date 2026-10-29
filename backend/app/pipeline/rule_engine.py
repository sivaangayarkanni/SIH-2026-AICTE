"""4B · AICTE Rule Engine. Runs only with a verified, signed rule bundle. Every finding carries a rule id,
an APH clause reference and (where possible) the exact page + bounding box of the evidence."""
import re
from datetime import date

MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
DATE_RE = re.compile(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})|(\d{4})-(\d{2})-(\d{2})|(\d{1,2})\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})")


def parse_date(s: str):
    m = DATE_RE.search(s)
    if not m:
        return None
    try:
        if m[1]:
            return date(int(m[3]), int(m[2]), int(m[1]))
        if m[4]:
            return date(int(m[4]), int(m[5]), int(m[6]))
        mon = MONTHS.get(m[8][:3].lower())
        return date(int(m[9]), mon, int(m[7])) if mon else None
    except ValueError:
        return None


def _find_line(lines, pattern, flags=re.I):
    rx = re.compile(pattern, flags)
    for l in lines:
        if not l.get("hidden") and rx.search(l["text"]):
            return l
    return None


def evaluate(doc_type: str, text: str, lines: list, rules: dict, today: date | None = None) -> dict:
    today = today or date.today()
    spec = rules["document_types"].get(doc_type)
    findings, facts = [], {}
    if not spec:
        return {"findings": [{"rule_id": "R-000", "clause": "-", "outcome": "warn", "severity": "medium",
                              "title": "Unknown document type", "detail": f"No rule set for '{doc_type}'."}], "facts": {}}
    clause = spec["clause"]
    tid = doc_type.split("_")[0].upper()[:5]
    for i, f in enumerate(spec.get("required_fields", []), 1):
        ln = _find_line(lines, f["pattern"], 0 if "[A-Z]" in f["pattern"] else re.I)
        findings.append({"rule_id": f"R-{tid}-F{i}", "clause": clause, "outcome": "pass" if ln else "fail",
                         "severity": "info" if ln else "medium",
                         "title": f"{f['name']} {'present' if ln else 'missing'}",
                         "detail": (f"Found on page {ln['page']}: “{ln['text'][:120]}”" if ln else
                                    f"The rule bundle requires '{f['name']}' for a {spec['label']}; it was not found."),
                         "page": ln["page"] if ln else None, "bbox": ln["bbox"] if ln else None})
    # issuer -> source registry
    iss = _find_line(lines, r"Issued By\s*[:\-]")
    if iss:
        issuer = re.split(r"Issued By\s*[:\-]\s*", iss["text"], flags=re.I)[-1].strip()
        facts["issuer"] = issuer
        known = next((r for r in rules.get("issuer_registry", []) if r.lower() in issuer.lower()), None)
        facts["issuer_registered"] = bool(known)
        findings.append({"rule_id": f"R-{tid}-SRC", "clause": "APH 2024-27 · Issuer verification (prototype ref)",
                         "outcome": "pass" if known else "warn", "severity": "info" if known else "medium",
                         "title": "Issuer confirmed in registry mirror" if known else "Issuer could not be confirmed at source",
                         "detail": (f"“{issuer}” matches registry entry “{known}”." if known else
                                    f"“{issuer}” is not in the local issuer registry mirror and no verification API is configured. "
                                    "Status is reported honestly as Source Unavailable."),
                         "page": iss["page"], "bbox": iss["bbox"], "source_unavailable": not known})
    # dates
    labels = "|".join(re.escape(x) for x in rules.get("date_labels", []))
    vl = _find_line(lines, rf"(?:{labels})\s*[:\-]?")
    issue_l = _find_line(lines, r"(?:Date of Issue|Issue Date|Issued On|Dated)\s*[:\-]?")
    if issue_l:
        d = parse_date(issue_l["text"])
        if d:
            facts["issue_date"] = d.isoformat()
            if d > today:
                findings.append({"rule_id": f"R-{tid}-D0", "clause": clause, "outcome": "fail", "severity": "high",
                                 "title": "Issue date is in the future", "detail": f"Issue date {d:%d %b %Y} is after today.",
                                 "page": issue_l["page"], "bbox": issue_l["bbox"]})
    if vl:
        d = parse_date(vl["text"])
        if d:
            facts["valid_until"] = d.isoformat()
            remaining = (d - today).days
            facts["days_remaining"] = remaining
            need = spec.get("min_remaining_days", 0)
            if remaining < 0:
                findings.append({"rule_id": f"R-{tid}-D1", "clause": clause, "outcome": "fail", "severity": "high",
                                 "title": "Document has expired", "expired": True,
                                 "detail": f"Validity ended on {d:%d %B %Y} ({-remaining} days ago).",
                                 "page": vl["page"], "bbox": vl["bbox"]})
            elif remaining < need:
                findings.append({"rule_id": f"R-{tid}-D2", "clause": clause, "outcome": "warn", "severity": "medium",
                                 "title": "Validity window too short",
                                 "detail": f"Valid until {d:%d %B %Y}; rule needs at least {need} days remaining.",
                                 "page": vl["page"], "bbox": vl["bbox"]})
            else:
                findings.append({"rule_id": f"R-{tid}-D1", "clause": clause, "outcome": "pass", "severity": "info",
                                 "title": "Document within validity", "detail": f"Valid until {d:%d %B %Y} ({remaining} days left).",
                                 "page": vl["page"], "bbox": vl["bbox"]})
    elif spec.get("validity_required"):
        findings.append({"rule_id": f"R-{tid}-D1", "clause": clause, "outcome": "fail", "severity": "medium",
                         "title": "Validity date not found", "detail": "This document type must state a validity / expiry date."})
    facts["label"] = spec["label"]
    return {"findings": findings, "facts": facts, "bundle": rules.get("bundle")}


def completeness(category: str, present_types: list[str], rules: dict) -> dict:
    cat = next((c for c in rules["categories"] if c["id"] == category), None)
    if not cat:
        return {"required": [], "missing": [], "complete": False}
    missing = [d for d in cat["docs"] if d not in present_types]
    return {"category": cat["label"], "required": cat["docs"], "missing": missing, "complete": not missing}
