"""Cash and bank accounts, opening balances, a deposit, the account chosen on a collection, and a patient advance."""
import os

from playwright.sync_api import sync_playwright, expect

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=os.environ.get("CHROME"), args=["--no-sandbox"])
    page = b.new_page(viewport={"width": 1360, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto("http://localhost:4173/")
    page.get_by_label("Phone number").fill("9876543210")
    page.get_by_label("PIN").fill("4321")
    page.get_by_role("button", name="Log in").click()
    page.get_by_role("button", name="New project").click()
    page.get_by_label("Project name").fill("Glisan Hospital")
    page.get_by_label("Pharmacy").check()
    page.get_by_role("button", name="Create project").click()
    page.get_by_role("button", name="Glisan Hospital").click()
    nav = page.get_by_role("navigation", name="Main")

    # opening balances: the cash box, and a second bank account
    nav.get_by_role("button", name="Cash and bank").click()
    page.get_by_role("button", name="Set the balance it started with").first.click()
    page.get_by_label("Balance (₹)").fill("35000")
    page.get_by_role("button", name="Save balance").click()
    expect(page.get_by_text("₹35,000").first).to_be_visible()
    page.get_by_role("button", name="Add an account").click()
    page.get_by_label("Name, for example").fill("HDFC current account")
    page.get_by_label("Balance it starts with").fill("1250000")
    page.get_by_role("button", name="Add account").click()
    expect(page.get_by_text("₹12,85,000")).to_be_visible()              # total

    # cash deposited in the bank
    page.get_by_role("button", name="Move money").click()
    page.get_by_label("From", exact=True).select_option(label="Cash in hand")
    page.get_by_label("To", exact=True).select_option(label="HDFC current account")
    page.get_by_label("Amount (₹)").fill("30000")
    page.get_by_role("button", name="Move money").click()
    expect(page.get_by_text("₹12,80,000")).to_be_visible()              # HDFC after the deposit
    expect(page.get_by_text("₹12,85,000")).to_be_visible()              # total unchanged
    page.screenshot(path="shots/web-12-cash-bank.png", full_page=True)

    # a UPI collection goes to the chosen bank
    nav.get_by_role("button", name="Record collection").click()
    page.get_by_label("Amount").fill("26400")
    page.get_by_role("button", name="UPI").click()
    page.get_by_label("Received into").select_option(label="HDFC current account")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_text("Money in today")).to_be_visible()
    expect(page.get_by_text("₹26,400").first).to_be_visible()           # deposit and opening balances are not money in

    # a patient advance: held, then used for the final bill, rest refunded
    page.get_by_role("button", name="Dues").click() if page.get_by_role("button", name="Dues").count() == 1 else nav.get_by_role("button", name="Dues").click()
    page.get_by_role("button", name="Advances", exact=True).click()
    page.get_by_role("button", name="Take an advance").click()
    page.get_by_label("Patient or IP number").fill("IP-1021")
    page.get_by_label("Amount (₹)").fill("100000")
    page.get_by_role("button", name="UPI").click()
    page.get_by_role("button", name="Save advance").click()
    expect(page.get_by_text("IP-1021")).to_be_visible()
    page.get_by_role("button", name="Use for the bill").click()
    page.get_by_label("Amount of the final bill").fill("85000")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_text("of ₹1,00,000")).to_be_visible()
    page.get_by_role("button", name="Refund").click()
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_text("No advances are held right now.")).to_be_visible()

    nav.get_by_role("button", name="Home").click()
    expect(page.get_by_text("₹13,96,400").first).to_be_visible()        # 12,85,000 + 26,400 + 1,00,000 - 15,000
    print("MONEY OK; page errors:", errors)
    b.close()
