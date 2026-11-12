"""Several cash boxes and bank accounts per project, opening balances, transfers, and patient advances."""
from datetime import timedelta
from decimal import Decimal

from app.api import today
from tests.test_ledger import assert_books_balance, balances

T = today()
D = T.isoformat()
START = (T - timedelta(days=10)).isoformat()


def accounts(g, project=None):
    r = g.client.get(f"/api/money-accounts?project_id={project or g.project}", headers=g.owner)
    assert r.status_code == 200, r.text
    return {a["name"]: a for a in r.json()["accounts"]}, r.json()["total"]


def post(g, path, body, headers=None):
    return g.client.post(f"/api{path}", headers=headers or g.owner, json=body)


def home(g):
    return g.client.get(f"/api/reports/home?project_id={g.project}", headers=g.owner).json()


def test_every_project_starts_with_cash_and_a_bank(group):
    accs, total = accounts(group)
    assert list(accs) == ["Cash in hand", "Main bank account"] and total == "0.00"
    assert accs["Cash in hand"]["kind"] == "cash" and not accs["Cash in hand"]["has_opening"]


def test_opening_balances_and_new_accounts(group, db):
    accs, _ = accounts(group)
    r = post(group, f"/money-accounts/{accs['Cash in hand']['id']}/opening", {"amount": "35000", "date": START})
    assert r.status_code == 201 and r.json()["balance"] == "35000.00"
    assert post(group, f"/money-accounts/{accs['Cash in hand']['id']}/opening", {"amount": "1", "date": START}).status_code == 409
    r = post(group, "/money-accounts", {"project_id": group.project, "name": "HDFC current account", "kind": "bank",
                                        "opening_balance": "1250000", "as_of": START})
    assert r.status_code == 201, r.text
    hdfc = r.json()
    assert (hdfc["balance"], hdfc["has_opening"]) == ("1250000.00", True)
    assert post(group, "/money-accounts", {"project_id": group.project, "name": "hdfc current account", "kind": "bank"}).status_code == 409

    # opening balances are already-there money: in the totals, not in today's money in, not income
    h = home(group)
    assert h["cash_and_bank"] == "1285000.00" and h["money_in_today"] == "0.00"
    assert all(u["income"] == "0.00" for u in h["units_this_month"])
    assert balances(db, group.tenant.id)["3900"] == Decimal("-1285000.00")
    assert_books_balance(db)


def test_entries_go_to_the_chosen_account_and_kinds_must_match(group):
    hdfc = post(group, "/money-accounts", {"project_id": group.project, "name": "HDFC", "kind": "bank"}).json()
    accs, _ = accounts(group)
    cash = accs["Cash in hand"]["id"]
    body = {"unit_id": group.units["hospital"], "date": D, "amount": "26400", "payment_mode": "upi", "money_account_id": hdfc["id"]}
    assert post(group, "/documents/collection", body).status_code == 201
    accs, total = accounts(group)
    assert (accs["HDFC"]["balance"], accs["Main bank account"]["balance"], total) == ("26400.00", "0.00", "26400.00")
    # a UPI payment cannot land in a cash box, and an account from another project is refused
    assert post(group, "/documents/collection", {**body, "money_account_id": cash}).status_code == 422
    other = post(group, "/projects", {"name": "City Lab", "units": ["path_lab"]}).json()
    lab_bank = accounts(group, other["id"])[0]["Main bank account"]["id"]
    assert post(group, "/documents/collection", {**body, "money_account_id": lab_bank}).status_code == 422


def test_transfers_move_money_without_counting_as_in_or_out(group, db):
    accs, _ = accounts(group)
    cash, bank = accs["Cash in hand"]["id"], accs["Main bank account"]["id"]
    post(group, "/documents/collection", {"unit_id": group.units["hospital"], "date": D, "amount": "60000", "payment_mode": "cash", "reference": "OP-1"})
    r = post(group, "/transfers", {"from_account_id": cash, "to_account_id": bank, "amount": "50000", "date": D, "note": "Deposited at branch"})
    assert r.status_code == 201, r.text
    accs, total = accounts(group)
    assert (accs["Cash in hand"]["balance"], accs["Main bank account"]["balance"], total) == ("10000.00", "50000.00", "60000.00")
    h = home(group)
    assert (h["money_in_today"], h["money_out_today"], h["cash_and_bank"]) == ("60000.00", "0.00", "60000.00")
    # cash cannot go below zero; the same account twice is refused
    assert "Only ₹10,000 was in Cash in hand" in post(group, "/transfers", {"from_account_id": cash, "to_account_id": bank, "amount": "20000", "date": D}).json()["detail"]
    assert post(group, "/transfers", {"from_account_id": cash, "to_account_id": cash, "amount": "1", "date": D}).status_code == 422
    # cancelling the transfer puts the money back
    t = [d for d in group.client.get(f"/api/documents?project_id={group.project}", headers=group.owner).json() if d["type"] == "transfer"][0]
    assert post(group, f"/documents/{t['id']}/reverse", {"reason": "deposit bounced"}).status_code == 200
    assert accounts(group)[0]["Cash in hand"]["balance"] == "60000.00"
    assert_books_balance(db)


