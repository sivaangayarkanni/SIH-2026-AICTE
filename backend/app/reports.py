"""Evidence Packet, highlighted rejection-helper PDF and decision letter (pypdfium2 render + Pillow + ReportLab)."""
import io
from datetime import datetime
from pathlib import Path
import pypdfium2 as pdfium
from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from .config import EVIDENCE_DIR

SEV_COL = {"critical": (220, 38, 38), "high": (234, 88, 12), "medium": (217, 119, 6), "low": (37, 99, 235), "info": (22, 163, 74)}


def render_page(pdf_path: str, page: int, scale: float = 1.6) -> Image.Image:
    doc = pdfium.PdfDocument(pdf_path)
    pg = doc[page - 1]
    return pg.render(scale=scale).to_pil().convert("RGB"), pg.get_size()


def highlight(pdf_path: str, page: int, boxes: list[dict], scale=1.6) -> Image.Image:
    img, (w, h) = render_page(pdf_path, page, scale)
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    for i, b in enumerate(boxes, 1):
        x0, y0, x1, y1 = b["bbox"]
        col = SEV_COL.get(b.get("severity", "high"), (220, 38, 38))
        r = [x0 * scale - 4, (h - y1) * scale - 4, x1 * scale + 4, (h - y0) * scale + 4]
        d.rectangle(r, fill=col + (60,), outline=col + (255,), width=3)
        d.ellipse([r[0] - 26, r[1] - 10, r[0] - 4, r[1] + 12], fill=col + (255,))
        d.text((r[0] - 19, r[1] - 7), str(i), fill=(255, 255, 255, 255))
    return Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")


def page_png(pdf_path: str, page: int, doc_id: int) -> Path:
    out = EVIDENCE_DIR / f"doc{doc_id}_p{page}.png"
    if not out.exists():
        img, _ = render_page(pdf_path, page, 1.6)
        img.save(out, optimize=True)
    return out


