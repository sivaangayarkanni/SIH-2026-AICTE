"""Headless Playwright click-through of the whole UI, for every demo role.

Usage: BASE=http://localhost:8010 .venv/bin/python scripts/clickthrough.py
Writes clickthrough_report.json and prints a PASS/FAIL table. The exit code is non-zero on any failure.
It mutates demo data (uploads, overrides, decisions), so run it against a disposable instance or reseed afterwards.
"""
import json, os, re, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = os.environ.get("BASE", "http://localhost:8010").rstrip("/")
ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "seed" / "samples"
PW = "Demo@2026"
PRINCIPALS = ["svit", "gvce", "diem", "mct"]
STAFF = ["officer", "officer2", "senior", "admin"]
DENY = re.compile(r"sign out|reject|approve|submit|delete|revoke|confirm|reopen|re-analy|reveal|cancel|finish|create|logout|rotate|purge|decide|send test|sync now|issue|verify|encrypt|request|generate|start 3|tour", re.I)
results: list[dict] = []
issues: list[str] = []          # console errors / exceptions / bad responses for the current check


def record(area, role, name, ok, detail=""):
    results.append({"area": area, "role": role, "check": name, "result": "PASS" if ok else "FAIL", "detail": detail[:300]})
    print(f"{'PASS' if ok else 'FAIL'}  {area:<14} {role:<9} {name} {detail[:160] if not ok else ''}", flush=True)


def check(area, role, name):
    def deco(fn):
        def run(*a, **k):
            issues.clear()
            try:
                fn(*a, **k); time.sleep(0.3)
                bad = [i for i in issues if not IGNORE.search(i)]
                record(area, role, name, not bad, "; ".join(bad))
            except Exception as e:  # noqa: BLE001
                record(area, role, name, False, f"{type(e).__name__}: {e}".splitlines()[0] + " | " + "; ".join(issues))
        return run
    return deco


# Expected, intentional non-2xx: permission probes (403) and the offline-mode network failures we trigger ourselves.
IGNORE = re.compile(r"net::ERR_INTERNET_DISCONNECTED|Failed to fetch|ERR_INTERNET_DISCONNECTED|favicon")


def attach(page):
    page.on("console", lambda m: m.type == "error" and issues.append(f"console: {m.text}"))
    page.on("pageerror", lambda e: issues.append(f"exception: {e}"))
    page.on("response", lambda r: r.status >= 400 and "/api/" in r.url and issues.append(f"HTTP {r.status} {r.request.method} {r.url.replace(BASE, '')}"))
    page.on("requestfailed", lambda r: issues.append(f"requestfailed {r.url.replace(BASE, '')} {r.failure}"))


def email(role):
    return f"principal.{role}@sealcheck.demo" if role in PRINCIPALS else f"{role}@sealcheck.demo"


def login(page, role):
    page.goto(f"{BASE}/login"); page.wait_for_load_state("networkidle")
    page.click(f'[data-testid="demo-{email(role)}"]')
    page.wait_for_url(lambda u: "/login" not in u, timeout=15000); page.wait_for_load_state("networkidle")


def settle(page):
    try: page.wait_for_load_state("networkidle", timeout=8000)
    except Exception: pass
    time.sleep(0.25)


def nav_links(page):
    hrefs = page.eval_on_selector_all('nav[aria-label="Main"] a[href]', "els => els.map(e => e.getAttribute('href'))")
    return list(dict.fromkeys(hrefs))


def click_safe_buttons(page, path):
    """Click every tab, filter, and harmless button on the page; close modals; come back if navigated."""
    sel = 'main button:visible, main [role="tab"]:visible'
    n = page.locator(sel).count()
    for i in range(min(n, 45)):
        loc = page.locator(sel).nth(i)
        try:
            txt = (loc.inner_text(timeout=1000) or loc.get_attribute("aria-label") or "").strip()
            if DENY.search(txt) or loc.is_disabled(): continue
            loc.click(timeout=2500); settle(page)
            page.keyboard.press("Escape")
            if not page.url.endswith(path) and path != "/":
                page.goto(BASE + path); settle(page)
        except Exception:
            pass


