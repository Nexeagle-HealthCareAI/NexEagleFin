"""Working from the assistant alone, on a fresh database: loan, instalment, bill payment, follow-up, cancel."""
import datetime
import os

from playwright.sync_api import sync_playwright, expect

last_month = (datetime.date.today().replace(day=1) - datetime.timedelta(days=1)).strftime("%B %Y")

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
    page.get_by_role("button", name="Assistant", exact=True).click()
    d = page.get_by_role("dialog", name="Assistant")
    box = d.get_by_label("Message to the assistant")

    def tell(text):
        box.fill(text)
        d.get_by_role("button", name="Send").click()

    # a loan, in one sentence
    tell("took a loan of 12 lakh from City Bank at 12% emi 40000")
    expect(d.get_by_role("heading", name="Add this loan?")).to_be_visible()
    expect(d.get_by_text("₹12,00,000").first).to_be_visible()
    d.get_by_role("button", name="Yes, record it").click()
    expect(d.get_by_text("Done. The loan from City Bank is added")).to_be_visible()

    # its instalment, by tapping a starter-style phrase
    tell("paid the emi")
    expect(d.get_by_role("heading", name="Record this instalment?")).to_be_visible()
    expect(d.get_by_text("₹28,000")).to_be_visible()                     # comes off the loan
    page.screenshot(path="shots/web-10-confirm-card.png")
    d.get_by_role("button", name="Yes, record it").click()
    expect(d.get_by_text("₹11,72,000 is still owed on this loan")).to_be_visible()

    # an unpaid bill, then paying part of it; the assistant asks how it was paid
    tell("Medi Distributors medicines bill 90000 to pay later")
    expect(d.get_by_text("I prepared 1 entry")).to_be_visible()
    card = d.locator("div.rounded-2xl").filter(has=page.get_by_role("button", name="Approve"))
    card.get_by_label("Unit").select_option(label="Pharmacy")
    card.get_by_role("button", name="Approve").click()
    expect(card).to_have_count(0)
    tell("paid Medi Distributors 40000")
    expect(d.get_by_text("How was ₹40,000 paid to Medi Distributors?")).to_be_visible()
    d.get_by_role("button", name="Cash", exact=True).click()
    expect(d.get_by_role("heading", name="Record this payment?")).to_be_visible()
    d.get_by_role("button", name="Yes, record it").click()
    expect(d.get_by_text("Done. The payment of ₹40,000 is recorded.")).to_be_visible()

    # a question and a follow-up
    tell("what is the profit this month?")
    expect(d.get_by_text("costs were ₹1,02,000")).to_be_visible()        # 90,000 medicines + 12,000 loan interest
    tell("and last month?")
    expect(d.get_by_text(f"In {last_month} income was ₹0 and costs were ₹0")).to_be_visible()

    # a risky change is shown in red and a No leaves the books alone
    tell("cancel the last entry")
    expect(d.get_by_role("heading", name="Cancel this entry?")).to_be_visible()
    page.screenshot(path="shots/web-11-cancel-card.png")
    d.get_by_role("button", name="No", exact=True).click()
    expect(d.get_by_text("All right, I have not done it.")).to_be_visible()

    page.keyboard.press("Escape")
    expect(page.get_by_text("₹11,20,000").first).to_be_visible()         # 12,00,000 - 40,000 - 40,000
    expect(page.get_by_text("₹50,000").first).to_be_visible()            # still to pay

    page.set_viewport_size({"width": 390, "height": 844})
    page.get_by_role("button", name="Open assistant").click()
    page.get_by_role("dialog").get_by_label("Message to the assistant").fill("close last month")
    page.get_by_role("dialog").get_by_role("button", name="Send").click()
    expect(page.get_by_role("dialog").get_by_role("heading", name=f"Close {last_month}?")).to_be_visible()
    page.wait_for_timeout(300)
    page.screenshot(path="shots/13-chat-phone.png")
    print("CHAT ACTIONS OK; page errors:", errors)
    b.close()
