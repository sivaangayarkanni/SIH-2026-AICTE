"""Orchestration: write-once storage, job queue + sandboxed worker, 4D collusion, policy decision, persistence."""
import json, os, threading, time, hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from . import audit
from .config import DEMO_PACE_MS, SANITIZED_DIR, JOBS_DIR, BACKEND_DIR, KEYS_DIR, WORKER_CPU_SECONDS
from .db import SessionLocal, Document, DocumentVersion, Job, Evidence, PhotoIndex, PiiVault, Application, College, \
    Notification, DocumentMetadata, now
from .security import issue_job_token, verify_job_token, job_token_key, kms, blind_index, mask_pan, mask_aadhaar, TokenError
from .pipeline import policy, rule_engine
from .rules_bundle import load_rules
from . import agents, sandbox

from .trust import trust_dir as _trust_dir  # noqa: E402
TRUST_DIR = _trust_dir(KEYS_DIR / "trust_roots")
STAGES = ["1 Category & checklist", "2 Secure upload + SHA-256", "3 CDR + sandbox", "4A PDF forensics",
          "4B AICTE rules", "4C Photo inspector", "4D Collusion graph", "5 Policy engine", "6 Evidence packet"]


def store_original(data: bytes, sha: str, ext: str) -> str:
    """Write-once store (STORAGE_BACKEND=fs|s3, see app/storage.py). Returns the local working path."""
    from .storage import get_store
    return get_store().put(data, sha, ext)


def read_original_verified(v: DocumentVersion) -> bytes:
    from .storage import materialize
    data = Path(materialize(v.stored_path)).read_bytes()
    if hashlib.sha256(data).hexdigest() != v.sha256:
        raise RuntimeError("WORM integrity check failed: original file hash changed")
    return data


_limits = sandbox.rlimits  # back-compat alias


def _progress(s, job, stage, status, detail=None):
    prog = list(job.progress_json or [])
    prog = [p for p in prog if p["stage"] != stage]
    prog.append({"stage": stage, "status": status, "at": now().isoformat(), "detail": detail})
    job.progress_json = prog
    job.stage = stage
    s.commit()


