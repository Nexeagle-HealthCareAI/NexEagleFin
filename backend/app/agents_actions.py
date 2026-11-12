"""Changes the chat assistant can prepare, and how each is carried out once the person says yes.

Preparing never changes the books. A prepare tool works out exactly what would be done, stores it as a
ChatAction and returns a confirm card. Only `execute`, called when the same person confirms, changes
anything, and it does so through the same functions the screens use, so every rule and permission
applies exactly as it does there.
"""

import json
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import api as A
from . import loans as L
from . import loans_api
from .agents import chat as C
from .agents.parse import find_date, find_mode
from .checks import cash_warnings
from .models import LOAN_TYPES, Category, ChatAction, Document, Loan, Party, Project, Unit, User

MODE_TEXT = {"cash": "Cash", "upi": "UPI", "card": "Card", "bank": "Bank transfer"}
MODE_OPTIONS = [{"label": text, "args": {"mode": mode}} for mode, text in MODE_TEXT.items()]
ZERO = Decimal("0")


def money(text) -> Decimal | None:
    """An amount from whatever was typed or passed: 162000, "1,62,000", "12 lakh"."""
    if text in (None, ""):
        return None
    found = C.amounts_in(str(text))
    return found[0][1] if found else None


def as_mode(value) -> str | None:
    """cash, upi, card or bank from a stored value or from the person's words."""
    text = str(value or "").strip().lower()
    return text if text in MODE_TEXT else find_mode(text)


def truthy(value) -> bool:
    return str(value).strip().lower() in ("yes", "true", "1", "y", "running", "reopen")


def loan_type_from(text: str | None) -> str:
    low = (text or "").lower()
    for word, kind in [("equipment", "Equipment loan"), ("machine", "Equipment loan"), ("vehicle", "Vehicle loan"),
                       ("ambulance", "Vehicle loan"), ("car ", "Vehicle loan"), ("building", "Building or property loan"),
                       ("property", "Building or property loan"), ("overdraft", "Working capital or overdraft"),
                       ("working capital", "Working capital or overdraft"), ("gold", "Gold loan"),
                       ("partner", "Loan from partner or family"), ("family", "Loan from partner or family"),
                       ("uncle", "Loan from partner or family"), ("friend", "Loan from partner or family"),
                       ("personal", "Personal or unsecured loan"), ("unsecured", "Personal or unsecured loan")]:
        if word in low:
            return kind
    return next((t for t in LOAN_TYPES if t.lower() == low.strip()), "Term loan")


