from decimal import Decimal

from sqlalchemy import func, select

from app.models import Account, JournalLine

D = "2026-11-10"


def balances(db, tenant_id):
    rows = db.execute(
        select(Account.code, func.sum(JournalLine.debit - JournalLine.credit))
        .join(Account, Account.id == JournalLine.account_id)
        .where(JournalLine.tenant_id == tenant_id)
        .group_by(Account.code)
    ).all()
    return {code: Decimal(str(v)).quantize(Decimal("0.01")) for code, v in rows if Decimal(str(v)) != 0}


def assert_books_balance(db):
    total = db.scalar(select(func.sum(JournalLine.debit - JournalLine.credit)))
    assert Decimal(str(total)) == 0


def post(g, path, body, headers=None, expect=201):
    r = g.client.post(f"/api{path}", json=body, headers=headers or g.owner)
    assert r.status_code == expect, r.text
    return r.json()


def test_pharmacy_collection_by_upi(group, db):
    post(group, "/documents/collection",
         {"unit_id": group.units["pharmacy"], "date": D, "amount": "50000", "payment_mode": "upi"})
    assert balances(db, group.tenant.id) == {"1010": Decimal("50000.00"), "4030": Decimal("-50000.00")}


def test_cashless_claim_keeps_billed_approved_deducted_received(group, db):
    claim = post(group, "/documents/claim",
                 {"unit_id": group.units["hospital"], "date": D, "amount": "180000", "payer": "National TPA",
                  "reference": "H-2291"})
    assert balances(db, group.tenant.id) == {"1200": Decimal("180000.00"), "4000": Decimal("-180000.00")}

    post(group, f"/documents/{claim['id']}/settle", {"date": D, "received": "162000", "deduction": "18000"})
    assert balances(db, group.tenant.id) == {
        "1010": Decimal("162000.00"), "5900": Decimal("18000.00"), "4000": Decimal("-180000.00")}

    # nothing left to settle
    post(group, f"/documents/{claim['id']}/settle", {"date": D, "received": "1"}, expect=409)
    assert_books_balance(db)


def test_expense_paid_in_cash(group, db):
    post(group, "/documents/expense",
         {"unit_id": group.units["hospital"], "date": D, "amount": "4850", "category_id": group.cats["Medical supplies"],
          "paid_to": "Shree Medical Gases", "paid": True, "payment_mode": "cash"})
    assert balances(db, group.tenant.id) == {"5000": Decimal("4850.00"), "1000": Decimal("-4850.00")}


def test_save_now_sort_later(group, db):
    doc = post(group, "/documents/expense",
               {"unit_id": group.units["hospital"], "date": D, "amount": "1200.50", "paid": True, "payment_mode": "upi"})
    assert doc["status"] == "needs_attention"
    assert balances(db, group.tenant.id) == {"5999": Decimal("1200.50"), "1010": Decimal("-1200.50")}

    home = group.client.get(f"/api/reports/home?on={D}", headers=group.owner).json()
    assert home["needs_attention"] == 1

    sorted_ = post(group, f"/documents/{doc['id']}/categorize", {"category_id": group.cats["Utilities"]}, expect=200)
    assert sorted_["status"] == "posted"
    assert balances(db, group.tenant.id) == {"5060": Decimal("1200.50"), "1010": Decimal("-1200.50")}

    home = group.client.get(f"/api/reports/home?on={D}", headers=group.owner).json()
    assert home["needs_attention"] == 0
    assert home["money_out_today"] == "1200.50"  # counted once, not once per re-posting
    assert_books_balance(db)


def test_unpaid_bill_then_part_payment(group, db):
    bill = post(group, "/documents/expense",
                {"unit_id": group.units["pharmacy"], "date": D, "amount": "90000", "category_id": group.cats["Medicines"],
                 "paid_to": "Medi Distributors", "paid": False})
    assert balances(db, group.tenant.id) == {"5010": Decimal("90000.00"), "2000": Decimal("-90000.00")}
    post(group, f"/documents/{bill['id']}/pay", {"date": D, "amount": "40000", "payment_mode": "bank"})
    assert balances(db, group.tenant.id) == {
        "5010": Decimal("90000.00"), "2000": Decimal("-50000.00"), "1010": Decimal("-40000.00")}
    post(group, f"/documents/{bill['id']}/pay", {"date": D, "amount": "50000.01", "payment_mode": "bank"}, expect=409)
    home = group.client.get(f"/api/reports/home?on={D}", headers=group.owner).json()
    assert home["to_pay"] == "50000.00"