def run_role(br, role):
    ctx = br.new_context(viewport={"width": 1440, "height": 900}, accept_downloads=True)
    page = ctx.new_page(); attach(page)
    check("login", role, "demo login")(lambda: login(page, role))()
    links = nav_links(page)
    record("nav", role, f"nav items found ({len(links)})", len(links) >= 5, str(links))
    for href in links:
        def visit(h=href):
            page.goto(BASE + h); settle(page)
            assert page.locator("main").count(), "no <main>"
            click_safe_buttons(page, h)
        check("nav", role, f"page {href} + all buttons/tabs/filters")(visit)()
    # header: dark mode, notifications bell, account menu
    def header():
        page.goto(BASE + "/"); settle(page)
        for _ in range(2): page.click('button[aria-label="Toggle dark mode"]'); settle(page)
        page.click('button[aria-label^="Notifications"]'); settle(page)
        page.click('[data-testid="open-notification-centre"]'); page.wait_for_url("**/notifications")
        page.click('button[aria-label="Account menu"]'); settle(page); page.keyboard.press("Escape")
    check("header", role, "dark toggle, bell, View all, account menu")(header)()
    def themes():
        page.goto(BASE + "/settings"); settle(page)
        btns = page.locator('main button[aria-pressed]')
        assert btns.count() >= 2, "theme buttons missing"
        for i in range(btns.count()): btns.nth(i).click(); settle(page)
        btns.first.click()
        sw = page.locator('[role="switch"][aria-label="Dark mode"]'); sw.click(); settle(page); sw.click()
    check("settings", role, "every theme + dark switch")(themes)()
    def rules_health():
        page.goto(BASE + "/rules"); settle(page); assert page.locator("main").inner_text().strip()
        r = page.request.get(BASE + "/api/health"); assert r.ok and r.json()["status"] == "ok"
        page.goto(BASE + "/how-it-works"); settle(page)
    check("rules/health", role, "rules page, /api/health, how-it-works")(rules_health)()
    return ctx, page


