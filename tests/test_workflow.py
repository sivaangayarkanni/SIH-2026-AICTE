"""Workflow module: routing, auto-advance, return/revert, deadlines with time travel, escalation, ICS,
cross-document mismatches, EVC summary, reports, config signing, cron auth, undertakings and validity."""
import io, sys
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
import seed_db


@pytest.fixture(scope="module")
def client():
    sys.argv = ["seed", "--force"]
    seed_db.main()
    from app import main as m
    m._attempts.clear()  # other modules deliberately trip the login limiter
    app = m.app
    with TestClient(app) as c:
        yield c


def login(c, email):
    r = c.post("/api/auth/login", json={"email": email, "password": "Demo@2026"})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def apps_by_code(c, h):
    return {a["ref"].split("-")[2] + ("" if a["submitted_at"] else "-draft"): a for a in c.get("/api/applications", headers=h).json()}


# ---------------------------------------------------------------- unit
def test_route_rules_are_config_driven():
    from app import workflow as wf
    cfg = wf.default_config()
    assert wf.pick_route(cfg, "new_institution")["id"] == "scrutiny_evc_sac"
    assert wf.pick_route(cfg, "extension_of_approval")["id"] == "only_scrutiny"
    assert wf.pick_route(cfg, "restoration_intake")["id"] == "only_evc"
    cfg["route_rules"].insert(0, {"categories": ["extension_of_approval"], "route": "scrutiny_evc"})
    assert wf.pick_route(cfg, "extension_of_approval")["id"] == "scrutiny_evc"


def test_ladder_reminders_and_escalation_steps():
    from app import workflow as wf
    cfg = wf.default_config()
    due = datetime(2027, 1, 31)
    assert wf._ladder_steps(cfg, "submission_deadline", due, datetime(2026, 12, 1)) == []
    st = wf._latest_reminder_only(wf._ladder_steps(cfg, "submission_deadline", due, datetime(2027, 1, 25)))
    assert st == [("reminder", "T-7", None)]
    st = wf._ladder_steps(cfg, "submission_deadline", due, datetime(2027, 2, 9))
    assert ("escalation", "+0", "officer") in st and ("escalation", "+7", "senior_officer") in st


def test_config_validation_rejects_bad_route():
    from app import workflow as wf
    cfg = wf.default_config()
    cfg["routes"][0]["stages"] = ["scrutiny"]          # last stage not terminal
    with pytest.raises(wf.ConfigError):
        wf.validate_config(cfg)
    cfg = wf.default_config(); cfg["escalation"]["stage_sla"] = [{"after_days": 1, "to": "college"}]
    with pytest.raises(wf.ConfigError):
        wf.validate_config(cfg)


def test_crosscheck_normalisation():
    from app.crosscheck import normalise, _same
    assert normalise("land_area", "2.1 acres  10.5 acres") == [2.1, 10.5]
    assert normalise("land_area", "1 ha") == [2.47]
    assert normalise("lease_end", "14/04/2046") == ["2046-04-14"]
    assert _same("trust_name", "ganga valley education society", "ganga valley educational society", 0.88)
    assert not _same("trust_name", "ganga valley education society", "kashi vidya trust", 0.88)


def test_ics_format():
    from app.wf_reports import to_ics
    ics = to_ics([{"id": "x-1", "kind": "stage_sla", "date": "2026-11-05", "title": "Scrutiny due, AICTE; test", "link": "/applications/1", "overdue": True}], "https://h.example")
    assert ics.startswith("BEGIN:VCALENDAR\r\n") and "DTSTART;VALUE=DATE:20261105" in ics and "DTEND;VALUE=DATE:20261106" in ics
    assert "SUMMARY:[OVERDUE] Scrutiny due\\, AICTE\\; test" in ics and ics.endswith("END:VCALENDAR\r\n")
    assert all(len(line.encode()) <= 75 for line in ics.split("\r\n"))


