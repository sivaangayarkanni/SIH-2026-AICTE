"""End-to-end smoke test against a running SealCheck server (default http://localhost:8000).
Run after a fresh seed:  RESEED=1 ./run.sh  then  python scripts/smoke.py"""
import sys, time, httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
PW = "Demo@2026"
c = httpx.Client(base_url=BASE, timeout=30)
ok = 0


def check(cond, msg):
    global ok
    if not cond:
        print("FAIL:", msg); sys.exit(1)
    ok += 1; print("PASS:", msg)


def login(email):
    r = c.post("/api/auth/login", json={"email": email, "password": PW})
    check(r.status_code == 200, f"login {email}")
    return {"Authorization": f"Bearer {r.json()['token']}"}


check(c.get("/api/health").json().get("status") == "ok", "health")
check(c.post("/api/auth/login", json={"email": "officer@sealcheck.demo", "password": "nope"}).status_code == 401, "bad password rejected")

off = login("officer@sealcheck.demo")
apps = c.get("/api/applications", headers=off).json()
apps = apps["items"] if isinstance(apps, dict) else apps
check(len(apps) >= 4, f"{len(apps)} applications visible to officer")
by = {}
for a in apps:
    code = a.get("code") or a.get("ref") or str(a["id"])
    by[code] = a
    print(f"   {code:22} status={a.get('status')} risk={a.get('risk_score', a.get('risk'))}")

# per-document expected statuses from the seed manifest
samples = {s["file"]: s["expected_status"] for s in c.get("/api/samples", headers=off).json()}
seen = 0
for a in apps:
    d = c.get(f"/api/applications/{a['id']}", headers=off).json()
    for doc in d.get("documents", []):
        if doc.get("filename") in samples:
            check(doc["status"] == samples[doc["filename"]], f"{doc['filename']} -> {doc['status']}")
            seen += 1
check(seen >= 10, f"{seen} seeded documents matched expected statuses")

gvce = next(a for k, a in by.items() if "GVCE" in k)
r = c.post(f"/api/applications/{gvce['id']}/decision", headers=off, json={"decision": "approve", "reason": "Looks fine to me"})
check(r.status_code == 409, "approving GVCE with unresolved mismatches is blocked (409)")

g = c.get(f"/api/applications/{gvce['id']}", headers=off).json()
bad = [d for d in g["documents"] if d["status"] != "Verified"]
r = c.post(f"/api/applications/{gvce['id']}/overrides", headers=off,
           json={"document_id": bad[0]["id"], "justification": "too short"})
check(r.status_code in (400, 422), "short override justification rejected")
r = c.post(f"/api/applications/{gvce['id']}/overrides", headers=off,
           json={"document_id": bad[0]["id"], "justification": "Original lease physically inspected at regional office; certified copy matches registry."})
check(r.status_code == 200, "officer requests override")
oid = r.json()["id"]
r = c.post(f"/api/overrides/{oid}/approve", headers=off, json={"note": "approving my own"})
check(r.status_code == 403, "requester cannot approve own override (403)")
sen = login("senior@sealcheck.demo")
r = c.post(f"/api/overrides/{oid}/approve", headers=sen, json={"note": "Verified with registry, approved."})
check(r.status_code == 200, "different senior officer approves override")

r = c.post(f"/api/applications/{gvce['id']}/decision", headers=off, json={"decision": "request_changes", "reason": "Upload the missing mandatory documents."})
check(r.status_code == 200, "request changes on GVCE")

draft = by["AICTE-26-SVIT-0005"]
r = c.post(f"/api/applications/{draft['id']}/decision", headers=off, json={"decision": "approve", "reason": "Trying a draft."})
check(r.status_code == 409, "deciding an unsubmitted draft is blocked (409)")
svit = by["AICTE-26-SVIT-0001"]
r = c.post(f"/api/applications/{svit['id']}/decision", headers=off, json={"decision": "approve", "reason": "All mandatory documents verified."})
check(r.status_code == 200, f"SVIT approve -> {r.status_code} {r.text[:120]}")

# college upload -> sandbox job completes
mct = login("principal.mct@sealcheck.demo")
m = c.get("/api/applications", headers=mct).json()
m = m["items"] if isinstance(m, dict) else m
target = next((a for a in m if not a.get("decision")), m[0])
pdf = c.get("/api/samples/svit_fire_noc.pdf", headers=mct).content
r = c.post(f"/api/applications/{target['id']}/documents", headers=mct,
           files={"file": ("smoke_fire_noc.pdf", pdf, "application/pdf")}, data={"doc_type": "fire_noc"})
check(r.status_code == 200, f"college upload accepted ({r.status_code})")
did = r.json().get("id") or r.json().get("document", {}).get("id")
for _ in range(30):
    st = c.get(f"/api/documents/{did}", headers=mct).json().get("status")
    if st not in ("Verification Pending", None):
        break
    time.sleep(1)
check(st not in ("Verification Pending", None), f"uploaded document analysed -> {st}")

v = c.get("/api/audit/verify", headers=login("admin@sealcheck.demo")).json()
check(v["valid"] is True, f"audit hash chain valid ({v['entries']} entries)")
print(f"\nSMOKE OK - {ok} checks passed")
