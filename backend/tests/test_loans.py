from datetime import date, timedelta
from decimal import Decimal

from app.api import today
from app.loans import add_months, month_interest
from tests.test_ledger import assert_books_balance, balances

T = today()
START = (T - timedelta(days=75)).isoformat()
FIRST = (T - timedelta(days=45)).isoformat()      # so two instalments have fallen due by today


def new_loan(g, **over):
    body = {"project_id": g.project, "lender": "State Bank", "loan_type": "Equipment loan", "amount": "1200000",
            "start_date": START, "payment_mode": "bank", "rate": "12", "emi": "40000", "first_due": FIRST}
    body.update(over)
    return g.client.post("/api/loans", headers=g.owner, json=body)


def test_date_and_interest_arithmetic():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 11, 15), 3) == date(2027, 2, 15)
    assert month_interest(Decimal("1200000"), Decimal("12")) == Decimal("12000.00")
    assert month_interest(Decimal("100000"), Decimal("10.5")) == Decimal("875.00")


def test_new_loan_instalments_and_tracking(group, db):
    r = new_loan(group)
    assert r.status_code == 201, r.text
    loan = r.json()
    # money arrives in the bank and is owed to the lender; it is not income
    assert balances(db, group.tenant.id) == {"1010": Decimal("1200000.00"), "2100": Decimal("-1200000.00")}
    assert (loan["outstanding"], loan["overdue"], loan["next_due"], loan["next_amount"], loan["next_interest"]) == (
        "1200000.00", 2, FIRST, "40000.00", "12000.00")

    # first instalment: 12,000 interest, 28,000 off the loan
    pay = lambda body: group.client.post(f"/api/loans/{loan['id']}/pay", headers=group.owner, json=body)
    r = pay({"date": FIRST, "amount": "40000", "payment_mode": "bank"})
    assert r.status_code == 201, r.text
    assert (r.json()["payment"]["interest"], r.json()["payment"]["principal"]) == ("12000.00", "28000.00")
    assert balances(db, group.tenant.id) == {
        "1010": Decimal("1160000.00"), "2100": Decimal("-1172000.00"), "5800": Decimal("12000.00")}

    # second instalment with the interest taken from the lender's statement
    r = pay({"date": T.isoformat(), "amount": "40000", "interest": "11800.50", "payment_mode": "bank"})
    after = r.json()["loan"]
    assert (after["outstanding"], after["interest_paid"], after["instalments_paid"], after["overdue"]) == (
        "1143800.50", "23800.50", 2, 0)
    assert after["next_due"] == add_months(date.fromisoformat(FIRST), 2).isoformat()
    assert after["instalments_left"] > 30
    assert_books_balance(db)

    # interest shows as a cost of the project; the loan itself never shows as income
    home = group.client.get("/api/reports/home", headers=group.owner).json()
    assert home["loans"]["outstanding"] == "1143800.50" and home["loans"]["count"] == 1
    assert home["loans"]["next"]["lender"] == "State Bank"
    dash = group.client.get("/api/reports/projects", headers=group.owner).json()["projects"][0]
    assert dash["income_this_month"] == "0.00"

    detail = group.client.get(f"/api/loans/{loan['id']}", headers=group.owner).json()
    assert [p["principal"] for p in detail["payments"]] == ["28199.50", "28000.00"]
    assert len(detail["plan"]) == 12 and detail["plan"][0]["interest"] == "11438.01"


def test_loan_already_running_has_no_cash_movement(group, db):
    r = new_loan(group, already_running=True, payment_mode=None, amount="500000", rate="0", emi="25000",
                 lender="Uncle Rafiq", loan_type="Loan from partner or family")
    assert r.status_code == 201, r.text
    assert balances(db, group.tenant.id) == {"3900": Decimal("500000.00"), "2100": Decimal("-500000.00")}
    home = group.client.get("/api/reports/home", headers=group.owner).json()
    assert home["cash_and_bank"] == "0.00" and home["money_in_today"] == "0.00"
    # interest-free: the whole instalment reduces the loan
    pay = lambda body: group.client.post(f"/api/loans/{r.json()['id']}/pay", headers=group.owner, json=body)
    body = {"date": T.isoformat(), "amount": "25000", "payment_mode": "cash"}
    warned = pay(body)                                  # repaying 20,000 or more in cash is questioned first
    assert warned.status_code == 409 and "should not be repaid in cash" in warned.json()["detail"]["warnings"][0]
    r = pay({**body, "confirmed": True})
    assert r.json()["loan"]["outstanding"] == "475000.00" and r.json()["payment"]["interest"] == "0.00"


