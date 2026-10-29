"""Seeds the database with SYNTHETIC colleges, demo users (one per role), and demo applications whose
documents are run through the real pipeline (gateway -> WORM store -> sandboxed worker -> policy engine)."""
import json, os, sys
from datetime import timedelta
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
from app.config import SAMPLES_DIR, DATA_DIR  # noqa
from app.rules_bundle import sign_bundle, verify_bundle  # noqa
from app.db import init_db, reset_db, IS_PG, SessionLocal, College, User, Application, Document, DocumentVersion, Notification, now  # noqa
from app.security import hash_password  # noqa
from app.pipeline import gateway  # noqa
from app import service, audit  # noqa

PASSWORD = "Demo@2026"
COLLEGES = [
    ("SVIT", "Sri Venkateswara Institute of Technology", "Chennai", "Tamil Nadu", 12.9010, 80.2279, "Private Self-Financing"),
    ("GVCE", "Ganga Valley College of Engineering", "Varanasi", "Uttar Pradesh", 25.3790, 83.0220, "Private Self-Financing"),
    ("DIEM", "Deccan Institute of Engineering & Management", "Hyderabad", "Telangana", 17.4401, 78.3489, "Private Self-Financing"),
    ("MCT", "Malabar College of Technology", "Kochi", "Kerala", 10.0159, 76.3419, "Government-Aided"),
]
USERS = [
    ("principal.svit@sealcheck.demo", "Dr. Kavitha Raman", "Principal, SVIT", "college", "SVIT", "kavitha"),
    ("principal.gvce@sealcheck.demo", "Dr. Arjun Mishra", "Principal, GVCE", "college", "GVCE", "arjun"),
    ("principal.diem@sealcheck.demo", "Dr. Farah Siddiqui", "Principal, DIEM", "college", "DIEM", "farah"),
    ("principal.mct@sealcheck.demo", "Dr. Thomas Kurian", "Principal, MCT", "college", "MCT", "thomas"),
    ("officer@sealcheck.demo", "Priya Nair", "Scrutiny Officer, AICTE (South)", "officer", None, "priya"),
    ("officer2@sealcheck.demo", "Rahul Verma", "Scrutiny Officer, AICTE (North)", "officer", None, "rahul"),
    ("senior@sealcheck.demo", "Dr. Meera Iyer", "Senior Officer, Approval Bureau", "senior_officer", None, "meera"),
    ("admin@sealcheck.demo", "Vikram Singh", "Platform Administrator", "admin", None, "vikram"),
]
APPS = [  # (college, category, docs from manifest, submitted)
    ("SVIT", "extension_of_approval", ["svit_application_form.pdf", "svit_land_lease.pdf", "svit_fire_noc.pdf", "svit_faculty_details.pdf",
                                       "svit_lab_cse.jpg", "svit_bank_fdr.pdf", "svit_affidavit.pdf"], 40),
    ("GVCE", "extension_of_approval", ["gvce_land_lease_forged.pdf", "gvce_fire_noc_tampered.pdf", "gvce_faculty_details.pdf", "gvce_lab_ece.jpg"], 30),
    ("DIEM", "increase_intake", ["diem_building_completion_expired_dsc.pdf", "diem_fire_noc_expired.pdf", "diem_lab_reused.jpg"], 64),
    ("MCT", "new_course", ["mct_affiliation_with_javascript.pdf", "mct_fire_noc_unknown_issuer.pdf"], 8),
]


