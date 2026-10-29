"""AICTE Portal theme screenshots (43 onwards). Usage: python scripts/screenshots_portal.py [outdir] (BASE env, default :8000)."""
import os, sys, re
from playwright.sync_api import sync_playwright
BASE = os.environ.get("BASE", "http://localhost:8000"); OUT = sys.argv[1] if len(sys.argv) > 1 else "../screenshots"
os.makedirs(OUT, exist_ok=True); errs = []


def shot(pg, name, full=False):
    pg.wait_for_timeout(1200); pg.evaluate("window.scrollTo(0, 0)"); pg.wait_for_timeout(300); print(name, pg.evaluate("[scrollY, innerWidth, document.activeElement.tagName]")); pg.screenshot(path=f"{OUT}/{name}.png", full_page=full); print("saved", name)


def login(pg, email):
    pg.goto(BASE + "/login"); pg.wait_for_load_state("networkidle")
    pg.click(f'[data-testid="demo-{email}"]'); pg.wait_for_url(lambda u: "/login" not in u); pg.wait_for_load_state("networkidle")


with sync_playwright() as p:
    b = p.chromium.launch()
    def ctx(**kw):
        c = b.new_context(viewport={"width": 1440, "height": 900}, **kw)
        c.add_init_script("localStorage.setItem('sealcheck.theme','portal')")
        pg = c.new_page(); pg.on("pageerror", lambda e: errs.append(str(e))); pg.on("console", lambda m: m.type == "error" and errs.append(m.text)); return c, pg
    c, pg = ctx(); pg.goto(BASE + "/login"); pg.wait_for_load_state("networkidle"); shot(pg, "43_portal_login")
    login(pg, "principal.svit@sealcheck.demo"); shot(pg, "44_portal_college_dashboard"); c.close()
    c, pg = ctx(); login(pg, "officer@sealcheck.demo"); shot(pg, "45_portal_officer_dashboard")
    pg.goto(BASE + "/queue"); pg.wait_for_load_state("networkidle")
    pg.locator('main a[href^="/applications/"]').first.click(); pg.wait_for_load_state("networkidle")
    pg.locator("main li button").filter(has_text=re.compile(r"\.pdf")).first.click(); shot(pg, "46_portal_application_detail")
    pg.goto(BASE + "/security"); pg.wait_for_load_state("networkidle"); shot(pg, "47_portal_security_centre")
    pg.click('[data-testid="lang-hi"]'); pg.hover('nav[aria-label="Main"] button >> nth=0'); shot(pg, "49_portal_hindi_nav")
    pg.click('[data-testid="lang-en"]'); pg.click('[data-testid="high-contrast"]'); pg.click('[data-testid="font-inc"]'); pg.goto(BASE + "/"); shot(pg, "50_portal_high_contrast_large_text")
    pg.click('[data-testid="high-contrast"]'); pg.click('[data-testid="font-reset"]')
    pg.locator('button[aria-label="Toggle dark mode"]').first.click(); shot(pg, "51_portal_dark"); pg.locator('button[aria-label="Toggle dark mode"]').first.click(); c.close()
    c = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True)
    c.add_init_script("localStorage.setItem('sealcheck.theme','portal')")
    pg = c.new_page(); login(pg, "officer@sealcheck.demo"); shot(pg, "48_portal_mobile"); c.close()
    b.close()
print("errors:", errs)
