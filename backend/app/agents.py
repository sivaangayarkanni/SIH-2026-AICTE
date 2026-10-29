"""Explainer agents (Advocate · Critic · Head). They ONLY explain the deterministic decision.
Default: rule-based templates (fully offline, reproducible). Optional: an OpenAI-compatible LLM rewrites the
explanations when OPENAI_API_KEY is set — the status is passed in as a fixed fact and is never changed."""


def _fmt(f):
    loc = f" (page {f['page']})" if f.get("page") else ""
    return f"{f['title']}{loc} — {f.get('rule_id')}"


def rule_based(doc_label: str, findings: list[dict], decision: dict) -> list[dict]:
    passes = [f for f in findings if f.get("outcome") == "pass"]
    issues = [f for f in findings if f.get("outcome") in ("fail", "warn")]
    issues.sort(key=lambda f: ["critical", "high", "medium", "low", "info"].index(f.get("severity", "info")))
    adv = (f"I reviewed the {doc_label}. " + (
        "Points supporting authenticity: " + "; ".join(_fmt(f) for f in passes[:5]) + "."
        if passes else "I could not find independent checks that confirm this document."))
    if issues:
        crit = "I disagree on these points: " + "; ".join(_fmt(f) for f in issues[:5]) + "."
        if any(f.get("forgery") for f in issues):
            crit += " At least one finding is a forgery indicator, which outweighs the positive checks."
    else:
        crit = "I looked for hidden text, overlays, post-signing edits, expiry and photo reuse and found no problems."
    head = (f"The deterministic policy engine applied rule {decision['policy_rule']} ({decision['policy_text']}) and set the "
            f"status to “{decision['status']}” with risk score {decision['risk_score']}/100. "
            + ("Recommendation: an officer should inspect the highlighted evidence before deciding. "
               if decision["status"] != "Verified" else "Recommendation: the officer can accept this document. ")
            + "This explanation is advisory; the final decision is made by a human officer.")
    return [{"agent": "Advocate", "stance": "for", "message": adv},
            {"agent": "Critic", "stance": "against", "message": crit},
            {"agent": "Head", "stance": "summary", "message": head, "engine": "rule-based"}]


def explain(doc_label: str, findings: list[dict], decision: dict) -> list[dict]:
    """Rule-based by default; optionally reworded by a guarded LLM (app/llm.py). The status never changes."""
    base = rule_based(doc_label, findings, decision)
    from .llm import reword
    try:
        out, meta = reword(base, findings, decision)
    except Exception:  # noqa: BLE001
        return base
    if meta.get("rejected"):
        out[-1] = {**out[-1], "guardrail": meta["rejected"]}
    return out
