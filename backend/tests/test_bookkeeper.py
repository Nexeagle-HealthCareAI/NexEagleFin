from datetime import date
from decimal import Decimal

import pytest

from app.agents.extractors import GroqExtractor, Guess, Guesses, RuleExtractor
from app.agents.parse import StatementError, find_amount, parse_bank_csv, parse_notes
from app.agents_api import extractor_dep
from app.api import today
from app.main import app
from tests.test_ledger import assert_books_balance, balances

TODAY = date(2026, 11, 10)


# ---------- the parser: plain code decides every number ----------

@pytest.mark.parametrize("text,amount,clear", [
    ("paid 4850 to Shree Medical Gases", "4850.00", True),
    ("Rs. 1,25,000 salary", "125000.00", True),
    ("₹4,850.50 oxygen", "4850.50", True),
    ("2 lakh advance to builder", "200000.00", True),
    ("15k banner", "15000.00", True),
    ("3 cylinders for ₹4,500", "4500.00", True),          # the marked number wins
    ("3 cylinders 4500", None, False),                     # two bare numbers: ask a person
    ("oxygen cylinders", None, False),
    ("call 9876543210 paid 700", "700.00", True),          # phone numbers are not amounts
    ("received 162000 from National TPA", "162000.00", True),   # six digits without commas is still an amount
    ("advance 2500000 to builder", "2500000.00", True),
])
def test_find_amount(text, amount, clear):
    got, is_clear = find_amount(text)
    assert (None if got is None else str(got), is_clear) == (amount, clear)


def test_parse_notes_reads_direction_mode_date_and_unpaid():
    items = parse_notes(
        "paid 4850 to Shree Medical Gases for oxygen cash\n"
        "- received 26400 pharmacy counter upi 09/11/2026\n"
        "Medi Distributors bill 90000 to pay later\n"
        "\n"
        "tea 120",
        TODAY,
    )
    got = [(i.direction, str(i.amount), i.mode, i.paid, i.doc_date.isoformat(), i.flags) for i in items]
    assert got == [
        ("out", "4850.00", "cash", True, "2026-11-10", []),
        ("in", "26400.00", "upi", True, "2026-11-09", []),
        ("out", "90000.00", None, False, "2026-11-10", []),
        ("out", "120.00", None, True, "2026-11-10", ["mode_unclear"]),
    ]


STATEMENT = """Account statement,,,,
Txn Date,Narration,Withdrawal Amt,Deposit Amt,Balance
09/11/2026,UPI/RAMESH KUMAR/9876543210/payment,,700.00,10700.00
09/11/2026,NEFT-SHREE MEDICAL GASES-oxygen cylinders,"4,850.00",,5850.00
10/11/2026,NEFT CR-NATIONAL TPA SERVICES-CLM H2291,,"1,62,000.00",167850.00
10/11/2026,BY CASH DEPOSIT,,"2,10,000.00",377850.00
,Total,"4,850.00","3,72,700.00",
"""


def test_parse_bank_csv():
    items = parse_bank_csv(STATEMENT, TODAY)
    assert [(i.direction, str(i.amount), i.mode, i.flags) for i in items] == [
        ("in", "700.00", "upi", []),
        ("out", "4850.00", "bank", []),
        ("in", "162000.00", "bank", []),
        ("in", "210000.00", "bank", ["cash_deposit"]),
    ]
    with pytest.raises(StatementError):
        parse_bank_csv("a,b,c\n1,2,3\n", TODAY)


def test_private_details_never_reach_the_model():
    items = parse_bank_csv(STATEMENT, TODAY)
    assert items[0].needs_model is False                      # patient UPI payment: narration is not sent at all
    assert items[1].needs_model is True
    note = parse_notes("paid 500 to Ravi a/c 123456789012 ravi@example.com cash", TODAY)[0]
    assert "123456789012" not in note.safe_text and "ravi@example.com" not in note.safe_text


# ---------- the Groq reader, with the model replaced by a stand-in ----------

class StandInModel:
    """Plays the part of Groq. Records what it was sent and answers with whatever the test sets."""

    def __init__(self, answer):
        self.answer, self.seen = answer, []

    def invoke(self, messages):
        self.seen.append(messages)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


