import time, sys, pytest
from fastapi.testclient import TestClient
from conftest import SAMPLES
import seed_db
from app import config


@pytest.fixture(scope="module")
def client():
    sys.argv = ["seed", "--force"]
    seed_db.main()
    from app.main import app
    with TestClient(app) as c:
        yield c


def login(c, email):
    r = c.post("/api/auth/login", json={"email": email, "password": "Demo@2026"})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_seeded_statuses(client):
    h = login(client, "officer@sealcheck.demo")
    q = client.get("/api/officer/queue", headers=h).json()
    st = {a["ref"].split("-")[2]: a["status"] for a in q}
    assert st["SVIT"] == "Verified" and st["GVCE"] == "Mismatch Detected" and st["DIEM"] == "Mismatch Detected"
    assert q[0]["priority"]["score"] >= q[-1]["priority"]["score"]


def test_bad_login_and_rbac(client):
    assert client.post("/api/auth/login", json={"email": "officer@sealcheck.demo", "password": "nope"}).status_code == 401
    hc = login(client, "principal.gvce@sealcheck.demo")
    apps = client.get("/api/applications", headers=hc).json()
    assert {a["college"] for a in apps} == {"Ganga Valley College of Engineering"}
    assert client.get("/api/applications/1", headers=hc).status_code == 404  # SVIT's application: row-level scope
    assert client.get("/api/officer/queue", headers=hc).status_code == 403
    assert client.get("/api/audit", headers=hc).status_code == 403


def test_upload_pipeline_and_precheck(client):
    hc = login(client, "principal.svit@sealcheck.demo")
    a = client.post("/api/applications", headers=hc, json={"category": "new_course"}).json()
    with open(SAMPLES / "svit_land_lease.pdf", "rb") as f:
        r = client.post(f"/api/applications/{a['id']}/documents", headers=hc,
                        files={"file": ("lease.pdf", f, "application/pdf")}, data={"doc_type": "land_document"})
    assert r.status_code == 200, r.text
    did = r.json()["document"]["id"]
    for _ in range(60):
        d = client.get(f"/api/documents/{did}", headers=hc).json()
        if d["job"]["status"] in ("done", "failed"):
            break
        time.sleep(0.5)
    assert d["status"] == "Verified", d.get("error")
    assert d["versions"][0]["worm"] is True
    stages = {p["stage"] for p in d["job"]["progress"]}
    assert "4A PDF forensics" in stages and "5 Policy engine" in stages
    bad = client.post(f"/api/applications/{a['id']}/documents", headers=hc,
                      files={"file": ("x.pdf", b"hello world", "application/pdf")}, data={"doc_type": "fire_noc"})
    assert bad.status_code == 415
    before = len(list((config.ORIGINALS_DIR).glob("*")))
    with open(SAMPLES / "diem_fire_noc_expired.pdf", "rb") as f:
        p = client.post("/api/readiness/precheck", headers=hc, files={"file": ("n.pdf", f, "application/pdf")},
                        data={"doc_type": "fire_noc"}).json()
    assert p["stored"] is False and p["predicted_status"] == "Expired"
    assert len(list(config.ORIGINALS_DIR.glob("*"))) == before


def test_two_person_override(client):
    h1 = login(client, "officer@sealcheck.demo")
    login(client, "senior@sealcheck.demo")
    app = client.get("/api/applications/2", headers=h1).json()
    flagged = [d for d in app["documents"] if d["status"] == "Mismatch Detected"]
    r = client.post("/api/applications/2/decision", headers=h1, json={"decision": "approve", "reason": "Looks fine overall"})
    assert r.status_code == 409
    r = client.post("/api/applications/2/overrides", headers=h1, json={"document_id": flagged[0]["id"], "justification": "too short"})
    assert r.status_code == 422
    r = client.post("/api/applications/2/overrides", headers=h1,
                    json={"document_id": flagged[0]["id"], "justification": "Original deed inspected physically at the Sub-Registrar office."})
    assert r.status_code == 200
    oid = r.json()["id"]
    assert client.post(f"/api/overrides/{oid}/approve", headers=h1, json={"note": "self approve"}).status_code == 403
    hs2 = login(client, "senior@sealcheck.demo")
    r = client.post(f"/api/overrides/{oid}/approve", headers=hs2, json={"note": "Verified physical deed copy."})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    d = client.get(f"/api/documents/{flagged[0]['id']}", headers=h1).json()
    assert d["status"] == "Verified"


