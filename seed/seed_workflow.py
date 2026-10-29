"""Development-only workflow seed: regions, EVC members, routed applications at different stages, an EVC visit,
undertakings, document-validity records and one scheduler run. All data is SYNTHETIC."""
from datetime import timedelta, date

from app.db import SessionLocal, User, Application, now
from app.security import hash_password
from app import workflow as wf
from app.workflow import UserRegion, WizardDraft, EvcVisit, Undertaking, ComplianceSubmission, DocumentValidity
from app.config import SAMPLES_DIR

EVC_USERS = [("evc1@sealcheck.demo", "Prof. Anand Rao", "EVC Member (Expert, Civil Engg.)", "anand"),
             ("evc2@sealcheck.demo", "Dr. Lakshmi Menon", "EVC Member (Expert, CSE)", "lakshmi")]
DECLARED = {
    "SVIT": {"institution_name": "Sri Venkateswara Institute of Technology", "trust_name": "Sri Venkateswara Educational Trust",
             "address": "Old Mahabalipuram Road, Sholinganallur, Chennai", "survey_no": "142/3B", "land_area": "12.5 acres",
             "lease_start": "2016-04-15", "lease_end": "2046-04-14", "lease_term": "30", "signatory": "Dr. V. Raghavan, Chairman"},
    "GVCE": {"institution_name": "Ganga Valley College of Engineering", "trust_name": "Ganga Valley Educational Society",
             "address": "Sarnath Road, Varanasi", "survey_no": "77/1", "land_area": "15 acres", "lease_start": "2019-02-11",
             "lease_end": "2034-02-10", "lease_term": "15", "signatory": "Sri R. K. Pandey, Secretary"},
}


def seed(password: str):
    s = SessionLocal()
    t = now()
    for email, name, title, av in EVC_USERS:
        s.add(User(email=email, name=name, title=title, role="evc_member", password_hash=hash_password(password), avatar_seed=av))
    s.commit()
    users = {u.email: u for u in s.query(User).all()}
    s.add(UserRegion(user_id=users["officer@sealcheck.demo"].id, region_code="R1"))
    s.add(UserRegion(user_id=users["officer2@sealcheck.demo"].id, region_code="R6"))
    s.commit()
    apps = {a.college.code + ("-draft" if not a.submitted_at else ""): a for a in s.query(Application).order_by(Application.id).all()}
    for code, data in DECLARED.items():
        s.add(WizardDraft(application_id=apps[code].id, step=3, data_json={"institution": data}, updated_at=t))
    s.commit()
    off, off2, sen = users["officer@sealcheck.demo"], users["officer2@sealcheck.demo"], users["senior@sealcheck.demo"]
    who = lambda u: f"{u.name} <{u.email}>"  # noqa: E731
    # SVIT: Only Scrutiny -> scrutiny completed 1 day ago -> awaiting the competent authority's decision
    a = apps["SVIT"]; wf.route_application(s, a, "seed", "college", at=t - timedelta(days=4))
    wf.advance(s, a, off, who(off), "Scrutiny complete: all documents consistent (seed).", at=t - timedelta(days=1))
    # GVCE: Only Scrutiny, stage started 20 days ago (SLA 15) -> overdue, escalations
    a = apps["GVCE"]; wf.route_application(s, a, "seed", "college", at=t - timedelta(days=20))
    # DIEM: Scrutiny + EVC -> moved to EVC 10 days ago, visit scheduled in 5 days
    a = apps["DIEM"]; wf.route_application(s, a, "seed", "college", at=t - timedelta(days=16))
    w = s.get(wf.AppWorkflow, a.id); w.state = "active"; s.commit()
    wf.advance(s, a, off, who(off), "Scrutiny complete; EVC required for increase in intake (seed).", auto=True, at=t - timedelta(days=10))
    v = s.query(EvcVisit).filter(EvcVisit.application_id == a.id).first()
    v.status, v.scheduled_for, v.members_json = "scheduled", t + timedelta(days=5), [users["evc1@sealcheck.demo"].id, users["evc2@sealcheck.demo"].id]
    s.commit()
    # MCT: Scrutiny + EVC -> returned to institution for correction
    a = apps["MCT"]; wf.route_application(s, a, "seed", "college", at=t - timedelta(days=2))
    wf.return_to_institution(s, a, off, who(off), "Fire NOC issuer is not a recognised authority; please re-upload a NOC from the State Fire Services.",
                             ["Fire Safety NOC (re-upload)"], at=t - timedelta(days=1))
    # undertakings
    s.add(Undertaking(application_id=apps["SVIT"].id, college_id=apps["SVIT"].college_id, condition="Submit renewed Fire NOC covering the new Block E",
                      evidence_required="Fire NOC PDF issued by the State Fire Services", due_date=(t + timedelta(days=10)).date(), created_by=who(sen)))
    s.add(Undertaking(application_id=apps["GVCE"].id, college_id=apps["GVCE"].college_id, condition="Fill vacant faculty positions to meet the declared faculty-student ratio",
                      evidence_required="Updated faculty list with appointment orders", due_date=(t - timedelta(days=9)).date(), created_by=who(off2)))
    ut = Undertaking(application_id=apps["DIEM"].id, college_id=apps["DIEM"].college_id, condition="Submit structural stability certificate for the new laboratory wing",
                     evidence_required="Certificate from a licensed structural engineer", due_date=(t + timedelta(days=20)).date(), status="submitted", created_by=who(sen))
    s.add(ut); s.flush()
    from app.pipeline import gateway
    from app import service
    data = (SAMPLES_DIR / "diem_building_completion_expired_dsc.pdf").read_bytes()
    g = gateway.inspect_upload(data, "stability_certificate.pdf")
    s.add(ComplianceSubmission(undertaking_id=ut.id, filename="stability_certificate.pdf", sha256=g["sha256"], size=g["size"],
                               stored_path=service.store_original(data, g["sha256"], "pdf"), note="Certificate attached (synthetic seed file)",
                               submitted_by="Dr. Farah Siddiqui <principal.diem@sealcheck.demo>"))
    s.commit()
    wf.sync_validity(s)
    s.add(DocumentValidity(college_id=apps["SVIT"].college_id, application_id=apps["SVIT"].id, doc_type="building_completion",
                           label="Building stability certificate (synthetic seed record)", valid_from=date(t.year - 3, t.month, 1),
                           valid_until=(t + timedelta(days=20)).date()))
    s.commit()
    s.close()
    return wf.evaluate(trigger="seed")
