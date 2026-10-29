"""PII validation + masking. Format/checksum checks ONLY — this is not identity verification.
Real Aadhaar authentication/eKYC requires UIDAI authorisation as an AUA/KUA (Aadhaar Act 2016, Reg. 2016) and is
deliberately NOT integrated. PAN existence checks require NSDL/Protean or ITD APIs (operator credentials)."""
import re

_D = [[0,1,2,3,4,5,6,7,8,9],[1,2,3,4,0,6,7,8,9,5],[2,3,4,0,1,7,8,9,5,6],[3,4,0,1,2,8,9,5,6,7],[4,0,1,2,3,9,5,6,7,8],
      [5,9,8,7,6,0,4,3,2,1],[6,5,9,8,7,1,0,4,3,2],[7,6,5,9,8,2,1,0,4,3],[8,7,6,5,9,3,2,1,0,4],[9,8,7,6,5,4,3,2,1,0]]
_P = [[0,1,2,3,4,5,6,7,8,9],[1,5,7,6,2,8,3,0,9,4],[5,8,0,3,7,9,6,1,4,2],[8,9,1,6,0,4,3,5,2,7],[9,4,5,3,1,2,6,8,7,0],
      [4,2,8,6,5,7,3,9,0,1],[2,7,9,3,8,0,6,4,1,5],[7,0,4,6,9,1,3,2,5,8]]
_INV = [0,4,3,2,1,5,6,7,8,9]
PAN_RE = re.compile(r"^[A-Z]{3}[ABCFGHLJPT][A-Z][0-9]{4}[A-Z]$")  # 4th char = holder type (P=person, C=company, ...)


def verhoeff_valid(num: str) -> bool:
    c = 0
    for i, ch in enumerate(reversed(num)):
        c = _D[c][_P[i % 8][int(ch)]]
    return c == 0


def verhoeff_digit(num: str) -> str:
    c = 0
    for i, ch in enumerate(reversed(num)):
        c = _D[c][_P[(i + 1) % 8][int(ch)]]
    return str(_INV[c])


def aadhaar_valid(a: str) -> bool:
    d = re.sub(r"\s", "", a)
    return bool(re.fullmatch(r"[2-9][0-9]{11}", d)) and verhoeff_valid(d)


def pan_valid(p: str) -> bool:
    return bool(PAN_RE.match(p.strip().upper()))


def mask_last4(v: str) -> str:
    s = re.sub(r"\s", "", v)
    return "X" * max(0, len(s) - 4) + s[-4:]