def test_rejection_helper_and_decision_pdf(client):
    h = login(client, "officer@sealcheck.demo")
    g = client.post("/api/applications/3/rejection-helper", headers=h, json={"reason": "Expired certificates and reused lab photo."}).json()
    assert len(g["items"]) >= 3
    pdf = client.get("/api/applications/3/rejection.pdf", headers=h)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    r = client.post("/api/applications/3/decision", headers=h, json={"decision": "request_changes", "reason": "See corrections list."})
    assert r.status_code == 200 and r.json()["decision"] == "Changes Requested"
    assert client.get("/api/applications/3/decision.pdf", headers=h).content.startswith(b"%PDF")


def test_assistant_answers_with_citation(client):
    h = login(client, "officer@sealcheck.demo")
    docs = client.get("/api/applications/3", headers=h).json()["documents"]
    noc = next(d for d in docs if d["doc_type"] == "fire_noc")
    r = client.post(f"/api/documents/{noc['id']}/ask", headers=h, json={"question": "When does this NOC expire?"}).json()
    assert "12 March 2024" in r["answer"] and r["citation"]["page"] == 1


def test_audit_chain_tamper_detection(client):
    h = login(client, "admin@sealcheck.demo")
    assert client.get("/api/audit/verify", headers=h).json()["valid"] is True
    from sqlalchemy import text
    from app.db import engine, IS_PG
    with engine.begin() as c:  # attacker with raw DB access (bypasses ORM guards; on PG also disables the trigger)
        if IS_PG:
            with pytest.raises(Exception, match="append-only"):
                with c.begin_nested():
                    c.execute(text("UPDATE audit_log SET actor='mallory' WHERE id=3"))
            c.execute(text("ALTER TABLE audit_log DISABLE TRIGGER trg_audit_append_only"))
        c.execute(text("UPDATE audit_log SET actor='mallory' WHERE id=3"))
        if IS_PG:
            c.execute(text("ALTER TABLE audit_log ENABLE TRIGGER trg_audit_append_only"))
    v = client.get("/api/audit/verify", headers=h).json()
    assert v["valid"] is False and v["broken_at"] == 3


def test_security_endpoints(client):
    h = login(client, "admin@sealcheck.demo")
    t = client.post("/api/security/token-demo", headers=h, json={"ttl": 60}).json()
    assert client.post("/api/security/token-verify", headers=h, json={"token": t["token"]}).json()["valid"]
    k = client.post("/api/security/kms-demo", headers=h, json={"plaintext": "1234 5678 9012"}).json()
    assert k["decrypted"] == "1234 5678 9012" and "1234" not in k["envelope"]["ciphertext"]
    pii = client.get("/api/security/pii", headers=h).json()
    assert pii and all("X" in p["masked"] for p in pii)
    g = client.get("/api/collusion/graph", headers=h).json()
    assert g["summary"]["links"] >= 2
    o = client.get("/api/security/overview", headers=h)
    assert o.status_code == 200, o.text
    b = o.json()["backends"]
    assert {"database", "auth", "sandbox", "kms", "storage", "queue", "vision", "llm", "notify", "revocation"} <= set(b)
    assert b["kms"] == "soft" and b["auth"] == "local"


def test_pii_reveal_requires_justification_and_is_audited(client):
    h = login(client, "admin@sealcheck.demo")
    pid = client.get("/api/security/pii", headers=h).json()[0]["id"]
    assert client.post(f"/api/security/pii/{pid}/reveal", headers=h, json={}).status_code == 422
    assert client.post(f"/api/security/pii/{pid}/reveal", headers=h, json={"justification": "x" * 25}).status_code == 422
    r = client.post(f"/api/security/pii/{pid}/reveal", headers=h,
                    json={"justification": "Case AICTE-26-GVCE collusion review, faculty PAN check"})
    assert r.status_code == 200 and len(r.json()["value"]) == 10
    a = client.get("/api/audit?limit=5", headers=h).json()
    rows = a["items"] if isinstance(a, dict) else a
    assert any(x["action"] == "pii.revealed" and "collusion review" in str(x.get("details")) for x in rows)
    off = login(client, "officer@sealcheck.demo")
    assert client.post(f"/api/security/pii/{pid}/reveal", headers=off, json={"justification": "Case AICTE-26-GVCE collusion review"}).status_code == 403
