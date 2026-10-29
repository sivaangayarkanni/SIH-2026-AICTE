"""Isolated analysis worker (sandbox). Spawned as a separate OS process by the API with:
  * stripped environment (no proxies / credentials), its own working dir, CPU-time + memory rlimits,
  * a Python-level network egress guard (socket connect is disabled before any analysis code runs),
  * a 60-second HMAC-signed, job-scoped token which it must verify before touching the file.
It never touches the database: it reads a read-only file and streams JSON-lines results on stdout.
Production: run in gVisor/Firecracker with a no-egress network namespace (see docs/SECURITY.md)."""
import socket


def _no_egress(*a, **k):
    raise PermissionError("Network egress is disabled inside the analysis sandbox")


socket.socket.connect = _no_egress            # noqa: E305  egress guard installed first
socket.socket.connect_ex = _no_egress
socket.create_connection = _no_egress

import json, os, sys, time, traceback  # noqa: E402
from pathlib import Path  # noqa: E402


PACE = int(os.environ.get("SEALCHECK_DEMO_PACE_MS", "0") or 0) / 1000


def emit(**kw):
    sys.stdout.write(json.dumps(kw, default=str) + "\n")
    sys.stdout.flush()
    if PACE and kw.get("status") == "running":
        time.sleep(PACE)


def pdf_findings(f: dict) -> list[dict]:
    out = []
    for h in f["hidden_text"]:
        out.append({"module": "4A", "rule_id": "F-HID-01", "clause": "Forensics · Hidden text", "outcome": "fail",
                    "severity": "critical", "forgery": True, "title": f"Hidden text detected ({h['reason']})",
                    "detail": f"Invisible to a human reader but machine-readable: “{h['text'][:140]}”",
                    "page": h["page"], "bbox": h["bbox"]})
    for o in f["overlays"]:
        out.append({"module": "4A", "rule_id": "F-OVL-01", "clause": "Forensics · Overlay / white-box masking",
                    "outcome": "fail", "severity": "critical", "forgery": True,
                    "title": "White box drawn over existing text",
                    "detail": "A filled white rectangle hides underlying text: " + "; ".join(f"“{c[:60]}”" for c in o["covers"]),
                    "page": o["page"], "bbox": o["bbox"]})
    sigs = [s for s in f["signatures"] if "error" not in s or s.get("field")]
    eh = f["edit_history"]
    if not sigs:
        out.append({"module": "4A", "rule_id": "F-DSC-00", "clause": "APH · DSC-signed uploads", "outcome": "warn",
                    "severity": "low", "title": "No digital signature (DSC) found",
                    "detail": "The PDF carries no embedded digital signature; authenticity relies on issuer verification."})
    for s in sigs:
        if s.get("error") and not s.get("signer"):
            out.append({"module": "4A", "rule_id": "F-DSC-01", "clause": "Forensics · DSC / ByteRange", "outcome": "fail",
                        "severity": "high", "manual_review": True, "title": "Signature could not be validated",
                        "detail": s["error"]})
            continue
        if not s.get("intact"):
            out.append({"module": "4A", "rule_id": "F-DSC-01", "clause": "Forensics · DSC / ByteRange", "outcome": "fail",
                        "severity": "critical", "forgery": True, "title": "Signed bytes were altered",
                        "detail": f"The /ByteRange digest of the signature by {s.get('signer')} no longer matches the file."})
        elif not s.get("covers_whole_file"):
            out.append({"module": "4A", "rule_id": "F-DSC-02", "clause": "Forensics · Post-signing modification",
                        "outcome": "fail", "severity": "critical", "forgery": True,
                        "title": "Content added after the document was signed",
                        "detail": f"Signature by {s.get('signer')} covers only part of the file (coverage {s.get('coverage')}, "
                                  f"modification level {s.get('modification_level')}). {eh['incremental_updates']} incremental "
                                  "update(s) were appended after signing."})
        else:
            out.append({"module": "4A", "rule_id": "F-DSC-02", "clause": "Forensics · DSC / ByteRange", "outcome": "pass",
                        "severity": "info", "title": "Digital signature intact and covers the whole file",
                        "detail": f"Signed by {s.get('signer')}; trusted chain: {'yes' if s.get('trusted') else 'no'}."})
        if s.get("signer") and s.get("cert_expired"):
            out.append({"module": "4A", "rule_id": "F-DSC-03", "clause": "Forensics · Certificate validity",
                        "outcome": "fail", "severity": "high", "expired": True, "title": "Signing certificate has expired",
                        "detail": f"Certificate of {s.get('signer')} was valid only until {s.get('not_after')}."})
        elif s.get("signer") and not s.get("trusted"):
            out.append({"module": "4A", "rule_id": "F-DSC-04", "clause": "Forensics · Certificate trust",
                        "outcome": "warn", "severity": "medium", "manual_review": True,
                        "title": "Signer certificate is not from a trusted CA",
                        "detail": f"Issuer “{s.get('issuer')}” is not in the trust store."})
    if eh["edited_after_creation"] and not sigs:
        out.append({"module": "4A", "rule_id": "F-EDT-01", "clause": "Forensics · Edit history", "outcome": "warn",
                    "severity": "medium", "manual_review": True, "title": "Document was edited after creation",
                    "detail": f"{eh['incremental_updates']} incremental update(s) (%%EOF={eh['eof_markers']}, /Prev={eh['prev_pointers']})."})
    mc = f["metadata_check"]
    if mc.get("editing_tool"):
        out.append({"module": "4A", "rule_id": "F-MET-01", "clause": "Forensics · Metadata cross-check", "outcome": "warn",
                    "severity": "medium", "manual_review": True, "title": "Produced by a PDF editing tool",
                    "detail": f"Producer/Creator metadata names “{mc['editing_tool']}”, unusual for an issuing authority."})
    return out