def run_job(job_id: int, token_ttl: int | None = None):
    s = SessionLocal()
    try:
        job = s.get(Job, job_id)
        doc = s.get(Document, job.document_id)
        app = doc.application
        college = s.get(College, app.college_id)
        ver = s.query(DocumentVersion).filter_by(document_id=doc.id).order_by(DocumentVersion.version_no.desc()).first()
        read_original_verified(ver)
        job.status, job.started_at, job.attempts = "running", now(), (job.attempts or 0) + 1
        token, claims = issue_job_token(job.id, doc.id, **({"ttl": token_ttl} if token_ttl else {}))
        job.token_jti, job.token_exp = claims["jti"], claims["exp"]
        s.commit()
        audit.log("job.token_issued", target=f"job:{job.id}", details={"jti": claims["jti"], "exp": claims["exp"], "scope": claims["scope"]})
        ext = "pdf" if doc.mime == "application/pdf" else ("jpg" if doc.mime == "image/jpeg" else "png")
        san = SANITIZED_DIR / f"doc{doc.id}_v{ver.version_no}.{ext}"
        cands = [{"document_id": p.document_id, "college_id": p.college_id, "phash": p.phash, "path": p.path}
                 for p in s.query(PhotoIndex).filter(PhotoIndex.college_id != app.college_id).all()]
        from .storage import materialize, save_artifact
        for c in cands:
            materialize(c.get("path"))
        spec = {"token": token, "token_key": job_token_key().hex(), "job_id": job.id, "document_id": doc.id,
                "file_path": ver.stored_path, "sanitized_path": str(JOBS_DIR / f"job{job.id}" / san.name), "mime": doc.mime, "doc_type": doc.doc_type,
                "trust_dir": str(TRUST_DIR), "backend_dir": str(BACKEND_DIR), "candidates": cands,
                "college_coords": [college.lat, college.lon] if college.lat else None}
        jd = JOBS_DIR / f"job{job.id}"
        jd.mkdir(exist_ok=True)
        env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(BACKEND_DIR), "HOME": str(jd), "OMP_NUM_THREADS": "1",
               "OPENBLAS_NUM_THREADS": "1", "LANG": "C.UTF-8", "SEALCHECK_DEMO_PACE_MS": str(DEMO_PACE_MS)}
        env.update({k: os.environ[k] for k in ("SEALCHECK_WORKER_SYSPATH", "SEALCHECK_DATA_DIR") if os.environ.get(k)})
        t0 = time.time()
        _progress(s, job, "3 CDR + sandbox", "running")
        env["SEALCHECK_SANDBOX"] = sandbox.active_backend()
        p = sandbox.popen({"scratch": str(jd), "ro": [ver.stored_path, str(TRUST_DIR)] + [c["path"] for c in cands if c.get("path")],
                           "rw_files": []}, env)
        p.stdin.write(json.dumps(spec)); p.stdin.close()
        results, final, extract, err = {}, None, None, None
        stage_map = {"sandbox": "3 CDR + sandbox", "cdr": "3 CDR + sandbox", "4A": "4A PDF forensics",
                     "4B": "4B AICTE rules", "4C": "4C Photo inspector"}
        for line in p.stdout:
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            st = msg.get("stage")
            if st in ("4A", "4B", "4C") or st == "cdr":
                if msg["status"] != "running":
                    results[st] = msg.get("result")
                _progress(s, job, stage_map[st], msg["status"],
                          {"findings": len(msg.get("findings") or [])} if msg.get("findings") is not None else None)
            elif st == "sandbox":
                results["sandbox"] = msg.get("detail")
            elif st == "4B-bundle":
                results["bundle"] = msg.get("result")
            elif st == "extract":
                extract = msg
            elif st == "final":
                final = msg
            elif st in ("error", "token"):
                err = msg.get("error")
        p.wait(timeout=90)
        if p.returncode != 0 or not final:
            raise RuntimeError(err or (p.stderr.read()[-500:] if p.stderr else f"worker exit {p.returncode}"))
        # API re-verifies the job token on result hand-back: late results (after 60 s) are rejected
        try:
            verify_job_token(token, job.id, doc.id)
        except TokenError as e:
            raise RuntimeError(f"Result rejected: {e} (job exceeded its scoped-token lifetime)")
        if final.get("token_jti") != claims["jti"]:
            raise RuntimeError("Result rejected: token id mismatch")
        findings = final["findings"]
        out_file = jd / san.name  # sandbox wrote into its scratch dir; copy out to the sanitized store
        if out_file.exists():
            import shutil
            shutil.copyfile(out_file, san)
            save_artifact(str(san))
        s.query(DocumentVersion).filter_by(id=ver.id).first()
        # persist sanitized path (immutable row => store as metadata instead)
        s.add(DocumentMetadata(document_id=doc.id, key="sanitized_path", value=str(san)))
        # ---- PII vault (envelope encryption) ----
        pii = (extract or {}).get("pii", {})
        for kind, vals in pii.items():
            for v in vals:
                enc = kms.encrypt(v.encode(), aad=f"{kind}:{college.id}".encode())
                s.add(PiiVault(college_id=college.id, document_id=doc.id, kind=kind, ciphertext=enc["ciphertext"],
                               nonce=enc["nonce"], wrapped_dek=enc["wrapped_dek"], key_id=enc["key_id"],
                               blind_index=blind_index(v), masked=mask_pan(v) if kind == "PAN" else mask_aadhaar(v)))
        s.flush()
        # mask PII in any text we persist
        lines = (extract or {}).get("lines", [])
        for l in lines:
            l["text"] = _mask(l["text"], pii)
        for f in findings:
            f["detail"] = _mask(f.get("detail", ""), pii)
        # ---- 4C (models) · DINOv2 / LightGlue / RT-DETR in the separate vision worker ----
        if (results.get("4C") or {}).get("phash"):
            findings += model_photo_findings(s, results["4C"], str(san), app.college_id)
        # ---- host-side trust: OCSP/CRL + issuer registry connectors (sandbox has no network) ----
        from . import trust
        findings = trust.enrich(findings, (results.get("4A") or {}).get("signatures") or [], (extract or {}).get("facts", {}),
                                ver.sha256, cache_file=KEYS_DIR / "revocation_cache.json")
        # ---- 4D Collusion ----
        _progress(s, job, "4D Collusion graph", "running")
        f4d = collusion_findings(s, doc, college, pii, results.get("4C"), str(san))
        findings += f4d
        _progress(s, job, "4D Collusion graph", "done", {"findings": len(f4d)})
        # ---- 5 Policy ----
        decision = policy.decide(findings)
        _progress(s, job, "5 Policy engine", "done", {"status": decision["status"], "rule": decision["policy_rule"]})
        rules = load_rules()
        label = rules["document_types"].get(doc.doc_type, {}).get("label", doc.doc_type)
        transcript = agents.explain(label, findings, decision)
        doc.status, doc.risk_score = decision["status"], decision["risk_score"]
        doc.analysis_json = {"label": label, "findings": findings, "decision": decision, "agents": transcript,
                             "modules": results, "lines": lines, "pages": (extract or {}).get("pages", []),
                             "facts": (extract or {}).get("facts", {}), "sanitized_path": str(san),
                             "pii_masked": [mask_pan(v) for v in pii.get("PAN", [])] + [mask_aadhaar(v) for v in pii.get("AADHAAR", [])]}
        s.query(Evidence).filter_by(document_id=doc.id).delete()
        for f in findings:
            s.add(Evidence(document_id=doc.id, module=f.get("module"), rule_id=f.get("rule_id"), clause=f.get("clause"),
                           severity=f.get("severity"), outcome=f.get("outcome"), title=f.get("title"),
                           detail=f.get("detail"), page=f.get("page"), bbox_json=f.get("bbox")))
        _progress(s, job, "6 Evidence packet", "done", {"evidence_items": len(findings)})
        job.status, job.finished_at = "done", now()
        job.duration_ms = int((time.time() - t0) * 1000)
        s.commit()
        refresh_application(s, app.id)
        audit.log("document.analyzed", target=f"document:{doc.id}",
                  details={"status": decision["status"], "rule": decision["policy_rule"], "risk": decision["risk_score"],
                           "sha256": doc.sha256, "duration_ms": job.duration_ms})
        if decision["status"] != "Verified":
            s.add(Notification(role="officer", message=f"{app.college.name}: {label} → {decision['status']}",
                               link=f"/applications/{app.id}"))
            s.add(Notification(college_id=app.college_id, message=f"{label}: {decision['status']}", link=f"/applications/{app.id}"))
            s.commit()
    except Exception as e:
        s.rollback()
        job = s.get(Job, job_id)
        job.status, job.error, job.finished_at = "failed", str(e)[:1000], now()
        doc = s.get(Document, job.document_id)
        doc.status = "Manual Review Required"
        doc.analysis_json = {"error": str(e)[:1000], "findings": [], "decision": {"status": "Manual Review Required",
                             "policy_rule": "P4", "policy_text": "Analysis failed safely; human review needed", "risk_score": 50}}
        s.commit()
        refresh_application(s, doc.application_id)
        audit.log("document.analysis_failed", target=f"document:{doc.id}", details={"error": str(e)[:300]})
    finally:
        s.close()


