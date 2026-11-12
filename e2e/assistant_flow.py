"""Bookkeeper agent through the browser, on a fresh database, with keyword rules (no Groq key)."""
import datetime
import os
import tempfile

from playwright.sync_api import sync_playwright, expect

today = datetime.date.today().strftime("%d/%m/%Y")
statement = f"""Txn Date,Narration,Withdrawal Amt,Deposit Amt,Balance
{today},UPI/RAMESH KUMAR/9876543210/payment,,700.00,10700.00
{today},NEFT-SHREE MEDICAL GASES-oxygen cylinders,"4,850.00",,5850.00
{today},NEFT-STATE ELECTRICITY BOARD-bill,"12,300.00",,
"""

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
    page.get_by_label("Pharmacy").check()
    page.get_by_role("button", name="Create project").click()
    page.get_by_role("button", name="Glisan Hospital").click()

    # notes -> suggestions
    page.get_by_role("button", name="Open assistant").click()
    page.get_by_role("dialog").get_by_role("button", name="Bank statement").click()   # the full assistant page
    page.get_by_role("button", name="Notes").click()
    page.get_by_label("One entry per line").fill(
        "paid 4850 to Shree Medical Gases for oxygen cash\nreceived 26400 pharmacy counter upi\n3 cylinders 4500 cash")
    page.get_by_role("button", name="Read and suggest entries").click()
    expect(page.get_by_text("3 suggestions waiting")).to_be_visible()
    expect(page.get_by_text("Amount not clear")).to_be_visible()
    page.screenshot(path="shots/7-assistant.png", full_page=True)

    cards = page.locator("div.rounded-2xl").filter(has=page.get_by_role("button", name="Approve"))
    gases = cards.filter(has_text="Shree Medical Gases for oxygen")
    gases.get_by_label("Unit").select_option(label="Hospital")
    gases.get_by_role("button", name="Approve").click()
    expect(page.get_by_text("2 suggestions waiting")).to_be_visible()

    counter = cards.filter(has_text="pharmacy counter")
    expect(counter.get_by_label("Unit")).to_have_value(counter.get_by_label("Unit").locator("option", has_text="Pharmacy").get_attribute("value"))
    counter.get_by_role("button", name="Approve").click()
    expect(page.get_by_text("1 suggestion waiting")).to_be_visible()

    unclear = cards.filter(has_text="3 cylinders")
    unclear.get_by_role("button", name="Approve").click()
    expect(unclear.get_by_role("alert")).to_have_text("Enter the amount")
    unclear.get_by_label("Amount").fill("4500")
    unclear.get_by_label("Unit").select_option(label="Hospital")
    unclear.get_by_label("What for").select_option(label="Sort later")
    unclear.get_by_role("button", name="Approve").click()
    expect(page.get_by_text("No suggestions waiting")).to_be_visible()

    # bank statement -> suggestions, with the repeat flagged
    page.get_by_role("button", name="Bank statement").click()
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
        f.write(statement)
    page.get_by_label("Statement file").set_input_files(f.name)
    page.get_by_role("button", name="Read and suggest entries").click()
    expect(page.get_by_text("3 suggestions waiting")).to_be_visible()
    expect(page.get_by_text("Looks already recorded")).to_have_count(1)
    page.screenshot(path="shots/8-assistant-bank.png", full_page=True)
    cards.filter(has_text="ELECTRICITY").get_by_label("Unit").select_option(label="Hospital")
    cards.filter(has_text="ELECTRICITY").get_by_role("button", name="Approve").click()
    cards.filter(has_text="SHREE MEDICAL GASES").get_by_role("button", name="Reject").click()
    expect(page.get_by_text("1 suggestion waiting")).to_be_visible()

    # the books: -4850 cash +26400 upi -4500 cash -12300 bank = 4750
    page.get_by_role("button", name="Back").click()
    expect(page.get_by_text("₹4,750")).to_be_visible()
    expect(page.get_by_text("1 expense needs a category")).to_be_visible()

    # desktop view of the same screen
    page.set_viewport_size({"width": 1360, "height": 900})
    page.get_by_role("button", name="Assistant", exact=True).click()
    page.get_by_role("dialog").get_by_role("button", name="Review").click()
    expect(page.get_by_text("1 suggestion waiting")).to_be_visible()
    page.screenshot(path="shots/web-5-assistant.png", full_page=True)
    print("ASSISTANT OK; page errors:", errors)
    b.close()
