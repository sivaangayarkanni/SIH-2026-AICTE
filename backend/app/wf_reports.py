"""Dashboards, reports (CSV/PDF), EVC summary and calendar/ICS for the workflow module."""
from __future__ import annotations
import csv, io
from collections import defaultdict
from datetime import datetime, timedelta, date

from .db import Application, College, User
from .workflow import (AppWorkflow, StageEvent, EvcVisit, Undertaking, DocumentValidity, Alert, UserRegion,
                       active_config, region_name, stage_label, region_for_state, SAFEGUARD, workflow_out)
from .db import now

AGE_BUCKETS = [(0, 7, "0-7 d"), (8, 15, "8-15 d"), (16, 30, "16-30 d"), (31, 10**6, "> 30 d")]


def _bucket(days):
    return next(l for lo, hi, l in AGE_BUCKETS if lo <= days <= hi)


def scope_apps(s, u, scope="auto"):
    """College: own. Regional officer: own region(s) when scope=mine (default for officers). Bureau/admin: all."""
    q = s.query(Application)
    if u.role == "college":
        return q.filter(Application.college_id == u.college_id).all(), None
    apps = q.all()
    if u.role == "officer" and scope in ("auto", "mine"):
        regs = {r.region_code for r in s.query(UserRegion).filter(UserRegion.user_id == u.id).all()}
        if regs:
            wfs = {w.application_id: w.region_code for w in s.query(AppWorkflow).all()}
            cfg = active_config(s)
            apps = [a for a in apps if (wfs.get(a.id) or region_for_state(cfg, a.college.state if a.college else None)) in regs]
            return apps, sorted(regs)
    return apps, None


