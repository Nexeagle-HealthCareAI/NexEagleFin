"""Cash boxes and bank accounts, opening balances, transfers between them, and patient advances."""

from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .agents.chat import inr
from .api import Amount, Mode, check_date, get_doc, project_units, save, settled_total, today
from .db import get_db
from .models import Account, AuditLog, Document, JournalEntry, JournalLine, MoneyAccount, Unit, User
from .security import current_user, require_unit, require_write
from .seed import ensure_chart, ensure_money_accounts

router = APIRouter()
Day = date
ZERO = Decimal("0.00")


def _keeper(user: User) -> None:
    if user.role not in ("owner", "accountant"):
        raise HTTPException(403, "Only the owner or accountant can manage cash and bank accounts")


def _general(db: Session, user: User, project_id: str) -> str:
    unit_ids = project_units(db, user, project_id)
    general = db.scalar(select(Unit.id).where(Unit.id.in_(unit_ids), Unit.kind == "general"))
    if not general:
        raise HTTPException(404, "Project not found")
    return general


def _account(db: Session, user: User, account_id: str) -> MoneyAccount:
    acc = db.get(MoneyAccount, account_id)
    if not acc or acc.tenant_id != user.tenant_id or not acc.active:
        raise HTTPException(404, "Account not found")
    project_units(db, user, acc.project_id)
    return acc


def balance(db: Session, acc: MoneyAccount, upto: date | None = None) -> Decimal:
    """What is in one cash box or bank account: its ledger lines within its own project."""
    units = select(Unit.id).where(Unit.project_id == acc.project_id)
    q = (select(func.coalesce(func.sum(JournalLine.debit - JournalLine.credit), 0))
         .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
         .where(JournalLine.account_id == acc.account_id, JournalLine.unit_id.in_(units)))
    if upto:
        q = q.where(JournalEntry.entry_date <= upto)
    return Decimal(str(db.scalar(q))).quantize(Decimal("0.01"))


def has_opening(db: Session, acc: MoneyAccount) -> bool:
    return bool(db.scalar(select(func.count()).select_from(Document).where(
        Document.type == "opening_balance", Document.money_account_id == acc.id, Document.status == "posted")))


def account_out(db: Session, acc: MoneyAccount) -> dict:
    return {"id": acc.id, "name": acc.name, "kind": acc.kind, "is_default": acc.is_default,
            "balance": str(balance(db, acc)), "has_opening": has_opening(db, acc)}


@router.get("/money-accounts")
def list_accounts(project_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _general(db, user, project_id)                         # whole-project view only
    ensure_money_accounts(db, user.tenant_id, project_id)  # projects made before accounts existed
    db.commit()
    rows = db.scalars(select(MoneyAccount).where(
        MoneyAccount.project_id == project_id, MoneyAccount.tenant_id == user.tenant_id, MoneyAccount.active.is_(True))
        .order_by(MoneyAccount.is_default.desc(), MoneyAccount.created_at, MoneyAccount.name))
    # cash box first, then banks; the default of each kind leads its kind
    out = [account_out(db, a) for a in sorted(rows, key=lambda a: (a.kind != "cash", not a.is_default))]
    return {"accounts": out, "total": str(sum((Decimal(a["balance"]) for a in out), ZERO))}


def _opening(db: Session, user: User, acc: MoneyAccount, amount: Decimal, when: date) -> None:
    check_date(when)
    doc = Document(tenant_id=user.tenant_id, unit_id=_general(db, user, acc.project_id), type="opening_balance",
                   doc_date=when, amount=amount, money_account_id=acc.id, payment_mode="cash" if acc.kind == "cash" else "bank",
                   note=f"Opening balance of {acc.name}", created_by=user.id)
    save(db, doc, user, confirmed=True)


class AccountIn(BaseModel):
    project_id: str
    name: str = Field(min_length=2, max_length=120)
    kind: Literal["cash", "bank"]
    opening_balance: Decimal = Field(Decimal("0"), ge=0, max_digits=14, decimal_places=2)
    as_of: Day | None = None


@router.post("/money-accounts", status_code=201)
def create_account(body: AccountIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _keeper(user)
    _general(db, user, body.project_id)
    name = body.name.strip()
    clash = db.scalar(select(MoneyAccount).where(MoneyAccount.project_id == body.project_id, MoneyAccount.active.is_(True),
                                                 func.lower(MoneyAccount.name) == name.lower()))
    if clash:
        raise HTTPException(409, "This project already has an account with that name")
    ensure_chart(db, user.tenant_id)
    base = "1000" if body.kind == "cash" else "1010"
    taken = set(db.scalars(select(Account.code).where(Account.tenant_id == user.tenant_id, Account.code.like(f"{base}-%"))))
    n = 1
    while f"{base}-{n}" in taken:
        n += 1
    ledger = Account(tenant_id=user.tenant_id, code=f"{base}-{n}", name=name, type="asset")
    db.add(ledger)
    db.flush()
    acc = MoneyAccount(tenant_id=user.tenant_id, project_id=body.project_id, name=name, kind=body.kind, account_id=ledger.id)
    db.add(acc)
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="money_account:create", ref=acc.id, detail=name))
    db.flush()
    if body.opening_balance > 0:
        _opening(db, user, acc, body.opening_balance, body.as_of or today())
    db.commit()
    return account_out(db, acc)


