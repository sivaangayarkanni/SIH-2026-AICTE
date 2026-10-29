"""Approval workflow engine: configurable stage routes, stage history, EVC visits, undertakings,
document validity, reminders/escalations (alerts) and a calendar feed.

Regulatory safeguard: automated alerts, recommendations and workflow actions SUPPORT the approval
process; they never replace statutory scrutiny, verification, inspections or decisions taken by the
competent authority. The engine only moves an application when an authorised person acts (or when an
authorised completion such as an EVC visit being marked complete triggers the next stage)."""
from __future__ import annotations
import copy, hashlib, hmac, json, threading
from datetime import datetime, timedelta, date

import yaml
from sqlalchemy import Column, Integer, String, Text, DateTime, Date, JSON, ForeignKey, Boolean, UniqueConstraint, text

from .db import Base, SessionLocal, IS_PG, Application, College, User, Document, Notification, now
from .config import RULES_DIR, secret
from . import audit

SAFEGUARD = ("Automated alerts, recommendations and workflow actions support the approval process; they do not replace "
             "statutory scrutiny, verification, inspections or decisions taken by the competent authority.")


# ----------------------------------------------------------------------------------------------- models
class WorkflowConfigVersion(Base):
    __tablename__ = "wf_config_versions"
    id = Column(Integer, primary_key=True)
    version = Column(Integer, nullable=False, unique=True)
    config_json = Column(Text, nullable=False)
    sha256 = Column(String(64), nullable=False)
    signature = Column(String(64), nullable=False)   # HMAC-SHA256(key, sha256)
    note = Column(String(400))
    created_by = Column(String(200))
    created_at = Column(DateTime, default=now)


class UserRegion(Base):
    """Which region a Regional officer covers (officer role). Bureau officers (senior_officer) see all regions."""
    __tablename__ = "wf_user_regions"
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    region_code = Column(String(10), nullable=False)


class AppWorkflow(Base):
    __tablename__ = "wf_app_workflow"
    application_id = Column(Integer, ForeignKey("applications.id"), primary_key=True)
    route_id = Column(String(40), nullable=False)
    stages_json = Column(JSON, nullable=False)        # route snapshot at routing time
    stage_index = Column(Integer, default=0)
    current_stage = Column(String(40))
    state = Column(String(20), default="active")      # active | returned | awaiting_decision | completed
    region_code = Column(String(10))
    assigned_officer_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    stage_started_at = Column(DateTime, default=now)
    stage_due_at = Column(DateTime)
    return_reason = Column(Text)
    config_version = Column(Integer)
    updated_at = Column(DateTime, default=now)


class StageEvent(Base):
    __tablename__ = "wf_stage_events"
    id = Column(Integer, primary_key=True)
    application_id = Column(Integer, ForeignKey("applications.id"), index=True)
    action = Column(String(20))       # routed | advanced | returned | resubmitted | reverted | completed
    from_stage = Column(String(40))
    to_stage = Column(String(40))
    reason = Column(Text)
    actor = Column(String(200))
    role = Column(String(20))
    at = Column(DateTime, default=now)


class EvcVisit(Base):
    __tablename__ = "wf_evc_visits"
    id = Column(Integer, primary_key=True)
    application_id = Column(Integer, ForeignKey("applications.id"), index=True)
    status = Column(String(20), default="to_schedule")   # to_schedule | scheduled | completed | cancelled
    schedule_by = Column(DateTime)
    scheduled_for = Column(DateTime)
    due_by = Column(DateTime)
    members_json = Column(JSON, default=list)            # user ids (evc_member)
    reports_json = Column(JSON, default=dict)            # {user_id: {checklist: {...}, remarks, at}}
    completed_at = Column(DateTime)
    completed_by = Column(String(200))
    created_at = Column(DateTime, default=now)


class Undertaking(Base):
    __tablename__ = "wf_undertakings"
    id = Column(Integer, primary_key=True)
    application_id = Column(Integer, ForeignKey("applications.id"), index=True)
    college_id = Column(Integer, ForeignKey("colleges.id"), index=True)
    condition = Column(Text, nullable=False)
    evidence_required = Column(Text)
    due_date = Column(Date, nullable=False)
    status = Column(String(20), default="open")    # open | submitted | verified | rejected
    created_by = Column(String(200))
    created_at = Column(DateTime, default=now)
    verified_by = Column(String(200))
    verified_at = Column(DateTime)
    remark = Column(Text)