# ---------------------------------------------------------------- API
def test_seeded_routes_and_stage_states(client):
    h = login(client, "senior@sealcheck.demo")
    apps = apps_by_code(client, h)
    w = {k: client.get(f"/api/wf/apps/{a['id']}", headers=h).json()["workflow"] for k, a in apps.items() if a["submitted_at"]}
    assert w["SVIT"]["route_id"] == "only_scrutiny" and w["SVIT"]["state"] == "awaiting_decision"
    assert w["GVCE"]["current_stage"] == "scrutiny" and w["GVCE"]["overdue"]
    assert w["DIEM"]["route_id"] == "scrutiny_evc" and w["DIEM"]["current_stage"] == "evc"
    assert w["MCT"]["state"] == "returned" and "Fire NOC" in w["MCT"]["return_reason"]
    assert [h_["action"] for h_ in w["SVIT"]["history"]] == ["routed", "advanced"]


def test_crosscheck_flags_gvce_not_svit(client):
    h = login(client, "officer2@sealcheck.demo")
    apps = apps_by_code(client, h)
    g = client.get(f"/api/wf/apps/{apps['GVCE']['id']}/crosscheck", headers=h).json()
    fields = {m["field"] for m in g["mismatches"]}
    assert "land_area" in fields
    m = next(m for m in g["mismatches"] if m["field"] == "land_area")
    assert {m["a"]["source"], m["b"]["source"]} & {"gvce_land_lease_forged.pdf"} and (m["a"]["page"] or m["b"]["page"]) == 1
    sv = client.get(f"/api/wf/apps/{apps['SVIT']['id']}/crosscheck", headers=h).json()
    assert sv["mismatches"] == [] and len(sv["fields"]) >= 5


def test_mismatch_notice_goes_to_institution(client):
    h = login(client, "officer2@sealcheck.demo")
    gid = apps_by_code(client, h)["GVCE"]["id"]
    r = client.post(f"/api/wf/apps/{gid}/crosscheck/notify", headers=h)
    assert r.status_code == 200 and r.json()["sent"] is True
    assert client.post(f"/api/wf/apps/{gid}/crosscheck/notify", headers=h).json()["sent"] is False  # idempotent
    hc = login(client, "principal.gvce@sealcheck.demo")
    assert any("to be corrected / re-uploaded" in n["message"] for n in client.get("/api/notifications", headers=hc).json())


def test_advance_rbac_and_mismatch_gate(client):
    hc = login(client, "principal.gvce@sealcheck.demo")
    gid = apps_by_code(client, hc)["GVCE"]["id"]
    assert client.post(f"/api/wf/apps/{gid}/advance", headers=hc, json={"note": "x"}).status_code == 403
    he = login(client, "evc1@sealcheck.demo")
    assert client.post(f"/api/wf/apps/{gid}/advance", headers=he, json={"note": "x"}).status_code == 403
    h = login(client, "officer2@sealcheck.demo")
    r = client.post(f"/api/wf/apps/{gid}/advance", headers=h, json={"note": "done"})
    assert r.status_code == 409 and "mismatch" in r.json()["detail"]
    r = client.post(f"/api/applications/{gid}/decision", headers=login(client, "senior@sealcheck.demo"), json={"decision": "reject", "reason": "Not at decision stage yet"})
    assert r.status_code == 409 and "stages" in r.json()["detail"]