def _mask(text, pii):
    for v in pii.get("PAN", []):
        text = text.replace(v, mask_pan(v))
    for v in pii.get("AADHAAR", []):
        text = text.replace(v, mask_aadhaar(v))
    return text


def model_photo_findings(s, photo_res, san_path, college_id):
    from .vision import client as vc
    from .db import similar_photos
    if vc.BACKEND not in ("models", "remote"):
        photo_res["vision_backend"] = "classic"
        return []
    def cands(emb):
        return [{"document_id": p.document_id, "college_id": p.college_id, "path": p.path, "similarity": sim,
                 "layout_hash": p.layout_hash} for p, sim in similar_photos(s, emb, college_id, limit=10)]
    try:
        r = vc.analyze_with_models(san_path, cands)
    except Exception as e:  # noqa: BLE001 - fall back to classic, say so
        photo_res["vision_backend"] = f"classic ({vc.BACKEND} failed)"
        photo_res["vision_error"] = str(e)[:300]
        return [{"module": "4C", "rule_id": "I-VIS-00", "clause": "Ops · Vision backend", "outcome": "warn", "severity": "low",
                 "title": "Model vision unavailable — classic matcher used",
                 "detail": f"VISION_BACKEND={vc.BACKEND} failed ({type(e).__name__}); pHash+ORB results shown instead."}]
    photo_res["vision_backend"] = vc.BACKEND
    photo_res["models"] = r
    out = []
    for m in r["matches"]:
        if m.get("error"):
            continue
        if vc.is_duplicate(m):
            out.append({"module": "4C", "rule_id": "I-DUP-02", "clause": "Forensics · Photo reuse (learned)", "outcome": "fail",
                        "severity": "critical", "forgery": True, "title": "Same scene as another college's lab photo",
                        "detail": f"Matches document #{m['document_id']} of college #{m['college_id']}: DINOv2 cosine "
                                  f"{m['cosine']:.3f}, {m['local']['inliers']} DISK+LightGlue geometric inliers.",
                        "match": m})
        elif m["cosine"] >= vc.SUSPECT_COSINE:
            out.append({"module": "4C", "rule_id": "I-SIM-01", "clause": "Forensics · Photo similarity", "outcome": "warn",
                        "severity": "medium", "manual_review": True, "title": "Visually similar to another college's photo",
                        "detail": f"DINOv2 cosine {m['cosine']:.3f} to document #{m['document_id']} but only "
                                  f"{m['local']['inliers']} geometric inliers; review manually.", "match": m})
    labels = sorted({d["label"] for d in r["detections"]})
    out.append({"module": "4C", "rule_id": "I-OBJ-01", "clause": "APH · Laboratory infrastructure", "outcome": "pass" if labels else "warn",
                "severity": "info" if labels else "low", "manual_review": not labels,
                "title": f"{len(r['detections'])} objects detected (COCO classes)" if labels else "No objects detected",
                "detail": ("RT-DETR (COCO-80) saw: " + ", ".join(labels) + ". COCO has no lab-specific classes; "
                           "presence of e.g. 'tv'/'keyboard' only suggests a computer lab.") if labels else
                          "RT-DETR found no COCO objects above threshold."})
    return out


