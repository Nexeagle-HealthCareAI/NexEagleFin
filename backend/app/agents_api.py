"""Endpoints for the agents. Agents suggest; people approve; the posting engine writes."""

import re
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import api as A
from . import agents_actions as X
from . import loans_api
from . import money_api
from .agents import chat as C
from .agents.bookkeeper import build_graph, existing_entries
from .agents.extractors import get_extractor
from .agents.parse import StatementError, find_mode
from .api import Amount, Mode, find_party, project_units, save, today
from .db import get_db
from .models import AuditLog, Category, Document, Proposal, Unit, User
from .security import current_user, require_write

router = APIRouter(prefix="/agents")
APPROVERS = ("owner", "accountant")
Day = date  # the field below is itself called "date"


def extractor_dep():
    return get_extractor()


def proposal_out(p: Proposal, categories: dict, units: dict) -> dict:
    return {
        "id": p.id,
        "status": p.status,
        "source": p.source,
        "raw_text": p.raw_text,
        "type": p.doc_type,
        "date": p.doc_date.isoformat(),
        "amount": None if p.amount is None else str(p.amount),
        "payment_mode": p.payment_mode,
        "paid": p.paid,
        "party": p.party_name,
        "category_id": p.category_id,
        "category": categories.get(p.category_id),
        "unit_id": p.unit_id,
        "unit": units.get(p.unit_id),
        "confidence": float(p.confidence),
        "reason": p.reason,
        "flags": [f for f in p.flags.split(",") if f],
        "read_by": p.read_by,
        "document_id": p.document_id,
    }


def _lookups(db: Session, user: User, unit_ids: list[str]) -> tuple[dict, dict]:
    cats = dict(db.execute(select(Category.id, Category.name).where(Category.tenant_id == user.tenant_id)).all())
    units = dict(db.execute(select(Unit.id, Unit.name).where(Unit.id.in_(unit_ids))).all())
    return cats, units


class RunIn(BaseModel):
    project_id: str
    source: Literal["text", "bank_csv"]
    content: str = Field(min_length=3, max_length=200_000)


@router.post("/bookkeeper/run", status_code=201)
def run_bookkeeper(body: RunIn, user: User = Depends(current_user), db: Session = Depends(get_db),
                   extractor=Depends(extractor_dep)):
    require_write(user)
    unit_ids = project_units(db, user, body.project_id)
    cats, units = _lookups(db, user, unit_ids)
    cat_by_name = {name: id_ for id_, name in cats.items()}
    unit_by_name = {name: id_ for id_, name in units.items()}
    # When the agent cannot tell the unit: a project with one real unit uses it; otherwise the entry
    # is parked in General and flagged so the approver picks.
    kinds = dict(db.execute(select(Unit.id, Unit.kind).where(Unit.id.in_(unit_ids))).all())
    real = [u for u, kind in kinds.items() if kind != "general"]
    general = next((u for u, kind in kinds.items() if kind == "general"), None)
    default_unit = real[0] if len(real) == 1 else (general or unit_ids[0])
    unit_is_a_guess = len(real) != 1

    on = today()
    try:
        result = build_graph(extractor).invoke({
            "source": body.source,
            "content": body.content,
            "today": on,
            "categories": sorted(cat_by_name),
            "units": sorted(unit_by_name),
            "existing": existing_entries(db, user.tenant_id, unit_ids, on - timedelta(days=120)),
        })
    except StatementError as e:
        raise HTTPException(422, str(e))
    if not result["drafts"]:
        raise HTTPException(422, "Nothing to read. Type one entry per line, for example: paid 4850 to Shree Gases cash")

    run_id = str(uuid.uuid4())
    made = []
    for d in result["drafts"]:
        if d["unit"] not in unit_by_name and unit_is_a_guess and d["doc_type"] != "investment":
            d["flags"].append("unit_unclear")
        p = Proposal(
            tenant_id=user.tenant_id, project_id=body.project_id, run_id=run_id, agent="bookkeeper",
            source=body.source, raw_text=d["raw_text"], doc_type=d["doc_type"], doc_date=d["doc_date"],
            amount=d["amount"], payment_mode=d["payment_mode"], paid=d["paid"], party_name=d["party_name"],
            category_id=cat_by_name.get(d["category"]), unit_id=unit_by_name.get(d["unit"], default_unit),
            confidence=d["confidence"], reason=d["reason"], flags=",".join(d["flags"]),
            read_by=result["read_by"], created_by=user.id,
        )
        db.add(p)
        made.append(p)
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="agent:bookkeeper", ref=run_id,
                    detail=f"{len(made)} suggestions from {body.source}, read by {result['read_by']}"))
    db.commit()
    return {"run_id": run_id, "read_by": result["read_by"], "proposals": [proposal_out(p, cats, units) for p in made]}