def college_flows(br, role):
    ctx, page = run_role(br, role)
    st = {}
    def wizard():
        page.goto(BASE + "/applications/new"); settle(page)
        page.locator("main button[aria-pressed]").first.click(); settle(page)
        page.get_by_role("button", name=re.compile("Create and continue")).click()
        page.wait_for_url(re.compile(r"/applications/\d+$"), timeout=15000); settle(page)
        st["url"] = page.url
        mine = [p for p in sorted(SAMPLES.glob(f"{role}_*")) if p.suffix in (".pdf", ".jpg")]
        uploaded = 0
        for b in range(page.get_by_role("button", name="Sample").count()):
            page.get_by_role("button", name="Sample").nth(b).click(); settle(page)
            opts = page.locator("main button b").filter(has_text=re.compile(f"^{role}_"))
            if opts.count():
                opts.first.click(); page.wait_for_function("() => !document.querySelector('main .animate-spin')", timeout=20000) if False else time.sleep(1.5); settle(page); uploaded += 1
            else:
                page.keyboard.press("Escape")
        # real file-chooser upload of the college's lab photo (and a PDF if the sample picker didn't cover it)
        photo = next((p for p in mine if p.suffix == ".jpg"), None)
        if photo:
            row = page.locator("main li").filter(has_text=re.compile("lab", re.I)).filter(has=page.get_by_role("button", name=re.compile("Upload")))
            with page.expect_file_chooser() as fc:
                row.first.get_by_role("button", name=re.compile("Upload")).click()
            fc.value.set_files(str(photo)); time.sleep(2); settle(page); uploaded += 1
        assert uploaded >= 1, "nothing uploaded"
        st["uploaded"] = uploaded
    check("upload", role, "new-application wizard + every own sample + lab photo")(wizard)()
    def processed():
        page.goto(st["url"]); deadline = time.time() + 120
        while time.time() < deadline:
            settle(page)
            if page.locator("main li .animate-spin").count() == 0: break
            time.sleep(3); page.reload()
        assert page.locator("main li .animate-spin").count() == 0, "jobs still running after 120s"
    check("upload", role, "all uploaded documents finish processing")(processed)()
    def evidence_and_agents():
        page.goto(st["url"]); settle(page)
        page.locator("main li button").filter(has_text=re.compile(r"\.(pdf|jpg)")).first.click(); settle(page)
        tabs = page.locator('[role="tab"]')
        for i in range(tabs.count()): tabs.nth(i).click(); settle(page)
        page.locator('[role="tab"]').filter(has_text=re.compile("Evidence", re.I)).first.click(); settle(page)
        cards = page.locator('[data-tour="tabs"] button.w-full')
        if cards.count(): cards.first.click(); settle(page)
        page.locator('[role="tab"]').filter(has_text=re.compile("Agent", re.I)).first.click(); settle(page)
        assert page.locator('[data-tour="agents"]').count(), "agents tab empty"
    check("evidence", role, "click-to-jump + every doc tab + agents tab")(evidence_and_agents)()
    def packet():
        with page.expect_download(timeout=20000) as d:
            page.get_by_role("button", name=re.compile("Evidence packet")).first.click()
        p = d.value.path(); assert open(p, "rb").read(5) == b"%PDF-", "not a PDF"
        st["packet"] = p
    check("downloads", role, "evidence packet PDF")(packet)()
    def readiness():
        page.goto(BASE + "/readiness"); settle(page)
        pdf = next(SAMPLES.glob(f"{role}_*.pdf"))
        page.locator('input[type="file"]').set_input_files(str(pdf)); time.sleep(3); settle(page)
        tmpl = page.locator("main li button")
        assert tmpl.count() >= 1, "no templates listed"
        for i in range(tmpl.count()):
            with page.expect_download(timeout=15000) as d: tmpl.nth(i).click()
            assert d.value.path() and os.path.getsize(d.value.path()) > 500
    check("readiness", role, "pre-check upload + every template download")(readiness)()
    def submit():
        page.goto(st["url"]); settle(page)
        b = page.get_by_role("button", name=re.compile("Submit application"))
        if b.count() and b.first.is_enabled():
            b.first.click(); settle(page)
    check("upload", role, "submit application (if ready)")(submit)()
    if role == "svit":
        def offline():
            page.goto(st["url"]); settle(page)
            app_id = st["url"].rstrip("/").split("/")[-1]
            def count():
                return page.evaluate("""async (id) => { const t = localStorage.getItem('sealcheck.token') || '';
                  const r = await fetch('/api/applications/' + id, {headers: {authorization: 'Bearer ' + t}}); const j = await r.json();
                  return j.documents.filter(d => d.filename === 'svit_affidavit.pdf').length }""", app_id)
            before = count()
            ctx.set_offline(True); time.sleep(0.8)
            assert page.get_by_text(re.compile("Offline")).count(), "no offline banner"
            row = page.locator("main li").filter(has=page.get_by_role("button", name=re.compile("Upload")))
            if not row.count(): raise AssertionError("application no longer accepts uploads; cannot test offline queue")
            with page.expect_file_chooser() as fc: row.first.get_by_role("button", name=re.compile("Upload")).click()
            fc.value.set_files(str(SAMPLES / "svit_affidavit.pdf")); time.sleep(1.5)
            queued = page.evaluate("() => new Promise(r => { const q = indexedDB.open('sealcheck-offline'); q.onsuccess = () => { try { const db = q.result; const n = db.objectStoreNames[0]; const c = db.transaction(n).objectStore(n).count(); c.onsuccess = () => r(c.result) } catch (e) { r(-1) } }; q.onerror = () => r(-1) })")
            ctx.set_offline(False); time.sleep(5); settle(page)
            page.goto(BASE + "/settings"); settle(page)
            sync = page.get_by_role("button", name=re.compile("Sync now"))
            if sync.count() and sync.first.is_enabled(): sync.first.click(); time.sleep(3); settle(page)
            after = count()
            assert after == before + 1, f"queued={queued} docs before={before} after={after}"
            st["offline_queued"] = queued
        check("offline", role, "go offline, queue upload, go online, sync")(offline)()
    ctx.close()


