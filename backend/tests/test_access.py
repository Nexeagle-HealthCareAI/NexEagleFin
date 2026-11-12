D = "2026-11-10"


def test_login_required(client):
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/reports/home").status_code == 401


def test_wrong_pin_locks_after_five_tries(group):
    for _ in range(5):
        r = group.client.post("/api/auth/login", json={"phone": "9000000001", "pin": "0000"})
        assert r.status_code == 401
    r = group.client.post("/api/auth/login", json={"phone": "9000000001", "pin": "4321"})
    assert r.status_code == 429


def test_one_group_cannot_touch_another(group, other_group):
    r = group.client.post("/api/documents/collection", headers=group.owner,
                          json={"unit_id": group.units["hospital"], "date": D, "amount": "500", "payment_mode": "cash"})
    doc_id = r.json()["id"]

    # the other group's owner cannot post into, read, sort or cancel it
    c = other_group.client
    h = other_group.owner
    assert c.post("/api/documents/collection", headers=h, json={
        "unit_id": group.units["hospital"], "date": D, "amount": "1", "payment_mode": "cash"}).status_code == 404
    assert c.post(f"/api/documents/{doc_id}/reverse", headers=h, json={"reason": "not mine"}).status_code == 404
    assert c.get("/api/documents", headers=h).json() == []
    assert c.get(f"/api/reports/home?on={D}", headers=h).json()["cash_and_bank"] == "0.00"
    # and cannot use the other group's categories
    assert c.post("/api/documents/expense", headers=h, json={
        "unit_id": other_group.units["hospital"], "date": D, "amount": "1", "paid": True, "payment_mode": "cash",
        "category_id": group.cats["Rent"]}).status_code == 422


def test_unit_incharge_sees_only_own_unit(group):
    pharm = group.add_user("9000000010", "unit_incharge", ["pharmacy"])
    c = group.client
    c.post("/api/documents/collection", headers=group.owner,
           json={"unit_id": group.units["hospital"], "date": D, "amount": "9000", "payment_mode": "cash"})
    ok = c.post("/api/documents/collection", headers=pharm,
                json={"unit_id": group.units["pharmacy"], "date": D, "amount": "700", "payment_mode": "cash"})
    assert ok.status_code == 201
    assert c.post("/api/documents/collection", headers=pharm, json={
        "unit_id": group.units["hospital"], "date": D, "amount": "1", "payment_mode": "cash"}).status_code == 404
    home = c.get(f"/api/reports/home?on={D}", headers=pharm).json()
    assert home["cash_and_bank"] == "700.00"
    assert [u["unit"] for u in home["units_this_month"]] == ["Pharmacy"]
    # cannot cancel entries or close months
    assert c.post(f"/api/documents/{ok.json()['id']}/reverse", headers=pharm, json={"reason": "oops"}).status_code == 403
    assert c.post(f"/api/projects/{group.project}/periods/2026-11/lock", headers=pharm).status_code == 403


def test_auditor_is_read_only(group):
    aud = group.add_user("9000000011", "auditor")
    r = group.client.post("/api/documents/collection", headers=aud, json={
        "unit_id": group.units["hospital"], "date": D, "amount": "1", "payment_mode": "cash"})
    assert r.status_code == 403
    assert group.client.get("/api/documents", headers=aud).status_code == 200