class ComplianceSubmission(Base):
    __tablename__ = "wf_compliance_submissions"
    id = Column(Integer, primary_key=True)
    undertaking_id = Column(Integer, ForeignKey("wf_undertakings.id"), nullable=True, index=True)
    validity_id = Column(Integer, ForeignKey("wf_document_validity.id"), nullable=True, index=True)
    filename = Column(String(300))
    sha256 = Column(String(64))
    stored_path = Column(String(400))
    size = Column(Integer)
    note = Column(Text)
    status = Column(String(20), default="pending")  # pending | verified | rejected
    submitted_by = Column(String(200))
    submitted_at = Column(DateTime, default=now)
    reviewed_by = Column(String(200))
    reviewed_at = Column(DateTime)
    remark = Column(Text)


class DocumentValidity(Base):
    __tablename__ = "wf_document_validity"
    id = Column(Integer, primary_key=True)
    college_id = Column(Integer, ForeignKey("colleges.id"), index=True)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=True, unique=True)
    doc_type = Column(String(40))
    label = Column(String(200))
    valid_from = Column(Date)
    valid_until = Column(Date, nullable=False)
    status = Column(String(24), default="valid")   # valid | renewal_submitted | renewed | superseded
    renewed_by_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=now)


class Alert(Base):
    __tablename__ = "wf_alerts"
    __table_args__ = (UniqueConstraint("dedupe_key", name="uq_wf_alert_dedupe"),)
    id = Column(Integer, primary_key=True)
    dedupe_key = Column(String(160), nullable=False)
    kind = Column(String(30))          # submission_deadline | stage_sla | evc_visit | undertaking | document_validity | mismatch
    level = Column(String(20))         # reminder | escalation | notice
    step = Column(String(20))          # e.g. T-7, +0, +7
    target_role = Column(String(20))
    target_user_id = Column(Integer, nullable=True)
    college_id = Column(Integer, nullable=True, index=True)
    application_id = Column(Integer, nullable=True, index=True)
    subject = Column(String(60))       # e.g. undertaking:3
    region_code = Column(String(10))
    message = Column(Text)
    due_at = Column(DateTime)
    created_at = Column(DateTime, default=now)
    closed_at = Column(DateTime)


class WizardDraft(Base):
    __tablename__ = "wf_wizard_drafts"
    application_id = Column(Integer, ForeignKey("applications.id"), primary_key=True)
    step = Column(Integer, default=0)
    data_json = Column(JSON, default=dict)
    updated_at = Column(DateTime, default=now)


class SchedulerRun(Base):
    __tablename__ = "wf_scheduler_runs"
    id = Column(Integer, primary_key=True)
    started_at = Column(DateTime, default=now)
    as_of = Column(DateTime)
    trigger = Column(String(20))
    created_alerts = Column(Integer, default=0)
    closed_alerts = Column(Integer, default=0)
    skipped = Column(Boolean, default=False)


# ----------------------------------------------------------------------------------------------- config
def default_config() -> dict:
    return yaml.safe_load((RULES_DIR / "workflow.yaml").read_text())


def _key() -> bytes:
    return secret("workflow_config.key")


def _canon(cfg: dict) -> str:
    return json.dumps(cfg, sort_keys=True, separators=(",", ":"))


def _sign(sha: str) -> str:
    return hmac.new(_key(), sha.encode(), hashlib.sha256).hexdigest()


class ConfigError(ValueError):
    pass


