from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from . import posting
from .checks import cash_warnings
from .db import get_db
from .models import (
    Account,
    AuditLog,
    Category,
    Document,
    JournalEntry,
    JournalLine,
    Loan,
    MoneyAccount,
    Party,
    Period,
    Project,
    Unit,
    User,
)
from .seed import add_project
from .security import allowed_unit_ids, clean_phone, current_user, make_token, require_unit, require_write, verify_pin

router = APIRouter()
IST = ZoneInfo("Asia/Kolkata")
ZERO = Decimal("0.00")
Amount = Field(gt=0, max_digits=14, decimal_places=2)
Mode = Literal["cash", "upi", "card", "bank"]


def today() -> date:
    return datetime.now(IST).date()


# ---------- auth ----------


class LoginIn(BaseModel):
    phone: str = Field(min_length=8, max_length=20)
    pin: str = Field(min_length=4, max_length=12)


@router.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.phone == clean_phone(body.phone), User.active))
    now = datetime.now(timezone.utc)
    bad = HTTPException(401, "Wrong phone number or PIN")
    if not user:
        raise bad
    locked = user.locked_until
    if locked and locked.replace(tzinfo=locked.tzinfo or timezone.utc) > now:
        raise HTTPException(429, "Too many wrong attempts. Try again in 15 minutes.")
    if not verify_pin(body.pin, user.pin_hash):
        user.failed_logins += 1
        if user.failed_logins >= 5:
            user.locked_until = now + timedelta(minutes=15)
            user.failed_logins = 0
        db.commit()
        raise bad
    user.failed_logins = 0
    user.locked_until = None
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="login"))
    db.commit()
    return {"token": make_token(user), "name": user.name, "role": user.role}


@router.get("/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    unit_ids = allowed_unit_ids(db, user)
    units = db.scalars(select(Unit).where(Unit.id.in_(unit_ids)).order_by(Unit.name)).all()
    projects = db.scalars(
        select(Project).where(Project.id.in_({u.project_id for u in units})).order_by(Project.name)
    ).all()
    cats = db.scalars(select(Category).where(Category.tenant_id == user.tenant_id).order_by(Category.name)).all()
    return {
        "name": user.name,
        "role": user.role,
        "projects": [
            {
                "id": p.id,
                "name": p.name,
                "units": [{"id": u.id, "name": u.name, "kind": u.kind} for u in units if u.project_id == p.id],
            }
            for p in projects
        ],
        "categories": [{"id": c.id, "name": c.name} for c in cats],
    }


# ---------- projects ----------


class ProjectIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    units: list[Literal["hospital", "diagnostics", "path_lab", "pharmacy"]] = []


@router.post("/projects", status_code=201)
def create_project(body: ProjectIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role != "owner":
        raise HTTPException(403, "Only the owner can create a project")
    name = body.name.strip()
    clash = db.scalar(
        select(Project).where(Project.tenant_id == user.tenant_id, func.lower(Project.name) == name.lower())
    )
    if clash:
        raise HTTPException(409, "You already have a project with this name")
    project = add_project(db, user.tenant_id, name, body.units)
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="project:create", ref=project.id))
    db.commit()
    units = db.scalars(select(Unit).where(Unit.project_id == project.id).order_by(Unit.name)).all()
    return {"id": project.id, "name": project.name,
            "units": [{"id": u.id, "name": u.name, "kind": u.kind} for u in units]}


def project_units(db: Session, user: User, project_id: str | None) -> list[str]:
    """Units the user may see, narrowed to one project when asked."""
    units = allowed_unit_ids(db, user)
    if not project_id:
        return units
    inside = list(db.scalars(select(Unit.id).where(Unit.project_id == project_id, Unit.id.in_(units))))
    if not inside:
        raise HTTPException(404, "Project not found")
    return inside


# ---------- helpers ----------


