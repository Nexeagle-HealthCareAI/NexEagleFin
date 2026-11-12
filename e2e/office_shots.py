"""Opens the 3D office and takes pictures during work, a meeting and a break. Needs WebGL (software is fine)."""
import os

from playwright.sync_api import sync_playwright, expect

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=os.environ.get("CHROME"),
                          args=["--no-sandbox", "--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
    page = b.new_page(viewport={"width": 1360, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto("http://localhost:4173/")
    page.get_by_label("Phone number").fill("9876543210")
    page.get_by_label("PIN").fill("4321")
    page.get_by_role("button", name="Log in").click()
    expect(page.get_by_role("button", name="New project")).to_be_visible()
    if page.get_by_role("button", name="Glisan Hospital").count() == 0:
        page.get_by_role("button", name="New project").click()
        page.get_by_label("Project name").fill("Glisan Hospital")
        page.get_by_role("button", name="Create project").click()
    page.get_by_role("button", name="Glisan Hospital").click()
    page.get_by_role("navigation", name="Main").get_by_role("button", name="Office").click()
    expect(page.get_by_role("img", name="Animated 3D office floor")).to_be_visible()
    expect(page.get_by_text("At the desk, books are up to date")).to_be_visible()
    page.wait_for_timeout(2500)
    page.screenshot(path="shots/office-1-work.png")
    expect(page.get_by_text("In a meeting").first).to_be_visible(timeout=30000)
    page.wait_for_timeout(6000)
    page.screenshot(path="shots/office-2-meeting.png")
    expect(page.get_by_text("Playing pool").first).to_be_visible(timeout=70000)
    page.wait_for_timeout(5000)
    page.screenshot(path="shots/office-3-break.png")
    page.get_by_role("button", name="Pause").click()
    expect(page.get_by_role("button", name="Play")).to_be_visible()
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(500)
    page.screenshot(path="shots/office-4-phone.png")
    print("OFFICE OK; errors:", errors)
    b.close()