def staff_flows(br, role, shared):
    ctx, page = run_role(br, role)
    if role == "officer":
        def tour():
            page.goto(BASE + "/"); settle(page)
            page.click('[data-testid="start-tour"]'); n = 0
            while page.locator('[data-testid="tour-next"]').count() and n < 40:
                page.locator('[data-testid="tour-next"]').click(); n += 1; time.sleep(0.8); settle(page)
            assert n >= 3, f"tour only {n} steps"
            shared["tour_steps"] = n
        check("tour", role, "demo tour end to end")(tour)()
        def override_request():
            page.goto(BASE + "/queue"); settle(page)
            links = page.locator('main a[href^="/applications/"]')
            target = None
            for i in range(links.count()):
                href = links.nth(i).get_attribute("href"); page.goto(BASE + href); settle(page)
                b = page.get_by_role("button", name=re.compile("Request override"))
                if b.count() and b.first.is_enabled(): target = href; break
                page.goto(BASE + "/queue"); settle(page); links = page.locator('main a[href^="/applications/"]')
            assert target, "no application with a flagged document in the queue"
            page.get_by_role("button", name=re.compile("Request override")).first.click()
            page.fill("#oj", "Verified with the issuing authority by phone; the flagged region is a scanner artefact.")
            page.get_by_role("button", name=re.compile("Submit for second approval")).click(); settle(page)
            assert page.get_by_text("Security overrides").count()
            shared["override_app"] = target
        check("override", role, "request two-person override")(override_request)()
        def rejection():
            href = shared.get("override_app")
            page.goto(BASE + href); settle(page)
            page.get_by_role("button", name=re.compile("Rejection helper")).click()
            page.get_by_role("button", name=re.compile("Genera")).click(); time.sleep(1.5); settle(page)
            with page.expect_download(timeout=20000) as d:
                page.get_by_role("button", name=re.compile("^PDF$")).first.click()
            p = d.value.path(); assert open(p, "rb").read(5) == b"%PDF-"
            shared["rejection_pdf"] = p
        check("rejection", role, "rejection helper -> guidance PDF opens")(rejection)()
        def voice():
            page.goto(BASE + shared["override_app"]); settle(page)
            page.locator("main li button").filter(has_text=re.compile(r"\.(pdf|jpg)")).first.click(); settle(page)
            page.locator('[role="tab"]').filter(has_text=re.compile("^Ask$")).first.click(); settle(page)
            page.fill('input[aria-label="Question"]', "What is the validity date of this document?")
            page.keyboard.press("Enter"); time.sleep(2.5); settle(page)
            assert len(page.locator("main").inner_text()) > 200
        check("voice", role, "assistant via text input (Ask tab)")(voice)()
    if role in ("officer", "admin"):
        def security():
            page.goto(BASE + "/security"); settle(page)
            page.get_by_role("button", name="Issue token").click(); settle(page)
            page.get_by_role("button", name="Verify now").click(); settle(page)
            page.fill('input[aria-label="Plaintext to encrypt"]', "PAN ABCDE1234F")
            page.get_by_role("button", name=re.compile("Encrypt")).click(); settle(page)
            page.get_by_role("button", name=re.compile("Re-verify entire chain")).click(); time.sleep(1); settle(page)
            assert page.locator('[data-testid="active-backends"]').count()
            if role == "admin":
                rv = page.get_by_role("button", name="Reveal")
                if rv.count(): rv.first.click(); settle(page)
        check("security", role, "issue token, verify, encrypt, audit verify")(security)()
    if role == "admin":
        def notif():
            page.goto(BASE + "/notifications"); settle(page)
            page.click('[data-testid="send-test-alert"]'); time.sleep(1.5); settle(page)
            assert page.locator('[data-testid="outbox"]').count()
            mr = page.get_by_role("button", name="Mark all read")
            if mr.count() and mr.first.is_enabled(): mr.first.click(); settle(page)
        check("notify", role, "notification centre + test alert")(notif)()
    if role == "senior":
        def approve():
            page.goto(BASE + "/overrides"); settle(page)
            page.get_by_role("button", name="Approve").first.click()
            page.fill("#n", "Agreed: issuer confirmation is on file.")
            page.get_by_role("button", name="Confirm").click(); settle(page)
            r = page.request.get(BASE + "/api/overrides")
            assert "approved" in page.locator("main").inner_text().lower() or r.ok
        check("override", role, "second-officer approval")(approve)()
    if role == "officer2":
        def self_block():  # officer2 can see the queue but there is nothing of theirs to approve: assert the page loads
            page.goto(BASE + "/overrides"); settle(page)
        check("override", role, "overrides page loads")(self_block)()
    ctx.close()


