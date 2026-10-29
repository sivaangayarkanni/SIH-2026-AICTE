"""Stage 2 · Secure Upload Gateway: allow-list by magic bytes, size limit, malware scan, SHA-256."""
import hashlib, shutil, subprocess, re
from ..config import MAX_UPLOAD_MB

MAGIC = {b"%PDF-": "application/pdf", b"\xff\xd8\xff": "image/jpeg", b"\x89PNG\r\n\x1a\n": "image/png"}
EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


class GatewayReject(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def sniff(data: bytes) -> str | None:
    head = data[:1024]
    for m, mime in MAGIC.items():
        if head.startswith(m) or (m == b"%PDF-" and m in head[:1024]):
            return mime
    return None


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def malware_scan(data: bytes, path: str | None = None) -> dict:
    """Uses ClamAV (clamscan) when installed; otherwise a heuristic scanner with the same result shape."""
    if path and shutil.which("clamscan"):
        r = subprocess.run(["clamscan", "--no-summary", path], capture_output=True, text=True, timeout=120)
        return {"engine": "ClamAV", "clean": r.returncode == 0, "signature": r.stdout.strip() if r.returncode else None}
    hits = []
    if EICAR in data:
        hits.append("EICAR-Test-Signature")
    # an embedded Windows executable inside a document is never legitimate for AICTE uploads
    if re.search(rb"MZ.{58}.{0,4}PE\x00\x00", data[64:], re.S) and b"This program cannot be run in DOS mode" in data:
        hits.append("Heuristic.EmbeddedPE")
    return {"engine": "SealCheck heuristic scanner (ClamAV not installed)", "clean": not hits,
            "signature": ", ".join(hits) or None}


def inspect_upload(data: bytes, filename: str) -> dict:
    if len(data) == 0:
        raise GatewayReject(400, "The file is empty.")
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise GatewayReject(413, f"File is larger than the {MAX_UPLOAD_MB} MB limit.")
    mime = sniff(data)
    if not mime:
        raise GatewayReject(415, "Only PDF, JPEG and PNG files are accepted (checked by file signature, not by name).")
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    ext_ok = {"application/pdf": ["pdf"], "image/jpeg": ["jpg", "jpeg"], "image/png": ["png"]}[mime]
    scan = malware_scan(data)
    if not scan["clean"]:
        raise GatewayReject(422, f"Malware scan failed: {scan['signature']}. The file was blocked and not stored.")
    return {"mime": mime, "size": len(data), "sha256": sha256(data), "extension_matches": ext in ext_ok,
            "malware_scan": scan}
