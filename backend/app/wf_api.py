"""HTTP API for the workflow module (/api/wf/*, /api/cron/evaluate). Every state change is audit-logged."""
from __future__ import annotations
import hashlib, hmac, json, os
from datetime import datetime, date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import Response, PlainTextResponse
from pydantic import BaseModel, Field

from . import audit, workflow as wf, wf_reports as rep
from .config import IS_PROD, secret
from .crosscheck import crosscheck, DECLARED_KEYS
from .db import Application, User, Notification, now
from .main import current_user, require, actor, db, scoped_app, ROLE_LABEL
from .workflow import (EvcVisit, Undertaking, ComplianceSubmission, DocumentValidity, Alert, WizardDraft, UserRegion,
                       WorkflowConfigVersion, WorkflowError, SAFEGUARD)

router = APIRouter()
STAFF = ("officer", "senior_officer", "admin")
DECIDERS = ("officer", "senior_officer")


def _wf_call(fn, *a, **k):
    try:
        return fn(*a, **k)
    except WorkflowError as e:
        raise HTTPException(e.status, e.msg)


def _as_of(v: str | None):
    """Time travel for evaluation/dashboards is a development/test aid only."""
    if not v:
        return None
    if IS_PROD:
        raise HTTPException(400, "as_of (time travel) is disabled in production.")
    try:
        return datetime.fromisoformat(v.replace("Z", ""))
    except ValueError:
        raise HTTPException(400, "as_of must be ISO-8601")


def _readable_app(s, app_id, u):
    a = scoped_app(s, app_id, u)
    if u.role == "evc_member":
        v = s.query(EvcVisit).filter(EvcVisit.application_id == a.id).all()
        if not any(u.id in (x.members_json or []) for x in v):
            raise HTTPException(404, "Application not found")
    return a


@router.get("/api/wf/meta")
def meta(u: User = Depends(current_user), s=Depends(db)):
    cfg = wf.active_config(s)
    return {"safeguard": SAFEGUARD, "reports": rep.REPORTS, "colors": rep.COLORS, "checklist": [{"id": k, "label": l} for k, l in rep.EVC_CHECKLIST],
            "regions": cfg["regions"], "stages": {k: v["label"] for k, v in cfg["stages"].items()}, "routes": cfg["routes"],
            "config_version": cfg.get("version"), "config_signed": cfg.get("_signed"), "declared_fields": DECLARED_KEYS}


# ------------------------------------------------------------------ application workflow
class NoteIn(BaseModel):
    note: str = Field("", max_length=2000)


class ReasonIn(BaseModel):
    reason: str = Field(min_length=5, max_length=2000)
    items: list[str] = []


@router.get("/api/wf/apps/{app_id}")
def app_workflow(app_id: int, u: User = Depends(current_user), s=Depends(db)):
    a = _readable_app(s, app_id, u)
    cfg = wf.active_config(s)
    cc = crosscheck(s, a)
    visits = s.query(EvcVisit).filter(EvcVisit.application_id == a.id).order_by(EvcVisit.id).all()
    uts = s.query(Undertaking).filter(Undertaking.application_id == a.id).order_by(Undertaking.id).all()
    return {"workflow": wf.workflow_out(s, a, cfg), "crosscheck": cc, "evc_visits": [_visit_out(s, v, u) for v in visits],
            "undertakings": [_ut_out(s, x) for x in uts], "safeguard": SAFEGUARD,
            "can_act": u.role in STAFF, "route_preview": wf.pick_route(cfg, a.category)}


@router.post("/api/wf/apps/{app_id}/advance")
def adv(app_id: int, body: NoteIn, u: User = Depends(require(*STAFF)), s=Depends(db)):
    a = scoped_app(s, app_id, u)
    _wf_call(wf.advance, s, a, u, actor(u), body.note)
    return app_workflow(app_id, u, s)


@router.post("/api/wf/apps/{app_id}/return")
def ret(app_id: int, body: ReasonIn, u: User = Depends(require(*STAFF)), s=Depends(db)):
    a = scoped_app(s, app_id, u)
    _wf_call(wf.return_to_institution, s, a, u, actor(u), body.reason, body.items)
    return app_workflow(app_id, u, s)


@router.post("/api/wf/apps/{app_id}/revert")
def rev(app_id: int, body: ReasonIn, u: User = Depends(require(*STAFF)), s=Depends(db)):
    a = scoped_app(s, app_id, u)
    _wf_call(wf.revert, s, a, u, actor(u), body.reason)
    return app_workflow(app_id, u, s)


