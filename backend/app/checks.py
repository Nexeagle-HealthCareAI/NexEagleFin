"""Warnings shown before an entry is saved. They never block recording the truth; they ask for a second look.

Cash limits under the income-tax rules (confirm the details with your CA):
- receiving 2,00,000 or more in cash from one person for one event (a patient's treatment) is penalised;
- an expense paid in cash above 10,000 to one person in a day is usually not allowed as a deduction;
- taking or repaying a loan of 20,000 or more in cash is not allowed.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Document, Party, Unit

RECEIPT_LIMIT = Decimal("200000")   # cash from one patient for one treatment, or one person in a day
PAYMENT_LIMIT = Decimal("10000")    # cash expense to one person in a day
LOAN_LIMIT = Decimal("20000")       # a loan taken or repaid in cash

CASH_RECEIPTS = ("collection", "claim_settlement", "advance_received", "investment")
CASH_PAYMENTS = ("expense", "vendor_payment")  # refunds of a patient's own advance are not expenses


def _inr(value: Decimal) -> str:
    from .agents.chat import inr

    return inr(value)


def _project_units(db: Session, unit_id: str) -> list[str]:
    project_id = db.scalar(select(Unit.project_id).where(Unit.id == unit_id))
    return list(db.scalars(select(Unit.id).where(Unit.project_id == project_id)))


def _cash_total(db: Session, doc: Document, types: tuple, **match) -> Decimal:
    q = select(func.coalesce(func.sum(Document.amount), 0)).where(
        Document.tenant_id == doc.tenant_id, Document.unit_id.in_(_project_units(db, doc.unit_id)),
        Document.type.in_(types), Document.payment_mode == "cash", Document.status != "reversed",
    )
    if doc.id:
        q = q.where(Document.id != doc.id)
    for column, value in match.items():
        q = q.where(getattr(Document, column) == value)
    return Decimal(str(db.scalar(q)))


def _who(db: Session, party_id: str | None) -> str:
    name = db.scalar(select(Party.name).where(Party.id == party_id)) if party_id else None
    return name or "this person"


def cash_warnings(db: Session, doc: Document) -> list[str]:
    """Plain-language warnings for a document about to be saved. Empty when nothing needs a second look."""
    if doc.payment_mode != "cash":
        return []
    amount = Decimal(doc.amount)
    when: date = doc.doc_date
    out: list[str] = []

    if doc.type in CASH_RECEIPTS:
        if doc.reference and doc.type in ("collection", "advance_received"):
            # one patient's treatment: every cash receipt against the same patient or bill number counts
            total = amount + _cash_total(db, doc, ("collection", "advance_received"), reference=doc.reference)
            who = f"patient or bill {doc.reference}"
        elif doc.party_id:
            total = amount + _cash_total(db, doc, CASH_RECEIPTS, party_id=doc.party_id, doc_date=when)
            who = _who(db, doc.party_id)
        else:
            total, who = amount, None
        if total >= RECEIPT_LIMIT:
            so_far = f" Cash from {who}, including this, comes to {_inr(total)}." if who and total != amount else ""
            out.append(
                f"Cash of {_inr(RECEIPT_LIMIT)} or more from one person for one treatment or in one day attracts a penalty "
                f"equal to the amount.{so_far} Take the rest by UPI, card or bank transfer."
            )
        elif doc.type in ("collection", "advance_received") and not doc.reference and amount >= Decimal("50000"):
            out.append("Add the patient or bill number, so cash from the same patient can be added up against the "
                       f"{_inr(RECEIPT_LIMIT)} cash limit.")

    if doc.type in CASH_PAYMENTS and (doc.type != "expense" or doc.paid):
        if doc.party_id:
            total = amount + _cash_total(db, doc, CASH_PAYMENTS, party_id=doc.party_id, doc_date=when)
            who = _who(db, doc.party_id)
        else:
            total, who = amount, None
        if total > PAYMENT_LIMIT:
            today_total = f" Cash paid to {who} that day would be {_inr(total)}." if who and total != amount else ""
            out.append(f"Expenses paid in cash above {_inr(PAYMENT_LIMIT)} to one person in a day are usually not "
                       f"allowed as a tax deduction.{today_total} Pay by bank or UPI where you can.")

    if doc.type in ("loan_received", "loan_payment") and amount >= LOAN_LIMIT:
        verb = "taken" if doc.type == "loan_received" else "repaid"
        out.append(f"A loan of {_inr(LOAN_LIMIT)} or more should not be {verb} in cash under the income-tax rules. "
                   "Use a bank transfer or cheque.")
    return out
