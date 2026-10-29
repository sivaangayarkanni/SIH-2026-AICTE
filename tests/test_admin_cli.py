import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


def test_admin_cli_roundtrip(capsys):
    import admin
    from app.db import SessionLocal, User, College, Application
    admin.main(["create-user", "--email", "Temp.Tester@example.org", "--role", "college", "--college-code", "TMP-CLI-1",
                "--college-name", "Temp CLI College", "--state", "Kerala"])
    admin.main(["issue-token", "--email", "temp.tester@example.org", "--ttl-min", "5"])
    tok = capsys.readouterr().out.strip().splitlines()[-1]
    from app.security import decode_jwt
    assert decode_jwt(tok)["role"] == "college"
    with SessionLocal() as s:
        c = s.query(College).filter_by(code="TMP-CLI-1").one()
        s.add(Application(college_id=c.id, **_app_kwargs())); s.commit()
    admin.main(["delete-user", "--email", "temp.tester@example.org", "--purge-college"])
    with SessionLocal() as s:
        assert not s.query(User).filter_by(email="temp.tester@example.org").first()
        assert not s.query(College).filter_by(code="TMP-CLI-1").first()


def _app_kwargs():
    from app.db import Application
    req = {c.name for c in Application.__table__.c if not c.nullable and c.default is None and not c.primary_key and c.name != "college_id"}
    vals = {"ref": "TMP-CLI-APP-1", "programme": "B.Tech", "category": "new_institution", "status": "draft", "title": "x", "approval_type": "new_institution"}
    return {k: vals.get(k, "x") for k in req}