@router.post("/api/wf/apps/{app_id}/resubmit")
def resub(app_id: int, body: NoteIn, u: User = Depends(require("college")), s=Depends(db)):
    a = scoped_app(s, app_id, u)
    _wf_call(wf.resubmit, s, a, u, actor(u), body.note)
    return app_workflow(app_id, u, s)


@router.get("/api/wf/apps/{app_id}/crosscheck")
def cc_get(app_id: int, u: User = Depends(current_user), s=Depends(db)):
    return crosscheck(s, _readable_app(s, app_id, u))


def notify_mismatches(s, a, who, role) -> dict:
    """Send the mismatch list to the institution ('to be corrected / re-uploaded') and flag it to officers. Idempotent per list."""
    mm = crosscheck(s, a)["mismatches"]
    if not mm:
        return {"sent": False, "mismatches": 0}
    digest = hashlib.sha256(json.dumps([(m["field"], m["a"]["value"], m["b"]["value"]) for m in mm]).encode()).hexdigest()[:16]
    items = [f"{m['field_label']}: '{m['a']['value']}' ({m['a']['source']}) vs '{m['b']['value']}' ({m['b']['source']})" for m in mm]
    key = f"mismatch:{a.id}:{digest}"
    if s.query(Alert).filter(Alert.dedupe_key == key + ":notice:college").first():
        return {"sent": False, "mismatches": len(mm), "detail": "This exact mismatch list was already sent."}
    for r in ("college", "officer"):
        s.add(Alert(dedupe_key=f"{key}:notice:{r}", kind="mismatch", level="notice", step="sent", target_role=r, college_id=a.college_id,
                    application_id=a.id, subject=f"mismatch:{a.id}", message=f"{a.ref}: {len(mm)} cross-document mismatch(es) - to be corrected / re-uploaded", created_at=now()))
    s.add(Notification(college_id=a.college_id, message=f"{a.ref}: {len(mm)} item(s) to be corrected / re-uploaded - " + "; ".join(items)[:380],
                       link=f"/applications/{a.id}", kind="mismatch", severity="warning"))
    s.add(Notification(role="officer", message=f"{a.ref}: {len(mm)} cross-document mismatch(es) flagged and sent to the institution",
                       link=f"/applications/{a.id}", kind="mismatch", severity="warning"))
    s.commit()
    audit.log("crosscheck.notified", who, role, f"application:{a.id}", {"mismatches": len(mm), "digest": digest, "items": items[:20]})
    return {"sent": True, "mismatches": len(mm)}


@router.post("/api/wf/apps/{app_id}/crosscheck/notify")
def cc_notify(app_id: int, u: User = Depends(require(*STAFF)), s=Depends(db)):
    a = scoped_app(s, app_id, u)
    res = notify_mismatches(s, a, actor(u), u.role)
    if not res["mismatches"]:
        raise HTTPException(409, "No cross-document mismatches to notify.")
    return res


class DraftIn(BaseModel):
    step: int = Field(0, ge=0, le=50)
    data: dict = {}


@router.get("/api/wf/apps/{app_id}/draft")
def draft_get(app_id: int, u: User = Depends(current_user), s=Depends(db)):
    a = _readable_app(s, app_id, u)
    d = s.get(WizardDraft, a.id)
    return {"application_id": a.id, "step": d.step if d else 0, "data": d.data_json if d else {}, "updated_at": d.updated_at.isoformat() if d else None}


@router.put("/api/wf/apps/{app_id}/draft")
def draft_put(app_id: int, body: DraftIn, u: User = Depends(require("college")), s=Depends(db)):
    a = scoped_app(s, app_id, u)
    if a.decision in ("Approved", "Rejected"):
        raise HTTPException(409, "A final decision exists; the form is closed.")
    inst = (body.data or {}).get("institution") or {}
    clean = {k: str(v)[:300] for k, v in inst.items() if k in DECLARED_KEYS}
    data = {**{k: v for k, v in (body.data or {}).items() if k != "institution"}, "institution": clean}
    if len(json.dumps(data)) > 20000:
        raise HTTPException(413, "Draft too large")
    d = s.get(WizardDraft, a.id) or WizardDraft(application_id=a.id)
    d.step, d.data_json, d.updated_at = body.step, data, now()
    s.merge(d); s.commit()
    audit.log("wizard.draft_saved", actor(u), u.role, f"application:{a.id}", {"step": body.step, "fields": sorted(clean)})
    return draft_get(app_id, u, s)


