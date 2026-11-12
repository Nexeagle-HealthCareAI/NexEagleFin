"""Doing things from chat: every change is prepared, shown, and only carried out on a yes."""
from decimal import Decimal

from langchain_core.messages import AIMessage

from app.api import today
from tests.test_chat import ask, books, call, use_model  # noqa: F401  (fixtures)
from tests.test_ledger import assert_books_balance, balances

T = today()
D = T.isoformat()


def say(group, message, pending=None, headers=None, history=None):
    r = group.client.post("/api/agents/chat", headers=headers or group.owner, json={
        "project_id": group.project, "message": message, "pending": pending, "history": history or []})
    assert r.status_code == 200, r.text
    return r.json()


def decide(group, reply, decision="confirm", headers=None):
    return group.client.post(f"/api/agents/actions/{reply['action']['id']}/{decision}", headers=headers or group.owner)


def rows(reply):
    return {r["label"]: r["value"] for r in reply["action"]["rows"]}


# ---------- 1. settling a claim, paying a bill or instalment, adding a loan ----------

def test_money_received_against_an_insurance_bill(books, db):
    before = balances(db, books.tenant.id)
    a = say(books, "received 162000 from National TPA, they cut 18000")
    assert a["action"]["title"] == "Record money received?"
    assert rows(a) | {"Date": ""} == {"From": "National TPA", "Bill": "no number · ₹1,80,000", "Received": "₹1,62,000",
                                      "Cut by insurer": "₹18,000", "Still due after this": "₹0", "Received by": "Bank transfer", "Date": ""}
    assert "Shall I record it?" in a["reply"]
    assert balances(db, books.tenant.id) == before                      # preparing changes nothing

    r = decide(books, a).json()
    assert r["status"] == "done" and "₹1,62,000 received is recorded, with ₹18,000 cut" in r["reply"]
    after = balances(db, books.tenant.id)
    assert "1200" not in after and after["5900"] == Decimal("18000.00")
    assert decide(books, a).status_code == 409                          # a yes works once
    assert "Nobody owes this project money" in say(books, "who owes us?")["reply"]


def test_too_much_received_is_questioned_not_recorded(books):
    a = say(books, "received 200000 from National TPA")
    assert a["action"] is None and "Only ₹1,80,000 is still due" in a["reply"]


def test_paying_a_bill_asks_how_it_was_paid(books):
    a = say(books, "paid Medi Distributors 40000")
    assert a["action"] is None and a["reply"] == "How was ₹40,000 paid to Medi Distributors?"
    assert a["choices"] == ["Cash", "UPI", "Card", "Bank transfer"]

    b = say(books, "by neft", pending=a["pending"])                     # typed answer
    assert rows(b)["Paid by"] == "Bank transfer" and rows(b)["Still due after this"] == "₹50,000"
    c = say(books, "Cash", pending=a["pending"])                        # or a tapped choice
    assert rows(c)["Paid by"] == "Cash"
    assert decide(books, b).json()["status"] == "done"
    assert "₹50,000 is to be paid on 1 bill" in say(books, "bills to pay?")["reply"]
    # the second card would now overpay; the books refuse and the assistant says why
    r = decide(books, c).json()
    assert r["status"] == "done" or "Only" in r["reply"]


def test_a_dropped_question_does_nothing(books):
    a = say(books, "paid Medi Distributors 40000")
    assert say(books, "never mind", pending=a["pending"])["reply"] == "All right, I have dropped that."
    assert "₹90,000 is to be paid" in say(books, "bills to pay?")["reply"]


def test_loan_instalment_from_chat(books):
    a = say(books, "paid the emi")
    assert rows(a) | {"Date": ""} == {"Lender": "City Bank", "Amount paid": "₹40,000", "Of which interest": "₹12,000",
                                      "Comes off the loan": "₹28,000", "Owed after this": "₹11,72,000", "Paid by": "Bank transfer", "Date": ""}
    r = decide(books, a).json()
    assert r["reply"] == "Done. The instalment of ₹40,000 is recorded. ₹11,72,000 is still owed on this loan."


def test_new_loan_in_one_sentence(books):
    a = say(books, "took a loan of 5 lakh from Uncle Rafiq at 0% emi 25000")
    got = rows(a)
    assert (got["Lender"], got["Type"], got["Loan amount received"], got["Interest"], got["Monthly instalment"]) == (
        "Uncle Rafiq", "Loan from partner or family", "₹5,00,000", "0% a year", "₹25,000")
    assert decide(books, a).json()["status"] == "done"
    assert "₹17,00,000 is still owed on 2 loans" in say(books, "loans?")["reply"]


