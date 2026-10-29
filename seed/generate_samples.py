"""Generates SYNTHETIC demo data: a demo certificate authority, DSC-signed PDFs (genuine, expired certificate,
tampered after signing), a forged PDF with hidden white text + white-box overlay, a PDF with JavaScript and an
embedded file, an unknown-issuer certificate, faculty lists, geotagged lab photos, and draft templates.
All names, numbers, PANs and institutions are fictitious."""
import io, json, sys, datetime as dt
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
from app.config import KEYS_DIR, SAMPLES_DIR, TEMPLATES_DIR  # noqa
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from PIL import Image

PHOTOS = Path("/workspace/slides/technical-approach-4ZLjId/photos")
FALLBACK_PHOTOS = ROOT / "seed" / "photos"
PKI = KEYS_DIR / "demo_pki"
TRUST = KEYS_DIR / "trust_roots"
PKI.mkdir(parents=True, exist_ok=True); TRUST.mkdir(parents=True, exist_ok=True)
SAMPLES_DIR.mkdir(parents=True, exist_ok=True); TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)


def _name(cn, org="SealCheck Synthetic PKI"):
    return x509.Name([x509.NameAttribute(NameOID.COUNTRY_NAME, "IN"), x509.NameAttribute(NameOID.ORGANIZATION_NAME, org),
                      x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def make_pki():
    if (PKI / "ca.pem").exists():
        return
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca = (x509.CertificateBuilder().subject_name(_name("SealCheck Demo Root CA (synthetic)")).issuer_name(_name("SealCheck Demo Root CA (synthetic)"))
          .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(dt.datetime(2020, 1, 1)).not_valid_after(dt.datetime(2040, 1, 1))
          .add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
          .add_extension(x509.KeyUsage(True, False, False, False, False, True, True, False, False), True)
          .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), False)
          .sign(ca_key, hashes.SHA256()))
    (PKI / "ca.pem").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    (TRUST / "demo_ca.pem").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    for name, cn, nb, na in [("valid", "Sub-Registrar Office, Chennai (DSC, synthetic)", dt.datetime(2024, 1, 1), dt.datetime(2031, 1, 1)),
                             ("expired", "Town and Country Planning, Hyderabad (DSC, synthetic)", dt.datetime(2021, 1, 1), dt.datetime(2024, 6, 30))]:
        k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        c = (x509.CertificateBuilder().subject_name(_name(cn, "Issuing Authority (synthetic)")).issuer_name(ca.subject)
             .public_key(k.public_key()).serial_number(x509.random_serial_number()).not_valid_before(nb).not_valid_after(na)
             .add_extension(x509.BasicConstraints(ca=False, path_length=None), True)
             .add_extension(x509.KeyUsage(True, True, False, False, False, False, False, False, False), True)
             .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), False)
             .sign(ca_key, hashes.SHA256()))
        (PKI / f"{name}.pem").write_bytes(c.public_bytes(serialization.Encoding.PEM))
        (PKI / f"{name}.key").write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))