def test_reversal_cancels_without_deleting(group, db):
    doc = post(group, "/documents/collection",
               {"unit_id": group.units["path_lab"], "date": D, "amount": "7000", "payment_mode": "cash"})
    before = db.scalar(select(func.count()).select_from(JournalLine))
    out = post(group, f"/documents/{doc['id']}/reverse", {"reason": "entered twice"}, expect=200)
    assert out["status"] == "reversed"
    assert balances(db, group.tenant.id) == {}
    assert db.scalar(select(func.count()).select_from(JournalLine)) == before * 2
    post(group, f"/documents/{doc['id']}/reverse", {"reason": "again"}, expect=409)
    home = group.client.get(f"/api/reports/home?on={D}", headers=group.owner).json()
    assert home["money_in_today"] == "0.00"


def test_home_and_unit_profit(group):
    post(group, "/documents/collection",
         {"unit_id": group.units["hospital"], "date": D, "amount": "300000", "payment_mode": "bank"})
    post(group, "/documents/collection",
         {"unit_id": group.units["pharmacy"], "date": D, "amount": "26400", "payment_mode": "cash"})
    post(group, "/documents/expense",
         {"unit_id": group.units["hospital"], "date": D, "amount": "112750", "category_id": group.cats["Salaries"],
          "paid": True, "payment_mode": "bank"})
    home = group.client.get(f"/api/reports/home?on={D}", headers=group.owner).json()
    assert home["cash_and_bank"] == "213650.00"
    assert home["money_in_today"] == "326400.00"
    assert home["money_out_today"] == "112750.00"
    by_unit = {u["unit"]: u for u in home["units_this_month"]}
    assert by_unit["Hospital"]["profit"] == "187250.00"
    assert by_unit["Pharmacy"]["profit"] == "26400.00"
    assert by_unit["Diagnostics"]["profit"] == "0.00"


def test_dues_ageing(group):
    for date, amt, payer in [("2026-11-01", "100000", "National TPA"), ("2026-09-20", "60000", "PM-JAY"),
                             ("2026-07-01", "35000", "PM-JAY")]:
        post(group, "/documents/claim", {"unit_id": group.units["hospital"], "date": date, "amount": amt, "payer": payer})
    dues = group.client.get(f"/api/reports/dues?on={D}", headers=group.owner).json()
    assert dues["total"] == "195000.00"
    assert dues["ageing"] == {"0-30": "100000.00", "31-60": "60000.00", "61-90": "0.00", "90+": "35000.00"}
    assert dues["payers"][0]["name"] == "PM-JAY" and dues["payers"][0]["claims"] == 2


def test_locked_month_refuses_entries(group):
    r = group.client.post(f"/api/projects/{group.project}/periods/2026-10/lock", headers=group.owner)
    assert r.status_code == 200
    post(group, "/documents/collection",
         {"unit_id": group.units["hospital"], "date": "2026-10-15", "amount": "100", "payment_mode": "cash"}, expect=409)
    post(group, "/documents/collection",
         {"unit_id": group.units["hospital"], "date": D, "amount": "100", "payment_mode": "cash"})


def test_amount_must_be_positive_with_two_decimals(group):
    for bad in ["0", "-5", "10.999"]:
        post(group, "/documents/collection",
             {"unit_id": group.units["hospital"], "date": D, "amount": bad, "payment_mode": "cash"}, expect=422)