@router.get("/proposals")
def list_proposals(project_id: str, status: str = "pending", user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    unit_ids = project_units(db, user, project_id)
    cats, units = _lookups(db, user, unit_ids)
    rows = db.scalars(
        select(Proposal).where(
            Proposal.tenant_id == user.tenant_id, Proposal.project_id == project_id,
            Proposal.unit_id.in_(unit_ids), Proposal.status == status,
        ).order_by(Proposal.created_at.desc(), Proposal.id).limit(300)
    ).all()
    return [proposal_out(p, cats, units) for p in rows]


def _get(db: Session, user: User, proposal_id: str) -> Proposal:
    p = db.get(Proposal, proposal_id)
    if not p or p.tenant_id != user.tenant_id or p.unit_id not in project_units(db, user, p.project_id):
        raise HTTPException(404, "Suggestion not found")
    if p.status != "pending":
        raise HTTPException(409, f"Already {p.status}")
    return p


class ApproveIn(BaseModel):
    """Anything sent here overrides what the agent suggested."""

    amount: Decimal | None = Field(None, gt=0, max_digits=14, decimal_places=2)
    date: Day | None = None
    category_id: str | None = None
    unit_id: str | None = None
    payment_mode: Mode | None = None
    party: str | None = Field(None, max_length=200)
    confirmed: bool = False


@router.post("/proposals/{proposal_id}/approve")
def approve(proposal_id: str, body: ApproveIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role not in APPROVERS:
        raise HTTPException(403, "Only the owner or accountant can approve a suggestion")
    p = _get(db, user, proposal_id)
    unit_ids = project_units(db, user, p.project_id)

    amount = body.amount or p.amount
    if amount is None:
        raise HTTPException(422, "Enter the amount")
    unit_id = body.unit_id or p.unit_id
    if unit_id not in unit_ids:
        raise HTTPException(422, "Unknown unit")
    # an explicit "sort later" (null) from the approver overrides the suggested category
    category_id = body.category_id if "category_id" in body.model_fields_set else p.category_id
    if category_id:
        cat = db.get(Category, category_id)
        if not cat or cat.tenant_id != user.tenant_id:
            raise HTTPException(422, "Unknown category")
    mode = body.payment_mode or p.payment_mode
    when = body.date or p.doc_date
    if when > today():
        raise HTTPException(422, "The date cannot be in the future")
    party = body.party if body.party is not None else p.party_name
    note = f"From {'bank statement' if p.source == 'bank_csv' else 'note'}: {p.raw_text}"[:1000]

    if p.doc_type == "expense":
        if p.paid and not mode:
            raise HTTPException(422, "Choose how it was paid")
        if not p.paid and not (party or "").strip():
            raise HTTPException(422, "Say who is to be paid")
        doc = Document(
            tenant_id=user.tenant_id, unit_id=unit_id, type="expense", doc_date=when, amount=amount,
            category_id=category_id, party_id=find_party(db, user.tenant_id, party, "vendor"), paid=p.paid,
            payment_mode=mode if p.paid else None, note=note, created_by=user.id,
            status="posted" if category_id else "needs_attention",
        )
    else:
        if not mode:
            raise HTTPException(422, "Choose how the money came in")
        if p.doc_type == "investment":
            general = db.scalar(select(Unit.id).where(Unit.project_id == p.project_id, Unit.kind == "general"))
            unit_id = general or unit_id
        doc = Document(
            tenant_id=user.tenant_id, unit_id=unit_id, type=p.doc_type, doc_date=when, amount=amount,
            payment_mode=mode, note=note, created_by=user.id,
        )
    db.add(doc)
    db.flush()
    p.status, p.decided_by, p.document_id = "approved", user.id, doc.id
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="proposal:approve", ref=p.id))
    saved = save(db, doc, user, body.confirmed)  # posts and commits; rolls everything back if posting fails or warns
    return {"proposal_id": p.id, "document": saved}


@router.post("/proposals/{proposal_id}/reject")
def reject(proposal_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role not in APPROVERS:
        raise HTTPException(403, "Only the owner or accountant can reject a suggestion")
    p = _get(db, user, proposal_id)
    p.status, p.decided_by = "rejected", user.id
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="proposal:reject", ref=p.id))
    db.commit()
    return {"proposal_id": p.id, "status": "rejected"}