def collusion_findings(s, doc, college, pii, photo_res, san_path=None):
    out = []
    # (a) same original file submitted by a different college
    dup = (s.query(Document).join(Application).filter(Document.sha256 == doc.sha256, Document.id != doc.id,
                                                       Application.college_id != college.id).first())
    if dup:
        out.append({"module": "4D", "rule_id": "C-HASH-01", "clause": "Collusion · Repeated evidence", "outcome": "fail",
                    "severity": "high", "manual_review": True, "title": "Identical file submitted by another college",
                    "detail": f"SHA-256 matches document #{dup.id} of {dup.application.college.name}."})
    # (b) faculty PAN shared across colleges (blind-index match; no decryption needed)
    for v in pii.get("PAN", []):
        bi = blind_index(v)
        other = s.query(PiiVault).filter(PiiVault.blind_index == bi, PiiVault.college_id != college.id).first()
        if other:
            oc = s.get(College, other.college_id)
            out.append({"module": "4D", "rule_id": "C-PAN-01", "clause": "APH · Faculty may serve one institution",
                        "outcome": "fail", "severity": "high", "manual_review": True,
                        "title": "Faculty PAN also listed by another college",
                        "detail": f"PAN {mask_pan(v)} also appears in faculty records of {oc.name}."})
    # (c) photo reuse -> index + graph
    if photo_res and photo_res.get("phash"):
        exif = photo_res.get("exif") or {}
        mres = photo_res.get("models") or {}
        s.add(PhotoIndex(document_id=doc.id, college_id=college.id, phash=photo_res["phash"],
                         path=san_path, embedding=mres.get("embedding"), layout_hash=mres.get("layout_hash"),
                         lat=(exif.get("gps") or {}).get("lat"), lon=(exif.get("gps") or {}).get("lon"), lab_type=doc.lab_type))
        s.flush()
        for m in photo_res.get("matches", []) + [m for m in mres.get("matches", []) if _vis_dup(m)]:
            if m.get("duplicate", True):
                oc = s.get(College, m["college_id"])
                out.append({"module": "4D", "rule_id": "C-IMG-01", "clause": "Collusion · Cross-college photo match",
                            "outcome": "fail", "severity": "high", "forgery": True,
                            "title": f"Photo link to {oc.name}", "detail": "Added to the collusion graph as a shared-evidence edge."})
    return out