class OpeningIn(BaseModel):
    amount: Decimal = Amount
    date: Day


@router.post("/money-accounts/{account_id}/opening", status_code=201)
def set_opening(account_id: str, body: OpeningIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The balance an account already had when these books started. Once per account; cancel it in Entries to change it."""
    _keeper(user)
    acc = _account(db, user, account_id)
    if has_opening(db, acc):
        raise HTTPException(409, "This account already has an opening balance. Cancel it in Entries to enter a new one.")
    _opening(db, user, acc, body.amount, body.date)
    return account_out(db, acc)


class TransferIn(BaseModel):
    from_account_id: str
    to_account_id: str
    amount: Decimal = Amount
    date: Day
    note: str | None = Field(None, max_length=1000)


@router.post("/transfers", status_code=201)
def transfer(body: TransferIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Money moved between two accounts of the same project: cash deposited, cash withdrawn, bank to bank."""
    require_write(user)
    src, dst = _account(db, user, body.from_account_id), _account(db, user, body.to_account_id)
    if src.id == dst.id:
        raise HTTPException(422, "Choose two different accounts")
    if src.project_id != dst.project_id:
        raise HTTPException(422, "Both accounts must belong to the same project")
    check_date(body.date)
    if src.kind == "cash" and balance(db, src, body.date) < body.amount:
        raise HTTPException(409, f"Only {inr(balance(db, src, body.date))} was in {src.name} on that date")
    doc = Document(tenant_id=user.tenant_id, unit_id=_general(db, user, src.project_id), type="transfer", doc_date=body.date,
                   amount=body.amount, money_account_id=src.id, to_money_account_id=dst.id,
                   note=body.note or f"{src.name} to {dst.name}", created_by=user.id)
    return save(db, doc, user, confirmed=True)


# ---------- patient advances ----------


class AdvanceIn(BaseModel):
    unit_id: str
    date: Day
    amount: Decimal = Amount
    payment_mode: Mode
    reference: str = Field(min_length=1, max_length=100)  # patient or IP number, so the advance can be found at discharge
    money_account_id: str | None = None
    note: str | None = Field(None, max_length=1000)
    confirmed: bool = False


@router.post("/advances", status_code=201)
def take_advance(body: AdvanceIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_write(user)
    require_unit(db, user, body.unit_id)
    check_date(body.date)
    doc = Document(tenant_id=user.tenant_id, unit_id=body.unit_id, type="advance_received", doc_date=body.date,
                   amount=body.amount, payment_mode=body.payment_mode, reference=body.reference.strip(),
                   money_account_id=body.money_account_id, paid=False, note=body.note, created_by=user.id)
    return save(db, doc, user, body.confirmed)


def _open_advance(db: Session, user: User, doc_id: str) -> tuple[Document, Decimal]:
    adv = get_doc(db, user, doc_id, lock=True)
    if adv.type != "advance_received" or adv.status != "posted":
        raise HTTPException(409, "Not an advance that is still held")
    held = adv.amount - settled_total(db, adv)
    if held <= 0:
        raise HTTPException(409, "Nothing of this advance is still held")
    return adv, held


class AdjustIn(BaseModel):
    date: Day
    amount: Decimal = Amount


@router.post("/documents/{doc_id}/adjust-advance", status_code=201)
def adjust_advance(doc_id: str, body: AdjustIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The final bill used the advance: that part now counts as the unit's income."""
    require_write(user)
    adv, held = _open_advance(db, user, doc_id)
    check_date(body.date, not_before=adv.doc_date)
    if body.amount > held:
        raise HTTPException(409, f"Only {held} of this advance is still held")
    doc = Document(tenant_id=user.tenant_id, unit_id=adv.unit_id, type="advance_adjusted", doc_date=body.date,
                   amount=body.amount, parent_id=adv.id, reference=adv.reference, created_by=user.id)
    return save(db, doc, user, confirmed=True)


class RefundIn(BaseModel):
    date: Day
    amount: Decimal = Amount
    payment_mode: Mode
    money_account_id: str | None = None
    confirmed: bool = False


@router.post("/documents/{doc_id}/refund-advance", status_code=201)
def refund_advance(doc_id: str, body: RefundIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_write(user)
    adv, held = _open_advance(db, user, doc_id)
    check_date(body.date, not_before=adv.doc_date)
    if body.amount > held:
        raise HTTPException(409, f"Only {held} of this advance is still held")
    doc = Document(tenant_id=user.tenant_id, unit_id=adv.unit_id, type="advance_refund", doc_date=body.date,
                   amount=body.amount, payment_mode=body.payment_mode, money_account_id=body.money_account_id,
                   parent_id=adv.id, reference=adv.reference, created_by=user.id)
    return save(db, doc, user, body.confirmed)
