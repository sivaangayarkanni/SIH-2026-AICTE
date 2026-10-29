"""Extra screenshots that need a differently-configured server (see scripts/screenshots_extra.sh).
  oidc   -> BASE=http://localhost:8001, AUTH_MODE=oidc against devtools/mock_oidc.py (MOCK IdP, not Keycloak)
  vision -> BASE=http://localhost:8002, VISION_BACKEND=models (DINOv2 + RT-DETR + LightGlue, synthetic photos)
Usage: python scripts/screenshots_extra.py oidc|vision out_dir"""
import base64, hashlib, hmac, struct, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright

mode, OUT = sys.argv[1], Path(sys.argv[2]); OUT.mkdir(parents=True, exist_ok=True)
errors = []


def totp(secret="JBSWY3DPEHPK3PXP"):
    h = hmac.new(base64.b32decode(secret), struct.pack(">Q", int(time.time() // 30)), hashlib.sha1).digest(); o = h[-1] & 15
    return str((struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % 10 ** 6).zfill(6)


def shot(page, name, wait=900):
    page.wait_for_timeout(wait); page.screenshot(path=str(OUT / f"{name}.png")); print("saved", name)


with sync_playwright() as p:
    b = p.chromium.launch(); page = b.new_page(viewport={"width": 1440, "height": 900})
    page.on("pageerror", lambda e: errors.append(str(e)))
    if mode == "oidc":
        BASE = "http://localhost:8001"
        page.goto(f"{BASE}/login"); page.evaluate("localStorage.clear()"); page.goto(f"{BASE}/login")
        page.wait_for_selector("[data-testid=sso-login]"); shot(page, "37_oidc_login")
        page.click("[data-testid=sso-login]"); page.wait_for_selector("#otp")
        page.select_option("#email", "officer@sealcheck.demo"); shot(page, "38_oidc_mock_idp_mfa", wait=300)
        page.fill("#otp", totp()); page.keyboard.press("Enter")
        page.wait_for_url(f"{BASE}/", timeout=20000); shot(page, "39_oidc_signed_in_officer", wait=1500)
    else:
        BASE = "http://localhost:8002"
        page.goto(f"{BASE}/login"); page.evaluate("localStorage.clear()"); page.goto(f"{BASE}/login")
        page.click("[data-testid='demo-officer@sealcheck.demo']"); page.wait_for_url(f"{BASE}/"); page.wait_for_timeout(800)
        page.goto(f"{BASE}/applications"); page.wait_for_timeout(1200)
        page.locator("text=AICTE-26-DIEM").first.click(); page.wait_for_selector("text=Evidence packet", timeout=20000)
        page.click("text=diem_lab_reused.jpg"); page.wait_for_timeout(1200); page.click("role=tab[name=/4C/]"); shot(page, "40_vision_models_photo_reuse", wait=1500)
        page.mouse.wheel(0, 700); shot(page, "41_vision_models_detections", wait=800)
        page.goto(f"{BASE}/security"); page.wait_for_selector("[data-testid=active-backends]"); page.locator("[data-testid=active-backends]").scroll_into_view_if_needed(); shot(page, "42_security_backends_models")
    b.close()
print("errors:", errors)