def validate_config(cfg: dict) -> dict:
    for k in ("regions", "stages", "routes", "route_rules", "reminders", "escalation"):
        if k not in cfg:
            raise ConfigError(f"missing section '{k}'")
    stages = cfg["stages"]
    roles = {"officer", "senior_officer", "admin", "college"}
    for sid, st in stages.items():
        if not isinstance(st.get("sla_days"), int) or st["sla_days"] < 1:
            raise ConfigError(f"stage {sid}: sla_days must be a positive integer")
        if not set(st.get("actors") or []) <= roles or not st.get("actors"):
            raise ConfigError(f"stage {sid}: actors must be a non-empty subset of {sorted(roles)}")
    ids = set()
    for r in cfg["routes"]:
        if not r.get("stages") or any(x not in stages for x in r["stages"]):
            raise ConfigError(f"route {r.get('id')}: unknown stage")
        if not stages[r["stages"][-1]].get("terminal"):
            raise ConfigError(f"route {r['id']}: last stage must be a terminal (decision) stage")
        ids.add(r["id"])
    if not any(x.get("default") for x in cfg["route_rules"]):
        raise ConfigError("route_rules needs a default rule")
    for x in cfg["route_rules"]:
        if x["route"] not in ids:
            raise ConfigError(f"route rule points to unknown route {x['route']}")
    for kind, offs in cfg["reminders"].items():
        if not all(isinstance(o, int) and o >= 0 for o in offs):
            raise ConfigError(f"reminders.{kind}: non-negative integers only")
    for kind, ladder in cfg["escalation"].items():
        for st in ladder:
            if st.get("to") not in roles - {"college"} or not isinstance(st.get("after_days"), int):
                raise ConfigError(f"escalation.{kind}: each step needs after_days (int) and to (officer|senior_officer|admin)")
    codes = [r["code"] for r in cfg["regions"]]
    if len(codes) != len(set(codes)):
        raise ConfigError("region codes must be unique")
    return cfg


_cache: dict = {}


def active_config(s=None) -> dict:
    """Latest saved version whose HMAC verifies; falls back to the shipped default (version from YAML)."""
    own = s is None
    s = s or SessionLocal()
    try:
        row = s.query(WorkflowConfigVersion).order_by(WorkflowConfigVersion.version.desc()).first()
        if row:
            if row.id in _cache:
                return _cache[row.id]
            ok = hashlib.sha256(row.config_json.encode()).hexdigest() == row.sha256 and hmac.compare_digest(_sign(row.sha256), row.signature)
            if ok:
                cfg = json.loads(row.config_json); cfg["version"] = row.version; cfg["_signed"] = True
                _cache.clear(); _cache[row.id] = cfg
                return cfg
            audit.log("workflow.config_signature_invalid", details={"version": row.version})
        cfg = default_config(); cfg["_signed"] = False
        return cfg
    finally:
        if own:
            s.close()


def save_config(s, cfg: dict, who: str, note: str = "") -> WorkflowConfigVersion:
    cfg = {k: v for k, v in copy.deepcopy(cfg).items() if not k.startswith("_")}
    validate_config(cfg)
    last = s.query(WorkflowConfigVersion).order_by(WorkflowConfigVersion.version.desc()).first()
    ver = max(last.version if last else 0, int(default_config().get("version", 1))) + 1
    cfg["version"] = ver
    body = _canon(cfg); sha = hashlib.sha256(body.encode()).hexdigest()
    row = WorkflowConfigVersion(version=ver, config_json=body, sha256=sha, signature=_sign(sha), note=note[:400], created_by=who)
    s.add(row); s.commit()
    return row


def region_for_state(cfg, state: str | None) -> str | None:
    for r in cfg["regions"]:
        if state and state.strip().lower() in [x.lower() for x in r.get("states", [])]:
            return r["code"]
    return None


def region_name(cfg, code):
    return next((r["name"] for r in cfg["regions"] if r["code"] == code), code or "Unassigned")


def stage_label(cfg, sid):
    return (cfg["stages"].get(sid) or {}).get("label", sid)


def pick_route(cfg, category: str) -> dict:
    for rule in cfg["route_rules"]:
        if rule.get("default") or category in (rule.get("categories") or []):
            return next(r for r in cfg["routes"] if r["id"] == rule["route"])
    raise ConfigError("no route")


# ----------------------------------------------------------------------------------------------- routing
class WorkflowError(Exception):
    def __init__(self, status: int, msg: str):
        super().__init__(msg); self.status = status; self.msg = msg


def _event(s, app_id, action, frm, to, reason, who, role, at=None):
    s.add(StageEvent(application_id=app_id, action=action, from_stage=frm, to_stage=to, reason=reason, actor=who, role=role, at=at or now()))


def _notify(s, msg, link, college_id=None, role=None, kind="workflow", severity="info", user_id=None):
    s.add(Notification(college_id=college_id, role=role, user_id=user_id, message=msg[:500], link=link, kind=kind, severity=severity))


def _officer_for_region(s, region):
    if not region:
        return None
    r = s.query(UserRegion).join(User, User.id == UserRegion.user_id).filter(UserRegion.region_code == region, User.role == "officer").first()
    return r.user_id if r else None