@router.get("/api/wf/apps/{app_id}/evc-summary")
def evc_sum(app_id: int, u: User = Depends(current_user), s=Depends(db)):
    if u.role == "college":
        raise HTTPException(403, "The EVC summary is for officers and EVC members.")
    a = _readable_app(s, app_id, u)
    audit.log("evc.summary_viewed", actor(u), u.role, f"application:{a.id}")
    return rep.evc_summary(s, a)


@router.get("/api/wf/apps/{app_id}/evc-summary.pdf")
def evc_sum_pdf(app_id: int, u: User = Depends(current_user), s=Depends(db)):
    if u.role == "college":
        raise HTTPException(403, "The EVC summary is for officers and EVC members.")
    a = _readable_app(s, app_id, u)
    pdf = rep.evc_summary_pdf(rep.evc_summary(s, a))
    audit.log("evc.summary_pdf", actor(u), u.role, f"application:{a.id}", {"bytes": len(pdf)})
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="EVC_summary_{a.ref}.pdf"'})


# ------------------------------------------------------------------ EVC
def _visit_out(s, v, u):
    a = s.get(Application, v.application_id)
    users = {x.id: x for x in s.query(User).filter(User.id.in_(v.members_json or [0])).all()}
    reports = v.reports_json or {}
    return {"id": v.id, "application_id": v.application_id, "ref": a.ref, "college": a.college.name, "new_institution": a.category == "new_institution",
            "status": v.status, "schedule_by": v.schedule_by.isoformat() if v.schedule_by else None,
            "scheduled_for": v.scheduled_for.isoformat() if v.scheduled_for else None, "due_by": v.due_by.isoformat() if v.due_by else None,
            "overdue": bool(v.status != "completed" and v.due_by and v.due_by < now()),
            "members": [{"id": m, "name": users[m].name if m in users else str(m)} for m in (v.members_json or [])],
            "reports": {k: r for k, r in reports.items()} if u.role != "college" else {},
            "my_report": reports.get(str(u.id)), "completed_at": v.completed_at.isoformat() if v.completed_at else None, "completed_by": v.completed_by}


@router.get("/api/wf/evc")
def evc_list(u: User = Depends(require(*STAFF, "evc_member")), s=Depends(db)):
    q = s.query(EvcVisit).order_by(EvcVisit.id.desc()).all()
    if u.role == "evc_member":
        q = [v for v in q if u.id in (v.members_json or [])]
    elif u.role == "officer":
        ids = {a.id for a in rep.scope_apps(s, u)[0]}
        q = [v for v in q if v.application_id in ids]
    return {"visits": [_visit_out(s, v, u) for v in q], "safeguard": SAFEGUARD}


@router.get("/api/wf/evc/members")
def evc_members(u: User = Depends(require(*STAFF)), s=Depends(db)):
    return [{"id": x.id, "name": x.name, "title": x.title, "email": x.email} for x in s.query(User).filter(User.role == "evc_member").all()]


class ScheduleIn(BaseModel):
    scheduled_for: datetime
    members: list[int] = Field(min_length=1, max_length=10)


@router.post("/api/wf/evc/{vid}/schedule")
def evc_schedule(vid: int, body: ScheduleIn, u: User = Depends(require(*DECIDERS, "admin")), s=Depends(db)):
    v = s.get(EvcVisit, vid)
    if not v:
        raise HTTPException(404, "Visit not found")
    a = scoped_app(s, v.application_id, u)
    if v.status == "completed":
        raise HTTPException(409, "Visit already completed")
    members = s.query(User).filter(User.id.in_(body.members), User.role == "evc_member").all()
    if len(members) != len(set(body.members)):
        raise HTTPException(400, "Every member must be an existing EVC member account.")
    v.scheduled_for, v.members_json, v.status = body.scheduled_for.replace(tzinfo=None), sorted(set(body.members)), "scheduled"
    for m in members:
        s.add(Notification(user_id=m.id, role="evc_member", message=f"EVC visit {a.ref} scheduled for {v.scheduled_for:%d %b %Y}", link="/evc", kind="evc_visit"))
    s.add(Notification(college_id=a.college_id, message=f"{a.ref}: Expert Visit Committee visit scheduled for {v.scheduled_for:%d %b %Y}", link=f"/applications/{a.id}", kind="evc_visit"))
    s.commit()
    audit.log("evc.scheduled", actor(u), u.role, f"evc_visit:{v.id}", {"application": a.id, "for": v.scheduled_for.isoformat(), "members": v.members_json})
    return _visit_out(s, v, u)


class ReportIn(BaseModel):
    checklist: dict[str, str] = {}
    remarks: str = Field("", max_length=4000)