# ---------- chat ----------


def chat_model_dep():
    return C.get_chat_model()


def build_tools(db: Session, user: User, project_id: str, extractor) -> dict[str, C.Tool]:
    """Everything the chat can do. Each tool runs the same code as the screens, as the asking user."""
    inr = C.inr

    def overview() -> C.Result:
        h = A.home(on=None, project_id=project_id, user=user, db=db)
        say = (f"Cash and bank stand at {inr(h['cash_and_bank'])}. Today {inr(h['money_in_today'])} came in and "
               f"{inr(h['money_out_today'])} went out.")
        if h["needs_attention"]:
            n = h["needs_attention"]
            say += f" {n} {'expense needs' if n == 1 else 'expenses need'} a category."
        return C.Result(say, [("Cash and bank", inr(h["cash_and_bank"])), ("Money in today", inr(h["money_in_today"])),
                              ("Money out today", inr(h["money_out_today"])), ("To receive", inr(h["to_receive"])),
                              ("To pay", inr(h["to_pay"]))])

    def profit(month: str | None = None) -> C.Result:
        month = month or A.today().strftime("%Y-%m")
        units = A.unit_pnl(month=month, project_id=project_id, user=user, db=db)["units"]
        income = sum((Decimal(u["income"]) for u in units), Decimal(0))
        costs = sum((Decimal(u["costs"]) for u in units), Decimal(0))
        net = income - costs
        word = "profit" if net >= 0 else "loss"
        say = (f"In {C.month_name(month)} income was {inr(income)} and costs were {inr(costs)}, "
               f"a {word} of {inr(abs(net))}.")
        facts = [(u["unit"], f"{inr(u['profit'])} (income {inr(u['income'])}, costs {inr(u['costs'])})")
                 for u in units if Decimal(u["income"]) or Decimal(u["costs"])]
        return C.Result(say, facts)

    def money_to_receive() -> C.Result:
        d = A.dues(on=None, project_id=project_id, user=user, db=db)
        if not d["payers"]:
            return C.Result("Nobody owes this project money right now.")
        late = Decimal(d["ageing"]["61-90"]) + Decimal(d["ageing"]["90+"])
        say = f"{inr(d['total'])} is still to be received from {len(d['payers'])} {'payer' if len(d['payers']) == 1 else 'payers'}."
        if late:
            say += f" {inr(late)} of it is more than 60 days old."
        facts = [(p["name"] or "Unknown", f"{inr(p['due'])} · {p['claims']} {'bill' if p['claims'] == 1 else 'bills'} · oldest {p['oldest_days']} days")
                 for p in d["payers"][:8]]
        return C.Result(say, facts)

    def bills_to_pay() -> C.Result:
        bills = A.open_items(kind="bill", project_id=project_id, on=None, user=user, db=db)
        if not bills:
            return C.Result("There are no unpaid bills.")
        total = sum((Decimal(b["due"]) for b in bills), Decimal(0))
        say = f"{inr(total)} is to be paid on {len(bills)} {'bill' if len(bills) == 1 else 'bills'}."
        return C.Result(say, [(b["party"] or "Unknown", f"{inr(b['due'])} · {b['age_days']} days old") for b in bills[:8]])

    def loans() -> C.Result:
        out = loans_api.list_loans(project_id=project_id, user=user, db=db)
        o = out["overview"]
        if not o["count"]:
            return C.Result("No loans are recorded for this project.")
        say = (f"{inr(o['outstanding'])} is still owed on {o['count']} {'loan' if o['count'] == 1 else 'loans'}, "
               f"with instalments of {inr(o['monthly_instalments'])} a month.")
        if o["next"]:
            say += f" Next is {inr(o['next']['amount'])} to {o['next']['lender']} on {C.nice_date(o['next']['date'])}."
        if o["overdue"]:
            say += f" {o['overdue']} {'instalment is' if o['overdue'] == 1 else 'instalments are'} overdue."
        facts = [(x["lender"], f"{inr(x['outstanding'])} owed · {inr(x['emi'])} a month · next {C.nice_date(x['next_due'])}")
                 for x in out["loans"] if x["next_due"]]
        return C.Result(say, facts)

    def accounts() -> C.Result:
        try:
            out = money_api.list_accounts(project_id=project_id, user=user, db=db)
        except Exception:
            return C.Result("Account balances are only shown to people who can see the whole project.")
        rows = out["accounts"]
        say = f"Across {len(rows)} {'account' if len(rows) == 1 else 'accounts'} you have {inr(out['total'])}."
        return C.Result(say, [(a["name"], inr(a["balance"])) for a in rows])

    def advances() -> C.Result:
        held = A.open_items(kind="advance", project_id=project_id, on=None, user=user, db=db)
        if not held:
            return C.Result("No patient advances are held right now.")
        total = sum((Decimal(a["due"]) for a in held), Decimal(0))
        say = (f"{inr(total)} of patient advances is held for {len(held)} {'patient' if len(held) == 1 else 'patients'}. "
               "It is the patients' money until their bills are settled.")
        return C.Result(say, [(a["reference"] or "No number", f"{inr(a['due'])} · {a['unit']} · {a['age_days']} days") for a in held[:8]])

    def entries(kind: str | None = None, month: str | None = None) -> C.Result:
        group = kind if kind in ("in", "out", "dues") else None
        docs = A.list_documents(status=None, type=None, group=group, unit_id=None, project_id=project_id, month=month,
                                limit=8, offset=0, user=user, db=db)
        docs = [d for d in docs if d["status"] != "reversed"]
        if not docs:
            return C.Result("There are no entries" + (f" in {C.month_name(month)}." if month else " yet."))
        label = {"collection": "Collection", "investment": "Investment", "claim": "Bill to", "claim_settlement": "Received from",
                 "vendor_payment": "Paid", "loan_received": "Loan from", "loan_payment": "Loan instalment to",
                 "transfer": "Transfer", "opening_balance": "Opening balance", "advance_received": "Advance",
                 "advance_adjusted": "Advance used for bill", "advance_refund": "Advance refunded"}
        facts = []
        for d in docs:
            name = (label.get(d["type"], "") + " " + (d["party"] or "")).strip() if d["type"] != "expense" else (d["party"] or "Expense")
            facts.append((f"{C.nice_date(d['date'])} · {name}", f"{inr(d['amount'])} · {d['unit']}"))
        which = {"in": "money-in ", "out": "money-out ", "dues": "dues "}.get(group or "", "")
        return C.Result(f"Here are the latest {len(docs)} {which}entries.", facts)

    def record(text: str | None = None) -> C.Result:
        if user.role not in ("owner", "accountant", "unit_incharge", "cashier"):
            return C.Result("Your login is read-only, so I cannot record entries for you.")
        out = run_bookkeeper(RunIn(project_id=project_id, source="text", content=text or ""), user=user, db=db, extractor=extractor)
        n = len(out["proposals"])
        check = sum(1 for p in out["proposals"] if p["flags"] or p["confidence"] < 0.8)
        say = f"I prepared {n} {'entry' if n == 1 else 'entries'} from that"
        say += f"; {check} {'needs' if check == 1 else 'need'} a look." if check else "."
        say += " Nothing is saved until it is approved."
        return C.Result(say, proposals=out["proposals"])

    T = C.Tool
    tools = [
        T("overview", "Cash and bank balance now, money in and out today, totals to receive and to pay.", overview),
        T("profit", "Income, costs and profit by unit for one month.", profit, {"month": "Month as YYYY-MM; leave empty for the current month"}),
        T("money_to_receive", "Who owes the project money (insurers, schemes, companies), how much and how old.", money_to_receive),
        T("bills_to_pay", "Unpaid vendor bills.", bills_to_pay),
        T("accounts", "Balance of each cash box and bank account, and their total.", accounts),
        T("advances", "Patient advances (deposits) still held, by patient or IP number.", advances),
        T("loans", "Loans taken: amount still owed, monthly instalments, next due date, overdue instalments.", loans),
        T("entries", "The latest entries.", entries, {"kind": "in, out or dues; empty for all", "month": "Month as YYYY-MM; empty for all"}),
        T("record", "Prepare entries from the user's own words about money paid or received. Pass their words unchanged.", record,
          {"text": "The user's words, one entry per line"}),
    ]
    tools += X.write_tools(db, user, project_id)
    return {t.name: t for t in tools}