@pytest.fixture()
def use_model(client):
    def install(answer):
        model = StandInModel(answer)
        app.dependency_overrides[extractor_dep] = lambda: GroqExtractor(structured_llm=model)
        return model
    yield install
    app.dependency_overrides.pop(extractor_dep, None)


def run(group, source, content, headers=None, expect=201):
    r = group.client.post("/api/agents/bookkeeper/run", headers=headers or group.owner,
                          json={"project_id": group.project, "source": source, "content": content})
    assert r.status_code == expect, r.text
    return r.json()


def test_model_guesses_are_checked_and_nothing_posts_until_approved(group, db, use_model):
    model = use_model(Guesses(items=[
        Guess(index=0, kind="expense", party="Shree Medical Gases", category="medical supplies", unit="Hospital",
              confidence=0.93, reason="Oxygen is a medical supply."),
        Guess(index=1, kind="expense", party="Acme", category="Bribes", unit="Mars", confidence=0.99,
              reason="made-up category and unit"),
        Guess(index=7, kind="expense", category="Rent", confidence=1, reason="index that was never asked for"),
    ]))
    out = run(group, "text", "paid 4850 to Shree Medical Gases for oxygen cash\npaid 999 to Acme a/c 123456789012 upi")
    assert out["read_by"] == "groq"
    one, two = out["proposals"]
    assert (one["category"], one["unit"], one["amount"], one["confidence"], one["flags"]) == (
        "Medical supplies", "Hospital", "4850.00", 0.93, [])
    # the invented category and unit are dropped, confidence is capped, and it lands in the General unit
    assert (two["category"], two["unit"], two["confidence"], two["flags"]) == (None, "General", 0.5, ["no_category", "unit_unclear"])
    assert len(out["proposals"]) == 2
    # the account number was masked before the model saw it
    assert "123456789012" not in str(model.seen)

    assert balances(db, group.tenant.id) == {}                # suggestions do not touch the ledger

    r = group.client.post(f"/api/agents/proposals/{one['id']}/approve", headers=group.owner, json={})
    assert r.status_code == 200, r.text
    assert balances(db, group.tenant.id) == {"5000": Decimal("4850.00"), "1000": Decimal("-4850.00")}
    assert group.client.post(f"/api/agents/proposals/{one['id']}/approve", headers=group.owner, json={}).status_code == 409

    # the second is fixed by a person on approval
    r = group.client.post(f"/api/agents/proposals/{two['id']}/approve", headers=group.owner,
                          json={"category_id": group.cats["Other"], "unit_id": group.units["pharmacy"]})
    assert r.status_code == 200, r.text
    assert r.json()["document"]["unit_id"] == group.units["pharmacy"]
    assert_books_balance(db)
    pending = group.client.get(f"/api/agents/proposals?project_id={group.project}", headers=group.owner).json()
    assert pending == []


def test_model_cannot_change_amount_or_direction(group, use_model):
    use_model(Guesses(items=[Guess(index=0, kind="income", category="Rent", confidence=0.9, reason="says income")]))
    p = run(group, "text", "paid 5000 rent cash")["proposals"][0]
    assert (p["type"], p["amount"]) == ("expense", "5000.00")  # money out stays money out


def test_falls_back_to_rules_when_the_model_fails(group, use_model):
    use_model(RuntimeError("Groq is down"))
    out = run(group, "text", "paid 3200 electricity bill upi")
    assert out["read_by"] == "rules"
    assert out["proposals"][0]["category"] == "Utilities"


# ---------- end to end with keyword rules (no model configured) ----------

