"""Desktop pass: logs in to an account that already has data and walks the sidebar."""
import os

from playwright.sync_api import sync_playwright, expect

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=os.environ.get("CHROME"), args=["--no-sandbox"])
    page = b.new_page(viewport={"width": 1360, "height": 900})
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto("http://localhost:4173/")
    page.get_by_label("Phone number").fill("9876543210")
    page.get_by_label("PIN").fill("4321")
    page.get_by_role("button", name="Log in").click()
    nav = page.get_by_role("navigation", name="Main")
    expect(nav.get_by_role("button", name="All projects")).to_have_attribute("aria-current", "page")
    page.screenshot(path="shots/web-1-projects.png", full_page=True)

    page.get_by_role("button", name="Glisan Hospital").click()
    expect(nav.get_by_role("button", name="Home")).to_have_attribute("aria-current", "page")
    expect(page.get_by_text("Latest entries")).to_be_visible()
    expect(page.get_by_role("button", name="Back")).to_be_hidden()
    page.screenshot(path="shots/web-2-home.png", full_page=True)

    nav.get_by_role("button", name="Dues").click()
    expect(page.get_by_text("Total to receive")).to_be_visible()
    page.get_by_role("button", name="To pay", exact=True).click()
    expect(page.get_by_text("Medi Distributors")).to_be_visible()
    page.screenshot(path="shots/web-3-dues.png", full_page=True)

    nav.get_by_role("button", name="Record expense").click()
    expect(page.get_by_label("Amount")).to_be_visible()
    page.screenshot(path="shots/web-4-expense.png", full_page=True)

    nav.get_by_role("button", name="All projects").click()
    expect(page.get_by_role("heading", name="All projects")).to_be_visible()
    w = page.evaluate("document.documentElement.scrollWidth")
    assert w <= 1360, f"page scrolls sideways: {w}"
    print("DESKTOP OK; console errors:", errors)
    b.close()