def write_tools(db: Session, user: User, project_id: str) -> list[C.Tool]:
    inr, today = C.inr, A.today()
    keeper = user.role in ("owner", "accountant")
    writer = user.role in ("owner", "accountant", "unit_incharge", "cashier")

    def warn(**fields) -> list[str]:
        """The same cash-limit check the save will run, so the card can show it before the yes."""
        return cash_warnings(db, Document(tenant_id=user.tenant_id, doc_date=today, paid=True, **fields))

    def card(kind: str, title: str, rows: list[tuple[str, str]], params: dict, say: str, danger: bool = False,
             warnings: list[str] | None = None) -> C.Result:
        shown = [{"label": k, "value": v} for k, v in rows]
        if warnings:
            say += " Before you confirm: " + " ".join(warnings)
        action = ChatAction(tenant_id=user.tenant_id, project_id=project_id, user_id=user.id, kind=kind, title=title,
                            params=json.dumps(params), rows=json.dumps(shown))
        db.add(action)
        db.commit()
        return C.Result(say, action={"id": action.id, "title": title, "rows": shown, "danger": danger, "warnings": warnings or []})

    def ask(say: str, tool: str, args: dict, missing: str, options: list[dict] | None = None) -> C.Result:
        kept = {k: v for k, v in args.items() if v not in (None, "")}
        return C.Result(say, ask={"tool": tool, "args": kept, "missing": missing, "options": options or []})

    def pick(items: list[dict], names_key: str, name: str | None, text: str | None) -> list[dict]:
        """Narrow a list of open items by the name given, or by names mentioned in the text."""
        if name:
            exact = [i for i in items if (i[names_key] or "").lower() == name.lower()]
            if exact:
                return exact
        wanted = C.best_names(" ".join(filter(None, [name, text])), [i[names_key] for i in items])
        return [i for i in items if i[names_key] in wanted] if wanted else items

    # ----- money received against an insurance or credit bill -----
    def settle_claim(payer=None, reference=None, received=None, deduction=None, mode=None, text=None, claim_id=None) -> C.Result:
        if not writer:
            return C.Result("Your login is read-only, so I cannot record this.")
        claims = A.open_items(kind="claim", project_id=project_id, on=None, user=user, db=db)
        if not claims:
            return C.Result("There are no open insurance or credit bills to receive money against.")
        if claim_id:
            claims = [c for c in claims if c["id"] == claim_id]
        else:
            if reference:
                by_ref = [c for c in claims if (c["reference"] or "").lower() == str(reference).lower()]
                claims = by_ref or claims
            claims = pick(claims, "party", payer, text)
        args = {"payer": payer, "reference": reference, "received": received, "deduction": deduction, "mode": mode}
        if len(claims) != 1:
            options = [{"label": f"{c['party']} · {c['reference'] or 'no bill number'} · {inr(c['due'])} due", "args": {"claim_id": c["id"]}}
                       for c in claims[:6]]
            return ask("Which bill is this money for?", "settle_claim", args, "choice", options)
        claim = claims[0]
        due, cut = Decimal(claim["due"]), money(deduction) or ZERO
        got = money(received) or (due - cut)
        if got <= 0 or got + cut > due:
            return C.Result(f"Only {inr(due)} is still due on that bill from {claim['party']}, so {inr(got)} received"
                            f"{f' plus {inr(cut)} cut' if cut else ''} does not fit. Tell me the right amounts.")
        mode = as_mode(mode) or "bank"
        rows = [("From", claim["party"] or "Unknown"), ("Bill", f"{claim['reference'] or 'no number'} · {inr(claim['amount'])}"),
                ("Received", inr(got))]
        if cut:
            rows.append(("Cut by insurer", inr(cut)))
        rows += [("Still due after this", inr(due - got - cut)), ("Received by", MODE_TEXT[mode]), ("Date", C.nice_date(today.isoformat()))]
        source = db.get(Document, claim["id"])
        return card("settle_claim", "Record money received?", rows,
                    {"claim_id": claim["id"], "received": str(got), "deduction": str(cut), "mode": mode, "date": today.isoformat()},
                    f"I have this ready: {inr(got)} received from {claim['party']}"
                    f"{f', with {inr(cut)} cut' if cut else ''}. Shall I record it?",
                    warnings=warn(type="claim_settlement", unit_id=source.unit_id, amount=got, payment_mode=mode, party_id=source.party_id))

    # ----- paying a vendor's unpaid bill -----
    def pay_bill(vendor=None, amount=None, mode=None, text=None, bill_id=None) -> C.Result:
        if not writer:
            return C.Result("Your login is read-only, so I cannot record this.")
        bills = A.open_items(kind="bill", project_id=project_id, on=None, user=user, db=db)
        if not bills:
            return C.Result("There are no unpaid bills. If you paid for something new, tell me what and how much and I will record it as an expense.")
        bills = [b for b in bills if b["id"] == bill_id] if bill_id else pick(bills, "party", vendor, text)
        args = {"vendor": vendor, "amount": amount, "mode": mode}
        if len(bills) != 1:
            options = [{"label": f"{b['party']} · {inr(b['due'])} due · {C.nice_date(b['date'])}", "args": {"bill_id": b["id"]}} for b in bills[:6]]
            return ask("Which bill did you pay?", "pay_bill", args, "choice", options)
        bill = bills[0]
        args["bill_id"] = bill["id"]
        due, pay = Decimal(bill["due"]), money(amount) or Decimal(bill["due"])
        if pay > due:
            return C.Result(f"Only {inr(due)} is still due to {bill['party']}, which is less than {inr(pay)}. How much was paid?")
        mode = as_mode(mode)
        if not mode:
            return ask(f"How was {inr(pay)} paid to {bill['party']}?", "pay_bill", {**args, "amount": str(pay)}, "mode", MODE_OPTIONS)
        rows = [("Paid to", bill["party"] or "Unknown"), ("Amount", inr(pay)), ("Still due after this", inr(due - pay)),
                ("Paid by", MODE_TEXT[mode]), ("Date", C.nice_date(today.isoformat()))]
        source = db.get(Document, bill["id"])
        return card("pay_bill", "Record this payment?", rows,
                    {"bill_id": bill["id"], "amount": str(pay), "mode": mode, "date": today.isoformat()},
                    f"I have this ready: {inr(pay)} paid to {bill['party']} by {MODE_TEXT[mode].lower()}. Shall I record it?",
                    warnings=warn(type="vendor_payment", unit_id=source.unit_id, amount=pay, payment_mode=mode, party_id=source.party_id))

    # ----- a loan instalment -----
    def pay_instalment(lender=None, amount=None, interest=None, mode=None, loan_id=None) -> C.Result:
        if not keeper:
            return C.Result("Only the owner or accountant can record loan payments.")
        loans = [x for x in loans_api.list_loans(project_id=project_id, user=user, db=db)["loans"] if x["status"] == "active"]
        if not loans:
            return C.Result("No active loans are recorded for this project.")
        loans = [x for x in loans if x["id"] == loan_id] if loan_id else pick(loans, "lender", lender, None)
        args = {"lender": lender, "amount": amount, "interest": interest, "mode": mode}
        if len(loans) != 1:
            options = [{"label": f"{x['lender']} · {inr(x['next_amount'])} due {C.nice_date(x['next_due'])}", "args": {"loan_id": x["id"]}} for x in loans[:6]]
            return ask("Which loan is this instalment for?", "pay_instalment", args, "choice", options)
        loan = loans[0]
        pay = money(amount) or Decimal(loan["next_amount"])
        part = money(interest) if interest not in (None, "") else None
        if part is None:
            part = min(Decimal(loan["next_interest"]), pay)
        owed = Decimal(loan["outstanding"])
        if part > pay or pay - part > owed:
            return C.Result(f"{inr(owed)} is still owed to {loan['lender']} and this month's interest is {inr(loan['next_interest'])}, "
                            f"so the most to pay is {inr(owed + Decimal(loan['next_interest']))}. How much was paid?")
        mode = as_mode(mode) or "bank"
        rows = [("Lender", loan["lender"]), ("Amount paid", inr(pay)), ("Of which interest", inr(part)),
                ("Comes off the loan", inr(pay - part)), ("Owed after this", inr(owed - (pay - part))),
                ("Paid by", MODE_TEXT[mode]), ("Date", C.nice_date(today.isoformat()))]
        return card("pay_instalment", "Record this instalment?", rows,
                    {"loan_id": loan["id"], "amount": str(pay), "interest": str(part), "mode": mode, "date": today.isoformat()},
                    f"I have this ready: {inr(pay)} instalment to {loan['lender']}, of which {inr(part)} is interest. Shall I record it?",
                    warnings=warn(type="loan_payment", unit_id=db.get(Loan, loan["id"]).unit_id, amount=pay, payment_mode=mode))

    # ----- a new loan -----
    def add_loan(lender=None, amount=None, rate=None, emi=None, loan_type=None, first_due=None, already_running=None, mode=None) -> C.Result:
        if not keeper:
            return C.Result("Only the owner or accountant can add a loan.")
        args = {"lender": lender, "amount": amount, "rate": rate, "emi": emi, "loan_type": loan_type, "first_due": first_due,
                "already_running": already_running, "mode": mode}
        principal, instalment = money(amount), money(emi)
        try:
            yearly = Decimal(str(rate).replace("%", "").strip()) if rate not in (None, "") else None
        except Exception:
            yearly = None
        if not (lender or "").strip():
            return ask("Who lent the money? A bank, a company or a person.", "add_loan", args, "lender")
        if principal is None:
            return ask(f"How much is the loan from {lender}?", "add_loan", args, "amount")
        if yearly is None or not (ZERO <= yearly <= 60):
            return ask("What is the yearly interest rate? Say 0 if there is no interest.", "add_loan", {**args, "rate": None}, "rate")
        if instalment is None:
            return ask("What is the monthly instalment?", "add_loan", args, "emi")
        if instalment <= L.month_interest(principal, yearly):
            return ask(f"An instalment of {inr(instalment)} does not cover one month's interest of {inr(L.month_interest(principal, yearly))}. "
                       "What is the correct monthly instalment?", "add_loan", {**args, "emi": None}, "emi")
        running = truthy(already_running)
        due, _ = find_date(str(first_due or ""), today)
        if not due or due < today:
            due = L.add_months(today, 1)
        kind = loan_type_from(loan_type)
        mode = as_mode(mode) or "bank"
        rows = [("Lender", lender.strip()), ("Type", kind),
                ("Amount still owed today" if running else "Loan amount received", inr(principal)),
                ("Interest", f"{yearly.normalize():f}% a year"), ("Monthly instalment", inr(instalment)),
                ("First instalment" if not running else "Next instalment", C.nice_date(due.isoformat()))]
        if not running:
            rows.append(("Received by", MODE_TEXT[mode]))
        return card("add_loan", "Add this loan?", rows,
                    {"lender": lender.strip(), "loan_type": kind, "amount": str(principal), "rate": str(yearly), "emi": str(instalment),
                     "first_due": due.isoformat(), "already_running": running, "mode": None if running else mode,
                     "start_date": today.isoformat()},
                    f"I have this ready: a {kind.lower()} of {inr(principal)} from {lender.strip()} at {yearly.normalize():f}% "
                    f"with {inr(instalment)} a month. Shall I add it?",
                    warnings=[] if running else warn(type="loan_received", unit_id=A.project_units(db, user, project_id)[0],
                                                     amount=principal, payment_mode=mode))

    # ----- cancel an entry -----
    def cancel_entry(amount=None, party=None, which=None, reason=None, text=None, doc_id=None) -> C.Result:
        if not keeper:
            return C.Result("Only the owner or accountant can cancel an entry.")
        docs = A.list_documents(status=None, type=None, group=None, unit_id=None, project_id=project_id, month=None,
                                limit=40, offset=0, user=user, db=db)
        docs = [d for d in docs if d["status"] != "reversed"]
        if doc_id:
            docs = [d for d in docs if d["id"] == doc_id]
        else:
            value = money(amount)
            if value is not None:
                docs = [d for d in docs if Decimal(d["amount"]) == value]
            named = C.best_names(" ".join(filter(None, [party, text])), [d["party"] for d in docs])
            if named:
                docs = [d for d in docs if d["party"] in named]
            if str(which or "").lower() == "last" and docs:
                docs = docs[:1]
        args = {"amount": amount, "party": party, "reason": reason}
        if not docs:
            return C.Result("I could not find an entry like that. Tell me its amount or who it was paid to.")

        def name(d: dict) -> str:
            words = {"collection": "Collection", "investment": "Investment", "claim": "Bill to", "claim_settlement": "Received from",
                     "vendor_payment": "Paid", "loan_received": "Loan from", "loan_payment": "Loan instalment to", "expense": "Expense",
                     "transfer": "Transfer", "opening_balance": "Opening balance", "advance_received": "Advance",
                     "advance_adjusted": "Advance used for bill", "advance_refund": "Advance refunded"}
            return (words.get(d["type"], d["type"]) + " " + (d["party"] or "")).strip()

        if len(docs) != 1:
            options = [{"label": f"{name(d)} · {inr(d['amount'])} · {C.nice_date(d['date'])}", "args": {"doc_id": d["id"]}} for d in docs[:6]]
            return ask("Which entry should I cancel?", "cancel_entry", args, "choice", options)
        d = docs[0]
        why = (reason or "").strip() or "Cancelled from the assistant"
        rows = [("Entry", name(d)), ("Amount", inr(d["amount"])), ("Date", C.nice_date(d["date"])), ("Unit", d["unit"]), ("Reason", why)]
        return card("cancel_entry", "Cancel this entry?", rows, {"doc_id": d["id"], "reason": why[:250]},
                    f"I found it: {name(d)}, {inr(d['amount'])} on {C.nice_date(d['date'])}. Cancelling undoes its effect on the books "
                    "and keeps it visible as cancelled. Shall I cancel it?", danger=True)

    # ----- give an unsorted expense a category -----
    def sort_expense(category=None, amount=None, text=None, doc_id=None) -> C.Result:
        if not writer:
            return C.Result("Your login is read-only, so I cannot sort entries.")
        waiting = A.list_documents(status="needs_attention", type=None, group=None, unit_id=None, project_id=project_id, month=None,
                                   limit=40, offset=0, user=user, db=db)
        if not waiting:
            return C.Result("Nothing is waiting for a category.")
        cats = dict(db.execute(select(Category.name, Category.id).where(Category.tenant_id == user.tenant_id)).all())
        match = C.best_names(category or "", list(cats)) or C.best_names(text or "", list(cats))
        args = {"category": category, "amount": amount}
        if doc_id:
            waiting = [d for d in waiting if d["id"] == doc_id]
        else:
            value = money(amount)
            if value is not None:
                waiting = [d for d in waiting if Decimal(d["amount"]) == value] or waiting
            named = C.best_names(text or "", [d["party"] for d in waiting])
            if named:
                waiting = [d for d in waiting if d["party"] in named]
        if len(waiting) != 1:
            options = [{"label": f"{d['party'] or 'No name'} · {inr(d['amount'])} · {C.nice_date(d['date'])}", "args": {"doc_id": d["id"]}} for d in waiting[:6]]
            return ask("Which expense do you mean?", "sort_expense", args, "choice", options)
        d = waiting[0]
        if len(match) != 1:
            options = [{"label": c, "args": {"category": c}} for c in sorted(cats)]
            return ask(f"Which category is the {inr(d['amount'])} expense{' to ' + d['party'] if d['party'] else ''}?",
                       "sort_expense", {**args, "category": None, "doc_id": d["id"]}, "choice", options)
        rows = [("Expense", d["party"] or "No name given"), ("Amount", inr(d["amount"])), ("Date", C.nice_date(d["date"])),
                ("Category", match[0])]
        return card("sort_expense", "Sort this expense?", rows, {"doc_id": d["id"], "category_id": cats[match[0]]},
                    f"I will put the {inr(d['amount'])} expense{' to ' + d['party'] if d['party'] else ''} under {match[0]}. Shall I?")

    # ----- close or reopen a month -----
    def close_month(month=None, reopen=None) -> C.Result:
        if user.role != "owner":
            return C.Result("Only the owner can close or reopen a month.")
        opening = truthy(reopen)
        this = today.strftime("%Y-%m")
        last = L.add_months(today.replace(day=1), -1).strftime("%Y-%m")
        try:
            A._month_range(month or "")
        except HTTPException:
            options = [{"label": C.month_name(m), "args": {"month": m}} for m in (last, this)]
            return ask(f"Which month should I {'reopen' if opening else 'close'}?", "close_month", {"reopen": reopen}, "choice", options)
        project = db.get(Project, project_id)
        rows = [("Project", project.name), ("Month", C.month_name(month)),
                ("Effect", "Entries can be added and cancelled again" if opening else "No entry can be added or cancelled in this month")]
        return card("close_month", f"{'Reopen' if opening else 'Close'} {C.month_name(month)}?", rows,
                    {"month": month, "action": "unlock" if opening else "lock"},
                    f"{'Reopening' if opening else 'Closing'} {C.month_name(month)} for {project.name}. "
                    f"{'Entries can then be changed again.' if opening else 'After that nothing can be added or cancelled in it.'} Shall I?",
                    danger=not opening)

    T = C.Tool
    said = "exactly as the user said it; empty if they did not say"
    return [
        T("settle_claim", "Prepare recording money received against an open insurance, scheme or company bill.", settle_claim,
          {"payer": f"who paid, {said}", "reference": "bill number if given", "received": f"amount received, {said}",
           "deduction": "amount the insurer cut, if said", "mode": "cash, upi, card or bank if said", "text": "the user's whole message"}),
        T("pay_bill", "Prepare recording a payment against a vendor's unpaid bill.", pay_bill,
          {"vendor": f"vendor name, {said}", "amount": f"amount paid, {said}", "mode": "cash, upi, card or bank if said",
           "text": "the user's whole message"}),
        T("pay_instalment", "Prepare recording a loan instalment (EMI) that was paid.", pay_instalment,
          {"lender": f"lender name, {said}", "amount": f"amount paid, {said}", "interest": "interest part if the user gave it",
           "mode": "cash, upi, card or bank if said"}),
        T("add_loan", "Prepare adding a loan the project has taken.", add_loan,
          {"lender": "who lent the money", "amount": "loan amount, or amount still owed if already running",
           "rate": "yearly interest rate as a number", "emi": "monthly instalment", "loan_type": "kind of loan in the user's words",
           "first_due": "date of the first or next instalment if given", "already_running": "yes if the loan was already being repaid",
           "mode": "how the money was received, if said"}),
        T("cancel_entry", "Prepare cancelling an entry that was recorded by mistake.", cancel_entry,
          {"amount": "amount of the entry if given", "party": "who it was paid to or received from, if given",
           "which": "last, if the user means the most recent entry", "reason": "why, if the user said", "text": "the user's whole message"}),
        T("sort_expense", "Prepare giving a category to an expense that was saved without one.", sort_expense,
          {"category": "category name", "amount": "amount of the expense if given", "text": "the user's whole message"}),
        T("close_month", "Prepare closing a month so nothing in it can change, or reopening it.", close_month,
          {"month": "month as YYYY-MM", "reopen": "yes to reopen instead of close"}),
    ]