@router.post("/api/wf/evc/{vid}/report")
def evc_report(vid: int, body: ReportIn, u: User = Depends(require("evc_member")), s=Depends(db)):
    """EVC members record observations (checklist + remarks). They cannot advance, approve or reject."""
    v = s.get(EvcVisit, vid)
    if not v or u.id not in (v.members_json or []):
        raise HTTPException(404, "Visit not found")
    if v.status == "completed":
        raise HTTPException(409, "The visit has been closed by the officer.")
    allowed = {k for k, _ in rep.EVC_CHECKLIST}
    bad = [k for k, val in body.checklist.items() if k not in allowed or val not in ("yes", "no", "na")]
    if bad:
        raise HTTPException(400, f"Unknown checklist items or values: {bad}")
    r = dict(v.reports_json or {})
    r[str(u.id)] = {"checklist": body.checklist, "remarks": body.remarks, "at": now().isoformat(), "name": u.name}
    v.reports_json = r
    s.commit()
    audit.log("evc.member_report", actor(u), u.role, f"evc_visit:{v.id}", {"items": len(body.checklist)})
    return _visit_out(s, v, u)


@router.post("/api/wf/evc/{vid}/complete")
def evc_complete(vid: int, body: NoteIn, u: User = Depends(require(*DECIDERS)), s=Depends(db)):
    v = s.get(EvcVisit, vid)
    if not v:
        raise HTTPException(404, "Visit not found")
    a = scoped_app(s, v.application_id, u)
    if v.status != "scheduled":
        raise HTTPException(409, "Only a scheduled visit can be completed.")
    if not v.reports_json:
        raise HTTPException(409, "At least one EVC member must record observations before the visit is closed.")
    v.status, v.completed_at, v.completed_by = "completed", now(), actor(u)
    s.commit()
    audit.log("evc.completed", actor(u), u.role, f"evc_visit:{v.id}", {"application": a.id, "note": body.note[:300]})
    w = s.get(wf.AppWorkflow, a.id)
    if w and w.state == "active" and wf.active_config(s)["stages"].get(w.current_stage, {}).get("needs_evc_visit"):
        _wf_call(wf.advance, s, a, u, actor(u), "Auto-advance: EVC visit completed" + (f" - {body.note}" if body.note else ""), auto=True)
    return _visit_out(s, v, u)


# ------------------------------------------------------------------ undertakings & compliance
def _ut_out(s, x):
    a = s.get(Application, x.application_id)
    subs = s.query(ComplianceSubmission).filter(ComplianceSubmission.undertaking_id == x.id).order_by(ComplianceSubmission.id).all()
    return {"id": x.id, "application_id": x.application_id, "ref": a.ref if a else None, "college": a.college.name if a else None,
            "condition": x.condition, "evidence_required": x.evidence_required, "due_date": x.due_date.isoformat(), "status": x.status,
            "overdue": x.status in ("open", "rejected") and x.due_date < now().date(), "remark": x.remark, "verified_by": x.verified_by,
            "submissions": [_sub_out(c) for c in subs]}


def _sub_out(c):
    return {"id": c.id, "filename": c.filename, "sha256": c.sha256, "size": c.size, "note": c.note, "status": c.status,
            "submitted_by": c.submitted_by, "submitted_at": c.submitted_at.isoformat(), "reviewed_by": c.reviewed_by, "remark": c.remark}


class UndertakingIn(BaseModel):
    application_id: int
    condition: str = Field(min_length=5, max_length=2000)
    evidence_required: str = Field("", max_length=1000)
    due_date: date


@router.get("/api/wf/undertakings")
def ut_list(u: User = Depends(current_user), s=Depends(db)):
    if u.role == "evc_member":
        raise HTTPException(403, "Not available for EVC members")
    ids = [a.id for a in rep.scope_apps(s, u)[0]]
    rows = s.query(Undertaking).filter(Undertaking.application_id.in_(ids or [0])).order_by(Undertaking.due_date).all()
    return [_ut_out(s, x) for x in rows]


@router.post("/api/wf/undertakings")
def ut_create(body: UndertakingIn, u: User = Depends(require(*DECIDERS)), s=Depends(db)):
    a = scoped_app(s, body.application_id, u)
    x = Undertaking(application_id=a.id, college_id=a.college_id, condition=body.condition, evidence_required=body.evidence_required,
                    due_date=body.due_date, created_by=actor(u))
    s.add(x)
    s.add(Notification(college_id=a.college_id, message=f"{a.ref}: new undertaking due {body.due_date:%d %b %Y} - {body.condition[:150]}", link="/compliance", kind="undertaking"))
    s.commit()
    audit.log("undertaking.created", actor(u), u.role, f"undertaking:{x.id}", {"application": a.id, "due": body.due_date.isoformat()})
    return _ut_out(s, x)