def test_final_instalment_closes_the_loan_and_overpaying_is_refused(group):
    loan = new_loan(group, amount="50000", rate="12", emi="30000").json()
    pay = lambda body: group.client.post(f"/api/loans/{loan['id']}/pay", headers=group.owner, json=body)
    assert pay({"date": T.isoformat(), "amount": "30000", "payment_mode": "bank"}).status_code == 201   # 500 interest
    now = group.client.get(f"/api/loans/{loan['id']}", headers=group.owner).json()
    assert (now["outstanding"], now["next_amount"], now["instalments_left"]) == ("20500.00", "20705.00", 1)
    assert pay({"date": T.isoformat(), "amount": "30000", "payment_mode": "bank"}).status_code == 409
    done = pay({"date": T.isoformat(), "amount": "20705", "payment_mode": "bank"}).json()["loan"]
    assert (done["status"], done["outstanding"], done["next_due"]) == ("closed", "0.00", None)
    assert pay({"date": T.isoformat(), "amount": "1", "payment_mode": "bank"}).status_code == 409
    assert group.client.get(f"/api/loans?project_id={group.project}", headers=group.owner).json()["overview"]["count"] == 0


def test_loan_rules(group, other_group):
    assert new_loan(group, emi="5000").status_code == 422                 # does not cover a month's interest
    assert new_loan(group, payment_mode=None).status_code == 422           # new loan must say how money came
    assert new_loan(group, first_due=(T - timedelta(days=400)).isoformat()).status_code == 422
    assert new_loan(group, loan_type="Payday").status_code == 422
    staff = group.add_user("9000000040", "unit_incharge", ["pharmacy"])
    body = {"project_id": group.project, "lender": "X Bank", "loan_type": "Term loan", "amount": "1000", "rate": "0",
            "start_date": START, "payment_mode": "bank", "emi": "100", "first_due": FIRST}
    assert group.client.post("/api/loans", headers=staff, json=body).status_code == 403
    assert group.client.post("/api/loans", headers=other_group.owner, json=body).status_code == 404
    loan = new_loan(group).json()
    c = group.client
    assert c.get(f"/api/loans/{loan['id']}", headers=other_group.owner).status_code == 404
    assert c.get(f"/api/loans?project_id={group.project}", headers=other_group.owner).status_code == 404


def test_cancelling_loan_entries(group, db):
    loan = new_loan(group).json()
    c, h = group.client, group.owner
    c.post(f"/api/loans/{loan['id']}/pay", headers=h, json={"date": T.isoformat(), "amount": "40000", "payment_mode": "bank"})
    docs = {d["type"]: d for d in c.get(f"/api/documents?project_id={group.project}", headers=h).json()}
    assert c.get(f"/api/documents?project_id={group.project}&group=out", headers=h).json()[0]["type"] == "loan_payment"
    # the loan cannot be cancelled while an instalment stands
    assert c.post(f"/api/documents/{docs['loan_received']['id']}/reverse", headers=h, json={"reason": "wrong"}).status_code == 409
    assert c.post(f"/api/documents/{docs['loan_payment']['id']}/reverse", headers=h, json={"reason": "wrong"}).status_code == 200
    assert c.get(f"/api/loans/{loan['id']}", headers=h).json()["outstanding"] == "1200000.00"
    assert c.post(f"/api/documents/{docs['loan_received']['id']}/reverse", headers=h, json={"reason": "wrong"}).status_code == 200
    assert balances(db, group.tenant.id) == {}
    assert c.get(f"/api/loans?project_id={group.project}", headers=h).json()["loans"] == []
