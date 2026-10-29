"""SealCheck administrator CLI (talks to the database in DATABASE_URL directly; run it from a trusted machine).

  python scripts/admin.py create-user  --email E --role college|officer|senior_officer|admin [--name N] [--college-code C --college-name N --state S]
  python scripts/admin.py issue-token  --email E [--ttl-min 30]      # needs the same SEALCHECK_JWT_SECRET as the server
  python scripts/admin.py set-role     --email E --role R
  python scripts/admin.py list-users
  python scripts/admin.py delete-user  --email E [--purge-college]   # --purge-college also removes that college's applications

Every change is written to the hash-chained audit log. WORM blobs and audit entries are never deleted (by design)."""
import argparse, os, secrets, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("SEALCHECK_DATA_DIR", "/tmp/sealcheck-admin-cli")
if not os.environ.get("DATABASE_URL") and os.environ.get("POSTGRES_URL"):
    os.environ["DATABASE_URL"] = os.environ["POSTGRES_URL"]

from sqlalchemy import delete, select  # noqa: E402
from app.db import SessionLocal, User, College, UserProfile, Application, Base, init_db, now  # noqa: E402
from app import audit  # noqa: E402
from app.security import hash_password  # noqa: E402

ACTOR = f"admin-cli ({os.environ.get('USER', 'operator')})"


def create_user(a):
    with SessionLocal() as s:
        if s.query(User).filter(User.email == a.email.lower()).first():
            sys.exit(f"user {a.email} already exists")
        cid = None
        if a.role == "college":
            if not a.college_code:
                sys.exit("--college-code is required for role college")
            c = s.query(College).filter(College.code == a.college_code.upper()).first()
            if not c:
                c = College(code=a.college_code.upper(), name=a.college_name or a.college_code, state=a.state); s.add(c); s.flush()
            cid = c.id
        u = User(email=a.email.lower(), name=a.name or a.email.split("@")[0], title=a.title or "", role=a.role, college_id=cid,
                 password_hash=hash_password(secrets.token_urlsafe(32)), avatar_seed=a.email.split("@")[0])
        s.add(u); s.flush()
        s.add(UserProfile(user_id=u.id, full_name=u.name, requested_role=("college" if a.role == "college" else "officer"),
                          official_email=u.email, status="approved", decided_by=ACTOR, decided_at=now()))
        s.commit(); uid = u.id
    audit.log("access.cli_create_user", ACTOR, "admin", f"user:{uid}", {"email": a.email, "role": a.role})
    print(f"created user {uid} {a.email} role={a.role}")


def issue_token(a):
    import jwt
    from app.security import _jwt_key
    with SessionLocal() as s:
        u = s.query(User).filter(User.email == a.email.lower()).first()
        if not u:
            sys.exit("no such user")
        t = int(time.time())
        tok = jwt.encode({"sub": str(u.id), "role": u.role, "cid": u.college_id, "iat": t, "exp": t + a.ttl_min * 60}, _jwt_key(), "HS256")
    audit.log("access.cli_issue_token", ACTOR, "admin", f"user:{u.id}", {"ttl_min": a.ttl_min})
    print(tok)


def set_role(a):
    with SessionLocal() as s:
        u = s.query(User).filter(User.email == a.email.lower()).first()
        if not u:
            sys.exit("no such user")
        old, u.role = u.role, a.role
        p = s.get(UserProfile, u.id)
        if p:
            p.status, p.decided_by, p.decided_at = "approved", ACTOR, now()
        s.commit()
    audit.log("access.cli_set_role", ACTOR, "admin", f"user:{u.id}", {"from": old, "to": a.role})
    print(f"{a.email}: {old} -> {a.role}")


def list_users(a):
    with SessionLocal() as s:
        for u in s.query(User).order_by(User.id):
            p = s.get(UserProfile, u.id)
            print(f"{u.id:5} {u.email:40} {u.role:15} {(u.college.code if u.college else ''):15} {p.status if p else ''}")


def _purge_college(s, cid):
    app_ids = [x for (x,) in s.execute(select(Application.id).where(Application.college_id == cid))]
    from app.db import Document
    doc_ids = [x for (x,) in s.execute(select(Document.id).where(Document.application_id.in_(app_ids)))] if app_ids else []
    n = 0
    for t in reversed(Base.metadata.sorted_tables):
        if t.name in ("audit_log", "blobs", "documents", "applications", "users", "colleges", "user_profiles"):
            continue
        for col, ids in (("document_id", doc_ids), ("application_id", app_ids), ("college_id", [cid])):
            if col in t.c and ids:
                n += s.execute(delete(t).where(t.c[col].in_(ids))).rowcount or 0
    if doc_ids:
        n += s.execute(delete(Document.__table__).where(Document.id.in_(doc_ids))).rowcount
    if app_ids:
        n += s.execute(delete(Application.__table__).where(Application.id.in_(app_ids))).rowcount
    return n, len(app_ids), len(doc_ids)


def delete_user(a):
    with SessionLocal() as s:
        u = s.query(User).filter(User.email == a.email.lower()).first()
        if not u:
            sys.exit("no such user")
        uid, cid, info = u.id, u.college_id, {}
        if a.purge_college and cid:
            others = s.query(User).filter(User.college_id == cid, User.id != uid).count()
            if others:
                sys.exit(f"refusing to purge: {others} other user(s) belong to this college")
            info["rows"], info["applications"], info["documents"] = _purge_college(s, cid)
        for t in Base.metadata.sorted_tables:   # null out soft references (decision_by, requested_by, ...)
            for c in t.c:
                if t.name not in ("audit_log", "blobs", "user_profiles") and any(fk.column.table.name == "users" for fk in c.foreign_keys):
                    s.execute(t.update().where(c == uid).values({c.name: None})) if c.nullable else s.execute(delete(t).where(c == uid))
        s.execute(delete(UserProfile.__table__).where(UserProfile.user_id == uid))
        s.execute(delete(User.__table__).where(User.id == uid))
        if a.purge_college and cid:
            s.execute(delete(College.__table__).where(College.id == cid)); info["college_deleted"] = True
        s.commit()
    audit.log("access.cli_delete_user", ACTOR, "admin", f"user:{uid}", {"email": a.email, **info})
    print(f"deleted user {uid} {a.email} {info}")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="cmd", required=True)
    c = sp.add_parser("create-user"); c.add_argument("--email", required=True)
    c.add_argument("--role", required=True, choices=["college", "officer", "senior_officer", "admin"])
    for k in ("--name", "--title", "--college-code", "--college-name", "--state"):
        c.add_argument(k)
    t = sp.add_parser("issue-token"); t.add_argument("--email", required=True); t.add_argument("--ttl-min", type=int, default=30)
    r = sp.add_parser("set-role"); r.add_argument("--email", required=True)
    r.add_argument("--role", required=True, choices=["pending", "college", "officer", "senior_officer", "admin"])
    sp.add_parser("list-users")
    d = sp.add_parser("delete-user"); d.add_argument("--email", required=True); d.add_argument("--purge-college", action="store_true")
    a = p.parse_args(argv)
    init_db()
    {"create-user": create_user, "issue-token": issue_token, "set-role": set_role, "list-users": list_users, "delete-user": delete_user}[a.cmd](a)


if __name__ == "__main__":
    main()