def main():
    from app.config import IS_PROD
    if IS_PROD and os.getenv("SEALCHECK_ALLOW_SEED") != "1":
        sys.exit("Refusing to seed demo data in ENV=production (set SEALCHECK_ALLOW_SEED=1 to override deliberately).")
    if (DATA_DIR / "sealcheck.db").exists() and "--force" not in sys.argv and not IS_PG:
        print("Database already exists (use --force to reset)."); return
    if "--force" in sys.argv:
        import shutil
        for sub in ("sealcheck.db", "sealcheck.db-wal", "sealcheck.db-shm"):
            p = DATA_DIR / sub
            if p.exists(): p.unlink()
        reset_db()
        for d in ("originals", "sanitized", "evidence", "jobs"):
            p = DATA_DIR / d
            if p.exists():
                for f in p.rglob("*"):
                    if f.is_file(): os.chmod(f, 0o644)
                shutil.rmtree(p)
            p.mkdir()
    if not verify_bundle()["valid"]:
        sign_bundle()
    assert verify_bundle()["valid"], "rule bundle signature invalid"
    init_db()
    s = SessionLocal()
    cmap = {}
    for code, name, city, state, lat, lon, typ in COLLEGES:
        c = College(code=code, name=name, city=city, state=state, lat=lat, lon=lon, institution_type=typ)
        s.add(c); s.flush(); cmap[code] = c
    for email, name, title, role, cc, seed in USERS:
        s.add(User(email=email, name=name, title=title, role=role, college_id=cmap[cc].id if cc else None,
                   password_hash=hash_password(PASSWORD), avatar_seed=seed))
    s.commit()
    audit.log("system.seeded", details={"colleges": len(COLLEGES), "users": len(USERS), "synthetic": True})
    man = {m["file"]: m for m in json.loads((SAMPLES_DIR / "manifest.json").read_text())}
    for i, (cc, cat, files, hours_ago) in enumerate(APPS, 1):
        a = Application(ref=f"AICTE-26-{cc}-{i:04d}", college_id=cmap[cc].id, category=cat, status="Verification Pending",
                        deadline=now() + timedelta(days=[12, 5, 2, 18][i - 1]), submitted_at=now() - timedelta(hours=hours_ago))
        from app.rules_bundle import load_rules
        a.title = next(c["label"] for c in load_rules()["categories"] if c["id"] == cat)
        s.add(a); s.commit()
        audit.log("application.created", f"seed:{cc}", "college", f"application:{a.id}", {"category": cat})
        for fn in files:
            data = (SAMPLES_DIR / fn).read_bytes()
            g = gateway.inspect_upload(data, fn)
            ext = fn.rsplit(".", 1)[-1]
            path = service.store_original(data, g["sha256"], ext)
            d = Document(application_id=a.id, doc_type=man[fn]["doc_type"], filename=fn, mime=g["mime"], size=g["size"],
                         sha256=g["sha256"], lab_type="CCE" if "cse" in fn or "reused" in fn else ("ECE" if "ece" in fn else None))
            s.add(d); s.flush()
            s.add(DocumentVersion(document_id=d.id, version_no=1, sha256=g["sha256"], stored_path=path, size=g["size"]))
            s.commit()
            audit.log("document.uploaded", f"seed:{cc}", "college", f"document:{d.id}", {"sha256": g["sha256"]})
            from app.db import Job
            j = Job(document_id=d.id, status="queued", progress_json=[
                {"stage": "1 Category & checklist", "status": "done", "at": now().isoformat()},
                {"stage": "2 Secure upload + SHA-256", "status": "done", "at": now().isoformat()}])
            s.add(j); s.commit()
            service.run_job(j.id)
            s.expire_all()
            d = s.get(Document, d.id)
            mark = "OK " if d.status == man[fn]["expected_status"] else "!! "
            print(f"{mark}{fn:45s} -> {d.status:24s} (expected {man[fn]['expected_status']})")
    # one draft application for the SVIT demo user to complete live
    s.add(Application(ref="AICTE-26-SVIT-0005", college_id=cmap["SVIT"].id, category="new_course",
                      title="Introduction of New Course / Programme", status="Draft", deadline=now() + timedelta(days=25)))
    s.commit()
    print("Audit chain:", audit.verify_chain())


if __name__ == "__main__":
    main()
