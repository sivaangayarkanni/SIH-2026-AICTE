"""Capture screenshots of key flows (1440x900 unless noted). Usage: python scripts/screenshots.py [out_dir]
Run against a freshly seeded server (RESEED=1 ./run.sh): it uploads, requests an override and generates guidance."""
import subprocess, sys
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright

BASE = "http://localhost:8000"
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "screenshots"); OUT.mkdir(parents=True, exist_ok=True)
errors = []
ids = {}


def login(page, email):
    page.goto(f"{BASE}/login"); page.evaluate("localStorage.removeItem('sealcheck.token'); localStorage.removeItem('sealcheck.tour')"); page.goto(f"{BASE}/login")
    page.click(f"[data-testid='demo-{email}']"); page.wait_for_url(f"{BASE}/"); page.wait_for_timeout(1200)


def shot(page, name, full=False, wait=900):
    page.wait_for_timeout(wait); page.screenshot(path=str(OUT / f"{name}.png"), full_page=full); print("saved", name)


def theme(page, t, mode="light"):
    page.evaluate(f"localStorage.setItem('sealcheck.theme','{t}'); localStorage.setItem('sealcheck.mode','{mode}')")


def open_app(page, ref):
    page.goto(f"{BASE}/applications/{ids[ref]}"); page.wait_for_selector("text=Evidence packet", timeout=20000); page.wait_for_timeout(800)