def rule_findings(r: dict) -> list[dict]:
    return [{**x, "module": "4B"} for x in r["findings"]]


def photo_findings(p: dict, expected_coords) -> list[dict]:
    out = []
    ex = p["exif"]
    if not ex.get("gps"):
        out.append({"module": "4C", "rule_id": "I-GEO-01", "clause": "APH · Geotagged lab photos", "outcome": "warn",
                    "severity": "medium", "manual_review": True, "title": "Photo has no geotag",
                    "detail": "EXIF GPS coordinates are missing; location of the lab cannot be confirmed."})
    elif expected_coords:
        from app.pipeline.photo import haversine_km
        d = haversine_km((ex["gps"]["lat"], ex["gps"]["lon"]), expected_coords)
        ok = d <= 5
        out.append({"module": "4C", "rule_id": "I-GEO-02", "clause": "APH · Geotagged lab photos",
                    "outcome": "pass" if ok else "fail", "severity": "info" if ok else "high",
                    "manual_review": not ok,
                    "title": "Geotag matches campus" if ok else "Geotag far from registered campus",
                    "detail": f"Photo taken {d:.1f} km from the college's registered location."})
    for m in p["matches"]:
        if m["duplicate"]:
            out.append({"module": "4C", "rule_id": "I-DUP-01", "clause": "Forensics · Photo reuse", "outcome": "fail",
                        "severity": "critical", "forgery": True, "title": "Same lab photo already submitted by another college",
                        "detail": f"Matches document #{m['document_id']} of college #{m['college_id']} "
                                  f"(perceptual-hash distance {m['phash_distance']}/64, {m['orb']['inliers']} ORB geometric inliers).",
                        "match": m})
    rc = p["room"]
    out.append({"module": "4C", "rule_id": "I-ROOM-01", "clause": "APH · Laboratory infrastructure",
                "outcome": "pass" if rc["indoor_structure_likely"] else "warn",
                "severity": "info" if rc["indoor_structure_likely"] else "low",
                "title": "Room structure cues found" if rc["indoor_structure_likely"] else "Weak room-structure cues",
                "detail": f"{rc['straight_lines']} straight-line features ({rc['horizontal']} horizontal, {rc['vertical']} vertical) "
                          "suggest walls, benches and fixtures."})
    if ex.get("software") and any(t in ex["software"].lower() for t in ("photoshop", "gimp", "snapseed", "canva")):
        out.append({"module": "4C", "rule_id": "I-EXF-01", "clause": "Forensics · Image metadata", "outcome": "warn",
                    "severity": "medium", "manual_review": True, "title": "Edited in image software",
                    "detail": f"EXIF Software tag: {ex['software']}"})
    return out


def selftest(spec):
    """Probe the sandbox from the inside (used by tests). Every probe must FAIL for the sandbox to be OK."""
    import _socket
    res = {}
    def probe(name, fn):
        try:
            fn(); res[name] = "ALLOWED"
        except Exception as e:  # noqa: BLE001
            res[name] = f"blocked: {type(e).__name__}: {e}"[:160]
    probe("socket_inet_raw", lambda: _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM).connect(("1.1.1.1", 80)))
    probe("socket_inet_guarded", lambda: socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("1.1.1.1", 80)))
    probe("socket_inet_create", lambda: _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM))
    probe("socket_inet6_create", lambda: _socket.socket(_socket.AF_INET6, _socket.SOCK_STREAM))
    for t in spec.get("unix_targets", []):  # AF_UNIX is allowed (asyncio needs it) but host sockets must be unreachable
        probe(f"unix_connect:{t}", lambda t=t: _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM).connect(t))
    for _i, t in enumerate(spec.get("write_targets", [])):
        probe(f"write_outside:{t}", lambda t=t: Path(t).write_text("escape"))
    for t in spec.get("read_targets", []):
        probe(f"read_secret:{t}", lambda t=t: Path(t).read_bytes())
    probe("write_scratch", lambda: Path(os.getcwd(), "scratch.txt").write_text("ok"))
    res["write_scratch_ok"] = res.pop("write_scratch") == "ALLOWED"
    return res


