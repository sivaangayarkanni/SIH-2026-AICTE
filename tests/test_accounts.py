"""Username + password accounts: policy, signup with roles, approval, lockout, password change/reset, token revocation, bootstrap."""
import sys

import pytest
from fastapi.testclient import TestClient
import seed_db

STRONG = "Kestrel-Harbour-42"


@pytest.fixture(scope="module")
def client():
    sys.argv = ["seed", "--force"]
    seed_db.main()
    from app import main as m
    m._attempts.clear(); m._signups.clear()
    with TestClient(m.app) as c:
        yield c


@pytest.fixture(autouse=True)
def _clear_limits():
    from app import main as m
    m._attempts.clear(); m._signups.clear()


def H(t):
    return {"Authorization": "Bearer " + t}


def login(c, ident, pw):
    return c.post("/api/auth/login", json={"username": ident, "password": pw})


def admin(c):
    r = login(c, "admin@sealcheck.demo", "Demo@2026"); assert r.status_code == 200, r.text
    return H(r.json()["token"])


def signup(c, **kw):
    body = {"full_name": "Test Person", "username": "tperson", "email": "tperson@example.org", "phone": "9876543210",
            "password": STRONG, "confirm": STRONG, "role": "college", "institution_name": "Test Institute of Technology",
            "aicte_id": "1-99999001", "state": "Kerala", "designation": "Principal", "region": "", "consent": True} | kw
    return c.post("/api/auth/signup", json=body)


def test_policy():
    from app.accounts import password_problems
    assert password_problems("short1A!")
    assert any("common" in p for p in password_problems("Password123!"))
    assert any("username" in p for p in password_problems("Ravi.Kumar2026!", "ravi.kumar"))
    assert password_problems("alllowercaseletters")
    assert password_problems(STRONG, "tperson", "tperson@example.org") == []


def test_hash_is_bcrypt_and_legacy_upgrades(client):
    from app.db import SessionLocal, User
    from app.security import verify_password
    login(client, "officer@sealcheck.demo", "Demo@2026")
    with SessionLocal() as s:
        u = s.query(User).filter_by(email="officer@sealcheck.demo").one()
        assert u.password_hash.startswith("bcrypt_sha256$$2b$") and verify_password("Demo@2026", u.password_hash)


def test_signup_validation_errors(client):
    r = signup(client, username="X!", password="abc", confirm="abd", phone="12", consent=False)
    assert r.status_code == 422
    f = r.json()["detail"]["fields"]
    assert {"username", "password", "confirm", "phone", "consent"} <= set(f)
    r = signup(client, role="officer", region="")
    assert r.status_code == 422 and "region" in r.json()["detail"]["fields"]


def test_college_signup_gets_access_and_duplicates_are_generic(client):
    r = signup(client); assert r.status_code == 200, r.text
    j = r.json(); assert j["status"] == "approved" and j["user"]["role"] == "college" and j["user"]["username"] == "tperson"
    assert client.get("/api/applications", headers=H(j["token"])).status_code == 200
    r2 = signup(client, email="other@example.org"); assert r2.status_code == 409
    r3 = signup(client, username="someoneelse"); assert r3.status_code == 409
    assert r2.json()["detail"]["message"] == r3.json()["detail"]["message"]
    # second representative of an existing institution is pending
    r4 = signup(client, username="second.rep", email="second@example.org")
    assert r4.json()["status"] == "pending" and r4.json()["user"]["role"] == "pending"


def test_officer_signup_pending_then_admin_approval(client):
    r = signup(client, username="newofficer", email="newofficer@example.org", role="officer", region="R3",
               institution_name="", aicte_id="", state="", designation="Deputy Director")
    assert r.status_code == 200, r.text
    j = r.json(); assert j["status"] == "pending" and j["user"]["role"] == "pending"
    tok = j["token"]
    assert client.get("/api/auth/me", headers=H(tok)).status_code == 200
    assert client.get("/api/applications", headers=H(tok)).status_code == 403
    a = admin(client)
    reqs = client.get("/api/admin/access-requests", headers=a).json()
    uid = next(x["user_id"] for x in reqs if x["email"] == "newofficer@example.org")
    assert client.post(f"/api/admin/access-requests/{uid}/approve", headers=a, json={}).json()["role"] == "officer"
    assert client.get("/api/auth/me", headers=H(tok)).status_code == 401   # role change revokes old sessions
    r = login(client, "newofficer", STRONG); assert r.status_code == 200
    assert r.json()["user"]["role"] == "officer"
    regs = client.get("/api/wf/regions", headers=a).json()
    assert next(o for o in regs["officers"] if o["id"] == uid)["region"] == "R3"
    from app.db import AuditLog, SessionLocal
    with SessionLocal() as s:
        acts = {x.action for x in s.query(AuditLog).all()}
    assert {"auth.signup", "access.approved", "auth.login"} <= acts