_ORDINALS = {"1": 0, "first": 0, "one": 0, "pehla": 0, "2": 1, "second": 1, "two": 1, "doosra": 1, "3": 2, "third": 2, "three": 2,
             "4": 3, "fourth": 3, "5": 4, "fifth": 4, "6": 5, "sixth": 5}
_FILLER = {"the", "one", "wala", "wali", "that", "this", "bill", "loan", "entry", "expense", "please", "it", "is", "by", "of", "for", "to", "from"}
_DROP = re.compile(r"^\s*(no|nahi|cancel|never ?mind|leave it|stop|forget it|skip)\b[\s.!]*$", re.I)


def resolve_pending(pending: dict, message: str) -> dict | None:
    """The person's answer to a question the assistant asked. Returns the completed arguments, or None
    when the message does not answer it (then it is treated as a fresh message)."""
    args = dict(pending.get("args") or {})
    options = pending.get("options") or []
    text = message.strip()
    low = text.lower()
    if options:
        chosen = next((o for o in options if o["label"].lower() == low), None)
        if not chosen:
            mode = find_mode(text)
            chosen = next((o for o in options if mode and o["args"].get("mode") == mode), None)
        if not chosen:
            words = re.findall(r"[a-z0-9-]+", low.replace(",", ""))
            core = [w for w in words if w not in _FILLER]
            if core and all(w in _ORDINALS for w in core):            # "the second one", "2"
                index = _ORDINALS[core[0]]
            elif not core and words and words[-1] in _ORDINALS:       # just "one"
                index = _ORDINALS[words[-1]]
            else:
                index = None
            if index is not None:
                chosen = options[index] if index < len(options) else None
            else:                                                     # "the sunrise one", "H-2301"
                said = {w for w in core if len(w) >= 3 or any(ch.isdigit() for ch in w)}
                hits = [o for o in options if said and said <= set(re.findall(r"[a-z0-9-]+", o["label"].lower().replace(",", "")))]
                chosen = hits[0] if len(hits) == 1 else None
        return {**args, **chosen["args"]} if chosen else None
    missing = pending.get("missing")
    if missing in ("amount", "emi"):
        found = C.amounts_in(text)
        return {**args, missing: str(found[0][1])} if found else None
    if missing == "rate":
        found = re.search(r"\d{1,2}(?:\.\d{1,2})?", text)
        return {**args, "rate": found.group()} if found else None
    if missing == "lender":
        return {**args, "lender": text[:200]} if 2 <= len(text) <= 80 and "?" not in text else None
    return None