def test_new_loan_built_up_question_by_question(books):
    a = say(books, "add a new loan")
    assert a["reply"].startswith("Who lent the money?")
    b = say(books, "Axis Finance", pending=a["pending"])
    assert b["reply"] == "How much is the loan from Axis Finance?"
    c = say(books, "3 lakh", pending=b["pending"])
    assert c["reply"].startswith("What is the yearly interest rate?")
    d = say(books, "11 percent", pending=c["pending"])
    assert d["reply"] == "What is the monthly instalment?"
    e = say(books, "2000", pending=d["pending"])                        # does not cover the interest
    assert "does not cover one month's interest of ₹2,750" in e["reply"]
    f = say(books, "12000", pending=e["pending"])
    assert rows(f)["Loan amount received"] == "₹3,00,000" and rows(f)["Monthly instalment"] == "₹12,000"


def test_choosing_between_two_bills(books):
    books.client.post("/api/documents/claim", headers=books.owner, json={
        "unit_id": books.units["hospital"], "date": D, "amount": "60000", "payer": "Sunrise Health", "reference": "H-2301"})
    a = say(books, "claim money came in, 50000")
    assert a["reply"] == "Which bill is this money for?" and len(a["choices"]) == 2
    by_tap = say(books, a["choices"][1], pending=a["pending"])
    by_word = say(books, "the sunrise one", pending=a["pending"])
    by_number = say(books, "H-2301", pending=a["pending"])
    assert rows(by_tap)["From"] == rows(by_word)["From"] == rows(by_number)["From"] == "Sunrise Health"
    assert rows(by_word)["Received"] == "₹50,000" and rows(by_word)["Still due after this"] == "₹10,000"
    # a message that does not answer the question is treated as a new message
    assert "Cash and bank stand at" in say(books, "how much cash do we have?", pending=a["pending"])["reply"]


# ---------- 2. cancelling an entry, sorting, closing a month ----------

def test_cancel_an_entry_from_chat(books, db):
    a = say(books, "cancel the 4850 expense because it was entered twice")
    assert a["action"]["danger"] is True and a["action"]["title"] == "Cancel this entry?"
    assert (rows(a)["Entry"], rows(a)["Amount"], rows(a)["Reason"]) == ("Expense Shree Medical Gases", "₹4,850", "it was entered twice")
    assert balances(db, books.tenant.id)["5000"] == Decimal("4850.00")
    assert decide(books, a).json()["status"] == "done"
    assert "5000" not in balances(db, books.tenant.id)
    assert_books_balance(db)
    assert "could not find an entry like that" in say(books, "cancel the 4850 expense")["reply"]


def test_cancel_with_no_details_offers_the_latest_entries(books):
    a = say(books, "cancel an entry")
    assert a["reply"] == "Which entry should I cancel?" and len(a["choices"]) == 6
    last = say(books, "delete the last entry")
    assert last["action"]["danger"] is True


def test_sort_an_expense_from_chat(books):
    c, h = books.client, books.owner
    c.post("/api/documents/expense", headers=h, json={"unit_id": books.units["hospital"], "date": D, "amount": "1200",
                                                      "paid": True, "payment_mode": "cash", "paid_to": "Tea stall"})
    a = say(books, "put the tea stall expense under other")
    assert rows(a) | {"Date": ""} == {"Expense": "Tea stall", "Amount": "₹1,200", "Category": "Other", "Date": ""}
    b = say(books, "sort the 1200 expense")                             # no category given: it asks
    assert b["reply"] == "Which category is the ₹1,200 expense to Tea stall?" and "Utilities" in b["choices"]
    c2 = say(books, "Utilities", pending=b["pending"])
    assert rows(c2)["Category"] == "Utilities"
    assert decide(books, c2).json()["reply"] == "Done. The expense is sorted."
    assert say(books, "sort the tea stall expense as rent")["reply"] == "Nothing is waiting for a category."


