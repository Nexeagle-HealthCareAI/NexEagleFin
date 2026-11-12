from datetime import date
from decimal import Decimal

import pytest
from langchain_core.messages import AIMessage

from app.agents.chat import find_month, inr, invented_figures, plan_by_rules
from app.agents_api import chat_model_dep
from app.api import today
from app.main import app
from tests.test_ledger import balances

D = today().isoformat()
NOW = date(2026, 11, 12)


@pytest.mark.parametrize("value,text", [
    ("1842500", "₹18,42,500"), ("4850.5", "₹4,850.50"), ("0", "₹0"), ("999", "₹999"), ("100000", "₹1,00,000"),
    ("-4150", "-₹4,150"), ("123456789.10", "₹12,34,56,789.10"),
])
def test_indian_rupee_format(value, text):
    assert inr(value) == text


def test_month_words():
    assert find_month("profit in october", NOW) == "2026-10"
    assert find_month("how was last month", NOW) == "2026-10"
    assert find_month("december costs", NOW) == "2025-12"       # a month still ahead means last year's
    assert find_month("show cash", NOW) is None


@pytest.mark.parametrize("message,tools", [
    ("how much cash do we have?", ["overview"]),
    ("what is our profit this month", ["profit"]),
    ("who owes us money?", ["money_to_receive"]),
    ("which bills are unpaid", ["bills_to_pay"]),
    ("when is the next emi", ["loans"]),
    ("show recent entries", ["entries"]),
    ("give me a summary", ["overview", "money_to_receive", "bills_to_pay", "loans"]),
    ("paid 4850 to Shree Medical Gases for oxygen cash", ["record"]),
    ("how much did we pay Shree Gases? 4850?", []),               # a question with a number is not an entry
    ("hello", []),
])
def test_rules_pick_the_right_tools(message, tools):
    assert [name for name, _ in plan_by_rules(message, NOW)] == tools


def test_invented_figures_are_caught():
    books = "Cash and bank stand at ₹18,42,500. Today ₹3,26,400 came in."
    assert invented_figures("You have ₹18,42,500 in hand.", books) == []
    assert invented_figures("You have ₹18,42,500, about ₹2,00,000 more than last week.", books) == [Decimal("200000")]
    assert invented_figures("3 bills are open.", books) == []      # small counts are not money


def ask(group, message, headers=None, history=None):
    r = group.client.post("/api/agents/chat", headers=headers or group.owner,
                          json={"project_id": group.project, "message": message, "history": history or []})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture()
def books(group):
    """A project with a little of everything."""
    c, h, u = group.client, group.owner, group.units
    post = lambda path, body: c.post(f"/api{path}", headers=h, json=body)
    post("/documents/investment", {"project_id": group.project, "date": D, "amount": "500000"})
    post("/documents/collection", {"unit_id": u["pharmacy"], "date": D, "amount": "26400", "payment_mode": "upi"})
    post("/documents/expense", {"unit_id": u["hospital"], "date": D, "amount": "4850", "category_id": group.cats["Medical supplies"],
                                "paid_to": "Shree Medical Gases", "paid": True, "payment_mode": "cash"})
    post("/documents/expense", {"unit_id": u["pharmacy"], "date": D, "amount": "90000", "category_id": group.cats["Medicines"],
                                "paid_to": "Medi Distributors", "paid": False})
    post("/documents/claim", {"unit_id": u["hospital"], "date": D, "amount": "180000", "payer": "National TPA"})
    post("/loans", {"project_id": group.project, "lender": "City Bank", "loan_type": "Equipment loan", "amount": "1200000",
                    "start_date": D, "payment_mode": "bank", "rate": "12", "emi": "40000", "first_due": D})
    return group


def test_answers_come_from_the_books(books):
    a = ask(books, "how much cash do we have?")
    assert a["answered_by"] == "rules"
    assert a["reply"].startswith("Cash and bank stand at ₹17,21,550.")       # 5,00,000 + 26,400 - 4,850 + 12,00,000
    assert {"label": "To pay", "value": "₹90,000"} in a["facts"]

    a = ask(books, "what is the profit this month?")
    assert "income was ₹2,06,400 and costs were ₹94,850, a profit of ₹1,11,550" in a["reply"]
    assert any(f["label"] == "Pharmacy" and f["value"].startswith("-₹63,600") for f in a["facts"])

    assert "₹1,80,000 is still to be received from 1 payer" in ask(books, "who owes us?")["reply"]
    assert "₹90,000 is to be paid on 1 bill" in ask(books, "any unpaid bills?")["reply"]
    a = ask(books, "tell me about our loans")
    assert "₹12,00,000 is still owed on 1 loan, with instalments of ₹40,000 a month" in a["reply"] and "City Bank" in a["reply"]
    assert len(ask(books, "show latest entries")["facts"]) == 6
    assert "Ask me about cash and bank" in ask(books, "hello")["reply"]
    assert "did not catch that" in ask(books, "sing me a song")["reply"]