def test_lockout_is_progressive_and_generic(client):
    signup(client, username="locky", email="locky@example.org", aicte_id="1-99999002")
    msgs = set()
    for _ in range(5):
        r = login(client, "locky", "Wrong-password-99"); assert r.status_code == 401; msgs.add(r.json()["detail"])
    r = login(client, "locky", STRONG); assert r.status_code == 401; msgs.add(r.json()["detail"])   # locked even with the right password
    r = login(client, "nobody-here", STRONG); msgs.add(r.json()["detail"])
    assert len(msgs) == 1
    from app.accounts import UserCredential
    from app.db import SessionLocal
    with SessionLocal() as s:
        c = s.query(UserCredential).filter_by(username="locky").one(); assert c.locked_until is not None
        c.locked_until = None; s.commit()
    assert login(client, "locky", STRONG).status_code == 200


def test_password_change_and_logout_everywhere(client):
    signup(client, username="changer", email="changer@example.org", aicte_id="1-99999003")
    t1 = login(client, "changer", STRONG).json()["token"]
    r = client.post("/api/auth/password", headers=H(t1), json={"current": "nope", "new": "x", "confirm": "x"}); assert r.status_code == 400
    r = client.post("/api/auth/password", headers=H(t1), json={"current": STRONG, "new": "password1", "confirm": "password1"}); assert r.status_code == 422
    new = "Monsoon-Lantern-77"
    r = client.post("/api/auth/password", headers=H(t1), json={"current": STRONG, "new": new, "confirm": new}); assert r.status_code == 200
    t2 = r.json()["token"]
    assert client.get("/api/auth/me", headers=H(t1)).status_code == 401
    assert client.get("/api/auth/me", headers=H(t2)).status_code == 200
    assert login(client, "changer", STRONG).status_code == 401
    t3 = login(client, "changer", new).json()["token"]
    assert client.post("/api/auth/logout-all", headers=H(t3)).status_code == 200
    assert client.get("/api/auth/me", headers=H(t3)).status_code == 401


def test_admin_reset_forces_change(client):
    j = signup(client, username="forgetful", email="forgetful@example.org", aicte_id="1-99999004").json()
    a = admin(client)
    r = client.post(f"/api/admin/users/{j['user']['id']}/reset-password", headers=a); assert r.status_code == 200
    tmp = r.json()["temporary_password"]
    assert client.get("/api/auth/me", headers=H(j["token"])).status_code == 401
    lj = login(client, "forgetful", tmp).json(); assert lj["must_change_password"] is True
    assert client.get("/api/applications", headers=H(lj["token"])).status_code == 403
    new = "Teak-Window-Sparrow-5"
    r = client.post("/api/auth/password", headers=H(lj["token"]), json={"current": tmp, "new": new, "confirm": new}); assert r.status_code == 200
    assert client.get("/api/applications", headers=H(r.json()["token"])).status_code == 200
    users = client.get("/api/admin/users", headers=a).json(); assert any(u["username"] == "forgetful" for u in users)
    # non-admins cannot reset
    assert client.post(f"/api/admin/users/{j['user']['id']}/reset-password", headers=H(r.json()["token"])).status_code == 403


def test_setup_only_without_admins_and_env_bootstrap(client, monkeypatch):
    assert client.get("/api/auth/setup").json()["needed"] is False
    r = client.post("/api/auth/setup", json={"full_name": "Eve Intruder", "username": "eve", "email": "eve@example.org", "password": STRONG, "confirm": STRONG})
    assert r.status_code == 409
    from app import accounts
    monkeypatch.setenv("SEALCHECK_BOOTSTRAP_ADMIN_USERNAME", "rootadmin")
    monkeypatch.setenv("SEALCHECK_BOOTSTRAP_ADMIN_PASSWORD", "Granite-Orbit-Falcon-31")
    accounts.bootstrap_from_env()
    r = login(client, "rootadmin", "Granite-Orbit-Falcon-31"); assert r.status_code == 200 and r.json()["user"]["role"] == "admin"
    monkeypatch.setenv("SEALCHECK_BOOTSTRAP_ADMIN_PASSWORD", "Different-Password-99")
    accounts.bootstrap_from_env()   # never overwrites
    assert login(client, "rootadmin", "Granite-Orbit-Falcon-31").status_code == 200


def test_first_run_setup_when_no_admin(client):
    from app.db import SessionLocal, User
    with SessionLocal() as s:
        admins = s.query(User).filter(User.role == "admin").all()
        ids = [u.id for u in admins]
        for u in admins: u.role = "officer"
        s.commit()
    try:
        assert client.get("/api/auth/setup").json()["needed"] is True
        r = client.post("/api/auth/setup", json={"full_name": "First Admin", "username": "firstadmin", "email": "first@example.org", "password": STRONG, "confirm": STRONG})
        assert r.status_code == 200 and r.json()["user"]["role"] == "admin"
        assert client.post("/api/auth/setup", json={"full_name": "Second", "username": "second", "email": "s@example.org", "password": STRONG, "confirm": STRONG}).status_code == 409
    finally:
        with SessionLocal() as s:
            for i in ids: s.get(User, i).role = "admin"
            s.commit()
