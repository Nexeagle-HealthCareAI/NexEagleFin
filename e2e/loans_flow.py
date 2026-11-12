"""Loans through the browser on a fresh database: add a loan, pay an instalment, add a running loan."""
import datetime
import os

from playwright.sync_api import sync_playwright, expect

today = datetime.date.today()
later = (today + datetime.timedelta(days=20)).isoformat()

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

    page.get_by_role("button", name="Loans None recorded").click()
    page.get_by_role("button", name="Add a loan").click()
    page.get_by_label("Who lent the money").fill("City Co-operative Bank")
    page.get_by_label("Type of loan").select_option(label="Equipment loan")
    page.get_by_label("Loan amount received").fill("1200000")
    page.get_by_label("Interest rate").fill("twelve")
    page.get_by_label("Monthly instalment").fill("40000")
    page.get_by_label("First instalment date").fill(today.isoformat())
    page.get_by_label("Note").fill("CT scanner")
    page.get_by_role("button", name="Save loan").click()
    expect(page.get_by_role("alert")).to_contain_text("Enter the yearly interest rate")
    page.get_by_label("Interest rate").fill("12")
    page.get_by_role("button", name="Save loan").click()
    expect(page.get_by_text("Due today")).to_be_visible()
    expect(page.get_by_text("₹12,00,000").first).to_be_visible()

    # pay the first instalment: the split is worked out for you
    page.get_by_role("button", name="Pay instalment").click()
    expect(page.get_by_label("Amount paid")).to_have_value("40000.00")
    expect(page.get_by_label("Of which interest")).to_have_value("12000.00")
    expect(page.get_by_text("₹28,000 comes off the loan.")).to_be_visible()
    page.screenshot(path="shots/10-loan-pay.png", full_page=True)
    page.get_by_role("button", name="Save payment").click()
    expect(page.get_by_text("₹11,72,000").first).to_be_visible()
    expect(page.get_by_text("Up to date")).to_be_visible()
    page.get_by_role("button", name="Payments and plan").click()
    expect(page.get_by_text("Coming up, if paid on time")).to_be_visible()

    # a loan that was already running: no money comes in
    page.get_by_role("button", name="Add a loan").click()
    page.get_by_label("Who lent the money").fill("Uncle Rafiq")
    page.get_by_label("Type of loan").select_option(label="Loan from partner or family")
    page.get_by_role("button", name="Already being repaid").click()
    page.get_by_label("Amount still owed today").fill("500000")
    page.get_by_label("Interest rate").fill("0")
    page.get_by_label("Monthly instalment").fill("25000")
    page.get_by_label("Next instalment date").fill(later)
    page.get_by_role("button", name="Save loan").click()
    expect(page.get_by_text("Uncle Rafiq")).to_be_visible()
    expect(page.get_by_text("₹16,72,000")).to_be_visible()          # still owed on all loans
    expect(page.get_by_text("₹65,000")).to_be_visible()             # instalments each month
    page.screenshot(path="shots/11-loans.png", full_page=True)

    # home: bank has loan money minus the instalment; the running loan added no cash
    page.get_by_role("button", name="Back").click()
    expect(page.get_by_text("₹11,60,000").first).to_be_visible()
    expect(page.get_by_text("₹16,72,000 still owed")).to_be_visible()

    page.set_viewport_size({"width": 1360, "height": 900})
    page.get_by_role("navigation", name="Main").get_by_role("button", name="Loans").click()
    expect(page.get_by_text("Uncle Rafiq")).to_be_visible()
    page.screenshot(path="shots/web-7-loans.png", full_page=True)
    print("LOANS OK; page errors:", errors)
    b.close()