def test_return_resubmit_and_revert_with_reason(client):
    h = login(client, "officer2@sealcheck.demo")
    gid = apps_by_code(client, h)["GVCE"]["id"]
    assert client.post(f"/api/wf/apps/{gid}/return", headers=h, json={"reason": "no"}).status_code == 422
    r = client.post(f"/api/wf/apps/{gid}/return", headers=h, json={"reason": "Land area differs between lease and form", "items": ["Land lease"]})
    assert r.status_code == 200 and r.json()["workflow"]["state"] == "returned"
    hc = login(client, "principal.gvce@sealcheck.demo")
    r = client.post(f"/api/wf/apps/{gid}/resubmit", headers=hc, json={"note": "Re-uploaded the lease"})
    assert r.status_code == 200 and r.json()["workflow"]["state"] == "active"
    hs = login(client, "senior@sealcheck.demo")
    sid = apps_by_code(client, hs)["SVIT"]["id"]
    r = client.post(f"/api/wf/apps/{sid}/revert", headers=hs, json={"reason": "Re-check the FDR before the decision"})
    assert r.status_code == 200 and r.json()["workflow"]["current_stage"] == "scrutiny"
    hist = r.json()["workflow"]["history"]
    assert hist[-1]["action"] == "reverted" and hist[-1]["reason"].startswith("Re-check")
    r = client.post(f"/api/wf/apps/{sid}/advance", headers=hs, json={"note": "FDR re-checked"})
    assert r.status_code == 200 and r.json()["workflow"]["state"] == "awaiting_decision"
    r = client.post(f"/api/applications/{sid}/decision", headers=hs, json={"decision": "approve", "reason": "Scrutiny complete and consistent."})
    assert r.status_code == 200
    assert client.get(f"/api/wf/apps/{sid}", headers=hs).json()["workflow"]["state"] == "completed"
    log = client.get("/api/audit", headers=hs).json()
    acts = {e["action"] for e in (log["entries"] if isinstance(log, dict) else log)}
    assert {"workflow.returned", "workflow.resubmitted", "workflow.reverted", "workflow.advanced"} <= acts


def test_evc_member_flow_and_auto_advance(client):
    he = login(client, "evc1@sealcheck.demo")
    visits = client.get("/api/wf/evc", headers=he).json()["visits"]
    assert len(visits) == 1 and visits[0]["status"] == "scheduled"
    v = visits[0]
    assert client.get("/api/wf/dashboard", headers=he).status_code == 403
    assert len(client.get("/api/applications", headers=he).json()) == 1
    s = client.get(f"/api/wf/apps/{v['application_id']}/evc-summary", headers=he).json()
    assert s["institution"]["code"] == "DIEM" and s["checklist"] and s["safeguard"]
    pdf = client.get(f"/api/wf/apps/{v['application_id']}/evc-summary.pdf", headers=he)
    assert pdf.content.startswith(b"%PDF")
    assert client.get(f"/api/wf/apps/{v['application_id']}/evc-summary", headers=login(client, "principal.diem@sealcheck.demo")).status_code == 403
    h = login(client, "officer@sealcheck.demo")
    assert client.post(f"/api/wf/evc/{v['id']}/complete", headers=h, json={"note": ""}).status_code == 409   # no member report yet
    r = client.post(f"/api/wf/evc/{v['id']}/report", headers=he, json={"checklist": {"land": "yes", "labs": "no"}, "remarks": "Lab 3 equipment missing"})
    assert r.status_code == 200
    assert client.post(f"/api/wf/evc/{v['id']}/report", headers=he, json={"checklist": {"bogus": "yes"}}).status_code == 400
    assert client.post(f"/api/wf/evc/{v['id']}/complete", headers=he, json={"note": ""}).status_code == 403   # members cannot decide
    r = client.post(f"/api/wf/evc/{v['id']}/complete", headers=h, json={"note": "Visit held"})
    assert r.status_code == 200 and r.json()["status"] == "completed"
    w = client.get(f"/api/wf/apps/{v['application_id']}", headers=h).json()["workflow"]
    assert w["current_stage"] == "decision" and w["history"][-1]["reason"].startswith("Auto-advance")


def test_scheduler_time_travel_idempotent_and_escalates(client):
    h = login(client, "admin@sealcheck.demo")
    future = (datetime.utcnow() + timedelta(days=40)).isoformat()
    r1 = client.post("/api/wf/evaluate", headers=h, json={"as_of": future}).json()
    assert r1["created"] > 0
    r2 = client.post("/api/wf/evaluate", headers=h, json={"as_of": future}).json()
    assert r2["created"] == 0          # idempotent: same as_of -> no duplicate alerts
    al = client.get("/api/wf/alerts", headers=h).json()
    kinds = {(a["kind"], a["level"]) for a in al}
    assert ("undertaking", "escalation") in kinds and ("document_validity", "escalation") in kinds
    assert any(a["target_role"] == "senior_officer" and a["level"] == "escalation" for a in al)
    hc = login(client, "principal.svit@sealcheck.demo")
    mine = client.get("/api/wf/alerts", headers=hc).json()
    assert mine and all(a["target_role"] == "college" for a in mine)


