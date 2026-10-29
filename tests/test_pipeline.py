import pikepdf, pytest
from conftest import SAMPLES
from app.pipeline import gateway, cdr, forensics, policy, rule_engine
from app.rules_bundle import load_rules, verify_bundle, BUNDLE, SIG, PUB, RuleBundleError
from app.service import TRUST_DIR


def test_gateway_magic_size_and_eicar():
    ok = gateway.inspect_upload((SAMPLES / "svit_fire_noc.pdf").read_bytes(), "a.pdf")
    assert ok["mime"] == "application/pdf" and len(ok["sha256"]) == 64
    with pytest.raises(gateway.GatewayReject) as e:
        gateway.inspect_upload(b"MZ\x90\x00 not a pdf", "evil.pdf")
    assert e.value.code == 415
    eicar = b"%PDF-1.4\n" + gateway.EICAR + b"\n%%EOF"
    with pytest.raises(gateway.GatewayReject) as e:
        gateway.inspect_upload(eicar, "eicar.pdf")
    assert e.value.code == 422
    with pytest.raises(gateway.GatewayReject) as e:
        gateway.inspect_upload(b"%PDF-" + b"0" * (16 * 1024 * 1024), "big.pdf")
    assert e.value.code == 413


def test_cdr_strips_javascript_and_attachments(tmp_path):
    out = tmp_path / "san.pdf"
    r = cdr.disarm_pdf(str(SAMPLES / "mct_affiliation_with_javascript.pdf"), str(out))
    kinds = {x["type"] for x in r["removed"]}
    assert "/JavaScript" in kinds or "JavaScript" in kinds
    assert "EmbeddedFiles" in kinds
    with pikepdf.open(out) as p:
        assert "/OpenAction" not in p.Root
        assert "/EmbeddedFiles" not in p.Root.get("/Names", {})


def test_cdr_clean_file_untouched(tmp_path):
    r = cdr.disarm_pdf(str(SAMPLES / "svit_fire_noc.pdf"), str(tmp_path / "s.pdf"))
    assert r["removed"] == []


def _analyze(name, tmp_path):
    san = tmp_path / "s.pdf"
    cdr.disarm_pdf(str(SAMPLES / name), str(san))
    return forensics.analyze_pdf(str(SAMPLES / name), str(san), str(TRUST_DIR))


def test_forged_hidden_text_and_overlay(tmp_path):
    fa = _analyze("gvce_land_lease_forged.pdf", tmp_path)
    assert any("15 acres" in h["text"] for h in fa["hidden_text"])
    assert fa["overlays"] and fa["overlays"][0]["page"] == 1
    assert fa["metadata_check"]["editing_tool"] == "ilovepdf"


def test_genuine_signature_intact_and_trusted(tmp_path):
    fa = _analyze("svit_land_lease.pdf", tmp_path)
    s = fa["signatures"][0]
    assert s["intact"] and s["covers_whole_file"] and s["trusted"] and not s["cert_expired"]
    assert fa["hidden_text"] == []


def test_tampered_after_signing(tmp_path):
    fa = _analyze("gvce_fire_noc_tampered.pdf", tmp_path)
    s = fa["signatures"][0]
    assert s["intact"] and not s["covers_whole_file"]
    assert fa["edit_history"]["eof_markers"] >= 3


def test_expired_certificate(tmp_path):
    fa = _analyze("diem_building_completion_expired_dsc.pdf", tmp_path)
    assert fa["signatures"][0]["cert_expired"] is True


def test_rule_engine_expiry_and_issuer(tmp_path):
    rules = load_rules()
    fa = _analyze("diem_fire_noc_expired.pdf", tmp_path)
    r = rule_engine.evaluate("fire_noc", fa["text"], fa["lines"], rules)
    exp = [f for f in r["findings"] if f.get("expired")]
    assert exp and exp[0]["page"] == 1 and exp[0]["bbox"]
    fa = _analyze("mct_fire_noc_unknown_issuer.pdf", tmp_path)
    r = rule_engine.evaluate("fire_noc", fa["text"], fa["lines"], rules)
    assert any(f.get("source_unavailable") for f in r["findings"])


def test_policy_precedence():
    assert policy.decide([{"forgery": True, "severity": "critical", "outcome": "fail"},
                          {"expired": True, "severity": "high", "outcome": "fail"}])["status"] == "Mismatch Detected"
    assert policy.decide([{"expired": True, "outcome": "fail", "severity": "high"}])["status"] == "Expired"
    assert policy.decide([{"source_unavailable": True, "outcome": "warn", "severity": "medium"}])["status"] == "Source Unavailable"
    assert policy.decide([{"manual_review": True, "outcome": "warn", "severity": "high"}])["status"] == "Manual Review Required"
    assert policy.decide([{"outcome": "pass", "severity": "info"}])["status"] == "Verified"
    assert policy.decide([], analysis_complete=False)["status"] == "Verification Pending"


def test_signed_rule_bundle_tamper_detected(tmp_path):
    assert verify_bundle()["valid"]
    bad = tmp_path / "rules.yaml"
    bad.write_text(BUNDLE.read_text().replace("min_remaining_days: 30", "min_remaining_days: 0"))
    assert not verify_bundle(bad, SIG, PUB)["valid"]
    with pytest.raises(RuleBundleError):
        load_rules(bad, SIG, PUB)


def test_photo_reuse_detected():
    from app.pipeline.photo import analyze_photo, phash
    a, b = SAMPLES / "svit_lab_cse.jpg", SAMPLES / "diem_lab_reused.jpg"
    r = analyze_photo(str(b), [{"document_id": 1, "college_id": 1, "phash": phash(str(a)), "path": str(a)}])
    assert r["matches"] and r["matches"][0]["duplicate"]
    assert r["exif"]["gps"]["lat"] == pytest.approx(17.4401, abs=1e-3)
    other = SAMPLES / "gvce_lab_ece.jpg"
    r2 = analyze_photo(str(other), [{"document_id": 1, "college_id": 1, "phash": phash(str(a)), "path": str(a)}])
    assert not any(m["duplicate"] for m in r2["matches"])


def test_qa_explains_flag_from_findings():
    from app import qa
    f = [{"outcome": "fail", "severity": "critical", "rule_id": "F-HID-01", "title": "Hidden text", "detail": "x", "page": 1, "bbox": [0, 0, 1, 1]}]
    r = qa.answer("Why was this flagged?", [], {}, "Land document", f, "Mismatch Detected")
    assert "F-HID-01" in r["answer"] and r["citation"]["page"] == 1
    assert "Nothing was flagged" in qa.answer("why flagged", [], {}, "x", [], "Verified")["answer"]