async def _store_upload(file: UploadFile, u, target):
    from .pipeline import gateway
    from . import service
    data = await file.read()
    try:
        g = gateway.inspect_upload(data, file.filename or "upload")
    except gateway.GatewayReject as e:
        audit.log("upload.blocked", actor(u), u.role, target, {"reason": e.message, "file": file.filename})
        raise HTTPException(e.status, e.message)
    ext = (file.filename or "x.bin").rsplit(".", 1)[-1].lower()[:5]
    return g, service.store_original(data, g["sha256"], ext)


@router.post("/api/wf/undertakings/{uid}/submit")
async def ut_submit(uid: int, file: UploadFile = File(...), note: str = Form(""), u: User = Depends(require("college")), s=Depends(db)):
    x = s.get(Undertaking, uid)
    if not x or x.college_id != u.college_id:
        raise HTTPException(404, "Undertaking not found")
    if x.status == "verified":
        raise HTTPException(409, "Already verified")
    g, path = await _store_upload(file, u, f"undertaking:{uid}")
    c = ComplianceSubmission(undertaking_id=x.id, filename=(file.filename or "evidence")[:300], sha256=g["sha256"], stored_path=path, size=g["size"],
                             note=note[:2000], submitted_by=actor(u))
    s.add(c); x.status = "submitted"
    a = s.get(Application, x.application_id)
    s.add(Notification(role="officer", message=f"{a.ref}: compliance evidence submitted for undertaking #{x.id}", link="/compliance", kind="undertaking"))
    s.commit()
    audit.log("undertaking.evidence_submitted", actor(u), u.role, f"undertaking:{x.id}", {"sha256": g["sha256"], "file": c.filename})
    return _ut_out(s, x)


class VerifyIn(BaseModel):
    accept: bool
    remark: str = Field("", max_length=2000)
    valid_until: date | None = None


@router.post("/api/wf/undertakings/{uid}/verify")
def ut_verify(uid: int, body: VerifyIn, u: User = Depends(require(*DECIDERS)), s=Depends(db)):
    x = s.get(Undertaking, uid)
    if not x:
        raise HTTPException(404, "Undertaking not found")
    a = scoped_app(s, x.application_id, u)
    if x.status != "submitted":
        raise HTTPException(409, "There is no pending submission to verify.")
    if not body.accept and len(body.remark) < 5:
        raise HTTPException(400, "Give a reason (at least 5 characters) when rejecting evidence.")
    last = s.query(ComplianceSubmission).filter(ComplianceSubmission.undertaking_id == x.id).order_by(ComplianceSubmission.id.desc()).first()
    x.status = "verified" if body.accept else "rejected"
    x.verified_by, x.verified_at, x.remark = actor(u), now(), body.remark
    if last:
        last.status, last.reviewed_by, last.reviewed_at, last.remark = ("verified" if body.accept else "rejected"), actor(u), now(), body.remark
    s.add(Notification(college_id=x.college_id, message=f"{a.ref}: undertaking #{x.id} evidence {x.status}" + (f" - {body.remark[:150]}" if body.remark else ""), link="/compliance", kind="undertaking"))
    s.commit()
    audit.log("undertaking.verified" if body.accept else "undertaking.rejected", actor(u), u.role, f"undertaking:{x.id}", {"remark": body.remark[:300]})
    return _ut_out(s, x)


@router.get("/api/wf/compliance/{sid}/file")
def sub_file(sid: int, u: User = Depends(current_user), s=Depends(db)):
    from .storage import materialize
    c = s.get(ComplianceSubmission, sid)
    if not c:
        raise HTTPException(404, "Not found")
    cid = s.get(Undertaking, c.undertaking_id).college_id if c.undertaking_id else s.get(DocumentValidity, c.validity_id).college_id
    if u.role == "evc_member" or (u.role == "college" and cid != u.college_id):
        raise HTTPException(404, "Not found")
    p = materialize(c.stored_path)
    data = open(p, "rb").read()
    if hashlib.sha256(data).hexdigest() != c.sha256:
        raise HTTPException(500, "Integrity check failed for this file.")
    audit.log("compliance.file_downloaded", actor(u), u.role, f"compliance:{c.id}")
    return Response(data, media_type="application/octet-stream", headers={"Content-Disposition": f'attachment; filename="{c.filename}"'})