def _enter_stage(s, cfg, wf: AppWorkflow, a: Application, at: datetime):
    sid = wf.stages_json[wf.stage_index]
    wf.current_stage, wf.stage_started_at = sid, at
    wf.stage_due_at = at + timedelta(days=cfg["stages"][sid]["sla_days"])
    wf.state = "awaiting_decision" if cfg["stages"][sid].get("terminal") else "active"
    wf.updated_at = at
    if cfg["stages"][sid].get("needs_evc_visit"):
        open_v = s.query(EvcVisit).filter(EvcVisit.application_id == a.id, EvcVisit.status.in_(["to_schedule", "scheduled"])).first()
        if not open_v:
            ev = cfg.get("evc", {})
            days = ev.get("new_institution_complete_within_days", 21) if a.category == "new_institution" else ev.get("complete_within_days", 30)
            s.add(EvcVisit(application_id=a.id, status="to_schedule", schedule_by=at + timedelta(days=ev.get("schedule_within_days", 21)),
                           due_by=at + timedelta(days=days), created_at=at))
            _notify(s, f"{a.ref} queued for an Expert Visit Committee (EVC) visit", "/evc", role="officer")


def route_application(s, a: Application, who="system", role="system", at=None) -> AppWorkflow:
    """Called when a college submits. Idempotent: an existing workflow is left untouched."""
    wf = s.get(AppWorkflow, a.id)
    if wf:
        return wf
    cfg = active_config(s)
    at = at or now()
    r = pick_route(cfg, a.category)
    region = region_for_state(cfg, a.college.state if a.college else None)
    wf = AppWorkflow(application_id=a.id, route_id=r["id"], stages_json=list(r["stages"]), stage_index=0, region_code=region,
                     assigned_officer_id=_officer_for_region(s, region), config_version=cfg.get("version"))
    s.add(wf)
    _enter_stage(s, cfg, wf, a, at)
    _event(s, a.id, "routed", None, wf.current_stage, f"Route '{r['label']}' selected by rule for category {a.category}", who, role, at)
    s.commit()
    audit.log("workflow.routed", who, role, f"application:{a.id}", {"route": r["id"], "region": region, "config_version": cfg.get("version")})
    return wf


def _need_wf(s, a):
    wf = s.get(AppWorkflow, a.id)
    if not wf:
        raise WorkflowError(409, "This application has not been routed yet (it is routed when the college submits).")
    return wf


def _authorised(cfg, wf, u: User):
    actors = cfg["stages"][wf.current_stage]["actors"]
    if u.role not in actors and u.role != "admin":
        raise WorkflowError(403, f"Only {', '.join(actors)} can act on the '{stage_label(cfg, wf.current_stage)}' stage.")


def advance(s, a: Application, u: User, who: str, note: str, auto=False, at=None) -> AppWorkflow:
    """Authorised completion of the current stage -> automatic move to the next configured stage."""
    cfg = active_config(s)
    wf = _need_wf(s, a)
    at = at or now()
    if wf.state == "returned":
        raise WorkflowError(409, "The application is with the institution for correction.")
    if wf.state in ("awaiting_decision", "completed"):
        raise WorkflowError(409, "The final stage is a decision by the competent authority; record it with the decision form.")
    if not auto:
        _authorised(cfg, wf, u)
        if cfg["stages"][wf.current_stage].get("needs_evc_visit"):
            v = s.query(EvcVisit).filter(EvcVisit.application_id == a.id, EvcVisit.status == "completed").first()
            if not v:
                raise WorkflowError(409, "The EVC visit has not been marked complete yet.")
        if wf.current_stage == "scrutiny":
            from .crosscheck import crosscheck
            open_mm = crosscheck(s, a)["mismatches"]
            if open_mm:
                raise WorkflowError(409, f"{len(open_mm)} cross-document mismatch(es) are open. Return the application to the "
                                         "institution for correction (or record a reason) before completing scrutiny.")
    frm = wf.current_stage
    wf.stage_index += 1
    _enter_stage(s, cfg, wf, a, at)
    _event(s, a.id, "advanced", frm, wf.current_stage, note or ("auto-advance after EVC completion" if auto else ""), who, u.role if u else "system", at)
    s.query(Alert).filter(Alert.subject == f"stage:{a.id}:{frm}", Alert.closed_at.is_(None)).update({"closed_at": at})
    _notify(s, f"{a.ref} moved from {stage_label(cfg, frm)} to {stage_label(cfg, wf.current_stage)}", f"/applications/{a.id}", college_id=a.college_id)
    s.commit()
    audit.log("workflow.advanced", who, u.role if u else "system", f"application:{a.id}", {"from": frm, "to": wf.current_stage, "auto": auto, "note": (note or "")[:300]})
    return wf