def _header(c, title, sub):
    W, H = A4
    c.setFillColor(colors.HexColor("#0b3a75"))
    c.rect(0, H - 28 * mm, W, 28 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    t, fs = "SealCheck · " + title, 16
    while fs > 9 and c.stringWidth(t, "Helvetica-Bold", fs) > W - 30 * mm:
        fs -= 0.5
    c.setFont("Helvetica-Bold", fs)
    c.drawString(15 * mm, H - 14 * mm, t)
    c.setFont("Helvetica", 9)
    c.drawString(15 * mm, H - 21 * mm, sub)
    c.setFillColor(colors.black)
    return H - 38 * mm


def _wrap(c, text, x, y, width_chars=105, size=9, leading=12):
    import textwrap
    c.setFont("Helvetica", size)
    for para in str(text).split("\n"):
        for ln in textwrap.wrap(para, width_chars) or [""]:
            if y < 20 * mm:
                c.showPage(); y = A4[1] - 20 * mm; c.setFont("Helvetica", size)
            c.drawString(x, y, ln)
            y -= leading
    return y


def _page_images(c, pdf_path, findings, title_fn):
    by_page = {}
    for _i, f in enumerate([f for f in findings if f.get("page") and f.get("bbox")], 1):
        by_page.setdefault(f["page"], []).append(f)
    W, H = A4
    for page, fs in sorted(by_page.items()):
        img = highlight(pdf_path, page, fs)
        c.showPage()
        y = _header(c, title_fn(page), "Highlighted regions are linked to the numbered findings below")
        iw = W - 30 * mm
        ih = iw * img.height / img.width
        maxh = H - 120 * mm
        if ih > maxh:
            ih = maxh; iw = ih * img.width / img.height
        c.drawImage(ImageReader(img), 15 * mm, y - ih, iw, ih)
        y = y - ih - 8 * mm
        for i, f in enumerate(fs, 1):
            c.setFont("Helvetica-Bold", 9)
            c.drawString(15 * mm, y, f"{i}. {f['title']}  [{f.get('rule_id')} · {f.get('clause')}]")
            y = _wrap(c, f.get("guidance") or f.get("detail", ""), 20 * mm, y - 11, 100, 8.5, 11) - 4


def evidence_packet(doc, app, analysis: dict, audit_rows: list, pdf_path: str | None) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    dec = analysis.get("decision", {})
    y = _header(c, "Evidence Packet", f"Application {app.ref} · Document #{doc.id} · generated {datetime.now():%d %b %Y %H:%M}")
    rows = [("Document", f"{analysis.get('label', doc.doc_type)} — {doc.filename}"), ("SHA-256 (original)", doc.sha256),
            ("Status (policy engine)", f"{dec.get('status')}  ·  rule {dec.get('policy_rule')}: {dec.get('policy_text')}"),
            ("Risk score", f"{dec.get('risk_score')}/100"), ("College", app.college.name)]
    for k, v in rows:
        c.setFont("Helvetica-Bold", 9); c.drawString(15 * mm, y, k)
        c.setFont("Helvetica", 9); c.drawString(55 * mm, y, str(v)[:95]); y -= 13
    y -= 6
    c.setFont("Helvetica-Bold", 11); c.drawString(15 * mm, y, "Findings (rule-to-evidence traceability)"); y -= 15
    for i, f in enumerate(analysis.get("findings", []), 1):
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(15 * mm, y, f"{i}. [{f.get('outcome','').upper()}/{f.get('severity')}] {f['title']} — {f.get('rule_id')} · {f.get('clause')}"[:120])
        y = _wrap(c, f.get("detail", "") + (f"  (page {f['page']})" if f.get("page") else ""), 20 * mm, y - 11, 105, 8, 10) - 3
        if y < 30 * mm:
            c.showPage(); y = A4[1] - 20 * mm
    y -= 6
    c.setFont("Helvetica-Bold", 11); c.drawString(15 * mm, y, "Explainer agents (advisory only)"); y -= 14
    for a in analysis.get("agents", []):
        y = _wrap(c, f"{a['agent']}: {a['message']}", 15 * mm, y, 110, 8, 10) - 4
    y -= 6
    c.setFont("Helvetica-Bold", 11); c.drawString(15 * mm, y, "Audit trail (hash-chained)"); y -= 14
    for r in audit_rows:
        y = _wrap(c, f"{r.ts}  {r.actor} ({r.role})  {r.action}  hash {r.hash[:16]}…", 15 * mm, y, 115, 7.5, 9.5)
    if pdf_path:
        _page_images(c, pdf_path, analysis.get("findings", []), lambda p: f"Evidence · page {p}")
    c.save()
    return buf.getvalue()


def rejection_pdf(app, items: list[dict], reason: str, docs: list[tuple]) -> bytes:
    """docs: list of (doc, pdf_path, findings). Highlights what the college must change."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    y = _header(c, "Corrections Required", f"Application {app.ref} · {app.college.name} · {datetime.now():%d %b %Y}")
    c.setFont("Helvetica-Bold", 11); c.drawString(15 * mm, y, "Officer's reason"); y -= 14
    y = _wrap(c, reason, 15 * mm, y) - 8
    c.setFont("Helvetica-Bold", 11); c.drawString(15 * mm, y, "What to fix before resubmitting"); y -= 14
    for i, it in enumerate(items, 1):
        y = _wrap(c, f"{i}. {it['action']}  ({it['document']} · {it['rule_id']})", 15 * mm, y, 105, 9, 12) - 3
    for doc, path, fs in docs:
        if path:
            _page_images(c, path, [{**f, "guidance": f.get("guidance")} for f in fs], lambda p, d=doc: f"{d.filename} · page {p} — change the highlighted parts")
    c.save()
    return buf.getvalue()


def decision_letter(app, officer, audit_head: str, override=None) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    y = _header(c, "Decision Record", f"Application {app.ref} · {app.college.name}")
    lines = [f"Category: {app.category}", f"Decision: {app.decision}", f"Decided by: {officer.name if officer else '-'} ({officer.title if officer else ''})",
             f"Decided at: {app.decided_at:%d %b %Y %H:%M} UTC" if app.decided_at else "", f"Verification status at decision: {app.status}",
             f"Risk score: {app.risk_score}/100", "", "Reason:", app.decision_reason or "-"]
    if override:
        lines += ["", f"Two-person override #{override.id}: requested by user #{override.requested_by}, approved by user #{override.approved_by}.",
                  f"Justification: {override.justification}"]
    lines += ["", f"Audit chain head at issue time: {audit_head}",
              "AI components advised; this decision was made by a human officer.",
              "SYNTHETIC PROTOTYPE OUTPUT — not an official AICTE communication."]
    for l in lines:
        y = _wrap(c, l, 15 * mm, y, 100, 10, 14)
    c.save()
    return buf.getvalue()
