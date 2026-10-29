"""Stage 3 · Quarantine + Content Disarm & Reconstruction (CDR) using pikepdf.
Removes active content (JavaScript, launch actions, auto-actions, embedded files, XFA) and rebuilds a clean copy."""
import pikepdf

ACTIVE_ACTIONS = {"/JavaScript", "/Launch", "/SubmitForm", "/ImportData", "/GoToR", "/URI", "/Rendition"}


def _action_kind(a):
    try:
        return str(a.get("/S")) if isinstance(a, pikepdf.Dictionary) else None
    except Exception:
        return None


def disarm_pdf(src: str, dst: str) -> dict:
    removed = []
    with pikepdf.open(src) as pdf:
        root = pdf.Root
        if "/OpenAction" in root:
            k = _action_kind(root.OpenAction)
            if k in ACTIVE_ACTIONS or k is None and isinstance(root.OpenAction, pikepdf.Dictionary):
                removed.append({"what": "Document OpenAction", "type": k or "action"})
                del root["/OpenAction"]
        if "/AA" in root:
            removed.append({"what": "Document additional-actions (/AA)", "type": "auto-action"})
            del root["/AA"]
        if "/Names" in root:
            names = root.Names
            for key, label in (("/JavaScript", "Document-level JavaScript"), ("/EmbeddedFiles", "Embedded file attachments")):
                if key in names:
                    removed.append({"what": label, "type": key.strip("/")})
                    del names[key]
        if "/AcroForm" in root and "/XFA" in root.AcroForm:
            removed.append({"what": "XFA dynamic form", "type": "XFA"})
            del root.AcroForm["/XFA"]
        for pno, page in enumerate(pdf.pages, start=1):
            if "/AA" in page.obj:
                removed.append({"what": f"Page {pno} auto-actions", "type": "auto-action"})
                del page.obj["/AA"]
            annots = page.obj.get("/Annots")
            if annots is None:
                continue
            keep = pikepdf.Array()
            for an in annots:
                kind = _action_kind(an.get("/A")) if "/A" in an else None
                if str(an.get("/Subtype")) == "/FileAttachment":
                    removed.append({"what": f"Page {pno} file-attachment annotation", "type": "EmbeddedFile"})
                    continue
                if kind in ("/JavaScript", "/Launch", "/SubmitForm", "/ImportData"):
                    removed.append({"what": f"Page {pno} link with {kind.strip('/')} action", "type": kind.strip("/")})
                    continue
                if "/AA" in an:
                    del an["/AA"]
                keep.append(an)
            page.obj["/Annots"] = keep
        pdf.save(dst, linearize=False, object_stream_mode=pikepdf.ObjectStreamMode.generate)
    return {"sanitized": True, "removed": removed, "active_content_found": bool(removed),
            "method": "pikepdf structural rebuild"}


def disarm_image(src: str, dst: str) -> dict:
    """Images are re-encoded (drops any trailing payload / polyglot data). EXIF is kept for geotag analysis."""
    from PIL import Image
    with Image.open(src) as im:
        exif = im.info.get("exif")
        fmt = "JPEG" if im.format == "JPEG" else "PNG"
        im.convert("RGB").save(dst, fmt, **({"exif": exif} if exif and fmt == "JPEG" else {}), quality=95)
    return {"sanitized": True, "removed": [], "active_content_found": False, "method": "Pillow re-encode"}