def test_patient_advance_held_adjusted_and_refunded(group, db):
    u = group.units["hospital"]
    adv = post(group, "/advances", {"unit_id": u, "date": START, "amount": "100000", "payment_mode": "upi", "reference": "IP-1021"})
    assert adv.status_code == 201, adv.text
    adv = adv.json()
    # held money is owed to the patient: in the bank, but not income
    h = home(group)
    assert (h["cash_and_bank"], h["advances_held"]) == ("100000.00", "100000.00")
    assert all(x["income"] == "0.00" for x in h["units_this_month"])
    held = group.client.get(f"/api/reports/open-items?kind=advance&project_id={group.project}", headers=group.owner).json()
    assert [(a["reference"], a["due"]) for a in held] == [("IP-1021", "100000.00")]

    # at discharge the bill was 85,000: that much becomes income, 15,000 is refunded
    assert post(group, f"/documents/{adv['id']}/adjust-advance", {"date": D, "amount": "85000"}).status_code == 201
    assert post(group, f"/documents/{adv['id']}/refund-advance", {"date": D, "amount": "20000", "payment_mode": "upi"}).status_code == 409
    assert post(group, f"/documents/{adv['id']}/refund-advance", {"date": D, "amount": "15000", "payment_mode": "upi"}).status_code == 201
    h = home(group)
    assert (h["cash_and_bank"], h["advances_held"]) == ("85000.00", "0.00")
    hospital = next(x for x in h["units_this_month"] if x["unit"] == "Hospital")
    assert hospital["income"] == "85000.00"
    assert group.client.get(f"/api/reports/open-items?kind=advance&project_id={group.project}", headers=group.owner).json() == []
    assert post(group, f"/documents/{adv['id']}/reverse", {"reason": "wrong patient"}).status_code == 409   # cancel its children first
    assert_books_balance(db)


def test_cash_advances_count_towards_the_patient_cash_limit(group):
    u = group.units["hospital"]
    assert post(group, "/advances", {"unit_id": u, "date": D, "amount": "150000", "payment_mode": "cash", "reference": "IP-77"}).status_code == 201
    r = post(group, "/documents/collection", {"unit_id": u, "date": D, "amount": "60000", "payment_mode": "cash", "reference": "IP-77"})
    assert r.status_code == 409 and "comes to ₹2,10,000" in r.json()["detail"]["warnings"][0]


def test_who_may_manage_accounts(group, other_group):
    staff = group.add_user("9000000080", "unit_incharge", ["pharmacy"])
    assert post(group, "/money-accounts", {"project_id": group.project, "name": "Petty cash", "kind": "cash"}, headers=staff).status_code == 403
    assert group.client.get(f"/api/money-accounts?project_id={group.project}", headers=staff).status_code == 404
    assert group.client.get(f"/api/money-accounts?project_id={group.project}", headers=other_group.owner).status_code == 404
    cash = accounts(group)[0]["Cash in hand"]["id"]
    assert post(group, f"/money-accounts/{cash}/opening", {"amount": "1", "date": D}, headers=other_group.owner).status_code == 404


def test_chat_knows_accounts_and_advances(group):
    post(group, "/money-accounts", {"project_id": group.project, "name": "HDFC current account", "kind": "bank",
                                    "opening_balance": "500000", "as_of": START})
    post(group, "/advances", {"unit_id": group.units["hospital"], "date": D, "amount": "40000", "payment_mode": "upi", "reference": "IP-5"})
    ask = lambda m: group.client.post("/api/agents/chat", headers=group.owner, json={"project_id": group.project, "message": m}).json()
    a = ask("show balance account wise")
    assert a["reply"] == "Across 3 accounts you have ₹5,40,000."
    assert {"label": "HDFC current account", "value": "₹5,00,000"} in a["facts"]
    b = ask("how much patient advance is held?")
    assert b["reply"].startswith("₹40,000 of patient advances is held for 1 patient.")