def dashboard(s, u, scope="auto", as_of=None):
    cfg = active_config(s)
    t = as_of or now()
    apps, regs = scope_apps(s, u, scope)
    ids = {a.id for a in apps}
    wfs = {w.application_id: w for w in s.query(AppWorkflow).all() if w.application_id in ids}
    users = {x.id: x for x in s.query(User).all()}
    by_region, by_stage, by_officer, by_inst, ageing = defaultdict(int), defaultdict(int), defaultdict(int), defaultdict(int), defaultdict(int)
    approaching, overdue = [], []
    for a in apps:
        w = wfs.get(a.id)
        if not w or w.state == "completed":
            continue
        by_region[region_name(cfg, w.region_code)] += 1
        by_stage[stage_label(cfg, w.current_stage) + (" (with institution)" if w.state == "returned" else "")] += 1
        by_officer[users[w.assigned_officer_id].name if w.assigned_officer_id in users else "Unassigned"] += 1
        by_inst[a.college.name if a.college else "?"] += 1
        days = (t - w.stage_started_at).days if w.stage_started_at else 0
        ageing[_bucket(days)] += 1
        row = {"id": a.id, "ref": a.ref, "college": a.college.name if a.college else "", "stage": stage_label(cfg, w.current_stage),
               "region": region_name(cfg, w.region_code), "due": w.stage_due_at.isoformat() if w.stage_due_at else None, "days_in_stage": days}
        if w.state == "active" and w.stage_due_at:
            if w.stage_due_at < t:
                overdue.append({**row, "days_overdue": (t - w.stage_due_at).days})
            elif w.stage_due_at - t <= timedelta(days=max(cfg["reminders"].get("stage_sla", [3]) or [3])):
                approaching.append({**row, "days_left": (w.stage_due_at - t).days})
    # bottlenecks: mean days spent per stage, from history
    spent = defaultdict(list)
    for aid in ids:
        ev = s.query(StageEvent).filter(StageEvent.application_id == aid).order_by(StageEvent.at, StageEvent.id).all()
        for e1, e2 in zip(ev, ev[1:]):
            if e1.to_stage and e1.to_stage != "institution":
                spent[e1.to_stage].append((e2.at - e1.at).total_seconds() / 86400)
        w = wfs.get(aid)
        if w and w.state in ("active", "returned") and w.stage_started_at:
            spent[w.current_stage].append((t - w.stage_started_at).total_seconds() / 86400)
    bottlenecks = sorted([{"stage": stage_label(cfg, k), "mean_days": round(sum(v) / len(v), 1), "n": len(v),
                           "sla_days": cfg["stages"].get(k, {}).get("sla_days")} for k, v in spent.items() if v],
                         key=lambda x: -(x["mean_days"] / (x["sla_days"] or 1)))
    alerts_q = s.query(Alert).filter(Alert.closed_at.is_(None))
    if u.role == "college":
        alerts_q = alerts_q.filter(Alert.college_id == u.college_id, Alert.target_role == "college")
    elif regs:
        alerts_q = alerts_q.filter(Alert.region_code.in_(regs))
    alerts = [{"id": x.id, "kind": x.kind, "level": x.level, "step": x.step, "target_role": x.target_role, "message": x.message,
               "application_id": x.application_id, "created_at": x.created_at.isoformat(), "due_at": x.due_at.isoformat() if x.due_at else None}
              for x in alerts_q.order_by(Alert.id.desc()).limit(60).all()]
    visits = s.query(EvcVisit).filter(EvcVisit.application_id.in_(ids)).all() if ids else []
    uts = s.query(Undertaking).filter(Undertaking.application_id.in_(ids)).all() if ids else []
    cids = {a.college_id for a in apps}
    dvs = s.query(DocumentValidity).filter(DocumentValidity.college_id.in_(cids)).all() if cids else []
    td = t.date()
    return {
        "as_of": t.isoformat(), "scope": {"regions": regs, "label": ("My region(s): " + ", ".join(region_name(cfg, r) for r in regs)) if regs else
                                           ("My institution" if u.role == "college" else "All regions")},
        "totals": {"in_workflow": sum(1 for w in wfs.values() if w.state != "completed"), "approaching": len(approaching), "overdue": len(overdue),
                   "returned": sum(1 for w in wfs.values() if w.state == "returned"), "awaiting_decision": sum(1 for w in wfs.values() if w.state == "awaiting_decision"),
                   "open_alerts": len(alerts), "escalations": sum(1 for x in alerts if x["level"] == "escalation")},
        "by_region": dict(by_region), "by_stage": dict(by_stage), "by_officer": dict(by_officer), "by_institution": dict(by_inst),
        "ageing": {l: ageing.get(l, 0) for _, _, l in AGE_BUCKETS}, "bottlenecks": bottlenecks,
        "approaching": sorted(approaching, key=lambda r: r["days_left"]), "overdue": sorted(overdue, key=lambda r: -r["days_overdue"]),
        "alerts": alerts,
        "evc": {"to_schedule": sum(v.status == "to_schedule" for v in visits), "scheduled": sum(v.status == "scheduled" for v in visits),
                "completed": sum(v.status == "completed" for v in visits), "overdue": sum(v.status != "completed" and v.due_by and v.due_by < t for v in visits)},
        "undertakings": {"open": sum(x.status == "open" for x in uts), "submitted": sum(x.status == "submitted" for x in uts),
                         "verified": sum(x.status == "verified" for x in uts), "overdue": sum(x.status in ("open", "rejected") and x.due_date < td for x in uts)},
        "validity": {"tracked": len(dvs), "expiring_60d": sum(x.status == "valid" and td <= x.valid_until <= td + timedelta(days=60) for x in dvs),
                     "expired": sum(x.status in ("valid", "renewal_submitted") and x.valid_until < td for x in dvs),
                     "renewal_pending": sum(x.status == "renewal_submitted" for x in dvs)},
        "safeguard": SAFEGUARD,
    }


# ------------------------------------------------------------------ reports
REPORTS = {
    "pendency": "Pendency (applications in workflow by stage)",
    "evc": "EVC status",
    "undertakings": "Undertaking compliance",
    "validity": "Document validity",
    "overdue": "Overdue items (all kinds)",
    "region_performance": "Region-wise performance",
}