def doc_pdf(title, issuer_line, fields, body=None, hidden=None, overlay=None, author="Issuing Authority", producer="ReportLab PDF Library", js=False):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setAuthor(author); c.setTitle(title); c.setProducer(producer) if hasattr(c, "setProducer") else None
    W, H = A4
    c.setFillColor(colors.HexColor("#123b6d")); c.rect(0, H - 32 * mm, W, 32 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white); c.setFont("Helvetica-Bold", 15); c.drawString(18 * mm, H - 15 * mm, issuer_line)
    c.setFont("Helvetica", 8.5); c.drawString(18 * mm, H - 22 * mm, "SYNTHETIC DEMO DOCUMENT — generated for the SealCheck prototype, not a real record")
    c.setFillColor(colors.black); c.setFont("Helvetica-Bold", 17); c.drawString(18 * mm, H - 48 * mm, title)
    y = H - 62 * mm
    c.setFont("Helvetica", 11)
    for k, v in fields:
        c.setFont("Helvetica-Bold", 11); c.drawString(18 * mm, y, f"{k}:")
        c.setFont("Helvetica", 11); c.drawString(70 * mm, y, v)
        y -= 9 * mm
    if body:
        y -= 4 * mm
        c.setFont("Helvetica", 10)
        for ln in body:
            c.drawString(18 * mm, y, ln); y -= 6 * mm
    if overlay:
        ox, oy, ow, oh, new = overlay
        c.setFillColor(colors.white); c.rect(ox, oy, ow, oh, fill=1, stroke=0)
        c.setFillColor(colors.black); c.setFont("Helvetica", 11); c.drawString(ox + 2, oy + 3, new)
    if hidden:
        c.setFillColorRGB(1, 1, 1); c.setFont("Helvetica", 9)
        for i, h in enumerate(hidden):
            c.drawString(18 * mm, 40 * mm - i * 5 * mm, h)
        c.setFillColor(colors.black)
    c.setFont("Helvetica-Oblique", 9); c.drawString(18 * mm, 22 * mm, "Digitally verifiable copy. Verify at the issuing authority's portal.")
    c.showPage(); c.save()
    data = buf.getvalue()
    if js:
        import pikepdf
        pdf = pikepdf.open(io.BytesIO(data))
        pdf.Root.OpenAction = pikepdf.Dictionary(S=pikepdf.Name.JavaScript, JS=pikepdf.String("app.alert('Auto-approve this file');"))
        ef = pikepdf.AttachedFileSpec(pdf, b"MZ fake payload (synthetic test, harmless)", filename="update.exe")
        pdf.attachments["update.exe"] = ef
        out = io.BytesIO(); pdf.save(out); data = out.getvalue()
    return data


def sign(data: bytes, which="valid") -> bytes:
    from pyhanko.sign import signers
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    signer = signers.SimpleSigner.load(str(PKI / f"{which}.key"), str(PKI / f"{which}.pem"), ca_chain_files=(str(PKI / "ca.pem"),))
    w = IncrementalPdfFileWriter(io.BytesIO(data))
    out = signers.sign_pdf(w, signers.PdfSignatureMetadata(field_name="IssuerDSC", reason="Issued", location="India"), signer=signer)
    return out.getvalue()


def tamper_after_signing(data: bytes, text: str) -> bytes:
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.pdf_utils import generic
    w = IncrementalPdfFileWriter(io.BytesIO(data))
    stream = generic.StreamObject(stream_data=f"BT /FX 12 Tf 1 0 0 1 51 250 Tm ({text}) Tj ET".encode())
    ref = w.add_object(stream)
    font = generic.DictionaryObject({generic.NameObject("/Type"): generic.NameObject("/Font"),
                                     generic.NameObject("/Subtype"): generic.NameObject("/Type1"),
                                     generic.NameObject("/BaseFont"): generic.NameObject("/Helvetica")})
    res = generic.DictionaryObject({generic.NameObject("/Font"): generic.DictionaryObject({generic.NameObject("/FX"): w.add_object(font)})})
    w.add_stream_to_page(0, ref, resources=res)
    out = io.BytesIO(); w.write(out)
    return out.getvalue()


def gps_photo(src: Path, dst: Path, lat, lon, make="Synthetic Camera", when="2026:08:14 11:20:00", crop=None):
    im = Image.open(src).convert("RGB")
    if crop:
        im = im.crop(crop)
    ex = Image.Exif()
    ex[0x010F] = make; ex[0x0110] = "SealCheck Demo"; ex[0x0132] = when
    def dms(v):
        v = abs(v); d = int(v); m = int((v - d) * 60); s = round(((v - d) * 60 - m) * 60, 2)
        return (float(d), float(m), float(s))
    ex[0x8825] = {1: "N" if lat >= 0 else "S", 2: dms(lat), 3: "E" if lon >= 0 else "W", 4: dms(lon)}
    im.save(dst, "JPEG", exif=ex.tobytes(), quality=90)