def return_to_institution(s, a, u, who, reason, items=None, at=None):
    cfg = active_config(s)
    wf = _need_wf(s, a)
    at = at or now()
    if wf.state != "active":
        raise WorkflowError(409, f"Cannot return an application in state '{wf.state}'.")
    _authorised(cfg, wf, u)
    wf.state, wf.return_reason, wf.updated_at = "returned", reason, at
    _event(s, a.id, "returned", wf.current_stage, "institution", reason, who, u.role, at)
    det = "; ".join(items or [])
    _notify(s, f"{a.ref} returned for correction: {reason[:200]}{(' | to be corrected/re-uploaded: ' + det[:200]) if det else ''}",
            f"/applications/{a.id}", college_id=a.college_id, kind="returned", severity="warning")
    s.commit()
    audit.log("workflow.returned", who, u.role, f"application:{a.id}", {"stage": wf.current_stage, "reason": reason[:300], "items": items or []})
    return wf


def resubmit(s, a, u, who, note="", at=None):
    cfg = active_config(s)
    wf = _need_wf(s, a)
    at = at or now()
    if wf.state != "returned":
        raise WorkflowError(409, "Nothing to resubmit: the application is not with the institution.")
    wf.state, wf.stage_started_at, wf.updated_at = "active", at, at
    wf.stage_due_at = at + timedelta(days=cfg["stages"][wf.current_stage]["sla_days"])
    _event(s, a.id, "resubmitted", "institution", wf.current_stage, note, who, u.role, at)
    _notify(s, f"{a.ref} resubmitted after correction", f"/applications/{a.id}", role="officer")
    s.commit()
    audit.log("workflow.resubmitted", who, u.role, f"application:{a.id}", {"stage": wf.current_stage})
    return wf


def revert(s, a, u, who, reason, at=None):
    cfg = active_config(s)
    wf = _need_wf(s, a)
    at = at or now()
    if u.role not in ("senior_officer", "admin") and not (u.role == "officer" and wf.state == "active"):
        raise WorkflowError(403, "Reverting a stage needs a Bureau (senior) officer, or a Regional officer on an active stage.")
    if wf.stage_index == 0:
        raise WorkflowError(409, "Already at the first stage of the route.")
    if a.decision in ("Approved", "Rejected"):
        raise WorkflowError(409, "A final decision exists; it cannot be reverted here.")
    frm = wf.current_stage
    wf.stage_index -= 1
    _enter_stage(s, cfg, wf, a, at)
    _event(s, a.id, "reverted", frm, wf.current_stage, reason, who, u.role, at)
    _notify(s, f"{a.ref} reverted to {stage_label(cfg, wf.current_stage)}: {reason[:200]}", f"/applications/{a.id}", role="officer")
    s.commit()
    audit.log("workflow.reverted", who, u.role, f"application:{a.id}", {"from": frm, "to": wf.current_stage, "reason": reason[:300]})
    return wf


def on_decision(s, a, who, role):
    wf = s.get(AppWorkflow, a.id)
    if not wf:
        return
    if a.decision in ("Approved", "Rejected"):
        wf.state = "completed"
        _event(s, a.id, "completed", wf.current_stage, None, f"Decision recorded: {a.decision}", who, role)
    elif a.decision == "Changes Requested":
        wf.state, wf.return_reason = "returned", a.decision_reason
        _event(s, a.id, "returned", wf.current_stage, "institution", a.decision_reason, who, role)
    s.query(Alert).filter(Alert.subject == f"stage:{a.id}:{wf.current_stage}", Alert.closed_at.is_(None)).update({"closed_at": now()})
    s.commit()