def report(s, u, kind, as_of=None) -> tuple[list[str], list[list]]:
    cfg = active_config(s)
    t = as_of or now()
    td = t.date()
    apps, _ = scope_apps(s, u, "auto")
    amap = {a.id: a for a in apps}
    wfs = {w.application_id: w for w in s.query(AppWorkflow).all() if w.application_id in amap}
    if kind == "pendency":
        rows = []
        for aid, w in sorted(wfs.items()):
            if w.state == "completed":
                continue
            a = amap[aid]
            rows.append([a.ref, a.college.name, region_name(cfg, w.region_code), w.route_id, stage_label(cfg, w.current_stage), w.state,
                         (t - w.stage_started_at).days if w.stage_started_at else "", w.stage_due_at.date().isoformat() if w.stage_due_at else "",
                         "yes" if w.stage_due_at and w.stage_due_at < t and w.state == "active" else "no"])
        return ["Application", "Institution", "Region", "Route", "Stage", "State", "Days in stage", "Stage due", "Overdue"], rows
    if kind == "evc":
        rows = []
        for v in s.query(EvcVisit).filter(EvcVisit.application_id.in_(list(amap) or [0])).order_by(EvcVisit.id).all():
            a = amap[v.application_id]
            rows.append([a.ref, a.college.name, "yes" if a.category == "new_institution" else "no", v.status,
                         v.scheduled_for.date().isoformat() if v.scheduled_for else "", v.due_by.date().isoformat() if v.due_by else "",
                         v.completed_at.date().isoformat() if v.completed_at else "", len(v.members_json or []), len(v.reports_json or {}),
                         "yes" if v.status != "completed" and v.due_by and v.due_by < t else "no"])
        return ["Application", "Institution", "New institution", "Status", "Scheduled for", "Complete by", "Completed", "Members", "Member reports", "Overdue"], rows
    if kind == "undertakings":
        rows = []
        for x in s.query(Undertaking).filter(Undertaking.application_id.in_(list(amap) or [0])).order_by(Undertaking.due_date).all():
            a = amap[x.application_id]
            rows.append([x.id, a.ref, a.college.name, x.condition, x.due_date.isoformat(), x.status, "yes" if x.status in ("open", "rejected") and x.due_date < td else "no", x.verified_by or ""])
        return ["#", "Application", "Institution", "Condition", "Due", "Status", "Overdue", "Verified by"], rows
    if kind == "validity":
        cids = {a.college_id for a in apps}
        cols = {c.id: c for c in s.query(College).all()}
        rows = []
        for x in s.query(DocumentValidity).filter(DocumentValidity.college_id.in_(list(cids) or [0])).order_by(DocumentValidity.valid_until).all():
            left = (x.valid_until - td).days
            rows.append([x.id, cols[x.college_id].name, x.label, x.valid_from.isoformat() if x.valid_from else "", x.valid_until.isoformat(), left, x.status,
                         "expired" if left < 0 and x.status in ("valid", "renewal_submitted") else ("expiring" if left <= 60 and x.status == "valid" else "ok")])
        return ["#", "Institution", "Document", "Valid from", "Valid until", "Days left", "Status", "Flag"], rows
    if kind == "overdue":
        rows = []
        for aid, w in wfs.items():
            if w.state == "active" and w.stage_due_at and w.stage_due_at < t:
                rows.append(["Stage SLA", amap[aid].ref, amap[aid].college.name, stage_label(cfg, w.current_stage), w.stage_due_at.date().isoformat(), (t - w.stage_due_at).days])
        for a in apps:
            if not a.submitted_at and a.deadline and a.deadline < t:
                rows.append(["Submission deadline", a.ref, a.college.name, "Not submitted", a.deadline.date().isoformat(), (t - a.deadline).days])
        for v in s.query(EvcVisit).filter(EvcVisit.application_id.in_(list(amap) or [0]), EvcVisit.status != "completed").all():
            if v.due_by and v.due_by < t:
                rows.append(["EVC visit", amap[v.application_id].ref, amap[v.application_id].college.name, v.status, v.due_by.date().isoformat(), (t - v.due_by).days])
        for x in s.query(Undertaking).filter(Undertaking.application_id.in_(list(amap) or [0]), Undertaking.status.in_(["open", "rejected"])).all():
            if x.due_date < td:
                rows.append(["Undertaking", amap[x.application_id].ref, amap[x.application_id].college.name, x.condition[:60], x.due_date.isoformat(), (td - x.due_date).days])
        cids = {a.college_id: a for a in apps}
        for x in s.query(DocumentValidity).filter(DocumentValidity.status.in_(["valid", "renewal_submitted"])).all():
            if x.college_id in cids and x.valid_until < td:
                rows.append(["Document validity", cids[x.college_id].ref, cids[x.college_id].college.name, x.label, x.valid_until.isoformat(), (td - x.valid_until).days])
        rows.sort(key=lambda r: -r[5])
        return ["Type", "Application", "Institution", "Item", "Due", "Days overdue"], rows
    if kind == "region_performance":
        agg = defaultdict(lambda: {"n": 0, "active": 0, "overdue": 0, "completed": 0, "days": [], "returned": 0})
        for aid, w in wfs.items():
            g = agg[region_name(cfg, w.region_code)]
            g["n"] += 1
            g["completed"] += w.state == "completed"
            g["returned"] += w.state == "returned"
            g["active"] += w.state in ("active", "awaiting_decision")
            g["overdue"] += bool(w.state == "active" and w.stage_due_at and w.stage_due_at < t)
            first = s.query(StageEvent).filter(StageEvent.application_id == aid).order_by(StageEvent.at).first()
            if first:
                g["days"].append((t - first.at).days)
        rows = [[r, g["n"], g["active"], g["returned"], g["completed"], g["overdue"], round(100 * g["overdue"] / max(1, g["active"]), 1),
                 round(sum(g["days"]) / len(g["days"]), 1) if g["days"] else ""] for r, g in sorted(agg.items())]
        return ["Region", "In workflow", "Active", "With institution", "Completed", "Overdue", "% overdue", "Mean age (days)"], rows
    raise KeyError(kind)