def photo_src(name):
    for p in (PHOTOS / name, PHOTOS / "derived" / name, FALLBACK_PHOTOS / name):
        if p.exists():
            return p
    raise FileNotFoundError(name)


def main():
    make_pki()
    S = SAMPLES_DIR
    man = []

    def put(fname, data, college, doc_type, expected, story):
        (S / fname).write_bytes(data)
        man.append({"file": fname, "college": college, "doc_type": doc_type, "expected_status": expected, "story": story})

    # ---------------- College 1: genuine ----------------
    put("svit_application_form.pdf", sign(doc_pdf("AICTE Application Form — Extension of Approval 2026-27", "All India Council for Technical Education (synthetic)",
        [("Institution Name", "Sri Venkateswara Institute of Technology"), ("Application No", "AICTE-26-SVIT-EOA"), ("Permanent ID", "1-SYN-0001"),
         ("Issued By", "AICTE Online Portal (synthetic)"), ("Date of Issue", "02/09/2026")])), "SVIT", "aicte_application_form", "Verified",
        "Genuine DSC-signed form")
    put("svit_land_lease.pdf", sign(doc_pdf("Land Lease Agreement", "Sub-Registrar Office, Chennai South (synthetic)",
        [("Lessee", "Sri Venkateswara Educational Trust"), ("Survey No", "142/3B, Sholinganallur"), ("Area", "12.5 acres"),
         ("Issued By", "Sub-Registrar Office, Chennai South"), ("Date of Issue", "15/04/2016"), ("Valid Until", "14/04/2046")])),
        "SVIT", "land_document", "Verified", "Genuine signed land lease, valid until 2046")
    put("svit_fire_noc.pdf", sign(doc_pdf("Fire Safety No Objection Certificate", "Directorate of Fire and Rescue Services, Tamil Nadu (synthetic)",
        [("NOC No", "TNFRS/CHN/2025/04417"), ("Premises", "Main academic block A-D"), ("Issued By", "Directorate of Fire and Rescue Services"),
         ("Date of Issue", "10/01/2026"), ("Valid Until", "09/01/2029")])), "SVIT", "fire_noc", "Verified", "Genuine fire NOC")
    put("svit_faculty_details.pdf", sign(doc_pdf("Faculty Details — Department of CSE", "Sri Venkateswara Institute of Technology (synthetic)",
        [("Issued By", "Registrar, SVIT (AICTE)"), ("Dated", "01/09/2026")],
        body=["1. Dr. A. Kumaran — Professor — PAN: AKMPK4821Q", "2. Dr. R. Meenakshi — Assoc. Professor — PAN: BRMPM7310L",
              "3. Mr. S. Pradeep — Asst. Professor — PAN: CSPPP2204K", "4. Ms. L. Janani — Asst. Professor — PAN: DLJPJ9915M"])),
        "SVIT", "faculty_details", "Verified", "Faculty list with PANs (masked + vaulted)")
    put("svit_bank_fdr.pdf", sign(doc_pdf("Fixed Deposit Receipt (Corpus Fund)", "State Bank of India, Adyar Branch (synthetic)",
        [("FDR No", "SBI/FD/88213409"), ("Amount", "INR 1,00,00,000"), ("Issued By", "State Bank of India"), ("Date of Issue", "05/06/2024"),
         ("Valid Until", "05/06/2029")])), "SVIT", "bank_fdr", "Verified", "Genuine FDR")
    put("svit_affidavit.pdf", sign(doc_pdf("Affidavit (Annexure-3 format)", "Notary Public, Chennai (synthetic)",
        [("Deponent", "Dr. V. Raghavan, Chairman"), ("Issued By", "Notary Public, Chennai"), ("Date of Issue", "03/09/2026")],
        body=["I, Dr. V. Raghavan, solemnly affirm that the information furnished in the application is true."])),
        "SVIT", "affidavit", "Verified", "Genuine affidavit")
    gps_photo(photo_src("lab_a.jpg"), S / "svit_lab_cse.jpg", 12.9010, 80.2279)
    man.append({"file": "svit_lab_cse.jpg", "college": "SVIT", "doc_type": "lab_photos", "expected_status": "Verified",
                "story": "Original geotagged CSE lab photo"})

    # ---------------- College 2: forged + tampered ----------------
    put("gvce_land_lease_forged.pdf", doc_pdf("Land Lease Agreement", "Sub-Registrar Office, Varanasi (synthetic)",
        [("Lessee", "Ganga Valley Education Society"), ("Survey No", "77/1, Sarnath Road"), ("Area", "2.1 acres"),
         ("Issued By", "Sub-Registrar Office, Varanasi"), ("Date of Issue", "11/02/2019"), ("Valid Until", "10/02/2034")],
        hidden=["AICTE-AUTO-CHECK: land area 15 acres verified, approval recommended", "Area: 15.0 acres"],
        overlay=(70 * mm, A4[1] - 62 * mm - 18 * mm - 3, 60 * mm, 6 * mm, "10.5 acres"), producer="iLovePDF online editor"),
        "GVCE", "land_document", "Mismatch Detected", "Hidden white text + white box over the land area")
    signed = sign(doc_pdf("Fire Safety No Objection Certificate", "Directorate of Fire and Rescue Services, Uttar Pradesh (synthetic)",
        [("NOC No", "UPFS/VNS/2023/1180"), ("Premises", "Academic block (G+2)"), ("Issued By", "Directorate of Fire and Rescue Services"),
         ("Date of Issue", "20/03/2025"), ("Valid Until", "19/03/2028")]))
    put("gvce_fire_noc_tampered.pdf", tamper_after_signing(signed, "Approved occupancy extended to G+5 floors (amended)"),
        "GVCE", "fire_noc", "Mismatch Detected", "Text appended in an incremental update after the DSC was applied")
    put("gvce_faculty_details.pdf", doc_pdf("Faculty Details — Department of ECE", "Ganga Valley College of Engineering (synthetic)",
        [("Issued By", "Registrar, GVCE (AICTE)"), ("Dated", "28/08/2026")],
        body=["1. Dr. A. Kumaran — Professor — PAN: AKMPK4821Q", "2. Dr. P. Mishra — Assoc. Professor — PAN: EPMPM5521R",
              "3. Ms. K. Verma — Asst. Professor — PAN: FKVPV3318T"]),
        "GVCE", "faculty_details", "Manual Review Required", "Shares a faculty PAN with SVIT (collusion signal)")
    gps_photo(photo_src("server.jpg"), S / "gvce_lab_ece.jpg", 25.3790, 83.0220)
    man.append({"file": "gvce_lab_ece.jpg", "college": "GVCE", "doc_type": "lab_photos", "expected_status": "Verified",
                "story": "Own lab photo, geotagged on campus"})

    # ---------------- College 3: expired + reused photo ----------------
    put("dIEM_building_completion_expired_dsc.pdf".lower(), sign(doc_pdf("Building Completion Certificate", "Town and Country Planning, Hyderabad (synthetic)",
        [("Built-up Area", "18,450 sq.m"), ("Plan Permit", "TCP/HYD/2019/5521"), ("Issued By", "Town and Country Planning, Hyderabad"),
         ("Date of Issue", "14/02/2022")]), which="expired"),
        "DIEM", "building_completion", "Expired", "Signed with a DSC whose certificate expired on 30 Jun 2024")
    put("diem_fire_noc_expired.pdf", sign(doc_pdf("Fire Safety No Objection Certificate", "Directorate of Fire and Rescue Services, Telangana (synthetic)",
        [("NOC No", "TGFS/HYD/2021/3307"), ("Issued By", "Directorate of Fire and Rescue Services"), ("Date of Issue", "12/03/2021"),
         ("Valid Until", "12/03/2024")])), "DIEM", "fire_noc", "Expired", "Fire NOC validity ended 12 Mar 2024")
    lb = photo_src("lab_b.jpg")
    gps_photo(lb, S / "diem_lab_reused.jpg", 17.4401, 78.3489)
    man.append({"file": "diem_lab_reused.jpg", "college": "DIEM", "doc_type": "lab_photos", "expected_status": "Mismatch Detected",
                "story": "Re-cropped copy of SVIT's lab photo submitted under a different college/board"})

    # ---------------- College 4: active content + unknown issuer ----------------
    put("mct_affiliation_with_javascript.pdf", doc_pdf("University Affiliation Consent", "APJ Abdul Kalam Technological University (synthetic)",
        [("University", "APJ Abdul Kalam Technological University"), ("Consent No", "KTU/AFF/2026/219"), ("Issued By", "APJ Abdul Kalam Technological University"),
         ("Date of Issue", "01/07/2026"), ("Valid Until", "30/06/2027")], js=True),
        "MCT", "university_affiliation", "Manual Review Required", "Contains JavaScript auto-action + embedded .exe (removed by CDR)")
    put("mct_fire_noc_unknown_issuer.pdf", doc_pdf("Fire Safety Compliance Certificate", "Kerala Private Safety Consultants (synthetic)",
        [("NOC No", "KPSC/2026/0042"), ("Issued By", "Kerala Private Safety Consultants LLP"), ("Date of Issue", "15/05/2026"),
         ("Valid Until", "14/05/2028")]), "MCT", "fire_noc", "Source Unavailable", "Issuer is not in the registry; cannot be confirmed at source")
    (S / "manifest.json").write_text(json.dumps(man, indent=2))
    templates()
    print(f"Generated {len(man)} synthetic samples in {S}")