def test_bank_statement_to_books(group, db):
    out = run(group, "bank_csv", STATEMENT.replace("09/11/2026", today().strftime("%d/%m/%Y")).replace(
        "10/11/2026", today().strftime("%d/%m/%Y")))
    assert out["read_by"] == "rules"
    upi, gases, tpa, cash = out["proposals"]
    assert (upi["type"], upi["payment_mode"], upi["reason"]) == ("collection", "upi", "Patient payment received.")
    assert (gases["type"], gases["category"], gases["amount"]) == ("expense", "Medical supplies", "4850.00")
    assert tpa["type"] == "collection"
    assert "unit_unclear" in upi["flags"] and upi["unit"] == "General"
    assert "cash_deposit" in cash["flags"] and cash["confidence"] <= 0.3

    for p, unit in ((upi, "pharmacy"), (gases, "hospital")):
        r = group.client.post(f"/api/agents/proposals/{p['id']}/approve", headers=group.owner,
                              json={"unit_id": group.units[unit]})
        assert r.status_code == 200, r.text
    r = group.client.post(f"/api/agents/proposals/{cash['id']}/reject", headers=group.owner)
    assert r.status_code == 200
    assert balances(db, group.tenant.id) == {
        "1010": Decimal("-4150.00"), "4030": Decimal("-700.00"), "5000": Decimal("4850.00")}

    # uploading the same statement again flags what is already in the books
    again = run(group, "bank_csv", STATEMENT.replace("09/11/2026", today().strftime("%d/%m/%Y")).replace(
        "10/11/2026", today().strftime("%d/%m/%Y")))
    flagged = [("possible_duplicate" in p["flags"]) for p in again["proposals"]]
    assert flagged == [True, True, False, False]


def test_unclear_amount_and_mode_must_be_fixed_by_a_person(group):
    a, b = run(group, "text", "3 cylinders 4500 cash\npaid 120 tea")["proposals"]
    assert a["amount"] is None and "amount_unclear" in a["flags"] and a["confidence"] <= 0.2
    approve = lambda p, body: group.client.post(f"/api/agents/proposals/{p['id']}/approve", headers=group.owner, json=body)
    assert approve(a, {}).status_code == 422
    assert approve(a, {"amount": "4500"}).status_code == 200
    assert approve(b, {}).status_code == 422                   # how was it paid?
    assert approve(b, {"payment_mode": "cash"}).status_code == 200


def test_who_can_run_and_approve(group, other_group):
    staff = group.add_user("9000000030", "unit_incharge", ["pharmacy"])
    auditor = group.add_user("9000000031", "auditor")
    run(group, "text", "paid 100 tea cash", headers=auditor, expect=403)
    p = run(group, "text", "paid 100 tea cash", headers=group.owner)["proposals"][0]
    c = group.client
    assert c.post(f"/api/agents/proposals/{p['id']}/approve", headers=staff, json={}).status_code == 403
    assert c.post(f"/api/agents/proposals/{p['id']}/approve", headers=other_group.owner, json={}).status_code == 404
    assert c.get(f"/api/agents/proposals?project_id={group.project}", headers=other_group.owner).status_code == 404
    run(group, "text", "paid 1 tea cash", headers=other_group.owner, expect=404)
    run(group, "bank_csv", "not,a,statement", expect=422)


def test_single_unit_project_needs_no_unit_choice(group):
    r = group.client.post("/api/projects", headers=group.owner, json={"name": "City Lab", "units": ["path_lab"]})
    lab = r.json()["id"]
    out = group.client.post("/api/agents/bookkeeper/run", headers=group.owner,
                            json={"project_id": lab, "source": "text", "content": "received 900 cash"}).json()
    p = out["proposals"][0]
    assert (p["unit"], p["flags"]) == ("Path lab", [])


def test_unit_named_in_the_line_is_used_even_when_the_model_is_not_asked(group):
    p = run(group, "text", "received 26400 pharmacy counter upi")["proposals"][0]
    assert (p["type"], p["unit"], p["flags"]) == ("collection", "Pharmacy", [])


def test_approver_can_clear_a_suggested_category(group):
    p = run(group, "text", "paid 3200 electricity bill upi")["proposals"][0]
    assert p["category"] == "Utilities"
    r = group.client.post(f"/api/agents/proposals/{p['id']}/approve", headers=group.owner, json={"category_id": None})
    assert r.json()["document"]["status"] == "needs_attention"


@pytest.mark.parametrize("line,party", [
    ("Medi Distributors medicines bill 90000 to pay later", "Medi Distributors"),
    ("paid 4850 to Shree Medical Gases for oxygen cash", "Shree Medical Gases"),
    ("Ramesh Electricals repair 3500 cash", "Ramesh Electricals"),
    ("paid 500 to pay later", None),
    ("salary 120000 bank", None),
    ("tea 120 cash", None),
    ("Paid 2000 for diesel", None),
])
def test_who_was_paid(line, party):
    from app.agents.extractors import find_party
    assert find_party(line) == party