# ------------------------------------------------------------------ document validity
def _dv_out(s, x):
    from .db import College
    col = s.get(College, x.college_id)
    subs = s.query(ComplianceSubmission).filter(ComplianceSubmission.validity_id == x.id).order_by(ComplianceSubmission.id).all()
    left = (x.valid_until - now().date()).days
    return {"id": x.id, "college": col.name if col else None, "college_id": x.college_id, "application_id": x.application_id, "document_id": x.document_id,
            "doc_type": x.doc_type, "label": x.label, "valid_from": x.valid_from.isoformat() if x.valid_from else None,
            "valid_until": x.valid_until.isoformat(), "days_left": left, "status": x.status,
            "flag": "expired" if left < 0 and x.status in ("valid", "renewal_submitted") else ("expiring" if left <= 60 and x.status == "valid" else "ok"),
            "submissions": [_sub_out(c) for c in subs]}


@router.get("/api/wf/validity")
def dv_list(u: User = Depends(current_user), s=Depends(db)):
    if u.role == "evc_member":
        raise HTTPException(403, "Not available for EVC members")
    wf.sync_validity(s)
    cids = {a.college_id for a in rep.scope_apps(s, u)[0]}
    if u.role == "college":
        cids = {u.college_id}
    rows = s.query(DocumentValidity).filter(DocumentValidity.college_id.in_(list(cids) or [0])).order_by(DocumentValidity.valid_until).all()
    return [_dv_out(s, x) for x in rows]


@router.post("/api/wf/validity/{vid}/renew")
async def dv_renew(vid: int, file: UploadFile = File(...), valid_until: date = Form(...), note: str = Form(""),
                   u: User = Depends(require("college")), s=Depends(db)):
    x = s.get(DocumentValidity, vid)
    if not x or x.college_id != u.college_id:
        raise HTTPException(404, "Not found")
    if x.status not in ("valid", "renewal_submitted"):
        raise HTTPException(409, "This record is already renewed or superseded.")
    if valid_until <= x.valid_until:
        raise HTTPException(400, "The renewed document must be valid beyond the current expiry date.")
    g, path = await _store_upload(file, u, f"validity:{vid}")
    s.add(ComplianceSubmission(validity_id=x.id, filename=(file.filename or "renewal")[:300], sha256=g["sha256"], stored_path=path, size=g["size"],
                               note=json.dumps({"note": note[:1500], "claimed_valid_until": valid_until.isoformat()}), submitted_by=actor(u)))
    x.status = "renewal_submitted"
    s.add(Notification(role="officer", message=f"Renewal submitted: {x.label} ({u.college.name if u.college else ''})", link="/compliance", kind="document_validity"))
    s.commit()
    audit.log("validity.renewal_submitted", actor(u), u.role, f"validity:{x.id}", {"sha256": g["sha256"], "claimed_valid_until": valid_until.isoformat()})
    return _dv_out(s, x)


@router.post("/api/wf/validity/{vid}/verify")
def dv_verify(vid: int, body: VerifyIn, u: User = Depends(require(*DECIDERS)), s=Depends(db)):
    x = s.get(DocumentValidity, vid)
    if not x:
        raise HTTPException(404, "Not found")
    if x.status != "renewal_submitted":
        raise HTTPException(409, "There is no renewal to verify.")
    last = s.query(ComplianceSubmission).filter(ComplianceSubmission.validity_id == x.id).order_by(ComplianceSubmission.id.desc()).first()
    if body.accept:
        claimed = body.valid_until or date.fromisoformat(json.loads(last.note or "{}").get("claimed_valid_until"))
        new = DocumentValidity(college_id=x.college_id, application_id=x.application_id, document_id=None, doc_type=x.doc_type,
                               label=x.label + " (renewed)", valid_from=now().date(), valid_until=claimed)
        s.add(new); s.flush()
        x.status, x.renewed_by_id = "renewed", new.id
    else:
        if len(body.remark) < 5:
            raise HTTPException(400, "Give a reason when rejecting a renewal.")
        x.status = "valid"
    last.status, last.reviewed_by, last.reviewed_at, last.remark = ("verified" if body.accept else "rejected"), actor(u), now(), body.remark
    s.add(Notification(college_id=x.college_id, message=f"Renewal of {x.label} {'verified' if body.accept else 'rejected'}" + (f": {body.remark[:150]}" if body.remark else ""), link="/compliance", kind="document_validity"))
    s.commit()
    audit.log("validity.renewal_verified" if body.accept else "validity.renewal_rejected", actor(u), u.role, f"validity:{x.id}", {"remark": body.remark[:300]})
    return _dv_out(s, x)


# ------------------------------------------------------------------ dashboards, alerts, reports
@router.get("/api/wf/dashboard")
def dash(scope: str = "auto", as_of: str | None = None, u: User = Depends(current_user), s=Depends(db)):
    if u.role == "evc_member":
        raise HTTPException(403, "EVC members use the EVC page.")
    return rep.dashboard(s, u, scope, _as_of(as_of))


