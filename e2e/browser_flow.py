import os

from playwright.sync_api import sync_playwright, expect

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=os.environ.get("CHROME"), args=["--no-sandbox"])
    page = b.new_page(viewport={"width": 390, "height": 844})
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto("http://localhost:4173/")

    # wrong PIN shows a plain message
    page.get_by_label("Phone number").fill("9876543210")
    page.get_by_label("PIN").fill("0000")
    page.get_by_role("button", name="Log in").click()
    expect(page.get_by_role("alert")).to_have_text("Wrong phone number or PIN")
    page.get_by_label("PIN").fill("4321")
    page.get_by_role("button", name="Log in").click()
    expect(page.get_by_text("No projects yet")).to_be_visible()
    page.screenshot(path="shots/1-empty.png")

    # create project
    page.get_by_role("button", name="New project").click()
    page.get_by_label("Project name").fill("Glisan Hospital")
    page.get_by_label("Pharmacy").check()
    page.get_by_role("button", name="Create project").click()
    page.get_by_role("button", name="Glisan Hospital").click()
    expect(page.get_by_role("heading", name="Glisan Hospital")).to_be_visible()

    # investment 50 lakh
    page.get_by_role("button", name="Add investment").click()
    page.get_by_label("Amount").fill("5000000")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_text("₹50,00,000").first).to_be_visible()

    # expense: validation first, then save
    page.get_by_role("button", name="Record expense").click()
    page.get_by_label("Amount").fill("4850")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("alert")).to_contain_text("Choose how the money moved")
    page.get_by_label("Paid to").fill("Shree Medical Gases")
    page.get_by_role("button", name="Medical supplies").click()
    page.get_by_role("button", name="Cash").click()
    page.screenshot(path="shots/2-expense.png", full_page=True)
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_text("₹49,95,150")).to_be_visible()

    # unsorted expense
    page.get_by_role("button", name="Record expense").click()
    page.get_by_label("Amount").fill("1200.50")
    page.get_by_role("button", name="UPI").click()
    page.get_by_role("button", name="Save now, sort later").click()
    expect(page.get_by_text("1 expense needs a category")).to_be_visible()

    # collection at pharmacy
    page.get_by_role("button", name="Record collection").click()
    page.get_by_label("Amount").fill("26400")
    page.get_by_label("Unit").select_option(label="Pharmacy")
    page.get_by_role("button", name="UPI").click()
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_text("₹50,20,349.50")).to_be_visible()
    page.screenshot(path="shots/3-project.png", full_page=True)

    # sort the unsorted expense
    page.get_by_role("button", name="Sort now").click()
    page.get_by_role("button", name="Utilities").click()
    expect(page.get_by_text("All sorted")).to_be_visible()
    page.get_by_role("button", name="Back").click()
    expect(page.get_by_text("needs a category")).to_have_count(0)

    # insurance bill: billed 1,80,000, received 1,62,000, cut 18,000
    page.get_by_role("button", name="To receive").click()
    page.get_by_role("button", name="Add insurance or credit bill").click()
    page.get_by_label("Who will pay").fill("National TPA Services")
    page.get_by_label("Billed amount").fill("180000")
    page.get_by_label("Bill number").fill("H-2291")
    page.get_by_role("button", name="Save bill").click()
    expect(page.get_by_text("Total to receive")).to_be_visible()
    expect(page.get_by_text("₹1,80,000").first).to_be_visible()
    page.screenshot(path="shots/5-dues.png", full_page=True)
    page.get_by_role("button", name="Record money received").click()
    page.get_by_label("Received").fill("162000")
    page.get_by_label("Cut by insurer").fill("20000")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("alert")).to_contain_text("Only 180000.00 is still due")
    page.get_by_label("Cut by insurer").fill("18000")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_text("Nobody owes this project money")).to_be_visible()
    page.get_by_role("button", name="Back").click()

    # unpaid vendor bill, then part payment
    page.get_by_role("button", name="Record expense").click()
    page.get_by_label("Amount").fill("90000")
    page.get_by_label("Paid to").fill("Medi Distributors")
    page.get_by_role("button", name="Medicines").click()
    page.get_by_role("button", name="To pay later").click()
    page.get_by_role("button", name="Save", exact=True).click()
    page.get_by_role("button", name="To pay").click()
    expect(page.get_by_text("Medi Distributors")).to_be_visible()
    page.get_by_role("button", name="Record payment").click()
    page.get_by_label("Paid now").fill("40000")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_text("of ₹90,000")).to_be_visible()
    expect(page.get_by_text("₹50,000").first).to_be_visible()
    page.screenshot(path="shots/6-to-pay.png", full_page=True)
    page.get_by_role("button", name="Back").click()
    # cash: 50,20,349.50 + 1,62,000 received - 40,000 paid
    expect(page.get_by_text("₹51,42,349.50")).to_be_visible()

    # dashboard
    page.get_by_role("button", name="Back").click()
    expect(page.get_by_text("Cash and bank, all projects")).to_be_visible()
    expect(page.get_by_text("₹51,42,349.50").first).to_be_visible()
    expect(page.get_by_text("₹92,349.50").first).to_be_visible()
    page.screenshot(path="shots/4-dashboard.png", full_page=True)

    # reload keeps the session; log out returns to login
    page.reload()
    expect(page.get_by_role("heading", name="All projects")).to_be_visible()
    page.get_by_role("button", name="Log out").click()
    expect(page.get_by_role("button", name="Log in")).to_be_visible()
    print("E2E OK; console errors:", [e for e in errors if "401" not in e])
    b.close()
