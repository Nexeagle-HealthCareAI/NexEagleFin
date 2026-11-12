"""Cash-limit warnings on screen, on a fresh database."""
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

    # 2.5 lakh cash from one patient: warned, then saved on purpose
    page.get_by_role("button", name="Record collection").click()
    page.get_by_label("Amount").fill("250000")
    page.get_by_role("button", name="Cash").click()
    page.get_by_label("Patient or bill number").fill("IP-1021")
    page.get_by_role("button", name="Save", exact=True).click()
    box = page.get_by_role("alert").filter(has_text="Check before saving")
    expect(box).to_contain_text("attracts a penalty")
    page.screenshot(path="shots/14-cash-warning.png", full_page=True)
    page.get_by_role("button", name="Save anyway").click()
    expect(page.get_by_text("₹2,50,000").first).to_be_visible()

    # 15,000 cash to a vendor: warned, gone back, switched to UPI, saved without a warning
    page.get_by_role("button", name="Record expense").click()
    page.get_by_label("Amount").fill("15000")
    page.get_by_label("Paid to").fill("Ramesh Electricals")
    page.get_by_role("button", name="Maintenance").click()
    page.get_by_role("button", name="Cash").click()
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("alert")).to_contain_text("usually not allowed as a tax deduction")
    page.get_by_role("button", name="Go back").click()
    expect(page.get_by_role("alert")).to_have_count(0)
    page.get_by_role("button", name="UPI").click()
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_text("₹2,35,000").first).to_be_visible()
    print("CASH LIMITS OK; page errors:", errors)
    b.close()
