"""5 · Deterministic Policy Engine. The ONLY component that sets a verification status.
Ordered rules (first match wins). AI agents can explain but never change the outcome."""

STATUSES = ["Verified", "Mismatch Detected", "Expired", "Verification Pending", "Source Unavailable",
            "Manual Review Required"]
SEV_W = {"info": 0, "low": 5, "medium": 15, "high": 30, "critical": 45}

POLICY_TABLE = [
    ("P1", "Mismatch Detected", "Forgery indicator: hidden text, masking overlay, broken/partial signature, or reused photo"),
    ("P2", "Expired", "Signing certificate or document validity has expired"),
    ("P3", "Source Unavailable", "Issuer cannot be confirmed against its source registry"),
    ("P4", "Manual Review Required", "Active content removed by CDR, unsigned edits, shared PII across colleges, or missing fields"),
    ("P5", "Verification Pending", "Analysis not finished"),
    ("P6", "Verified", "All checks passed"),
]


def decide(findings: list[dict], analysis_complete: bool = True) -> dict:

    def any_(pred):
        hits = [f for f in findings if pred(f)]
        return hits

    p1 = any_(lambda f: f.get("forgery"))
    p2 = any_(lambda f: f.get("expired"))
    p3 = any_(lambda f: f.get("source_unavailable"))
    p4 = any_(lambda f: f.get("manual_review") or (f.get("outcome") == "fail" and f.get("module") == "4B"
                                                    and not f.get("expired")))
    risk = min(100, sum(SEV_W.get(f.get("severity", "info"), 0) for f in findings if f.get("outcome") != "pass"))
    if not analysis_complete:
        status, rule, basis = "Verification Pending", "P5", []
    elif p1:
        status, rule, basis = "Mismatch Detected", "P1", p1
    elif p2:
        status, rule, basis = "Expired", "P2", p2
    elif p3:
        status, rule, basis = "Source Unavailable", "P3", p3
    elif p4:
        status, rule, basis = "Manual Review Required", "P4", p4
    else:
        status, rule, basis = "Verified", "P6", []
    return {"status": status, "policy_rule": rule,
            "policy_text": next(t for r, s, t in POLICY_TABLE if r == rule),
            "basis": [b.get("rule_id") for b in basis], "risk_score": risk}


ORDER = {"Mismatch Detected": 0, "Expired": 1, "Manual Review Required": 2, "Source Unavailable": 3,
         "Verification Pending": 4, "Verified": 5}


def aggregate(doc_statuses: list[str], complete: bool) -> str:
    if not doc_statuses:
        return "Draft"
    worst = min(doc_statuses, key=lambda s: ORDER.get(s, 9))
    if worst == "Verified" and not complete:
        return "Verification Pending"
    return worst
