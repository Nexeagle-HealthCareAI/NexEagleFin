"""Loan arithmetic. Plain code: what is owed, how an instalment splits, what is due and when."""

import calendar
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Document, Loan

ZERO = Decimal("0.00")
CENT = Decimal("0.01")


def money(value) -> str:
    """Always two decimals, whether the value came from the database or straight from a request."""
    return str(Decimal(value).quantize(CENT))


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def month_interest(outstanding: Decimal, rate: Decimal) -> Decimal:
    """One month's interest on the reducing balance."""
    return (outstanding * rate / Decimal(1200)).quantize(CENT, ROUND_HALF_UP)


def payments(db: Session, loan: Loan) -> list[Document]:
    return list(db.scalars(
        select(Document).where(Document.loan_id == loan.id, Document.type == "loan_payment", Document.status == "posted")
        .order_by(Document.doc_date, Document.created_at)
    ))


def summary(db: Session, loan: Loan, today: date) -> dict:
    paid = payments(db, loan)
    principal_paid = sum((p.amount - p.interest for p in paid), ZERO)
    interest_paid = sum((p.interest for p in paid), ZERO)
    outstanding = loan.amount - principal_paid
    closed = outstanding <= ZERO

    # instalment k (0-based) falls due on first_due + k months; the next unpaid one is number len(paid)
    next_due = None if closed else add_months(loan.first_due, len(paid))
    expected = 0
    while add_months(loan.first_due, expected) < today and expected < 1200:  # due today is not yet overdue
        expected += 1
    overdue = 0 if closed else max(0, expected - len(paid))

    interest = ZERO if closed else month_interest(outstanding, loan.rate)
    next_amount = ZERO if closed else min(loan.emi, outstanding + interest)

    # how many more instalments at the current rate and instalment
    left, bal = 0, outstanding
    if not closed:
        while bal > ZERO and left < 600:
            i = month_interest(bal, loan.rate)
            if loan.emi <= i:
                left = None  # the instalment does not even cover the interest
                break
            bal -= loan.emi - i
            left += 1

    return {
        "id": loan.id,
        "project_id": loan.project_id,
        "lender": loan.lender,
        "loan_type": loan.loan_type,
        "amount": money(loan.amount),
        "already_running": loan.already_running,
        "rate": str(loan.rate),
        "emi": money(loan.emi),
        "start_date": loan.start_date.isoformat(),
        "note": loan.note,
        "status": "cancelled" if loan.status == "cancelled" else "closed" if closed else "active",
        "outstanding": money(max(outstanding, ZERO)),
        "principal_paid": money(principal_paid),
        "interest_paid": money(interest_paid),
        "instalments_paid": len(paid),
        "instalments_left": left,
        "next_due": next_due.isoformat() if next_due else None,
        "next_amount": money(next_amount),
        "next_interest": money(min(interest, next_amount)),
        "overdue": overdue,
        "days_to_due": (next_due - today).days if next_due else None,
    }


def project_loans(db: Session, tenant_id: str, project_ids: list[str], today: date) -> list[dict]:
    loans = db.scalars(
        select(Loan).where(Loan.tenant_id == tenant_id, Loan.project_id.in_(project_ids), Loan.status == "active")
        .order_by(Loan.created_at)
    )
    return [summary(db, loan, today) for loan in loans]


def overview(rows: list[dict]) -> dict:
    """The few numbers the home screen shows, and what an assistant will watch later."""
    live = [r for r in rows if r["status"] == "active"]
    upcoming = sorted(live, key=lambda r: r["next_due"])
    return {
        "count": len(live),
        "outstanding": money(sum((Decimal(r["outstanding"]) for r in live), ZERO)),
        "monthly_instalments": money(sum((Decimal(r["emi"]) for r in live), ZERO)),
        "overdue": sum(r["overdue"] for r in live),
        "next": None if not upcoming else {
            "lender": upcoming[0]["lender"], "date": upcoming[0]["next_due"], "amount": upcoming[0]["next_amount"],
            "days": upcoming[0]["days_to_due"],
        },
    }