def to_csv(header, rows) -> str:
    b = io.StringIO()
    w = csv.writer(b)
    w.writerow(header)
    for r in rows:
        w.writerow(["'" + str(c) if isinstance(c, str) and c[:1] in ("=", "+", "-", "@") else c for c in r])   # CSV-injection guard
    return b.getvalue()


def _pdf_doc(title, subtitle, blocks) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    buf = io.BytesIO()
    land = any(b[0] == "table" and len(b[1]) > 6 for b in blocks)
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4) if land else A4, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36,
                            title=title, author="SealCheck (prototype)")
    st = getSampleStyleSheet()
    small = st["BodyText"].clone("small", fontSize=8, leading=10)
    flow = [Paragraph(f"<b>{title}</b>", st["Title"]), Paragraph(subtitle, small),
            Paragraph("Prototype - not an official AICTE system. " + SAFEGUARD, small), Spacer(1, 8)]
    for b in blocks:
        if b[0] == "h":
            flow += [Spacer(1, 6), Paragraph(f"<b>{b[1]}</b>", st["Heading3"])]
        elif b[0] == "p":
            flow.append(Paragraph(b[1], st["BodyText"]))
        elif b[0] == "table":
            header, rows = b[1], b[2]
            data = [[Paragraph(f"<b>{h}</b>", small) for h in header]] + [[Paragraph(str(c).replace("&", "&amp;").replace("<", "&lt;"), small) for c in r] for r in rows]
            if not rows:
                data.append([Paragraph("No rows", small)] + [""] * (len(header) - 1))
            tb = Table(data, repeatRows=1, hAlign="LEFT")
            tb.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.3, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef7")),
                                    ("VALIGN", (0, 0), (-1, -1), "TOP")]))
            flow.append(tb)
    doc.build(flow)
    return buf.getvalue()


def report_pdf(title, header, rows, as_of) -> bytes:
    return _pdf_doc(title, f"Generated {as_of:%d %b %Y %H:%M} UTC - {len(rows)} row(s)", [("table", header, rows)])


# ------------------------------------------------------------------ EVC summary
EVC_CHECKLIST = [
    ("land", "Land and possession match the submitted land documents"),
    ("building", "Built-up area and building as per approved plan"),
    ("labs", "Laboratories and equipment as declared"),
    ("faculty", "Faculty present as per submitted list"),
    ("fire", "Fire safety arrangements in place"),
    ("library", "Library and learning resources available"),
    ("accessibility", "Accessibility provisions (ramps, toilets)"),
]