def workflow_out(s, a, cfg=None) -> dict | None:
    cfg = cfg or active_config(s)
    wf = s.get(AppWorkflow, a.id)
    if not wf:
        return None
    hist = s.query(StageEvent).filter(StageEvent.application_id == a.id).order_by(StageEvent.at, StageEvent.id).all()
    route = next((r for r in cfg["routes"] if r["id"] == wf.route_id), {"label": wf.route_id})
    t = now()
    return {"route_id": wf.route_id, "route_label": route["label"], "state": wf.state, "current_stage": wf.current_stage,
            "current_label": stage_label(cfg, wf.current_stage), "stage_index": wf.stage_index,
            "stages": [{"id": x, "label": stage_label(cfg, x), "done": i < wf.stage_index or wf.state == "completed",
                        "current": i == wf.stage_index and wf.state != "completed", "actors": cfg["stages"].get(x, {}).get("actors", [])}
                       for i, x in enumerate(wf.stages_json)],
            "region": wf.region_code, "region_name": region_name(cfg, wf.region_code),
            "stage_started_at": wf.stage_started_at.isoformat() if wf.stage_started_at else None,
            "stage_due_at": wf.stage_due_at.isoformat() if wf.stage_due_at else None,
            "days_in_stage": (t - wf.stage_started_at).days if wf.stage_started_at else 0,
            "overdue": bool(wf.stage_due_at and wf.stage_due_at < t and wf.state == "active"),
            "return_reason": wf.return_reason if wf.state == "returned" else None,
            "history": [{"action": h.action, "from": h.from_stage, "to": h.to_stage, "from_label": stage_label(cfg, h.from_stage) if h.from_stage else None,
                         "to_label": stage_label(cfg, h.to_stage) if h.to_stage else None, "reason": h.reason, "actor": h.actor,
                         "role": h.role, "at": h.at.isoformat()} for h in hist],
            "config_version": wf.config_version, "safeguard": SAFEGUARD}


# ----------------------------------------------------------------------------------------------- validity sync
def sync_validity(s) -> int:
    """Create a DocumentValidity row for every analysed document of a tracked type that carries a valid-until date."""
    cfg = active_config(s)
    types = set(cfg.get("validity_doc_types") or [])
    have = {r[0] for r in s.query(DocumentValidity.document_id).filter(DocumentValidity.document_id.isnot(None)).all()}
    n = 0
    for d in s.query(Document).filter(Document.doc_type.in_(types)).all():
        if d.id in have:
            continue
        facts = (d.analysis_json or {}).get("facts") or {}
        vu = facts.get("valid_until")
        if not vu:
            continue
        try:
            vu_d = date.fromisoformat(vu[:10])
            vf = date.fromisoformat(facts["issue_date"][:10]) if facts.get("issue_date") else None
        except ValueError:
            continue
        a = s.get(Application, d.application_id)
        s.add(DocumentValidity(college_id=a.college_id, application_id=a.id, document_id=d.id, doc_type=d.doc_type,
                               label=facts.get("label") or d.doc_type, valid_from=vf, valid_until=vu_d)); n += 1
    if n:
        s.commit()
    return n


# ----------------------------------------------------------------------------------------------- scheduler
_local_lock = threading.Lock()
LOCK_ID = 726355


def _ladder_steps(cfg, kind, due: datetime, t: datetime):
    """Yield (level, step_label, target) for every ladder step that is due at time t (idempotency via dedupe key)."""
    out = []
    for off in sorted(cfg["reminders"].get(kind, []), reverse=True):
        if due - timedelta(days=off) <= t < due:
            out.append(("reminder", f"T-{off}", None))
    for st in cfg["escalation"].get(kind, []):
        if t >= due + timedelta(days=st["after_days"]):
            out.append(("escalation", f"+{st['after_days']}", st["to"]))
    return out


def _latest_reminder_only(steps):
    """A run that starts late must not spray T-30, T-15 and T-7 at once: keep only the nearest reminder."""
    rem = [x for x in steps if x[0] == "reminder"]
    return ([rem[-1]] if rem else []) + [x for x in steps if x[0] == "escalation"]


def evaluate(as_of: datetime | None = None, trigger: str = "manual") -> dict:
    """Idempotent evaluation of every deadline. Concurrency: PG advisory xact lock / in-process lock on SQLite."""
    t = as_of or now()
    stats = {"as_of": t.isoformat(), "created": 0, "closed": 0, "validity_synced": 0, "by_kind": {}}
    if not _local_lock.acquire(blocking=False):
        stats["skipped"] = "another evaluation is running"; return stats
    try:
        lock_conn = None
        if IS_PG:   # transaction-scoped advisory lock on a dedicated connection (safe behind a transaction pooler)
            from .db import engine
            lock_conn = engine.connect(); lock_conn.begin()
            if not lock_conn.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": LOCK_ID}).scalar():
                lock_conn.rollback(); lock_conn.close()
                stats["skipped"] = "advisory lock held by another instance"
                return stats
        try:
            return _evaluate_locked(t, trigger, stats)
        finally:
            if lock_conn is not None:
                lock_conn.rollback(); lock_conn.close()
    finally:
        _local_lock.release()