def find_party(db: Session, tenant_id: str, name: str | None, kind: str) -> str | None:
    if not name or not name.strip():
        return None
    name = name.strip()
    party = db.scalar(
        select(Party).where(Party.tenant_id == tenant_id, Party.kind == kind, func.lower(Party.name) == name.lower())
    )
    if not party:
        party = Party(tenant_id=tenant_id, name=name, kind=kind)
        db.add(party)
        db.flush()
    return party.id


def check_date(when: date, not_before: date | None = None) -> None:
    if when > today():
        raise HTTPException(422, "The date cannot be in the future")
    if not_before and when < not_before:
        raise HTTPException(422, f"The date cannot be before {not_before.strftime('%d %b %Y')}, the date of the bill")


def get_doc(db: Session, user: User, doc_id: str, lock: bool = False) -> Document:
    # lock=True holds the row until the request finishes, so two payments recorded at the same
    # moment cannot both pass the "how much is still due" check (PostgreSQL; SQLite ignores it)
    doc = db.get(Document, doc_id, with_for_update=lock)
    if not doc or doc.tenant_id != user.tenant_id or doc.unit_id not in allowed_unit_ids(db, user):
        raise HTTPException(404, "Entry not found")
    return doc


def save(db: Session, doc: Document, user: User, confirmed: bool = False) -> dict:
    """Post a document to the ledger. Unless the person has already seen and accepted them,
    cash-limit warnings stop the save and are sent back for a second look."""
    for account_id in filter(None, (doc.money_account_id, doc.to_money_account_id)):
        acc = db.get(MoneyAccount, account_id)
        project_id = db.scalar(select(Unit.project_id).where(Unit.id == doc.unit_id))
        if not acc or acc.tenant_id != doc.tenant_id or acc.project_id != project_id or not acc.active:
            raise HTTPException(422, "That cash or bank account is not part of this project")
        if doc.type not in ("transfer", "opening_balance") and doc.payment_mode and (acc.kind == "cash") != (doc.payment_mode == "cash"):
            raise HTTPException(422, f"{acc.name} is a {acc.kind} account; it cannot take a {doc.payment_mode} payment")
    if not confirmed:
        warnings = cash_warnings(db, doc)
        if warnings:
            db.rollback()
            raise HTTPException(409, {"code": "confirm", "warnings": warnings})
    db.add(doc)
    db.flush()
    try:
        posting.post(db, doc, user)
    except posting.PostingError as e:
        db.rollback()
        raise HTTPException(409, str(e))
    db.commit()
    return doc_out(doc)


def doc_out(d: Document) -> dict:
    return {
        "id": d.id,
        "type": d.type,
        "status": d.status,
        "date": d.doc_date.isoformat(),
        "unit_id": d.unit_id,
        "amount": str(d.amount),
        "deduction": str(d.deduction),
        "interest": str(d.interest),
        "payment_mode": d.payment_mode,
        "paid": d.paid,
        "category_id": d.category_id,
        "party_id": d.party_id,
        "reference": d.reference,
        "note": d.note,
    }


def settled_total(db: Session, parent: Document) -> Decimal:
    """How much of a claim or unpaid bill has been cleared by later documents."""
    total = db.scalar(
        select(func.coalesce(func.sum(Document.amount + Document.deduction), 0)).where(
            Document.parent_id == parent.id, Document.status == "posted"
        )
    )
    return Decimal(str(total)).quantize(Decimal("0.01"))


# ---------- documents ----------


class CollectionIn(BaseModel):
    unit_id: str
    date: date
    amount: Decimal = Amount
    payment_mode: Mode
    reference: str | None = Field(None, max_length=100)
    note: str | None = Field(None, max_length=1000)
    confirmed: bool = False  # the person has seen the cash-limit warnings and wants to save anyway
    money_account_id: str | None = None  # which cash box or bank account; empty for the project's default