def evc_summary(s, a) -> dict:
    from .crosscheck import crosscheck
    cfg = active_config(s)
    wf = workflow_out(s, a, cfg)
    cc = crosscheck(s, a)
    docs = [{"id": d.id, "filename": d.filename, "doc_type": d.doc_type, "status": d.status,
             "valid_until": ((d.analysis_json or {}).get("facts") or {}).get("valid_until"),
             "issuer": ((d.analysis_json or {}).get("facts") or {}).get("issuer"),
             "top_findings": [f.get("title") for f in ((d.analysis_json or {}).get("findings") or []) if f.get("outcome") in ("fail", "warn")][:3]}
            for d in a.documents]
    td = now().date()
    dvs = s.query(DocumentValidity).filter(DocumentValidity.college_id == a.college_id).all()
    uts = s.query(Undertaking).filter(Undertaking.application_id == a.id).all()
    v = s.query(EvcVisit).filter(EvcVisit.application_id == a.id).order_by(EvcVisit.id.desc()).first()
    users = {x.id: x for x in s.query(User).all()}
    flagged = [d for d in docs if d["status"] == "Mismatch Detected"]
    return {
        "application": {"id": a.id, "ref": a.ref, "title": a.title, "category": a.category, "status": a.status, "risk_score": a.risk_score,
                        "submitted_at": a.submitted_at.isoformat() if a.submitted_at else None},
        "institution": {"name": a.college.name, "code": a.college.code, "city": a.college.city, "state": a.college.state,
                        "type": a.college.institution_type, "region": region_name(cfg, region_for_state(cfg, a.college.state))},
        "workflow": wf,
        "at_a_glance": {"documents": len(docs), "flagged_documents": len(flagged), "cross_document_mismatches": len(cc["mismatches"]),
                        "expired_documents": sum(1 for x in dvs if x.valid_until < td and x.status in ("valid", "renewal_submitted")),
                        "open_undertakings": sum(1 for x in uts if x.status in ("open", "rejected"))},
        "documents": docs,
        "mismatches": cc["mismatches"],
        "validity": [{"label": x.label, "valid_until": x.valid_until.isoformat(), "status": x.status, "days_left": (x.valid_until - td).days} for x in dvs],
        "undertakings": [{"id": x.id, "condition": x.condition, "due_date": x.due_date.isoformat(), "status": x.status} for x in uts],
        "visit": None if not v else {"id": v.id, "status": v.status, "scheduled_for": v.scheduled_for.isoformat() if v.scheduled_for else None,
                                     "due_by": v.due_by.isoformat() if v.due_by else None,
                                     "members": [{"id": m, "name": users[m].name if m in users else f"user {m}"} for m in (v.members_json or [])],
                                     "reports": [{"member": users[int(k)].name if int(k) in users else k, **r} for k, r in (v.reports_json or {}).items()]},
        "checklist": [{"id": k, "label": l} for k, l in EVC_CHECKLIST],
        "focus_points": ([f"Cross-check field '{m['field_label']}': {m['a']['value']} vs {m['b']['value']}" for m in cc["mismatches"][:6]] +
                         [f"Document flagged by analysis: {d['filename']}" for d in flagged[:4]] +
                         [f"Expired document: {x.label} (until {x.valid_until:%d %b %Y})" for x in dvs if x.valid_until < td and x.status == "valid"][:4]),
        "safeguard": SAFEGUARD,
        "generated_at": now().isoformat(),
    }


def evc_summary_pdf(sm) -> bytes:
    ap, ins, g = sm["application"], sm["institution"], sm["at_a_glance"]
    wf = sm["workflow"] or {}
    blocks = [("h", "One-page summary"),
              ("table", ["Field", "Value"], [["Application", f"{ap['ref']} - {ap['title']}"], ["Institution", f"{ins['name']} ({ins['code']}), {ins['city']}, {ins['state']}"],
                                             ["Region", ins["region"]], ["Route / stage", f"{wf.get('route_label', '-')} / {wf.get('current_label', '-')}"],
                                             ["Documents", f"{g['documents']} ({g['flagged_documents']} flagged by analysis)"],
                                             ["Cross-document mismatches", g["cross_document_mismatches"]], ["Expired documents", g["expired_documents"]],
                                             ["Open undertakings", g["open_undertakings"]]]),
              ("h", "Points to verify on site"),
              ("table", ["#", "Focus point"], [[i + 1, p] for i, p in enumerate(sm["focus_points"])] or [["-", "No automated focus points"]]),
              ("h", "Verification checklist (to be filled by EVC members)"),
              ("table", ["Item", "Observed (Yes / No / NA)", "Remarks"], [[c["label"], "", ""] for c in sm["checklist"]]),
              ("h", "Detail: documents"),
              ("table", ["File", "Type", "Status", "Issuer", "Valid until", "Findings"], [[d["filename"], d["doc_type"], d["status"], d["issuer"] or "", d["valid_until"] or "", "; ".join(d["top_findings"])] for d in sm["documents"]]),
              ("h", "Detail: cross-document mismatches"),
              ("table", ["Field", "Value A (source, page)", "Value B (source, page)"],
               [[m["field_label"], f"{m['a']['value']} ({m['a']['source']}, p{m['a']['page'] or '-'})", f"{m['b']['value']} ({m['b']['source']}, p{m['b']['page'] or '-'})"] for m in sm["mismatches"]]),
              ("h", "Detail: document validity and undertakings"),
              ("table", ["Item", "Due / valid until", "Status"], [[x["label"], x["valid_until"], x["status"]] for x in sm["validity"]] + [[f"Undertaking: {x['condition']}", x["due_date"], x["status"]] for x in sm["undertakings"]])]
    if sm["visit"] and sm["visit"]["reports"]:
        blocks += [("h", "EVC member observations"), ("table", ["Member", "Remarks", "Checklist"],
                                                     [[r["member"], r.get("remarks", ""), ", ".join(f"{k}: {v}" for k, v in (r.get("checklist") or {}).items())] for r in sm["visit"]["reports"]])]
    blocks.append(("p", "The EVC records observations only. Recommendations and decisions are taken by the competent authority."))
    return _pdf_doc(f"EVC summary - {ap['ref']}", f"Generated {sm['generated_at'][:16]} UTC", blocks)