@router.get("/api/wf/alerts")
def alerts(open_only: bool = True, u: User = Depends(current_user), s=Depends(db)):
    q = s.query(Alert)
    if open_only:
        q = q.filter(Alert.closed_at.is_(None))
    if u.role == "college":
        q = q.filter(Alert.college_id == u.college_id, Alert.target_role == "college")
    elif u.role == "evc_member":
        return []
    return [{"id": x.id, "kind": x.kind, "level": x.level, "step": x.step, "target_role": x.target_role, "message": x.message, "application_id": x.application_id,
             "region": x.region_code, "created_at": x.created_at.isoformat(), "closed_at": x.closed_at.isoformat() if x.closed_at else None}
            for x in q.order_by(Alert.id.desc()).limit(300).all()]


@router.get("/api/wf/reports")
def reports_index(u: User = Depends(require(*STAFF)), s=Depends(db)):
    return {"reports": rep.REPORTS}


@router.get("/api/wf/reports/{kind}")
def report(kind: str, format: str = "json", as_of: str | None = None, u: User = Depends(require(*STAFF)), s=Depends(db)):
    if kind not in rep.REPORTS:
        raise HTTPException(404, "Unknown report")
    t = _as_of(as_of) or now()
    header, rows = rep.report(s, u, kind, t)
    audit.log("report.generated", actor(u), u.role, f"report:{kind}", {"format": format, "rows": len(rows)})
    fn = f"sealcheck_{kind}_{t:%Y%m%d}"
    if format == "csv":
        return Response(rep.to_csv(header, rows), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{fn}.csv"'})
    if format == "pdf":
        return Response(rep.report_pdf(rep.REPORTS[kind], header, rows, t), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{fn}.pdf"'})
    return {"kind": kind, "title": rep.REPORTS[kind], "header": header, "rows": rows, "as_of": t.isoformat(), "safeguard": SAFEGUARD}


# ------------------------------------------------------------------ calendar
def _cal_key(uid: int) -> str:
    return hmac.new(secret("calendar_feed.key"), f"ics:{uid}".encode(), hashlib.sha256).hexdigest()[:32]


@router.get("/api/wf/calendar")
def calendar(start: date | None = None, end: date | None = None, u: User = Depends(current_user), s=Depends(db)):
    t = now().date()
    start = start or t.replace(day=1) - timedelta(days=7)
    end = end or start + timedelta(days=60)
    if (end - start).days > 800:
        raise HTTPException(400, "Range too large")
    return {"events": rep.calendar_events(s, u, start, end), "colors": rep.COLORS, "start": start.isoformat(), "end": end.isoformat()}


@router.get("/api/wf/calendar/subscription")
def cal_sub(request: Request, u: User = Depends(current_user)):
    base = os.environ.get("PUBLIC_BASE_URL") or str(request.base_url).rstrip("/")
    url = f"{base.rstrip('/')}/api/wf/calendar.ics?uid={u.id}&key={_cal_key(u.id)}"
    audit.log("calendar.subscription_link", actor(u), u.role, f"user:{u.id}")
    return {"url": url, "webcal": url.replace("https://", "webcal://").replace("http://", "webcal://"),
            "note": "Private read-only link. Anyone with it can see your deadline titles; do not share it."}


@router.get("/api/wf/calendar.ics")
def cal_ics(request: Request, uid: int, key: str, s=Depends(db)):
    if not hmac.compare_digest(key, _cal_key(uid)):
        raise HTTPException(403, "Invalid calendar key")
    u = s.get(User, uid)
    if not u or u.role == "pending":
        raise HTTPException(403, "Invalid calendar key")
    t = now().date()
    ev = rep.calendar_events(s, u, t - timedelta(days=60), t + timedelta(days=400))
    base = os.environ.get("PUBLIC_BASE_URL") or str(request.base_url)
    return PlainTextResponse(rep.to_ics(ev, base), media_type="text/calendar; charset=utf-8",
                             headers={"Content-Disposition": 'inline; filename="sealcheck.ics"'})


# ------------------------------------------------------------------ config (admin) + regions
@router.get("/api/wf/config")
def cfg_get(u: User = Depends(require(*STAFF)), s=Depends(db)):
    cfg = wf.active_config(s)
    vers = s.query(WorkflowConfigVersion).order_by(WorkflowConfigVersion.version.desc()).limit(20).all()
    return {"config": {k: v for k, v in cfg.items() if not k.startswith("_")}, "signed": cfg.get("_signed"), "version": cfg.get("version"),
            "versions": [{"version": v.version, "sha256": v.sha256, "note": v.note, "created_by": v.created_by, "created_at": v.created_at.isoformat()} for v in vers],
            "source": "database (signed)" if cfg.get("_signed") else "shipped default (rules/workflow.yaml)"}


class CfgIn(BaseModel):
    config: dict
    note: str = Field(min_length=3, max_length=400)


@router.put("/api/wf/config")
def cfg_put(body: CfgIn, u: User = Depends(require("admin")), s=Depends(db)):
    try:
        row = wf.save_config(s, body.config, actor(u), body.note)
    except (wf.ConfigError, KeyError, TypeError) as e:
        raise HTTPException(400, f"Invalid workflow config: {e}")
    audit.log("workflow.config_saved", actor(u), u.role, f"wf_config:{row.version}", {"sha256": row.sha256, "note": body.note})
    return cfg_get(u, s)


@router.get("/api/wf/regions")
def regions(u: User = Depends(require(*STAFF)), s=Depends(db)):
    cfg = wf.active_config(s)
    assign = {r.user_id: r.region_code for r in s.query(UserRegion).all()}
    officers = [{"id": x.id, "name": x.name, "role": x.role, "role_label": ROLE_LABEL.get(x.role, x.role), "region": assign.get(x.id)}
                for x in s.query(User).filter(User.role.in_(["officer", "senior_officer"])).all()]
    return {"regions": cfg["regions"], "officers": officers, "note": "Region names and state mapping are editable defaults (Region 1..N)."}


class AssignIn(BaseModel):
    user_id: int
    region_code: str | None = None


@router.put("/api/wf/regions/assign")
def region_assign(body: AssignIn, u: User = Depends(require("admin")), s=Depends(db)):
    cfg = wf.active_config(s)
    tgt = s.get(User, body.user_id)
    if not tgt or tgt.role != "officer":
        raise HTTPException(400, "Only Regional officers (officer role) are assigned to a region.")
    if body.region_code and body.region_code not in {r["code"] for r in cfg["regions"]}:
        raise HTTPException(400, "Unknown region")
    row = s.get(UserRegion, tgt.id)
    if body.region_code:
        if row:
            row.region_code = body.region_code
        else:
            s.add(UserRegion(user_id=tgt.id, region_code=body.region_code))
    elif row:
        s.delete(row)
    s.commit()
    audit.log("region.assigned", actor(u), u.role, f"user:{tgt.id}", {"region": body.region_code})
    return regions(u, s)


# ------------------------------------------------------------------ scheduler
class EvalIn(BaseModel):
    as_of: str | None = None


@router.post("/api/wf/evaluate")
def evaluate_now(body: EvalIn, u: User = Depends(require("admin", "senior_officer")), s=Depends(db)):
    t = _as_of(body.as_of)
    res = wf.evaluate(t, trigger="manual")
    audit.log("scheduler.manual_run", actor(u), u.role, "workflow", {"as_of": body.as_of})
    return res


@router.api_route("/api/cron/evaluate", methods=["GET", "POST"])
def cron(request: Request):
    """Vercel Cron calls this with 'Authorization: Bearer $CRON_SECRET'. No secret configured -> disabled."""
    sec = os.environ.get("CRON_SECRET", "")
    if not sec:
        raise HTTPException(503, "CRON_SECRET is not configured; the cron endpoint is disabled.")
    got = request.headers.get("authorization", "")
    if not hmac.compare_digest(got, f"Bearer {sec}"):
        audit.log("cron.denied", "anonymous", "system", "workflow", {"ip": request.client.host if request.client else ""})
        raise HTTPException(401, "Unauthorized")
    return wf.evaluate(trigger="cron")


@router.get("/api/wf/scheduler")
def scheduler_status(u: User = Depends(require(*STAFF)), s=Depends(db)):
    rows = s.query(wf.SchedulerRun).order_by(wf.SchedulerRun.id.desc()).limit(20).all()
    return {"cron_configured": bool(os.environ.get("CRON_SECRET")), "dev_loop_s": int(os.environ.get("WF_SCHEDULER_S", "0") or 0),
            "runs": [{"id": r.id, "started_at": r.started_at.isoformat(), "as_of": r.as_of.isoformat() if r.as_of else None, "trigger": r.trigger,
                      "created": r.created_alerts, "closed": r.closed_alerts, "skipped": r.skipped} for r in rows]}


@router.get("/api/wf/integrations")
def integrations(u: User = Depends(require(*STAFF))):
    from . import integrations as ig
    return ig.describe()