@router.post("/documents/collection", status_code=201)
def create_collection(body: CollectionIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_write(user)
    check_date(body.date)
    require_unit(db, user, body.unit_id)
    doc = Document(
        tenant_id=user.tenant_id, unit_id=body.unit_id, type="collection", doc_date=body.date,
        amount=body.amount, payment_mode=body.payment_mode, reference=body.reference, note=body.note,
        created_by=user.id,
    )
    doc.money_account_id = body.money_account_id
    return save(db, doc, user, body.confirmed)


class ExpenseIn(BaseModel):
    unit_id: str
    date: date
    amount: Decimal = Amount
    category_id: str | None = None  # empty = "save now, sort later"
    paid_to: str | None = Field(None, max_length=200)
    paid: bool = True
    payment_mode: Mode | None = None
    note: str | None = Field(None, max_length=1000)
    attachment_key: str | None = Field(None, max_length=500)
    confirmed: bool = False  # the person has seen the cash-limit warnings and wants to save anyway
    money_account_id: str | None = None  # which cash box or bank account; empty for the project's default


@router.post("/documents/expense", status_code=201)
def create_expense(body: ExpenseIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_write(user)
    check_date(body.date)
    require_unit(db, user, body.unit_id)
    if body.category_id:
        cat = db.get(Category, body.category_id)
        if not cat or cat.tenant_id != user.tenant_id:
            raise HTTPException(422, "Unknown category")
    if body.paid and not body.payment_mode:
        raise HTTPException(422, "Choose how it was paid")
    if not body.paid and not (body.paid_to or "").strip():
        raise HTTPException(422, "Say who is to be paid")
    doc = Document(
        tenant_id=user.tenant_id, unit_id=body.unit_id, type="expense", doc_date=body.date,
        amount=body.amount, category_id=body.category_id,
        party_id=find_party(db, user.tenant_id, body.paid_to, "vendor"),
        paid=body.paid, payment_mode=body.payment_mode if body.paid else None,
        note=body.note, attachment_key=body.attachment_key, created_by=user.id,
        status="posted" if body.category_id else "needs_attention",
    )
    doc.money_account_id = body.money_account_id
    return save(db, doc, user, body.confirmed)


class CategorizeIn(BaseModel):
    category_id: str


@router.post("/documents/{doc_id}/categorize")
def categorize(doc_id: str, body: CategorizeIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_write(user)
    doc = get_doc(db, user, doc_id)
    cat = db.get(Category, body.category_id)
    if doc.type != "expense" or doc.status == "reversed":
        raise HTTPException(409, "Only a live expense can be sorted")
    if not cat or cat.tenant_id != user.tenant_id:
        raise HTTPException(422, "Unknown category")
    try:
        posting.reverse(db, doc, user, "re-categorised")
        doc.category_id = cat.id
        doc.status = "posted"
        posting.post(db, doc, user)
    except posting.PostingError as e:
        db.rollback()
        raise HTTPException(409, str(e))
    db.commit()
    return doc_out(doc)


class ReverseIn(BaseModel):
    reason: str = Field(min_length=3, max_length=250)


@router.post("/documents/{doc_id}/reverse")
def reverse_document(doc_id: str, body: ReverseIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role not in ("owner", "accountant"):
        raise HTTPException(403, "Only the owner or accountant can cancel an entry")
    doc = get_doc(db, user, doc_id)
    if doc.status == "reversed":
        raise HTTPException(409, "Already cancelled")
    live_children = db.scalar(
        select(func.count()).select_from(Document).where(Document.parent_id == doc.id, Document.status == "posted")
    )
    if live_children:
        raise HTTPException(409, "Cancel the payments recorded against this entry first")
    if doc.type == "loan_received":
        paid = db.scalar(select(func.count()).select_from(Document).where(
            Document.loan_id == doc.loan_id, Document.type == "loan_payment", Document.status == "posted"))
        if paid:
            raise HTTPException(409, "Cancel the instalments paid on this loan first")
        loan = db.get(Loan, doc.loan_id)
        if loan:
            loan.status = "cancelled"
    try:
        posting.reverse(db, doc, user, body.reason)
    except posting.PostingError as e:
        db.rollback()
        raise HTTPException(409, str(e))
    doc.status = "reversed"
    db.commit()
    return doc_out(doc)


class ClaimIn(BaseModel):
    unit_id: str
    date: date
    amount: Decimal = Amount
    payer: str = Field(min_length=2, max_length=200)
    reference: str | None = Field(None, max_length=100)  # bill or claim number


@router.post("/documents/claim", status_code=201)
def create_claim(body: ClaimIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_write(user)
    check_date(body.date)
    require_unit(db, user, body.unit_id)
    doc = Document(
        tenant_id=user.tenant_id, unit_id=body.unit_id, type="claim", doc_date=body.date,
        amount=body.amount, party_id=find_party(db, user.tenant_id, body.payer, "payer"),
        paid=False, reference=body.reference, created_by=user.id,
    )
    return save(db, doc, user)


class SettleIn(BaseModel):
    date: date
    received: Decimal = Amount
    deduction: Decimal = Field(Decimal("0"), ge=0, max_digits=14, decimal_places=2)
    payment_mode: Mode = "bank"
    confirmed: bool = False  # the person has seen the cash-limit warnings and wants to save anyway
    money_account_id: str | None = None  # which cash box or bank account; empty for the project's default


@router.post("/documents/{doc_id}/settle", status_code=201)
def settle_claim(doc_id: str, body: SettleIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_write(user)
    claim = get_doc(db, user, doc_id, lock=True)
    if claim.type != "claim" or claim.status != "posted":
        raise HTTPException(409, "Not an open claim")
    check_date(body.date, not_before=claim.doc_date)
    outstanding = claim.amount - settled_total(db, claim)
    if body.received + body.deduction > outstanding:
        raise HTTPException(409, f"Only {outstanding} is still due on this claim")
    doc = Document(
        tenant_id=user.tenant_id, unit_id=claim.unit_id, type="claim_settlement", doc_date=body.date,
        amount=body.received, deduction=body.deduction, payment_mode=body.payment_mode,
        party_id=claim.party_id, parent_id=claim.id, reference=claim.reference, created_by=user.id,
    )
    doc.money_account_id = body.money_account_id
    return save(db, doc, user, body.confirmed)


class PayIn(BaseModel):
    date: date
    amount: Decimal = Amount
    payment_mode: Mode
    confirmed: bool = False  # the person has seen the cash-limit warnings and wants to save anyway
    money_account_id: str | None = None  # which cash box or bank account; empty for the project's default


@router.post("/documents/{doc_id}/pay", status_code=201)
def pay_bill(doc_id: str, body: PayIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_write(user)
    bill = get_doc(db, user, doc_id, lock=True)
    if bill.type != "expense" or bill.paid or bill.status == "reversed":
        raise HTTPException(409, "Not an unpaid bill")
    check_date(body.date, not_before=bill.doc_date)
    outstanding = bill.amount - settled_total(db, bill)
    if body.amount > outstanding:
        raise HTTPException(409, f"Only {outstanding} is still due on this bill")
    doc = Document(
        tenant_id=user.tenant_id, unit_id=bill.unit_id, type="vendor_payment", doc_date=body.date,
        amount=body.amount, payment_mode=body.payment_mode, party_id=bill.party_id, parent_id=bill.id,
        created_by=user.id,
    )
    doc.money_account_id = body.money_account_id
    return save(db, doc, user, body.confirmed)


class InvestmentIn(BaseModel):
    project_id: str
    date: date
    amount: Decimal = Amount
    payment_mode: Mode = "bank"
    note: str | None = Field(None, max_length=1000)
    confirmed: bool = False  # the person has seen the cash-limit warnings and wants to save anyway
    money_account_id: str | None = None  # which cash box or bank account; empty for the project's default


@router.post("/documents/investment", status_code=201)
def create_investment(body: InvestmentIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role not in ("owner", "accountant"):
        raise HTTPException(403, "Only the owner or accountant can record an investment")
    general = db.scalar(
        select(Unit).where(Unit.project_id == body.project_id, Unit.tenant_id == user.tenant_id, Unit.kind == "general")
    )
    if not general:
        raise HTTPException(404, "Project not found")
    check_date(body.date)
    doc = Document(
        tenant_id=user.tenant_id, unit_id=general.id, type="investment", doc_date=body.date,
        amount=body.amount, payment_mode=body.payment_mode, note=body.note, created_by=user.id,
    )
    doc.money_account_id = body.money_account_id
    return save(db, doc, user, body.confirmed)


def _names(db: Session, docs: list[Document]) -> tuple[dict, dict]:
    party_ids = {d.party_id for d in docs if d.party_id}
    unit_ids = {d.unit_id for d in docs}
    parties = dict(db.execute(select(Party.id, Party.name).where(Party.id.in_(party_ids))).all()) if party_ids else {}
    units = dict(db.execute(select(Unit.id, Unit.name).where(Unit.id.in_(unit_ids))).all()) if unit_ids else {}
    return parties, units


GROUPS = {
    # how the Entries screen groups document types
    "in": lambda: or_(Document.type.in_(("collection", "investment", "claim_settlement", "advance_received")),
                      and_(Document.type == "loan_received", Document.payment_mode.is_not(None))),
    "out": lambda: or_(Document.type.in_(("vendor_payment", "loan_payment", "advance_refund")), and_(Document.type == "expense", Document.paid.is_(True))),
    "dues": lambda: or_(Document.type == "claim", and_(Document.type == "expense", Document.paid.is_(False))),
}


@router.get("/documents")
def list_documents(
    status: str | None = None,
    type: str | None = None,
    group: Literal["in", "out", "dues"] | None = None,
    unit_id: str | None = None,
    project_id: str | None = None,
    month: str | None = None,
    limit: int = 50,
    offset: int = 0,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    units = project_units(db, user, project_id)
    q = select(Document).where(Document.tenant_id == user.tenant_id, Document.unit_id.in_(units))
    if status:
        q = q.where(Document.status == status)
    if type:
        q = q.where(Document.type == type)
    if group:
        q = q.where(GROUPS[group]())
    if unit_id:
        q = q.where(Document.unit_id == unit_id)
    if month:
        start, end = _month_range(month)
        q = q.where(Document.doc_date >= start, Document.doc_date < end)
    q = q.order_by(Document.doc_date.desc(), Document.created_at.desc(), Document.id)
    docs = list(db.scalars(q.limit(min(max(limit, 1), 200)).offset(max(offset, 0))))
    parties, unit_names = _names(db, docs)
    cats = dict(db.execute(select(Category.id, Category.name).where(Category.tenant_id == user.tenant_id)).all())
    return [
        {**doc_out(d), "party": parties.get(d.party_id), "unit": unit_names[d.unit_id], "category": cats.get(d.category_id)}
        for d in docs
    ]


@router.get("/documents/{doc_id}")
def document_detail(doc_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """One entry with everything behind it: who recorded it, how it went into the books, payments against it."""
    d = get_doc(db, user, doc_id)
    parties, unit_names = _names(db, [d])
    cat = db.get(Category, d.category_id) if d.category_id else None
    author = db.get(User, d.created_by)
    rows = db.execute(
        select(Account.code, Account.name, JournalLine.debit, JournalLine.credit, JournalEntry.reverses_id)
        .join(Account, Account.id == JournalLine.account_id)
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .where(JournalEntry.document_id == d.id)
        .order_by(JournalEntry.created_at, JournalLine.credit, Account.code)
    ).all()
    children = list(db.scalars(select(Document).where(Document.parent_id == d.id).order_by(Document.doc_date)))
    month = d.doc_date.strftime("%Y-%m")
    project_id = db.scalar(select(Unit.project_id).where(Unit.id == d.unit_id))
    period = db.get(Period, (user.tenant_id, project_id, month))
    return {
        **doc_out(d),
        "party": parties.get(d.party_id),
        "unit": unit_names[d.unit_id],
        "category": cat.name if cat else None,
        "recorded_by": author.name if author else None,
        "recorded_at": d.created_at.isoformat(),
        "month_locked": bool(period and period.locked),
        "books": [
            {"account": f"{code} {name}", "debit": str(debit), "credit": str(credit), "reversal": rev is not None}
            for code, name, debit, credit, rev in rows
        ],
        "payments": [
            {"id": c.id, "type": c.type, "date": c.doc_date.isoformat(), "amount": str(c.amount),
             "deduction": str(c.deduction), "status": c.status}
            for c in children
        ],
    }


@router.get("/reports/open-items")
def open_items(kind: Literal["claim", "bill", "advance"], project_id: str | None = None, on: date | None = None,
               user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Claims still to be received, or vendor bills still to be paid, oldest first."""
    on = on or today()
    units = project_units(db, user, project_id)
    q = select(Document).where(Document.tenant_id == user.tenant_id, Document.unit_id.in_(units))
    if kind == "claim":
        q = q.where(Document.type == "claim", Document.status == "posted")
    elif kind == "advance":
        q = q.where(Document.type == "advance_received", Document.status == "posted")
    else:
        q = q.where(Document.type == "expense", Document.paid.is_(False), Document.status != "reversed")
    docs = list(db.scalars(q))
    parties, unit_names = _names(db, docs)
    out = []
    for d in docs:
        due = d.amount - settled_total(db, d)
        if due <= ZERO:
            continue
        out.append({
            "id": d.id, "party": parties.get(d.party_id), "reference": d.reference, "date": d.doc_date.isoformat(),
            "unit": unit_names[d.unit_id], "amount": str(d.amount), "due": str(due),
            "age_days": (on - d.doc_date).days,
        })
    return sorted(out, key=lambda r: -r["age_days"])


# ---------- reports ----------


def _sum(db: Session, user: User, units: list[str], codes: list[str], col, *conds) -> Decimal:
    q = (
        select(func.coalesce(func.sum(col), 0))
        .join(Account, Account.id == JournalLine.account_id)
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .where(JournalLine.tenant_id == user.tenant_id, JournalLine.unit_id.in_(units), Account.code.in_(codes), *conds)
    )
    return Decimal(str(db.scalar(q))).quantize(Decimal("0.01"))


def _balance(db: Session, user: User, units: list[str], codes: list[str], upto: date) -> Decimal:
    return _sum(db, user, units, codes, JournalLine.debit - JournalLine.credit, JournalEntry.entry_date <= upto)


def money_codes(db: Session, tenant_id: str) -> list[str]:
    """Ledger codes of every cash box and bank account of the tenant (the two defaults always included)."""
    extra = db.scalars(select(Account.code).join(MoneyAccount, MoneyAccount.account_id == Account.id)
                       .where(MoneyAccount.tenant_id == tenant_id))
    return sorted({posting.CASH, posting.BANK, *extra})


NOT_MONEY_IN_OR_OUT = ("transfer", "opening_balance")  # money moving between own accounts, or already there


def _day_flow(db: Session, user: User, units: list[str], codes: list[str], on: date, side: str) -> Decimal:
    """Money in (debit) or out (credit) on one day. A reversal cancels its original instead of
    showing up as a movement in the opposite direction."""
    col, other = (JournalLine.debit, JournalLine.credit) if side == "debit" else (JournalLine.credit, JournalLine.debit)
    same_day = JournalEntry.entry_date == on
    real = JournalEntry.document_id.not_in(select(Document.id).where(Document.type.in_(NOT_MONEY_IN_OR_OUT)))
    gross = _sum(db, user, units, codes, col, same_day, real, JournalEntry.reverses_id.is_(None))
    undone = _sum(db, user, units, codes, other, same_day, real, JournalEntry.reverses_id.is_not(None))
    return gross - undone


def _unit_pnl(db: Session, user: User, units: list[str], start: date, end: date) -> list[dict]:
    rows = db.execute(
        select(
            JournalLine.unit_id,
            Account.type,
            func.coalesce(func.sum(JournalLine.credit - JournalLine.debit), 0),
        )
        .join(Account, Account.id == JournalLine.account_id)
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .where(
            JournalLine.tenant_id == user.tenant_id,
            JournalLine.unit_id.in_(units),
            Account.type.in_(("income", "expense")),
            JournalEntry.entry_date >= start,
            JournalEntry.entry_date < end,
        )
        .group_by(JournalLine.unit_id, Account.type)
    ).all()
    names = dict(db.execute(select(Unit.id, Unit.name).where(Unit.id.in_(units))).all())
    out = {u: {"unit_id": u, "unit": names[u], "income": ZERO, "costs": ZERO} for u in units}
    for unit_id, type_, net in rows:
        net = Decimal(str(net)).quantize(Decimal("0.01"))
        if type_ == "income":
            out[unit_id]["income"] = net
        else:
            out[unit_id]["costs"] = -net
    result = []
    for r in sorted(out.values(), key=lambda r: r["unit"]):
        result.append({**r, "income": str(r["income"]), "costs": str(r["costs"]), "profit": str(r["income"] - r["costs"])})
    return result


def _month_range(month: str) -> tuple[date, date]:
    try:
        start = datetime.strptime(month, "%Y-%m").date()
    except ValueError:
        raise HTTPException(422, "Month must look like 2026-11")
    end = date(start.year + (start.month == 12), start.month % 12 + 1, 1)
    return start, end


def loans_overview(db: Session, user: User, unit_ids: list[str], on: date) -> dict:
    from . import loans as L  # local import: loans has no dependency on this module

    project_ids = list(db.scalars(select(Unit.project_id).where(Unit.id.in_(unit_ids)).distinct()))
    general_ok = set(db.scalars(select(Unit.project_id).where(Unit.id.in_(unit_ids), Unit.kind == "general")))
    return L.overview(L.project_loans(db, user.tenant_id, [p for p in project_ids if p in general_ok], on))


@router.get("/reports/home")
def home(on: date | None = None, project_id: str | None = None, user: User = Depends(current_user),
         db: Session = Depends(get_db)):
    on = on or today()
    units = project_units(db, user, project_id)
    money = money_codes(db, user.tenant_id)
    start, end = _month_range(on.strftime("%Y-%m"))
    waiting = db.scalar(
        select(func.count()).select_from(Document).where(
            Document.tenant_id == user.tenant_id, Document.unit_id.in_(units), Document.status == "needs_attention"
        )
    )
    return {
        "date": on.isoformat(),
        "cash_and_bank": str(_balance(db, user, units, money, on)),
        "money_in_today": str(_day_flow(db, user, units, money, on, "debit")),
        "money_out_today": str(_day_flow(db, user, units, money, on, "credit")),
        "to_receive": str(_balance(db, user, units, [posting.RECEIVABLE], on)),
        "to_pay": str(-_balance(db, user, units, [posting.PAYABLE], on)),
        "needs_attention": waiting,
        "loans": loans_overview(db, user, units, on),
        "advances_held": str(-_balance(db, user, units, [posting.ADVANCES], on)),
        "units_this_month": _unit_pnl(db, user, units, start, end),
    }


@router.get("/reports/unit-pnl")
def unit_pnl(month: str, project_id: str | None = None, user: User = Depends(current_user),
             db: Session = Depends(get_db)):
    start, end = _month_range(month)
    return {"month": month, "units": _unit_pnl(db, user, project_units(db, user, project_id), start, end)}


@router.get("/reports/projects")
def projects_dashboard(on: date | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """One row per project, plus totals across all of them."""
    on = on or today()
    start, end = _month_range(on.strftime("%Y-%m"))
    units = db.scalars(select(Unit).where(Unit.id.in_(allowed_unit_ids(db, user)))).all()
    projects = db.scalars(
        select(Project).where(Project.id.in_({u.project_id for u in units})).order_by(Project.name)
    ).all()
    money = money_codes(db, user.tenant_id)
    keys = ("cash_and_bank", "invested", "income_this_month", "costs_this_month", "profit_this_month",
            "to_receive", "to_pay")
    totals = {k: ZERO for k in keys}
    rows = []
    for p in projects:
        ids = [u.id for u in units if u.project_id == p.id]
        pnl = _unit_pnl(db, user, ids, start, end)
        income = sum((Decimal(r["income"]) for r in pnl), ZERO)
        costs = sum((Decimal(r["costs"]) for r in pnl), ZERO)
        row = {
            "cash_and_bank": _balance(db, user, ids, money, on),
            "invested": -_balance(db, user, ids, [posting.CAPITAL], on),
            "income_this_month": income,
            "costs_this_month": costs,
            "profit_this_month": income - costs,
            "to_receive": _balance(db, user, ids, [posting.RECEIVABLE], on),
            "to_pay": -_balance(db, user, ids, [posting.PAYABLE], on),
        }
        for k in keys:
            totals[k] += row[k]
        rows.append({"id": p.id, "name": p.name, **{k: str(v) for k, v in row.items()}})
    return {"date": on.isoformat(), "projects": rows, "totals": {k: str(v) for k, v in totals.items()}}


@router.get("/reports/dues")
def dues(on: date | None = None, project_id: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Open claims grouped by payer with ageing buckets."""
    on = on or today()
    units = project_units(db, user, project_id)
    claims = db.scalars(
        select(Document).where(
            Document.tenant_id == user.tenant_id, Document.unit_id.in_(units),
            Document.type == "claim", Document.status == "posted",
        )
    ).all()
    buckets = ("0-30", "31-60", "61-90", "90+")
    payers: dict[str, dict] = {}
    totals = {b: ZERO for b in buckets}
    for c in claims:
        due = c.amount - settled_total(db, c)
        if due <= ZERO:
            continue
        age = (on - c.doc_date).days
        b = buckets[0] if age <= 30 else buckets[1] if age <= 60 else buckets[2] if age <= 90 else buckets[3]
        p = payers.setdefault(c.party_id, {"party_id": c.party_id, "claims": 0, "due": ZERO, "oldest_days": 0})
        p["claims"] += 1
        p["due"] += due
        p["oldest_days"] = max(p["oldest_days"], age)
        totals[b] += due
    names = dict(db.execute(select(Party.id, Party.name).where(Party.id.in_(payers.keys()))).all()) if payers else {}
    rows = sorted(payers.values(), key=lambda p: -p["oldest_days"])
    return {
        "total": str(sum(totals.values(), ZERO)),
        "ageing": {b: str(v) for b, v in totals.items()},
        "payers": [{**p, "name": names.get(p["party_id"]), "due": str(p["due"])} for p in rows],
    }


# ---------- month close ----------


def _own_project(db: Session, user: User, project_id: str) -> None:
    project = db.get(Project, project_id)
    if not project or project.tenant_id != user.tenant_id:
        raise HTTPException(404, "Project not found")


@router.get("/periods")
def list_periods(project_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    project_units(db, user, project_id)
    rows = db.scalars(select(Period).where(
        Period.tenant_id == user.tenant_id, Period.project_id == project_id, Period.locked.is_(True)))
    return {"locked": sorted(p.month for p in rows)}


@router.post("/projects/{project_id}/periods/{month}/{action}")
def set_period(project_id: str, month: str, action: Literal["lock", "unlock"], user: User = Depends(current_user),
               db: Session = Depends(get_db)):
    if user.role != "owner":
        raise HTTPException(403, "Only the owner can close or reopen a month")
    _own_project(db, user, project_id)
    _month_range(month)
    period = db.get(Period, (user.tenant_id, project_id, month))
    if not period:
        period = Period(tenant_id=user.tenant_id, project_id=project_id, month=month)
        db.add(period)
    period.locked = action == "lock"
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action=f"period:{action}", ref=project_id, detail=month))
    db.commit()
    return {"month": month, "locked": period.locked}
