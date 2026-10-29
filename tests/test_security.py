import time, pytest
from app.security import issue_job_token, verify_job_token, TokenError, kms, hash_password, verify_password, mask_pan, mask_aadhaar


def test_job_token_valid_and_scoped():
    tok, c = issue_job_token(7, 9, ttl=60)
    assert verify_job_token(tok, 7, 9)["jti"] == c["jti"]
    with pytest.raises(TokenError, match="scope"):
        verify_job_token(tok, 7, 10)


def test_job_token_expires():
    tok, c = issue_job_token(1, 1, ttl=1)
    with pytest.raises(TokenError, match="expired"):
        verify_job_token(tok, 1, 1, now=time.time() + 61)


def test_job_token_tamper():
    tok, _ = issue_job_token(1, 1)
    body, sig = tok.split(".")
    with pytest.raises(TokenError, match="signature"):
        verify_job_token(body + "." + sig[::-1], 1, 1)


def test_kms_envelope_roundtrip_and_aad():
    blob = kms.encrypt(b"ABCDE1234F", b"PAN:1")
    assert b"ABCDE1234F" not in blob["ciphertext"].encode()
    assert kms.decrypt(blob, b"PAN:1") == b"ABCDE1234F"
    with pytest.raises(Exception):
        kms.decrypt(blob, b"PAN:2")


def test_passwords_and_masking():
    h = hash_password("Demo@2026")
    assert verify_password("Demo@2026", h) and not verify_password("x", h)
    assert mask_pan("ABCDE1234F") == "XXXXXX234F"
    assert mask_aadhaar("1234 5678 9012") == "XXXX XXXX 9012"


def test_verhoeff_pan_and_last4_masking():
    from app.pii import verhoeff_digit, aadhaar_valid, pan_valid, mask_last4
    base = "23456789012"
    good = base + verhoeff_digit(base)
    assert aadhaar_valid(good) and aadhaar_valid(f"{good[:4]} {good[4:8]} {good[8:]}")
    bad = good[:-1] + str((int(good[-1]) + 1) % 10)
    assert not aadhaar_valid(bad)
    assert not aadhaar_valid("1" + good[1:])  # cannot start with 0/1
    assert aadhaar_valid("499118665246")  # published Verhoeff test vector style number (synthetic)
    assert pan_valid("AKMPK4821Q") and not pan_valid("AKMXK4821Q") and not pan_valid("AKM1K4821Q")
    assert mask_last4("ABCDE1234F") == "XXXXXX234F" and mask_aadhaar(good)[-4:] == good[-4:]