with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    page.on("console", lambda m: m.type == "error" and errors.append(m.text))
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{BASE}/login"); page.evaluate("localStorage.clear()"); page.goto(f"{BASE}/login"); page.wait_for_selector("[data-testid^='demo-']"); shot(page, "01_login")
    login(page, "principal.gvce@sealcheck.demo"); shot(page, "02_college_dashboard")
    page.goto(f"{BASE}/readiness"); page.wait_for_timeout(600)
    page.set_input_files("input[type=file]", "seed/samples/gvce_land_lease_forged.pdf"); page.wait_for_selector("text=Predicted", timeout=30000); shot(page, "03_readiness_precheck")
    login(page, "officer@sealcheck.demo")
    tok = page.evaluate("localStorage.getItem('sealcheck.token')")
    apps = httpx.get(f"{BASE}/api/applications", headers={"Authorization": f"Bearer {tok}"}).json()
    apps = apps["items"] if isinstance(apps, dict) else apps
    for a in apps:
        ids[a["ref"].split("-")[2]] = a["id"]
    shot(page, "04_officer_dashboard")
    page.goto(f"{BASE}/queue"); shot(page, "05_priority_queue")
    open_app(page, "GVCE"); page.locator("img[alt^='Page 1']").wait_for(); shot(page, "06_application_evidence", wait=1200)
    page.click("role=tab[name=/Agents/]"); page.wait_for_timeout(600); page.locator("[data-tour=agents]").evaluate("e => e.scrollIntoView({block: 'start'})"); shot(page, "07_agents_debate")
    page.click("role=tab[name=/4A/]"); shot(page, "08_forensics_4a")
    page.click("role=tab[name=/Ask/]"); page.wait_for_timeout(500)
    page.fill("input[aria-label=Question]", "Why was this document flagged?"); page.click("button[aria-label=Ask]")
    page.wait_for_selector("text=Show on page", timeout=15000); page.click("text=Show on page"); shot(page, "15_voice_assistant_qa", wait=1200)
    page.locator("[data-tour=override]").evaluate("e => { e.scrollIntoView({block: 'center'}); e.click() }"); page.fill("#oj", "Called the Sub-Registrar office, Varanasi on 28 Oct; registry entry matches the lease number and parties.")
    shot(page, "16_override_modal", wait=500)
    page.click("text=Submit for second approval"); page.wait_for_timeout(1200)
    page.locator("button:has-text('Rejection helper')").evaluate("e => { e.scrollIntoView({block: 'center'}); e.click() }"); shot(page, "17_rejection_helper_modal", wait=500)
    page.click("text=Generate guidance"); page.wait_for_timeout(1500)
    pdf = httpx.get(f"{BASE}/api/applications/{ids['GVCE']}/rejection.pdf", headers={"Authorization": f"Bearer {tok}"}).content
    (OUT / "_guidance.pdf").write_bytes(pdf)
    subprocess.run(["pdftoppm", "-png", "-r", "70", "-f", "2", "-l", "2", str(OUT / "_guidance.pdf"), str(OUT / "_g")], check=True)
    g = sorted(OUT.glob("_g*.png"))[0]
    page.set_content(f"<html><body style='margin:0;background:#525659;display:flex;justify-content:center;padding:24px'><img src='data:image/png;base64,{__import__('base64').b64encode(g.read_bytes()).decode()}' style='height:850px;box-shadow:0 4px 30px #0008'></body></html>")
    shot(page, "18_rejection_helper_highlighted_pdf", wait=300)
    for f in [OUT / "_guidance.pdf", *OUT.glob("_g*.png")]:
        f.unlink()
    page.goto(f"{BASE}/collusion"); page.wait_for_timeout(1500); shot(page, "09_collusion_graph")
    page.goto(f"{BASE}/security"); page.click("text=Issue token"); shot(page, "10_security_center")
    page.goto(f"{BASE}/audit"); shot(page, "11_audit_log")
    page.goto(f"{BASE}/applications"); shot(page, "31_all_applications")
    page.goto(f"{BASE}/overrides"); shot(page, "32_security_overrides")
    page.goto(f"{BASE}/rules"); shot(page, "33_rule_bundles")
    page.goto(f"{BASE}/how-it-works"); shot(page, "12_how_it_works")
    theme(page, "emerald", "dark"); page.goto(f"{BASE}/settings"); shot(page, "13_settings_emerald_dark")
    theme(page, "saffron"); open_app(page, "DIEM")
    page.click("text=diem_lab_reused.jpg"); page.wait_for_timeout(1200); page.click("role=tab[name=/4C/]"); shot(page, "14_saffron_photo_reuse")
    for i, t in enumerate(["aicte", "emerald", "indigo", "saffron"]):
        theme(page, t); page.goto(f"{BASE}/"); page.wait_for_selector("text=Awaiting decision"); shot(page, f"{19 + i}_theme_{t}", wait=1500)
    theme(page, "portal")
    # demo tour: start from dashboard, advance to the evidence step
    page.goto(f"{BASE}/"); page.click("[data-testid=start-tour]"); page.wait_for_selector("text=step 1 of", timeout=8000); shot(page, "23_demo_tour_queue", wait=1200)
    page.click("[data-testid=tour-next]"); page.click("[data-testid=tour-next]"); page.wait_for_selector("text=step 3 of"); page.locator("img[alt^='Page 1']").wait_for(); shot(page, "24_demo_tour_evidence", wait=1500)
    page.click("[aria-label='End tour']")
    # live pipeline on a college upload
    login(page, "principal.mct@sealcheck.demo"); page.goto(f"{BASE}/applications/{ids['MCT']}"); page.wait_for_timeout(1500)
    page.locator("button[title='Use a synthetic demo file']").first.click(); page.wait_for_timeout(300)
    page.locator("text=expected:").first.click()
    try: page.wait_for_selector("[data-tour=pipeline] .animate-spin", timeout=10000); page.wait_for_timeout(250)
    except Exception as e: errors.append(f"25_upload_live_pipeline: spinner not seen ({e.__class__.__name__})")
    page.screenshot(path=str(OUT / "25_upload_live_pipeline.png")); print("saved 25_upload_live_pipeline")
    page.goto(f"{BASE}/applications/new"); shot(page, "35_new_application")
    login(page, "admin@sealcheck.demo")
    page.goto(f"{BASE}/notifications"); page.wait_for_selector("[data-testid=send-test-alert]"); page.click("[data-testid=send-test-alert]"); page.wait_for_timeout(1500)
    page.goto(f"{BASE}/notifications"); page.wait_for_selector("[data-testid=outbox]"); shot(page, "29_notification_centre")
    page.goto(f"{BASE}/security"); page.wait_for_selector("[data-testid=active-backends]"); page.locator("[data-testid=active-backends]").scroll_into_view_if_needed(); shot(page, "30_security_active_backends")
    page.goto(f"{BASE}/admin"); shot(page, "34_system_health")
    # 1280x720 login + mobile
    for name, vp, path, who in [("26_login_1280x720", (1280, 720), "/login", None), ("27_mobile_login", (390, 844), "/login", None),
                                ("28_mobile_college_dashboard", (390, 844), "/", "principal.gvce@sealcheck.demo"),
                                ("36_application_detail_1280x720", (1280, 720), "/applications/" + str(ids.get("GVCE", "")), "officer@sealcheck.demo")]:
        c2 = b.new_context(viewport={"width": vp[0], "height": vp[1]}, device_scale_factor=2 if vp[0] < 500 else 1, is_mobile=vp[0] < 500, has_touch=vp[0] < 500)
        p2 = c2.new_page(); p2.on("pageerror", lambda e: errors.append(str(e)))
        if who:
            login(p2, who); p2.wait_for_timeout(500)
            if path != "/": p2.goto(f"{BASE}{path}"); p2.wait_for_selector("text=Evidence packet", timeout=20000)
            if p2.locator("[aria-label='Dismiss']").count(): p2.locator("[aria-label='Dismiss']").first.click()
        else: p2.goto(f"{BASE}{path}"); p2.wait_for_selector("[data-testid^='demo-']")
        shot(p2, name); c2.close()
    b.close()
print("console errors:", errors)