def test_recording_from_chat_only_prepares_suggestions(books, db):
    before = balances(db, books.tenant.id)
    a = ask(books, "paid 3200 electricity bill upi")
    assert "I prepared 1 entry" in a["reply"] and "Nothing is saved until it is approved" in a["reply"]
    assert a["proposals"][0]["amount"] == "3200.00" and a["proposals"][0]["category"] == "Utilities"
    assert balances(db, books.tenant.id) == before


def test_chat_respects_who_is_asking(books, other_group):
    staff = books.add_user("9000000060", "unit_incharge", ["pharmacy"])
    a = ask(books, "how much cash do we have and what about loans?", headers=staff)
    assert "Cash and bank stand at ₹26,400." in a["reply"]                     # only their unit
    assert "No loans are recorded" in a["reply"]                                # loans belong to the whole project
    auditor = books.add_user("9000000061", "auditor")
    assert "read-only" in ask(books, "paid 100 tea cash", headers=auditor)["reply"]
    r = books.client.post("/api/agents/chat", headers=other_group.owner, json={"project_id": books.project, "message": "cash?"})
    assert r.status_code == 404


# ---------- with a model: Groq replaced by a stand-in that follows a script ----------

class ScriptedModel:
    def __init__(self, *steps):
        self.steps, self.seen = list(steps), []

    def bind_tools(self, tools):
        self.tool_names = [t.name for t in tools]
        return self

    def invoke(self, messages):
        self.seen.append(messages)
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def call(name, **args):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call-{name}"}])


@pytest.fixture()
def use_model(client):
    def install(*steps):
        model = ScriptedModel(*steps)
        app.dependency_overrides[chat_model_dep] = lambda: model
        return model
    yield install
    app.dependency_overrides.pop(chat_model_dep, None)


def test_model_looks_up_then_answers_in_its_own_words(books, use_model):
    model = use_model(call("overview"), AIMessage(content="You have ₹17,21,550 across cash and bank. Today ₹17,26,400 came in."))
    a = ask(books, "paisa kitna hai?", history=[{"who": "you", "text": "hello"}, {"who": "assistant", "text": "Hello."}])
    assert a["answered_by"] == "groq"
    assert a["reply"] == "You have ₹17,21,550 across cash and bank. Today ₹17,26,400 came in."
    assert "record" in model.tool_names
    second_round = str(model.seen[1])
    assert "Cash and bank stand at ₹17,21,550" in second_round                  # the tool result went back to the model
    assert "hello" in str(model.seen[0])                                        # earlier turns give it context


def test_a_figure_the_books_did_not_give_is_never_shown(books, use_model):
    use_model(call("overview"), AIMessage(content="You have about ₹20,00,000, up ₹3,00,000 on last month."))
    a = ask(books, "how much cash?")
    assert a["answered_by"] == "rules"
    assert a["reply"].startswith("Cash and bank stand at ₹17,21,550.") and "20,00,000" not in a["reply"]

    use_model(call("overview"), AIMessage(content="You have roughly 17.2 lakh."))    # converting counts as inventing
    assert "17.2 lakh" not in ask(books, "how much cash?")["reply"]


def test_model_failure_falls_back_to_rules(books, use_model):
    use_model(RuntimeError("Groq is down"))
    a = ask(books, "how much cash do we have?")
    assert a["answered_by"] == "rules" and "₹17,21,550" in a["reply"]


def test_model_cannot_call_tools_that_do_not_exist_or_loop_forever(books, use_model):
    use_model(call("delete_everything"), AIMessage(content="I cannot do that from chat."))
    assert ask(books, "delete all entries")["reply"] == "I cannot do that from chat."
    use_model(*[call("overview") for _ in range(10)])
    a = ask(books, "cash?")
    assert a["reply"].startswith("Cash and bank stand at")                     # gave up after a few rounds, still answered
