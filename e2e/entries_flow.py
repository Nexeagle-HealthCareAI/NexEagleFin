"""Entries screen through the browser on a fresh database: filter, open, cancel, close and reopen a month."""
import os

from playwright.sync_api import sync_playwright, expect

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=os.environ.get("CHROME"), args=["--no-sandbox"])
    page = b.new_page(viewport={"width": 390, "height": 844})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto("http://localhost:4173/")
    page.get_by_label("Phone number").fill("9876543210")
    page.get_by_label("PIN").fill("4321")
    page.get_by_role("button", name="Log in").click()
    page.get_by_role("button", name="New project").click()
    page.get_by_label("Project name").fill("Glisan Hospital")
    page.get_by_role("button", name="Create project").click()
    page.get_by_role("button", name="Glisan Hospital").click()

    page.get_by_role("button", name="Record expense").click()
    page.get_by_label("Amount").fill("4850")
    page.get_by_label("Paid to").fill("Shree Medical Gases")
    page.get_by_role("button", name="Medical supplies").click()
    page.get_by_role("button", name="Cash").click()
    page.get_by_role("button", name="Save", exact=True).click()
    page.get_by_role("button", name="Record collection").click()
    page.get_by_label("Amount").fill("700")
    page.get_by_role("button", name="UPI").click()
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_text("-₹4,150").first).to_be_visible()        # cash and bank: 700 - 4850

    page.get_by_role("button", name="See all").click()
    rows = page.locator("li").filter(has=page.locator("button[aria-expanded]"))
    expect(rows).to_have_count(2)
    page.get_by_role("button", name="Money out").click()
    expect(rows).to_have_count(1)
    rows.first.locator("button[aria-expanded]").click()
    expect(page.get_by_text("5000 Medical supplies")).to_be_visible()
    expect(page.get_by_text("1000 Cash in hand")).to_be_visible()
    page.screenshot(path="shots/9-entries.png", full_page=True)

    page.get_by_role("button", name="Cancel this entry").click()
    page.get_by_role("button", name="Cancel entry", exact=True).click()
    expect(page.get_by_role("alert")).to_have_text("Say why this entry is being cancelled")
    page.get_by_label("Why is it being cancelled?").fill("entered twice")
    page.get_by_role("button", name="Cancel entry", exact=True).click()
    expect(page.get_by_text("Cancelled", exact=True)).to_be_visible()

    # closing the month blocks new entries with a plain message; reopening allows them again
    page.get_by_role("button", name="Close month").click()
    expect(page.get_by_text("is closed for this project. Entries in it cannot be added or cancelled.")).to_be_visible()
    page.get_by_role("button", name="Back").click()
    expect(page.get_by_text("₹700").first).to_be_visible()      # the cancelled expense no longer counts
    page.get_by_role("button", name="Record collection").click()
    page.get_by_label("Amount").fill("100")
    page.get_by_role("button", name="Cash").click()
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("alert")).to_contain_text("is closed")
    page.get_by_role("button", name="Back").click()
    page.get_by_role("button", name="See all").click()
    page.get_by_role("button", name="Reopen month").click()
    expect(page.get_by_text("is open.")).to_be_visible()

    page.set_viewport_size({"width": 1360, "height": 900})
    expect(page.get_by_role("navigation", name="Main").get_by_role("button", name="Entries")).to_have_attribute("aria-current", "page")
    rows.first.locator("button[aria-expanded]").click()
    page.wait_for_timeout(400)
    page.screenshot(path="shots/web-6-entries.png", full_page=True)
    print("ENTRIES OK; page errors:", errors)
    b.close()