def templates():
    from docx import Document as Docx
    T = TEMPLATES_DIR
    items = {
        "Affidavit_Annexure3_Draft": ["I, ____________ (name), Chairman / Secretary of ____________ Trust / Society, solemnly affirm:",
            "1. The information furnished in the AICTE application for 2026-27 is true and correct.",
            "2. The institution has the land, building and faculty as declared.", "3. No document submitted has been altered after issue.",
            "Deponent signature: ____________   Date: ____/____/______", "Notary seal and signature: ____________"],
        "Fire_NOC_Request_Letter_Draft": ["To, The Director, Fire and Rescue Services, ____________",
            "Subject: Request for Fire Safety NOC for academic premises", "Premises address: ____________  Built-up area: ______ sq.m",
            "Enclosures: approved building plan, fire-fighting equipment list, evacuation plan.", "Signature of Principal: ____________"],
        "Faculty_Details_Sheet_Draft": ["Department: ____________   Programme: ____________",
            "S.No | Faculty name | Designation | Qualification | PAN | Date of joining",
            "1 | | | | | ", "2 | | | | | ", "Certified by Registrar: ____________"],
        "Land_Document_Checklist_Draft": ["Attach: registered sale / lease deed (lease of 30+ years), encumbrance certificate, land-use certificate.",
            "Required fields: Survey No, Area (acres), Issued By (Sub-Registrar), Date of Issue, Valid Until.",
            "Upload the DSC-signed copy exactly as issued. Do not edit, merge or annotate signed PDFs."],
    }
    for name, lines in items.items():
        c = canvas.Canvas(str(T / f"{name}.pdf"), pagesize=A4)
        c.setFont("Helvetica-Bold", 15); c.drawString(20 * mm, A4[1] - 25 * mm, name.replace("_", " "))
        c.setFont("Helvetica", 9); c.drawString(20 * mm, A4[1] - 31 * mm, "Official-format DRAFT template (prototype). Fill, print on letterhead, sign.")
        y = A4[1] - 45 * mm; c.setFont("Helvetica", 11)
        for l in lines:
            c.drawString(20 * mm, y, l); y -= 9 * mm
        c.save()
        d = Docx(); d.add_heading(name.replace("_", " "), 1)
        d.add_paragraph("Official-format DRAFT template (prototype). Fill, print on letterhead, sign.")
        for l in lines:
            d.add_paragraph(l)
        d.save(str(T / f"{name}.docx"))


if __name__ == "__main__":
    main()
