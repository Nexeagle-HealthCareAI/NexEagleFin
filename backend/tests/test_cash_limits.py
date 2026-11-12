"""Cash-limit warnings: shown before saving, never silently saved, and saving anyway is possible once seen."""
from app.api import today

D = today().isoformat()


def post(g, path, body, confirmed=False):
    return g.client.post(f"/api{path}", headers=g.owner, json={**body, **({"confirmed": True} if confirmed else {})})


def warnings(r):
    assert r.status_code == 409, r.text
    return r.json()["detail"]["warnings"]


def collect(g, amount, ref=None, mode="cash", confirmed=False):
    return post(g, "/documents/collection", {"unit_id": g.units["hospital"], "date": D, "amount": amount,
                                             "payment_mode": mode, "reference": ref}, confirmed)


def test_two_lakh_cash_from_one_patient_is_added_up_across_visits(group):
    assert collect(group, "120000", ref="IP-1021").status_code == 201
    w = warnings(collect(group, "90000", ref="IP-1021"))           # 2,10,000 for the same patient
    assert "attracts a penalty" in w[0] and "comes to ₹2,10,000" in w[0]
    assert collect(group, "90000", ref="IP-1022").status_code == 201   # a different patient is fine
    assert collect(group, "90000", ref="IP-1021", mode="upi").status_code == 201   # UPI is not cash
    assert collect(group, "90000", ref="IP-1021", confirmed=True).status_code == 201  # saved once seen


def test_large_cash_without_a_patient_number(group):
    assert "attracts a penalty" in warnings(collect(group, "200000"))[0]
    assert "Add the patient or bill number" in warnings(collect(group, "60000"))[0]
    assert collect(group, "45000").status_code == 201


def test_cash_over_ten_thousand_to_one_vendor_in_a_day(group):
    body = {"unit_id": group.units["hospital"], "date": D, "category_id": group.cats["Maintenance"],
            "paid_to": "Ramesh Electricals", "paid": True, "payment_mode": "cash"}
    assert post(group, "/documents/expense", {**body, "amount": "6000"}).status_code == 201
    w = warnings(post(group, "/documents/expense", {**body, "amount": "5000"}))
    assert "usually not allowed as a tax deduction" in w[0] and "Ramesh Electricals that day would be ₹11,000" in w[0]
    assert post(group, "/documents/expense", {**body, "amount": "5000", "payment_mode": "bank"}).status_code == 201
    assert post(group, "/documents/expense", {**body, "amount": "4000", "paid_to": "Other Vendor"}).status_code == 201
    # an unpaid bill is not a cash payment; paying it in cash later is
    bill = post(group, "/documents/expense", {**body, "amount": "30000", "paid": False, "payment_mode": None, "paid_to": "Medi"}).json()
    assert "tax deduction" in warnings(post(group, f"/documents/{bill['id']}/pay", {"date": D, "amount": "30000", "payment_mode": "cash"}))[0]


def test_loans_in_cash(group):
    body = {"project_id": group.project, "lender": "Friend", "loan_type": "Personal or unsecured loan", "amount": "50000",
            "start_date": D, "payment_mode": "cash", "rate": "0", "emi": "5000", "first_due": D}
    assert "should not be taken in cash" in warnings(post(group, "/loans", body))[0]
    assert post(group, "/loans", body, confirmed=True).status_code == 201


def test_cancelled_entries_do_not_count(group):
    first = collect(group, "150000", ref="IP-9").json()
    group.client.post(f"/api/documents/{first['id']}/reverse", headers=group.owner, json={"reason": "wrong amount"})
    assert collect(group, "60000", ref="IP-9").status_code == 201


def test_bookkeeper_approval_shows_the_warning(group):
    run = group.client.post("/api/agents/bookkeeper/run", headers=group.owner, json={
        "project_id": group.project, "source": "text", "content": "paid 15000 to Ramesh Electricals for repair cash"}).json()
    p = run["proposals"][0]
    r = group.client.post(f"/api/agents/proposals/{p['id']}/approve", headers=group.owner, json={"unit_id": group.units["hospital"]})
    assert "tax deduction" in warnings(r)[0]
    still = group.client.get(f"/api/agents/proposals?project_id={group.project}", headers=group.owner).json()
    assert len(still) == 1                                                # nothing half-saved
    r = group.client.post(f"/api/agents/proposals/{p['id']}/approve", headers=group.owner,
                          json={"unit_id": group.units["hospital"], "confirmed": True})
    assert r.status_code == 200


def test_chat_card_carries_the_warning_and_yes_saves(group):
    c, h = group.client, group.owner
    c.post("/api/documents/expense", headers=h, json={"unit_id": group.units["pharmacy"], "date": D, "amount": "40000",
                                                      "category_id": group.cats["Medicines"], "paid_to": "Medi Distributors", "paid": False})
    a = c.post("/api/agents/chat", headers=h, json={"project_id": group.project, "message": "paid Medi Distributors 40000 cash"}).json()
    assert a["action"]["warnings"] and "tax deduction" in a["action"]["warnings"][0]
    assert "Before you confirm" in a["reply"]
    assert c.post(f"/api/agents/actions/{a['action']['id']}/confirm", headers=h).json()["status"] == "done"