def main():
    spec = json.loads(sys.stdin.read())
    sys.path[0] = spec["backend_dir"]  # replace script dir so app modules cannot shadow stdlib
    from app.security import verify_job_token, TokenError
    t0 = time.time()
    try:
        claims = verify_job_token(spec["token"], spec["job_id"], spec["document_id"], key=bytes.fromhex(spec["token_key"]))
    except TokenError as e:
        emit(stage="token", status="rejected", error=str(e))
        sys.exit(3)
    sb = os.environ.get("SEALCHECK_SANDBOX", "process")
    emit(stage="sandbox", status="done", detail={"token_jti": claims["jti"], "token_expires_in_s": claims["exp"] - int(time.time()),
                                                 "backend": sb, "pid": os.getpid(),
                                                 "egress": "no network namespace + seccomp socket() deny" if sb == "namespace" else
                                                           ("--network none" if sb == "docker" else "Python socket guard only"),
                                                 "pid_isolated": sb != "process"})
    if spec.get("selftest"):
        emit(stage="final", status="done", selftest=selftest(spec), findings=[], token_jti=claims["jti"])
        return
    try:
        from app.pipeline.cdr import disarm_pdf, disarm_image
        from app.rules_bundle import load_rules
        from app.pipeline import rule_engine
        src, dst = spec["file_path"], spec["sanitized_path"]
        is_pdf = spec["mime"] == "application/pdf"
        cdr = disarm_pdf(src, dst) if is_pdf else disarm_image(src, dst)
        emit(stage="cdr", status="done", result=cdr)
        findings = []
        if cdr["active_content_found"]:
            findings.append({"module": "3", "rule_id": "S-CDR-01", "clause": "Security · Content Disarm & Reconstruction",
                             "outcome": "warn", "severity": "high", "manual_review": True,
                             "title": "Active content removed by CDR",
                             "detail": "Removed: " + "; ".join(r["what"] for r in cdr["removed"]) +
                                       ". Analysis ran on the sanitised copy; the original is kept read-only."})
        rules = load_rules()
        emit(stage="4B-bundle", status="done", result=rules["_verification"])
        if is_pdf:
            from app.pipeline.forensics import analyze_pdf
            emit(stage="4A", status="running")
            fa = analyze_pdf(src, dst, spec.get("trust_dir"))
            f4a = pdf_findings(fa)
            findings += f4a
            emit(stage="4A", status="done", result={k: fa[k] for k in ("signatures", "edit_history", "object_tree",
                                                                        "metadata_check", "ocr", "hidden_text", "overlays")},
                 findings=f4a)
            emit(stage="4B", status="running")
            ra = rule_engine.evaluate(spec["doc_type"], fa["text"], fa["lines"], rules)
            f4b = rule_findings(ra)
            findings += f4b
            emit(stage="4B", status="done", result={"facts": ra["facts"], "bundle": ra["bundle"]}, findings=f4b)
            emit(stage="4C", status="skipped", result={"reason": "Not a photo"})
            import re
            from app.pii import pan_valid, aadhaar_valid
            pan_c = set(re.findall(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", fa["text"]))
            aad_c = set(re.findall(r"\b\d{4}\s\d{4}\s\d{4}\b", fa["text"]))
            pans = sorted(p for p in pan_c if pan_valid(p))
            aad = sorted(a for a in aad_c if aadhaar_valid(a))
            bad = len(pan_c) - len(pans) + len(aad_c) - len(aad)
            if bad:
                f = {"module": "4B", "rule_id": "R-PII-01", "clause": "Data quality · Identifier format", "outcome": "warn",
                     "severity": "low", "manual_review": True, "title": f"{bad} identifier(s) failed format/checksum",
                     "detail": "PAN structure or Aadhaar Verhoeff checksum invalid (format check only; not identity verification)."}
                findings.append(f)
            emit(stage="extract", status="done", lines=fa["lines"], pages=fa["pages"], text=fa["text"][:20000],
                 pii={"PAN": pans, "AADHAAR": aad}, facts=ra["facts"])
        else:
            from app.pipeline.photo import analyze_photo
            emit(stage="4A", status="skipped", result={"reason": "Not a PDF"})
            emit(stage="4B", status="done", result={"facts": {}, "bundle": rules.get("bundle")}, findings=[])
            emit(stage="4C", status="running")
            pa = analyze_photo(dst, spec.get("candidates", []))
            f4c = photo_findings(pa, spec.get("college_coords"))
            findings += f4c
            emit(stage="4C", status="done", result=pa, findings=f4c)
            emit(stage="extract", status="done", lines=[], pages=[], text="", pii={"PAN": [], "AADHAAR": []}, facts={})
        emit(stage="final", status="done", findings=findings, token_jti=claims["jti"],
             elapsed_ms=int((time.time() - t0) * 1000))
    except Exception as e:
        emit(stage="error", status="failed", error=f"{type(e).__name__}: {e}", trace=traceback.format_exc()[-1500:])
        sys.exit(2)


if __name__ == "__main__":
    main()