def test_open_items_and_unsorted_list(group):
    h = group.owner
    claim = post(group, "/documents/claim", {"unit_id": group.units["hospital"], "date": "2026-10-01", "amount": "180000",
                                             "payer": "National TPA", "reference": "H-2291"})
    post(group, f"/documents/{claim['id']}/settle", {"date": D, "received": "100000"})
    bill = post(group, "/documents/expense", {"unit_id": group.units["pharmacy"], "date": D, "amount": "90000",
                                              "category_id": group.cats["Medicines"], "paid_to": "Medi Distributors",
                                              "paid": False})
    post(group, "/documents/expense", {"unit_id": group.units["hospital"], "date": D, "amount": "500", "paid": True,
                                       "payment_mode": "cash", "paid_to": "Tea stall"})

    claims = group.client.get(f"/api/reports/open-items?kind=claim&on={D}&project_id={group.project}", headers=h).json()
    assert [(c["party"], c["reference"], c["due"], c["age_days"]) for c in claims] == [("National TPA", "H-2291", "80000.00", 40)]
    bills = group.client.get(f"/api/reports/open-items?kind=bill&on={D}", headers=h).json()
    assert [(b["party"], b["due"], b["unit"]) for b in bills] == [("Medi Distributors", "90000.00", "Pharmacy")]

    post(group, f"/documents/{bill['id']}/pay", {"date": D, "amount": "90000", "payment_mode": "bank"})
    assert group.client.get(f"/api/reports/open-items?kind=bill&on={D}", headers=h).json() == []

    unsorted = group.client.get(f"/api/documents?status=needs_attention&project_id={group.project}", headers=h).json()
    assert [(u["party"], u["amount"], u["unit"]) for u in unsorted] == [("Tea stall", "500.00", "Hospital")]


def test_entries_list_filters_and_detail(group):
    h, c = group.owner, group.client
    post(group, "/documents/collection", {"unit_id": group.units["pharmacy"], "date": D, "amount": "700", "payment_mode": "upi"})
    exp = post(group, "/documents/expense", {"unit_id": group.units["hospital"], "date": D, "amount": "4850",
                                             "category_id": group.cats["Medical supplies"], "paid_to": "Shree Gases",
                                             "paid": True, "payment_mode": "cash"})
    bill = post(group, "/documents/expense", {"unit_id": group.units["hospital"], "date": "2026-10-20", "amount": "900",
                                              "category_id": group.cats["Rent"], "paid_to": "Landlord", "paid": False})
    post(group, f"/documents/{bill['id']}/pay", {"date": D, "amount": "400", "payment_mode": "bank"})

    def ids(query):
        return [d["type"] for d in c.get(f"/api/documents?project_id={group.project}&{query}", headers=h).json()]

    assert sorted(ids("group=in")) == ["collection"]
    assert sorted(ids("group=out")) == ["expense", "vendor_payment"]
    assert ids("group=dues") == ["expense"]
    assert len(ids("month=2026-11")) == 3 and ids("month=2026-10") == ["expense"]
    assert len(ids("limit=2")) == 2 and len(ids("limit=2&offset=2")) == 2

    d = c.get(f"/api/documents/{exp['id']}", headers=h).json()
    assert (d["party"], d["category"], d["unit"], d["recorded_by"], d["month_locked"]) == (
        "Shree Gases", "Medical supplies", "Hospital", "Owner", False)
    assert [(b["account"], b["debit"], b["credit"]) for b in d["books"]] == [
        ("5000 Medical supplies", "4850.00", "0.00"), ("1000 Cash in hand", "0.00", "4850.00")]

    b = c.get(f"/api/documents/{bill['id']}", headers=h).json()
    assert [(p["type"], p["amount"]) for p in b["payments"]] == [("vendor_payment", "400.00")]

    c.post(f"/api/projects/{group.project}/periods/2026-10/lock", headers=h)
    assert c.get(f"/api/periods?project_id={group.project}", headers=h).json() == {"locked": ["2026-10"]}
    assert c.get(f"/api/documents/{bill['id']}", headers=h).json()["month_locked"] is True
    # after a cancel the detail shows both the original and the reversing lines
    c.post(f"/api/documents/{exp['id']}/reverse", headers=h, json={"reason": "entered twice"})
    d = c.get(f"/api/documents/{exp['id']}", headers=h).json()
    assert d["status"] == "reversed" and [b["reversal"] for b in d["books"]] == [False, False, True, True]