def _evaluate_locked(t, trigger, stats):
    if True:
        with SessionLocal() as s:
            stats["validity_synced"] = sync_validity(s)
            cfg = active_config(s)
            existing = {k for (k,) in s.query(Alert.dedupe_key).all()}
            new_alerts = []

            def emit(kind, subject, level, step, target_role, msg, due, college_id=None, app_id=None, region=None, target_user=None, link="/"):
                key = f"{subject}:{level}:{step}"
                if key in existing:
                    return
                existing.add(key)
                al = Alert(dedupe_key=key, kind=kind, level=level, step=step, target_role=target_role, target_user_id=target_user,
                           college_id=college_id, application_id=app_id, subject=subject, region_code=region, message=msg, due_at=due, created_at=t)
                s.add(al); new_alerts.append(al)
                if target_role == "college":
                    _notify(s, msg, link, college_id=college_id, kind=kind, severity="warning" if level == "reminder" else "danger")
                else:
                    _notify(s, msg, link, role=target_role, kind=kind, severity="danger" if level == "escalation" else "warning")
                stats["by_kind"][kind] = stats["by_kind"].get(kind, 0) + 1

            apps = {a.id: a for a in s.query(Application).all()}
            wfs = {w.application_id: w for w in s.query(AppWorkflow).all()}

            def region_of(a):
                w = wfs.get(a.id)
                return w.region_code if w else region_for_state(cfg, a.college.state if a.college else None)

            # 1. submission deadline (not yet submitted)
            for a in apps.values():
                if a.submitted_at or not a.deadline:
                    continue
                for lvl, step, to in _latest_reminder_only(_ladder_steps(cfg, "submission_deadline", a.deadline, t)):
                    if lvl == "reminder":
                        emit("submission_deadline", f"deadline:{a.id}", lvl, step, "college",
                             f"Reminder ({step}): {a.ref} must be submitted by {a.deadline:%d %b %Y}", a.deadline, a.college_id, a.id, region_of(a), link=f"/apply/{a.id}")
                    else:
                        emit("submission_deadline", f"deadline:{a.id}", lvl, step, to,
                             f"Escalation ({step} days): {a.ref} ({a.college.name}) missed its submission deadline of {a.deadline:%d %b %Y}",
                             a.deadline, a.college_id, a.id, region_of(a), _officer_for_region(s, region_of(a)) if to == "officer" else None, f"/applications/{a.id}")
            # 2. stage SLA
            for w in wfs.values():
                if w.state != "active" or not w.stage_due_at:
                    continue
                a = apps[w.application_id]
                for lvl, step, to in _latest_reminder_only(_ladder_steps(cfg, "stage_sla", w.stage_due_at, t)):
                    who = to or (cfg["stages"][w.current_stage]["actors"][0])
                    emit("stage_sla", f"stage:{a.id}:{w.current_stage}", lvl, step, who,
                         (f"{stage_label(cfg, w.current_stage)} for {a.ref} is due {w.stage_due_at:%d %b %Y} ({step})" if lvl == "reminder" else
                          f"Escalation ({step} days): {stage_label(cfg, w.current_stage)} for {a.ref} exceeded its {cfg['stages'][w.current_stage]['sla_days']}-day timeline"),
                         w.stage_due_at, a.college_id, a.id, w.region_code, w.assigned_officer_id if who == "officer" else None, f"/applications/{a.id}")
            # 3. EVC visits (scheduling deadline and completion deadline)
            for v in s.query(EvcVisit).filter(EvcVisit.status.in_(["to_schedule", "scheduled"])).all():
                a = apps.get(v.application_id)
                if not a:
                    continue
                if v.status == "to_schedule" and v.schedule_by:
                    for lvl, step, to in _latest_reminder_only(_ladder_steps(cfg, "evc_visit", v.schedule_by, t)):
                        emit("evc_visit", f"evc-schedule:{v.id}", lvl, step, to or "officer",
                             (f"EVC for {a.ref} must be scheduled by {v.schedule_by:%d %b %Y}" if lvl == "reminder" else
                              f"Escalation ({step} days): EVC for {a.ref} has not been scheduled"), v.schedule_by, a.college_id, a.id, region_of(a), link="/evc")
                if v.due_by:
                    for lvl, step, to in _latest_reminder_only(_ladder_steps(cfg, "evc_visit", v.due_by, t)):
                        emit("evc_visit", f"evc:{v.id}", lvl, step, to or "officer",
                             (f"EVC visit for {a.ref} must be completed by {v.due_by:%d %b %Y}" if lvl == "reminder" else
                              f"Escalation ({step} days): EVC visit for {a.ref} is overdue"
                              + (" (new institution)" if a.category == "new_institution" else "")), v.due_by, a.college_id, a.id, region_of(a), link="/evc")
            # 4. undertakings
            for ut in s.query(Undertaking).filter(Undertaking.status.in_(["open", "rejected"])).all():
                due = datetime.combine(ut.due_date, datetime.min.time())
                a = apps.get(ut.application_id)
                for lvl, step, to in _latest_reminder_only(_ladder_steps(cfg, "undertaking", due, t)):
                    if lvl == "reminder":
                        emit("undertaking", f"undertaking:{ut.id}", lvl, step, "college",
                             f"Reminder ({step}): compliance evidence for undertaking #{ut.id} is due {ut.due_date:%d %b %Y}", due, ut.college_id, ut.application_id, region_of(a) if a else None, link="/compliance")
                    else:
                        emit("undertaking", f"undertaking:{ut.id}", lvl, step, to,
                             f"Escalation ({step} days): undertaking #{ut.id} ({a.ref if a else ''}) is overdue: {ut.condition[:120]}", due, ut.college_id, ut.application_id, region_of(a) if a else None, link="/compliance")
            # 5. document validity
            for dv in s.query(DocumentValidity).filter(DocumentValidity.status.in_(["valid", "renewal_submitted"])).all():
                due = datetime.combine(dv.valid_until, datetime.min.time())
                col = s.get(College, dv.college_id)
                reg = region_for_state(cfg, col.state if col else None)
                for lvl, step, to in _latest_reminder_only(_ladder_steps(cfg, "document_validity", due, t)):
                    if dv.status == "renewal_submitted" and lvl == "reminder":
                        continue
                    if lvl == "reminder":
                        emit("document_validity", f"validity:{dv.id}", lvl, step, "college",
                             f"Reminder ({step}): {dv.label} expires on {dv.valid_until:%d %b %Y}; submit the renewed document", due, dv.college_id, dv.application_id, reg, link="/compliance")
                    else:
                        emit("document_validity", f"validity:{dv.id}", lvl, step, to,
                             f"Escalation ({step} days): {dv.label} of {col.name if col else ''} expired on {dv.valid_until:%d %b %Y}", due, dv.college_id, dv.application_id, reg, link="/compliance")
            # close alerts whose subject is resolved
            closed = 0
            for al in s.query(Alert).filter(Alert.closed_at.is_(None)).all():
                done = False
                kind, _, rest = (al.subject or "").partition(":")
                if kind == "deadline":
                    done = bool(apps.get(int(rest)) and apps[int(rest)].submitted_at)
                elif kind == "stage":
                    aid, _, st = rest.partition(":"); w = wfs.get(int(aid))
                    done = not w or w.current_stage != st or w.state != "active"
                elif kind in ("evc", "evc-schedule"):
                    v = s.get(EvcVisit, int(rest)); done = not v or v.status in ("completed", "cancelled") or (kind == "evc-schedule" and v.status == "scheduled")
                elif kind == "undertaking":
                    ut = s.get(Undertaking, int(rest)); done = not ut or ut.status in ("verified", "submitted")
                elif kind == "validity":
                    dv = s.get(DocumentValidity, int(rest)); done = not dv or dv.status in ("renewed", "superseded")
                if done:
                    al.closed_at = t; closed += 1
            stats["created"], stats["closed"] = len(new_alerts), closed
            s.add(SchedulerRun(as_of=t, trigger=trigger, created_alerts=len(new_alerts), closed_alerts=closed))
            s.commit()
            esc = [a.message for a in new_alerts if a.level == "escalation"]
        audit.log("scheduler.evaluated", "scheduler", "system", "workflow", {k: v for k, v in stats.items() if k != "by_kind"} | {"by_kind": stats["by_kind"], "trigger": trigger})
        if esc:
            from .events import notify_event
            notify_event("workflow.escalation", {"count": len(esc), "items": esc[:20]})
        return stats