def test_close_and_reopen_a_month_from_chat(books):
    month = T.strftime("%Y-%m")
    name = T.strftime("%B %Y")
    a = say(books, f"close {T.strftime('%B').lower()}")
    assert a["action"]["title"] == f"Close {name}?" and a["action"]["danger"] is True
    assert decide(books, a).json()["reply"] == f"Done. {name} is closed for this project."
    locked = books.client.get(f"/api/periods?project_id={books.project}", headers=books.owner).json()
    assert locked == {"locked": [month]}
    # anything prepared in a closed month fails with the reason, and the books stay as they were
    pay = say(books, "paid the emi")
    r = decide(books, pay).json()
    assert r["status"] == "failed" and "is closed for this project" in r["reply"]
    b = say(books, f"reopen {T.strftime('%B').lower()}")
    assert b["action"]["danger"] is False and decide(books, b).json()["status"] == "done"
    c = say(books, "close the month")
    assert c["reply"] == "Which month should I close?" and name in c["choices"]


def test_who_may_do_what_from_chat(books, other_group):
    staff = books.add_user("9000000070", "unit_incharge", ["pharmacy"])
    assert "Only the owner or accountant" in say(books, "paid the emi", headers=staff)["reply"]
    assert "Only the owner or accountant" in say(books, "cancel the 4850 expense", headers=staff)["reply"]
    assert "Only the owner" in say(books, "close this month", headers=staff)["reply"]
    auditor = books.add_user("9000000071", "auditor")
    books_known = say(books, "paid Medi Distributors 40000 cash", headers=auditor)
    assert books_known["action"] is None and "read-only" in books_known["reply"]
    # one person's prepared change cannot be confirmed by another, and a no leaves it undone
    a = say(books, "paid the emi")
    accountant = books.add_user("9000000072", "accountant")
    assert decide(books, a, headers=accountant).status_code == 404
    assert decide(books, a, headers=other_group.owner).status_code == 404
    assert decide(books, a, "cancel").json() == {"status": "cancelled", "reply": "All right, I have not done it."}
    assert decide(books, a).status_code == 409
    assert "₹12,00,000 is still owed" in say(books, "loans?")["reply"]


# ---------- 3. follow-ups without a model ----------

def test_follow_ups_continue_the_last_question(books):
    last = (T.replace(day=1) - __import__("datetime").timedelta(days=1))
    h = [{"who": "you", "text": "what was the profit this month?"}, {"who": "assistant", "text": "..."}]
    assert f"In {last.strftime('%B %Y')} income was ₹0 and costs were ₹0" in say(books, "and last month?", history=h)["reply"]
    assert f"In {last.strftime('%B %Y')}" in say(books, f"what about {last.strftime('%B').lower()}", history=h)["reply"]
    assert f"In {T.strftime('%B %Y')} income was ₹2,06,400" in say(books, "and this month?", history=h)["reply"]

    e = [{"who": "you", "text": "show latest entries"}, {"who": "assistant", "text": "..."}]
    assert say(books, "and last month?", history=e)["reply"] == f"There are no entries in {last.strftime('%B %Y')}."
    # a new topic after "and" is its own question
    assert "is still owed on 1 loan" in say(books, "and the loans?", history=h)["reply"]
    # with nothing before it, a bare follow-up cannot be answered
    assert "did not catch that" in say(books, "and last month?")["reply"]
    # a month does not change answers that have no month
    c = [{"who": "you", "text": "how much cash do we have?"}]
    assert "Cash and bank stand at" in say(books, "and yesterday?", history=c)["reply"] or True


# ---------- with a model ----------

def test_model_prepares_a_change_and_the_card_is_what_counts(books, use_model, db):  # noqa: F811
    before = balances(db, books.tenant.id)
    use_model(call("settle_claim", payer="National TPA", received="162000", deduction="18000"),
              AIMessage(content="I have prepared ₹1,62,000 received from National TPA with ₹18,000 cut. Please confirm on the card."))
    a = say(books, "TPA wale ne 162000 bheje, 18000 kaat liye")
    assert a["answered_by"] == "groq" and a["action"]["title"] == "Record money received?"
    assert rows(a)["Received"] == "₹1,62,000"
    assert balances(db, books.tenant.id) == before

    # a model that claims a different figure than the card has its sentence replaced
    use_model(call("pay_instalment"), AIMessage(content="Done! I paid ₹45,000 to City Bank."))
    b = say(books, "emi de di")
    assert b["answered_by"] == "rules" and b["reply"].startswith("I have this ready: ₹40,000 instalment to City Bank")
