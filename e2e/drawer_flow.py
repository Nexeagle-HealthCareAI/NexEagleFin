"""Assistant drawer and collapsible menu, on a fresh database."""
import os

from playwright.sync_api import sync_playwright, expect

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=os.environ.get("CHROME"), args=["--no-sandbox"])
    page = b.new_page(viewport={"width": 1360, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto("http://localhost:4173/")
    page.get_by_label("Phone number").fill("+91 98765 43210")          # typed with country code and spaces
    page.get_by_label("PIN").fill("4321")
    page.get_by_role("button", name="Log in").click()
    page.get_by_role("button", name="New project").click()
    page.get_by_label("Project name").fill("Glisan Hospital")
    page.get_by_label("Pharmacy").check()
    page.get_by_role("button", name="Create project").click()
    page.get_by_role("button", name="Glisan Hospital").click()

    # --- the menu folds down to icons and remembers it ---
    aside = page.locator("aside")
    assert aside.bounding_box()["width"] == 240
    page.get_by_role("button", name="Collapse menu").click()
    expect(page.get_by_role("button", name="Expand menu")).to_be_visible()
    page.wait_for_timeout(300)
    assert aside.bounding_box()["width"] == 72
    expect(page.get_by_role("navigation", name="Main").get_by_role("button", name="Entries")).to_be_visible()   # still named for screen readers
    page.screenshot(path="shots/web-8-collapsed.png")
    page.reload()
    page.wait_for_timeout(500)
    assert page.locator("aside").bounding_box()["width"] == 72
    page.get_by_role("button", name="Expand menu").click()

    # --- the assistant opens in a drawer from the top of the menu ---
    page.get_by_role("button", name="Glisan Hospital").click()
    page.get_by_role("button", name="Assistant", exact=True).click()
    drawer = page.get_by_role("dialog", name="Assistant")
    expect(drawer).to_be_visible()
    expect(drawer.get_by_label("Message to the assistant")).to_be_focused()

    # ask with one tap, then in your own words
    drawer.get_by_role("button", name="How much cash do we have?").click()
    expect(drawer.get_by_text("Cash and bank stand at ₹0.")).to_be_visible()

    box = drawer.get_by_label("Message to the assistant")
    box.fill("paid 4850 to Shree Medical Gases for oxygen cash\nreceived 26400 pharmacy counter upi")
    drawer.get_by_role("button", name="Send").click()
    expect(drawer.get_by_text("I prepared 2 entries")).to_be_visible()
    cards = drawer.locator("div.rounded-2xl").filter(has=page.get_by_role("button", name="Approve"))
    expect(cards).to_have_count(2)
    cards.filter(has_text="pharmacy counter").get_by_role("button", name="Approve").click()
    expect(cards).to_have_count(1)

    # the answer now reflects what was just approved, and only that
    box.fill("how much cash do we have now?")
    box.press("Control+Enter")
    expect(drawer.get_by_text("Cash and bank stand at ₹26,400.")).to_be_visible()
    box.fill("what is the profit this month")
    drawer.get_by_role("button", name="Send").click()
    expect(drawer.get_by_text("income was ₹26,400 and costs were ₹0, a profit of ₹26,400")).to_be_visible()
    page.screenshot(path="shots/web-9-drawer.png")

    page.keyboard.press("Escape")
    expect(drawer).to_be_hidden()
    expect(page.get_by_text("₹26,400").first).to_be_visible()      # the screen behind picked up the new entry

    # reopening shows what is still waiting
    page.get_by_role("button", name="Assistant", exact=True).click()
    expect(page.get_by_role("dialog").get_by_text("1 earlier suggestion is waiting")).to_be_visible()
    page.get_by_role("dialog").get_by_role("button", name="Close assistant").click()

    # --- phone: the assistant sits in the top corner of every screen ---
    page.set_viewport_size({"width": 390, "height": 844})
    page.get_by_role("button", name="Open assistant").click()
    expect(page.get_by_role("dialog", name="Assistant")).to_be_visible()
    page.wait_for_timeout(300)
    page.screenshot(path="shots/12-drawer-phone.png")
    print("DRAWER OK; page errors:", errors)
    b.close()