def test_cron_endpoint_auth(client, monkeypatch):
    monkeypatch.delenv("CRON_SECRET", raising=False)
    assert client.get("/api/cron/evaluate").status_code == 503
    monkeypatch.setenv("CRON_SECRET", "s3cret-for-tests")
    assert client.get("/api/cron/evaluate", headers={"Authorization": "Bearer nope"}).status_code == 401
    r = client.get("/api/cron/evaluate", headers={"Authorization": "Bearer s3cret-for-tests"})
    assert r.status_code == 200 and "created" in r.json()


def test_calendar_and_ics_subscription(client):
    h = login(client, "senior@sealcheck.demo")
    ev = client.get("/api/wf/calendar", headers=h, params={"start": "2026-01-01", "end": "2027-12-31"}).json()["events"]
    assert ev and {e["kind"] for e in ev} >= {"evc_visit"}
    sub = client.get("/api/wf/calendar/subscription", headers=h).json()
    path = sub["url"].split("://", 1)[1].split("/", 1)[1]
    r = client.get("/" + path)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar") and "BEGIN:VEVENT" in r.text
    bad = "/" + path.rsplit("key=", 1)[0] + "key=" + "0" * 32
    assert client.get(bad).status_code == 403
    hc = login(client, "principal.svit@sealcheck.demo")
    cev = client.get("/api/wf/calendar", headers=hc, params={"start": "2026-01-01", "end": "2027-12-31"}).json()["events"]
    assert cev and all("SVIT" in e["title"] or e["kind"] in ("undertaking", "document_validity", "stage_sla", "submission_deadline") for e in cev)


def test_reports_all_kinds_csv_pdf(client):
    h = login(client, "senior@sealcheck.demo")
    kinds = client.get("/api/wf/reports", headers=h).json()["reports"]
    assert set(kinds) == {"pendency", "evc", "undertakings", "validity", "overdue", "region_performance"}
    for k in kinds:
        j = client.get(f"/api/wf/reports/{k}", headers=h).json()
        assert j["header"]
        csv = client.get(f"/api/wf/reports/{k}?format=csv", headers=h)
        assert csv.headers["content-type"].startswith("text/csv") and csv.text.splitlines()[0].startswith(j["header"][0])
        assert client.get(f"/api/wf/reports/{k}?format=pdf", headers=h).content.startswith(b"%PDF")
    rp = client.get("/api/wf/reports/region_performance", headers=h).json()
    assert any("Region" in r[0] for r in rp["rows"])
    assert client.get("/api/wf/reports/pendency", headers=login(client, "principal.svit@sealcheck.demo")).status_code == 403


def test_dashboard_region_scope(client):
    h = login(client, "officer@sealcheck.demo")    # Region 1 (South): SVIT (Tamil Nadu), MCT (Kerala)
    d = client.get("/api/wf/dashboard", headers=h).json()
    assert d["scope"]["regions"] == ["R1"] and set(d["by_region"]) <= {"Region 1 (South)"}
    d_all = client.get("/api/wf/dashboard?scope=all", headers=h).json()
    assert len(d_all["by_region"]) >= 2 and d_all["bottlenecks"]
    hs = login(client, "senior@sealcheck.demo")
    assert client.get("/api/wf/dashboard", headers=hs).json()["scope"]["regions"] is None


