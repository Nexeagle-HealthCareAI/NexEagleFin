D = "2026-11-10"


def new_project(g, name, units):
    r = g.client.post("/api/projects", headers=g.owner, json={"name": name, "units": units})
    assert r.status_code == 201, r.text
    return r.json()


def test_each_project_has_its_own_numbers_and_the_dashboard_adds_them_up(group):
    c, h = group.client, group.owner
    lab = new_project(group, "City Diagnostics Centre", ["diagnostics"])
    lab_unit = next(u["id"] for u in lab["units"] if u["kind"] == "diagnostics")

    # project 1: invest 50 lakh, spend 12 lakh on equipment upkeep, collect 3 lakh
    c.post("/api/documents/investment", headers=h, json={"project_id": group.project, "date": D, "amount": "5000000"})
    c.post("/api/documents/expense", headers=h, json={
        "unit_id": group.units["hospital"], "date": D, "amount": "1200000", "category_id": group.cats["Maintenance"],
        "paid": True, "payment_mode": "bank"})
    c.post("/api/documents/collection", headers=h, json={
        "unit_id": group.units["hospital"], "date": D, "amount": "300000", "payment_mode": "upi"})
    # project 2: invest 10 lakh, collect 40 thousand
    c.post("/api/documents/investment", headers=h, json={"project_id": lab["id"], "date": D, "amount": "1000000"})
    c.post("/api/documents/collection", headers=h, json={
        "unit_id": lab_unit, "date": D, "amount": "40000", "payment_mode": "cash"})

    dash = c.get(f"/api/reports/projects?on={D}", headers=h).json()
    rows = {p["name"]: p for p in dash["projects"]}
    assert set(rows) == {"City Care Group Hospital", "City Diagnostics Centre"}
    one, two = rows["City Care Group Hospital"], rows["City Diagnostics Centre"]
    assert (one["invested"], one["cash_and_bank"], one["profit_this_month"]) == ("5000000.00", "4100000.00", "-900000.00")
    assert (two["invested"], two["cash_and_bank"], two["profit_this_month"]) == ("1000000.00", "1040000.00", "40000.00")
    assert dash["totals"]["invested"] == "6000000.00"
    assert dash["totals"]["cash_and_bank"] == "5140000.00"
    assert dash["totals"]["profit_this_month"] == "-860000.00"

    # investment is not income
    assert one["income_this_month"] == "300000.00"

    # the home screen can be narrowed to one project
    home = c.get(f"/api/reports/home?on={D}&project_id={lab['id']}", headers=h).json()
    assert home["cash_and_bank"] == "1040000.00"


def test_project_rules(group, other_group):
    c = group.client
    assert c.post("/api/projects", headers=group.owner, json={"name": "city care group hospital"}).status_code == 409
    staff = group.add_user("9000000020", "unit_incharge", ["pharmacy"])
    assert c.post("/api/projects", headers=staff, json={"name": "Side project"}).status_code == 403
    assert c.post("/api/documents/investment", headers=staff, json={
        "project_id": group.project, "date": D, "amount": "1"}).status_code == 403
    # another account cannot invest into or view this project
    assert c.post("/api/documents/investment", headers=other_group.owner, json={
        "project_id": group.project, "date": D, "amount": "1"}).status_code == 404
    assert c.get(f"/api/reports/home?project_id={group.project}", headers=other_group.owner).status_code == 404
    names = [p["name"] for p in c.get("/api/reports/projects", headers=other_group.owner).json()["projects"]]
    assert names == ["Another Group Hospital"]