class ChatTurn(BaseModel):
    who: Literal["you", "assistant"]
    text: str = Field(max_length=4000)


class ChatIn(BaseModel):
    project_id: str
    message: str = Field(min_length=1, max_length=4000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)
    pending: dict | None = None  # the question the assistant asked last, sent back with the answer


def chat_out(reply: str, results: list, answered_by: str) -> dict:
    action = next((r.action for r in results if r.action), None)
    ask = next((r.ask for r in results if r.ask), None)
    return {
        "reply": reply,
        "facts": [{"label": k, "value": v} for r in results for k, v in r.facts],
        "proposals": [p for r in results for p in r.proposals],
        "action": action,
        "pending": ask,
        "choices": [o["label"] for o in (ask or {}).get("options", [])],
        "answered_by": answered_by,
    }


@router.post("/chat")
def chat(body: ChatIn, user: User = Depends(current_user), db: Session = Depends(get_db),
         extractor=Depends(extractor_dep), model=Depends(chat_model_dep)):
    project_units(db, user, body.project_id)  # 404 unless this user can see the project
    tools = build_tools(db, user, body.project_id, extractor)
    message = body.message.strip()

    # an answer to a question the assistant just asked is handled by plain code, with or without a model
    if body.pending and body.pending.get("tool") in tools:
        if _DROP.match(message):
            return chat_out("All right, I have dropped that.", [], "rules")
        args = resolve_pending(body.pending, message)
        if args is not None:
            tool = tools[body.pending["tool"]]
            result = tool.run(**{k: v for k, v in args.items() if k in tool.params or k.endswith("_id")})
            return chat_out(result.say, [result], "rules")

    result = C.build_chat(model).invoke({
        "message": message,
        "history": [t.model_dump() for t in body.history],
        "today": today(),
        "tools": tools,
        "known": X.known_names(db, user, body.project_id),
    })
    return chat_out(result["reply"], result.get("results", []), result.get("answered_by", "rules"))


@router.post("/actions/{action_id}/{decision}")
def decide_action(action_id: str, decision: Literal["confirm", "cancel"], user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    """The person's yes or no to a change the assistant prepared. Only a yes changes the books."""
    return X.decide(db, user, action_id, decision == "confirm")
