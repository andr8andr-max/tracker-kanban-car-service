# UI-смоук: проверка фронтенда в headless-браузере.
# Запуск: python tests/ui_smoke.py   (сервер должен быть на http://127.0.0.1:8000)
import sys

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
FAILED = []
ERRORS = []
STEP = ["init"]


def check(name, cond, info=""):
    STEP[0] = name
    print(f"[{'OK ' if cond else 'FAIL'}] {name} {info}", flush=True)
    if not cond:
        FAILED.append(name)


def run(page):
    # --- login
    page.goto(BASE)
    page.wait_for_selector("#login-form", timeout=15000)
    check("login page", page.locator(".login-title").count() == 1)
    page.fill("input[name=login]", "admin")
    page.fill("input[name=password]", "admin123")
    page.click("#login-form button[type=submit]")
    page.wait_for_selector(".shell", timeout=15000)
    check("shell after login", True)

    # --- board
    page.wait_for_selector(".column", timeout=15000)
    cols = page.locator(".column").count()
    check("board columns", cols >= 5, f"cols={cols}")
    cards = page.locator(".card").count()
    check("board cards", cards >= 1, f"cards={cards}")

    # --- filters / chips
    page.click("#chip-mine")
    page.wait_for_timeout(400)
    page.click("#chip-mine")
    page.wait_for_timeout(400)
    check("filters toggle", True)

    # --- open first order
    if cards:
        page.locator(".card").first.click()
        page.wait_for_selector(".order-head", timeout=10000)
        check("order page", True)
        for tab in ["works", "checklist", "time", "comments", "history", "vin", "main"]:
            page.click(f'#order-tabs .tab[data-tab="{tab}"]')
            page.wait_for_timeout(250)
            check(f"order tab {tab}", page.locator("#order-body").inner_html().strip() != "")

    # --- create order modal
    page.goto(BASE + "/#/")
    page.wait_for_selector(".board", timeout=10000)
    if page.locator("#btn-new").count():
        page.click("#btn-new")
        page.wait_for_selector(".modal", timeout=5000)
        check("create modal", True)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        check("escape closes modal", page.locator(".modal").count() == 0)

    # --- notifications
    page.goto(BASE + "/#/notifications")
    page.wait_for_selector("#nf-list", timeout=10000)
    check("notifications page", True)
    page.click("#nf-all")
    page.wait_for_timeout(500)
    check("notifications filter", True)

    # --- stats
    page.goto(BASE + "/#/stats")
    page.wait_for_selector("#st-body .stat-card", timeout=10000)
    check("stats page", page.locator("#st-body .stat-card").count() >= 4)
    page.click("#st-reset")
    page.wait_for_timeout(600)
    check("stats reset", page.locator("#st-body .stat-card").count() >= 4)

    # --- profile
    page.goto(BASE + "/#/profile")
    page.wait_for_selector("#pf-save", timeout=10000)
    check("profile page", True)
    page.click("#pf-pwd")
    page.wait_for_selector("#pw-save", timeout=5000)
    check("password modal", True)
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    check("password modal closed", page.locator(".modal").count() == 0)

    # --- admin tabs
    admin_tabs = ["users", "roles", "statuses", "worktypes", "checklists",
                  "templates", "settings", "telegram", "backup", "audit", "trash"]
    for tab in admin_tabs:
        page.goto(BASE + "/#/admin/" + tab)
        page.wait_for_timeout(800)
        body = page.locator("#adm-body").inner_html().strip()
        ok = body != "" and "alert-danger" not in body
        check(f"admin tab {tab}", ok, f"len={len(body)}")

    # --- settings interactions
    page.goto(BASE + "/#/admin/settings")
    page.wait_for_selector("#se-save", timeout=10000)
    check("settings form", page.locator(".nm-cb").count() > 0 and page.locator("#cr-list .form-row").count() > 0)

    # --- users interactions
    page.goto(BASE + "/#/admin/users")
    page.wait_for_selector("#u-add", timeout=10000)
    page.click("#u-add")
    page.wait_for_selector("#um-save", timeout=5000)
    check("create user modal", True)
    page.keyboard.press("Escape")

    # --- language switch via user menu
    page.goto(BASE + "/#/")
    page.wait_for_selector(".shell", timeout=10000)
    page.click("#userchip")
    page.wait_for_timeout(300)
    page.click('.dropdown-menu [data-lang="en"]')
    page.wait_for_timeout(1500)
    board_text = page.inner_html(".board") if page.locator(".board").count() else ""
    check("EN switch", "New order" in page.content() or "board" in board_text.lower(), "lang=en")
    default_lang = page.evaluate(
        "fetch('/api/me').then(r=>r.json()).then(d=>(d.user&&d.user.settings&&d.user.settings.default_lang)||'ru')"
    )
    page.click("#userchip")
    page.wait_for_timeout(300)
    page.click(f'.dropdown-menu [data-lang="{default_lang}"]')
    page.wait_for_timeout(1500)


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.on("console", lambda m: ERRORS.append(f"[{STEP[0]}] console.{m.type}: {m.text}") if m.type == "error" else None)
    page.on("pageerror", lambda e: ERRORS.append(f"[{STEP[0]}] pageerror: {e} | {getattr(e, 'stack', '')}"))
    try:
        run(page)
    except Exception as e:  # noqa: BLE001
        check("run completed", False, str(e)[:200])
    finally:
        browser.close()

print("\n--- console/page errors ---")
seen = set()
for e in ERRORS:
    if e not in seen:
        seen.add(e)
        print(" ", e)
if not ERRORS:
    print("  none")

print(f"\nfailed: {len(FAILED)}")
for f in FAILED:
    print("  FAIL:", f)
sys.exit(1 if FAILED else 0)