def _vis_dup(m):
    from .vision import client as vc
    return not m.get("error") and vc.is_duplicate(m)


def fix_photo_paths(s):
    for p in s.query(PhotoIndex).filter(PhotoIndex.path.is_(None)).all():
        d = s.get(Document, p.document_id)
        if d and d.analysis_json:
            p.path = d.analysis_json.get("sanitized_path")
    s.commit()


def refresh_application(s, app_id):
    app = s.get(Application, app_id)
    rules = load_rules()
    present = [d.doc_type for d in app.documents]
    comp = rule_engine.completeness(app.category, present, rules)
    statuses = [d.status for d in app.documents]
    if app.decision is None:
        app.status = policy.aggregate(statuses, comp["complete"])
    app.risk_score = min(100, max([d.risk_score or 0 for d in app.documents] + [0]) + 5 * len(comp["missing"]))
    s.commit()


# ---------------- queue runner ----------------
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="sealcheck-job")
_inflight = set()
_lock = threading.Lock()


def enqueue(document_id: int) -> int:
    s = SessionLocal()
    try:
        j = Job(document_id=document_id, status="queued", progress_json=[
            {"stage": "1 Category & checklist", "status": "done", "at": now().isoformat()},
            {"stage": "2 Secure upload + SHA-256", "status": "done", "at": now().isoformat()}])
        s.add(j); s.commit()
        jid = j.id
    finally:
        s.close()
    _submit(jid)
    return jid


QUEUE_BACKEND = os.environ.get("QUEUE_BACKEND", "thread")  # thread (dev) | rq (Redis) | db (separate worker polls jobs table) | inline (serverless demo)


def run_job_task(jid: int):
    """Entry point used by the RQ / DB queue workers (app/queue_worker.py)."""
    run_job(jid)
    s = SessionLocal(); fix_photo_paths(s); s.close()


def _submit(jid):
    if QUEUE_BACKEND == "rq":
        from .queue_worker import rq_queue
        rq_queue().enqueue("app.service.run_job_task", jid, job_id=f"sealcheck-job-{jid}", job_timeout=WORKER_CPU_SECONDS * 4)
        return
    if QUEUE_BACKEND == "db":
        return  # queue_worker --db claims queued rows itself
    if QUEUE_BACKEND == "inline":  # serverless demo (Vercel): finish the job inside the request, no background threads
        run_job_task(jid)
        return
    with _lock:
        if jid in _inflight:
            return
        _inflight.add(jid)

    def run():
        try:
            run_job(jid)
            s = SessionLocal(); fix_photo_paths(s); s.close()
        finally:
            with _lock:
                _inflight.discard(jid)
    _pool.submit(run)


def resume_queued():
    s = SessionLocal()
    for j in s.query(Job).filter(Job.status.in_(["queued", "running"])).all():
        j.status = "queued"
        s.commit()
        _submit(j.id)
    s.close()