def test_undertaking_and_validity_flows(client):
    hs = login(client, "senior@sealcheck.demo")
    hc = login(client, "principal.svit@sealcheck.demo")
    sid = apps_by_code(client, hs)["SVIT"]["id"]
    r = client.post("/api/wf/undertakings", headers=hs, json={"application_id": sid, "condition": "Install additional fire exits", "due_date": "2027-01-15"})
    assert r.status_code == 200
    uid = r.json()["id"]
    pdf = open(seed_db.SAMPLES_DIR / "svit_fire_noc.pdf", "rb").read()
    r = client.post(f"/api/wf/undertakings/{uid}/submit", headers=hc, files={"file": ("exits.pdf", io.BytesIO(pdf), "application/pdf")}, data={"note": "Done"})
    assert r.status_code == 200 and r.json()["status"] == "submitted"
    sub = r.json()["submissions"][0]
    assert client.get(f"/api/wf/compliance/{sub['id']}/file", headers=hs).content == pdf
    assert client.post(f"/api/wf/undertakings/{uid}/verify", headers=hs, json={"accept": False, "remark": ""}).status_code == 400
    r = client.post(f"/api/wf/undertakings/{uid}/verify", headers=hs, json={"accept": True, "remark": "Verified"})
    assert r.json()["status"] == "verified"
    dv = [x for x in client.get("/api/wf/validity", headers=hc).json() if "stability" in x["label"]][0]
    assert dv["flag"] == "expiring"
    r = client.post(f"/api/wf/validity/{dv['id']}/renew", headers=hc, files={"file": ("renewal.pdf", io.BytesIO(pdf), "application/pdf")},
                    data={"valid_until": "2030-01-01", "note": "renewed"})
    assert r.status_code == 200 and r.json()["status"] == "renewal_submitted"
    r = client.post(f"/api/wf/validity/{dv['id']}/verify", headers=hs, json={"accept": True, "remark": "Original seen"})
    assert r.json()["status"] == "renewed"
    assert any(x["valid_until"] == "2030-01-01" for x in client.get("/api/wf/validity", headers=hc).json())


def test_wizard_draft_save_and_resume(client):
    hc = login(client, "principal.svit@sealcheck.demo")
    did = apps_by_code(client, hc)["SVIT-draft"]["id"]
    r = client.put(f"/api/wf/apps/{did}/draft", headers=hc, json={"step": 2, "data": {"institution": {"land_area": "12.5 acres", "evil": "x"}}})
    assert r.status_code == 200
    d = client.get(f"/api/wf/apps/{did}/draft", headers=hc).json()
    assert d["step"] == 2 and d["data"]["institution"] == {"land_area": "12.5 acres"}
    assert client.put(f"/api/wf/apps/{did}/draft", headers=login(client, "principal.gvce@sealcheck.demo"), json={"step": 1, "data": {}}).status_code == 404


def test_signed_versioned_config(client):
    h = login(client, "admin@sealcheck.demo")
    cur = client.get("/api/wf/config", headers=h).json()
    assert client.put("/api/wf/config", headers=login(client, "officer@sealcheck.demo"), json={"config": cur["config"], "note": "x"}).status_code == 403
    bad = {**cur["config"], "route_rules": [{"categories": ["x"], "route": "nope"}]}
    assert client.put("/api/wf/config", headers=h, json={"config": bad, "note": "broken"}).status_code == 400
    cfg = cur["config"]; cfg["stages"]["scrutiny"]["sla_days"] = 12
    r = client.put("/api/wf/config", headers=h, json={"config": cfg, "note": "Shorter scrutiny SLA"}).json()
    assert r["signed"] and r["version"] == (cur["version"] or 1) + 1 and r["config"]["stages"]["scrutiny"]["sla_days"] == 12
    from app.db import SessionLocal
    from app import workflow as wf
    with SessionLocal() as s:     # tampering with the stored JSON breaks the HMAC -> falls back to the shipped default
        row = s.query(wf.WorkflowConfigVersion).order_by(wf.WorkflowConfigVersion.version.desc()).first()
        row.config_json = row.config_json.replace('"sla_days":12', '"sla_days":99'); s.commit()
        wf._cache.clear()
        assert wf.active_config(s)["_signed"] is False
        s.delete(row); s.commit(); wf._cache.clear()