# ------------------------------------------------------------------ calendar
COLORS = {"submission_deadline": "#d97706", "stage_sla": "#2563eb", "evc_visit": "#7c3aed", "undertaking": "#059669", "document_validity": "#dc2626"}


def calendar_events(s, u, start: date, end: date) -> list[dict]:
    cfg = active_config(s)
    apps, _ = scope_apps(s, u, "auto")
    amap = {a.id: a for a in apps}
    out = []
    t = now()

    def add(kind, uid, d, title, link, overdue=False, extra=None):
        dd = d.date() if isinstance(d, datetime) else d
        if dd and start <= dd <= end:
            out.append({"id": uid, "kind": kind, "date": dd.isoformat(), "title": title, "link": link, "color": COLORS[kind], "overdue": overdue, **(extra or {})})

    for a in apps:
        if a.deadline and not a.submitted_at:
            add("submission_deadline", f"deadline-{a.id}", a.deadline, f"Submission deadline: {a.ref}", f"/apply/{a.id}", a.deadline < t)
    for w in s.query(AppWorkflow).filter(AppWorkflow.application_id.in_(list(amap) or [0])).all():
        if w.state == "active" and w.stage_due_at:
            add("stage_sla", f"stage-{w.application_id}", w.stage_due_at, f"{stage_label(cfg, w.current_stage)} due: {amap[w.application_id].ref}",
                f"/applications/{w.application_id}", w.stage_due_at < t)
    for v in s.query(EvcVisit).filter(EvcVisit.application_id.in_(list(amap) or [0])).all():
        a = amap[v.application_id]
        if u.role == "evc_member" and u.id not in (v.members_json or []):
            continue
        if v.scheduled_for:
            add("evc_visit", f"evc-{v.id}", v.scheduled_for, f"EVC visit: {a.ref} ({a.college.name})", "/evc", False, {"status": v.status})
        if v.status != "completed" and v.due_by:
            add("evc_visit", f"evc-due-{v.id}", v.due_by, f"EVC must be complete: {a.ref}", "/evc", v.due_by < t)
    for x in s.query(Undertaking).filter(Undertaking.application_id.in_(list(amap) or [0]), Undertaking.status.in_(["open", "rejected", "submitted"])).all():
        add("undertaking", f"ut-{x.id}", x.due_date, f"Undertaking due: {x.condition[:60]}", "/compliance", x.due_date < t.date() and x.status != "submitted")
    cids = {a.college_id for a in apps}
    for x in s.query(DocumentValidity).filter(DocumentValidity.college_id.in_(list(cids) or [0]), DocumentValidity.status.in_(["valid", "renewal_submitted"])).all():
        col = s.get(College, x.college_id)
        add("document_validity", f"dv-{x.id}", x.valid_until, f"{x.label} expires ({col.code})", "/compliance", x.valid_until < t.date())
    return sorted(out, key=lambda e: e["date"])


def _ics_escape(v: str) -> str:
    return v.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def to_ics(events, base_url: str, name="SealCheck deadlines") -> str:
    stamp = now().strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//SealCheck prototype//Workflow calendar//EN", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", f"X-WR-CALNAME:{_ics_escape(name)}"]
    for e in events:
        d = e["date"].replace("-", "")
        nd = (date.fromisoformat(e["date"]) + timedelta(days=1)).strftime("%Y%m%d")
        lines += ["BEGIN:VEVENT", f"UID:{e['id']}@sealcheck", f"DTSTAMP:{stamp}", f"DTSTART;VALUE=DATE:{d}", f"DTEND;VALUE=DATE:{nd}",
                  f"SUMMARY:{_ics_escape(('[OVERDUE] ' if e['overdue'] else '') + e['title'])}", f"CATEGORIES:{e['kind']}",
                  f"URL:{base_url.rstrip('/')}{e['link']}", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    out = []
    for ln in lines:   # RFC 5545 line folding at 75 octets
        while len(ln.encode()) > 75:
            out.append(ln[:73]); ln = " " + ln[73:]
        out.append(ln)
    return "\r\n".join(out) + "\r\n"