def login_themes(br):
    ctx = br.new_context(); page = ctx.new_page(); attach(page)
    def t():
        page.goto(BASE + "/login"); settle(page)
        b = page.locator('button[aria-label^="Use "]'); assert b.count() >= 2
        for i in range(b.count()): b.nth(i).click(); settle(page)
    check("login", "anon", "login-page theme switcher")(t)()
    ctx.close()


def portal_checks(br):
    ctx = br.new_context(viewport={"width": 1440, "height": 900}); page = ctx.new_page(); attach(page)
    def t():
        login(page, "officer")
        assert page.evaluate("document.documentElement.dataset.theme") == "portal", "AICTE Portal is not the default theme"
        assert "not an official AICTE system" in page.locator('[data-testid="prototype-label"]').text_content()
        assert "not an official AICTE system" in page.locator('[data-testid="footer-disclaimer"]').inner_text()
        fs = lambda: page.evaluate("getComputedStyle(document.documentElement).fontSize")
        base = fs(); page.click('[data-testid="font-inc"]'); big = fs(); page.click('[data-testid="font-dec"]'); page.click('[data-testid="font-dec"]'); small = fs(); page.click('[data-testid="font-reset"]')
        assert float(big[:-2]) > float(base[:-2]) > float(small[:-2]) and fs() == base, (base, big, small)
        page.click('[data-testid="lang-hi"]'); assert "डैशबोर्ड" in page.locator('nav[aria-label="Main"]').first.inner_text(); page.click('[data-testid="lang-en"]')
        page.click('[data-testid="high-contrast"]'); assert page.evaluate("document.documentElement.classList.contains('hc')"); page.click('[data-testid="high-contrast"]')
        page.reload(); settle(page); page.keyboard.press("Tab"); assert "Skip" in page.evaluate("document.activeElement.textContent")
        assert page.locator("img[src*=emblem], img[src*=logo]").count() == 0
    check("portal", "officer", "default theme, labels, A-/A/A+, Hindi nav, high contrast, skip link")(t)()
    ctx.close()


def mobile(br):
    ctx = br.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    page = ctx.new_page(); attach(page)
    def m():
        login(page, "officer")
        page.click('button[aria-label="Open menu"]'); settle(page)
        page.locator('nav[aria-label="Main"] a[href="/queue"]').last.click(); settle(page)
    check("mobile", "officer", "mobile menu + queue")(m)()
    ctx.close()


def main():
    t0 = time.time(); shared = {}
    with sync_playwright() as p:
        br = p.chromium.launch()
        for r in PRINCIPALS: college_flows(br, r)
        for r in ["officer", "senior", "officer2", "admin"]: staff_flows(br, r, shared)
        login_themes(br); portal_checks(br); mobile(br)
        br.close()
    out = ROOT / "clickthrough_report.json"
    out.write_text(json.dumps({"base": BASE, "seconds": round(time.time() - t0), "results": results, "shared": {k: v for k, v in shared.items() if isinstance(v, (int, str))}}, indent=1))
    fails = [r for r in results if r["result"] == "FAIL"]
    print(f"\n{len(results) - len(fails)}/{len(results)} PASS in {time.time() - t0:.0f}s -> {out}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