def known_names(db: Session, user: User, project_id: str) -> dict:
    """Names already in the books, so the rules can tell a payment against a bill from a new entry."""
    claims = A.open_items(kind="claim", project_id=project_id, on=None, user=user, db=db)
    bills = A.open_items(kind="bill", project_id=project_id, on=None, user=user, db=db)
    lenders = db.scalars(select(Loan.lender).where(Loan.tenant_id == user.tenant_id, Loan.project_id == project_id, Loan.status == "active"))
    cats = db.scalars(select(Category.name).where(Category.tenant_id == user.tenant_id))
    return {"payers": [c["party"] for c in claims], "vendors": [b["party"] for b in bills], "lenders": list(lenders),
            "categories": list(cats)}


def execute(db: Session, user: User, action: ChatAction) -> str:
    """Carry out a confirmed action through the same functions the screens call. Returns what to tell the person."""
    p, inr = json.loads(action.params), C.inr
    day = lambda key: date.fromisoformat(p[key])  # noqa: E731
    if action.kind == "settle_claim":
        A.settle_claim(p["claim_id"], A.SettleIn(date=day("date"), received=Decimal(p["received"]), deduction=Decimal(p["deduction"]),
                                                 payment_mode=p["mode"], confirmed=True), user=user, db=db)
        cut = Decimal(p["deduction"])
        return f"Done. {inr(p['received'])} received is recorded{f', with {inr(cut)} cut by the insurer' if cut else ''}."
    if action.kind == "pay_bill":
        A.pay_bill(p["bill_id"], A.PayIn(date=day("date"), amount=Decimal(p["amount"]), payment_mode=p["mode"], confirmed=True),
                  user=user, db=db)
        return f"Done. The payment of {inr(p['amount'])} is recorded."
    if action.kind == "pay_instalment":
        out = loans_api.pay_instalment(p["loan_id"], loans_api.PayIn(date=day("date"), amount=Decimal(p["amount"]),
                                       interest=Decimal(p["interest"]), payment_mode=p["mode"], confirmed=True), user=user, db=db)
        left = out["loan"]["outstanding"]
        return f"Done. The instalment of {inr(p['amount'])} is recorded. {inr(left)} is still owed on this loan."
    if action.kind == "add_loan":
        loans_api.create_loan(loans_api.LoanIn(project_id=action.project_id, lender=p["lender"], loan_type=p["loan_type"],
                              amount=Decimal(p["amount"]), already_running=p["already_running"], start_date=day("start_date"),
                              payment_mode=p["mode"], rate=Decimal(p["rate"]), emi=Decimal(p["emi"]), first_due=day("first_due"), confirmed=True),
                              user=user, db=db)
        return f"Done. The loan from {p['lender']} is added, and I will track its instalments."
    if action.kind == "cancel_entry":
        A.reverse_document(p["doc_id"], A.ReverseIn(reason=p["reason"]), user=user, db=db)
        return "Done. The entry is cancelled and its effect on the books is undone."
    if action.kind == "sort_expense":
        A.categorize(p["doc_id"], A.CategorizeIn(category_id=p["category_id"]), user=user, db=db)
        return "Done. The expense is sorted."
    if action.kind == "close_month":
        A.set_period(action.project_id, p["month"], p["action"], user=user, db=db)
        return f"Done. {C.month_name(p['month'])} is {'closed' if p['action'] == 'lock' else 'open again'} for this project."
    raise HTTPException(422, "I do not know how to do that")


def decide(db: Session, user: User, action_id: str, confirm: bool) -> dict:
    action = db.get(ChatAction, action_id)
    if not action or action.tenant_id != user.tenant_id or action.user_id != user.id:
        raise HTTPException(404, "That request was not found")
    if action.status != "pending":
        raise HTTPException(409, f"This was already {action.status}")
    A.project_units(db, user, action.project_id)
    stamp = datetime.now(timezone.utc)
    if not confirm:
        action.status, action.decided_at = "cancelled", stamp
        db.commit()
        return {"status": "cancelled", "reply": "All right, I have not done it."}
    try:
        reply = execute(db, user, action)
    except HTTPException as e:
        db.rollback()
        action = db.get(ChatAction, action_id)
        action.status, action.decided_at, action.result = "failed", stamp, str(e.detail)[:1000]
        db.commit()
        return {"status": "failed", "reply": f"I could not do that: {e.detail}"}
    action = db.get(ChatAction, action_id)
    action.status, action.decided_at, action.result = "done", stamp, reply
    db.commit()
    return {"status": "done", "reply": reply}
