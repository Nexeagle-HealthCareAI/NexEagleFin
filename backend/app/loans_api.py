from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import loans as L
from .api import Amount, Mode, doc_out, find_party, project_units, save, today
from .db import get_db
from .models import LOAN_TYPES, AuditLog, Document, Loan, Unit, User
from .security import current_user
from .seed import ensure_chart

router = APIRouter()
Day = date


def _keeper(user: User) -> None:
    if user.role not in ("owner", "accountant"):
        raise HTTPException(403, "Only the owner or accountant can manage loans")


def _get(db: Session, user: User, loan_id: str) -> Loan:
    loan = db.get(Loan, loan_id)
    if not loan or loan.tenant_id != user.tenant_id or loan.unit_id not in project_units(db, user, loan.project_id):
        raise HTTPException(404, "Loan not found")
    return loan


class LoanIn(BaseModel):
    project_id: str
    lender: str = Field(min_length=2, max_length=200)
    loan_type: Literal[LOAN_TYPES]  # type: ignore[valid-type]
    amount: Decimal = Amount                                    # new loan: amount received. Running loan: principal still owed.
    already_running: bool = False
    start_date: Day                                             # date received, or the date the balance is as of
    payment_mode: Mode | None = None                            # how the money arrived (new loans only)
    rate: Decimal = Field(ge=0, le=60, max_digits=5, decimal_places=2)
    emi: Decimal = Amount
    first_due: Day
    note: str | None = Field(None, max_length=1000)
    confirmed: bool = False
    money_account_id: str | None = None


@router.get("/loan-types")
def loan_types():
    return list(LOAN_TYPES)


@router.post("/loans", status_code=201)
def create_loan(body: LoanIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _keeper(user)
    unit_ids = project_units(db, user, body.project_id)
    general = db.scalar(select(Unit.id).where(Unit.id.in_(unit_ids), Unit.kind == "general"))
    if not general:
        raise HTTPException(404, "Project not found")
    if body.start_date > today():
        raise HTTPException(422, "The start date cannot be in the future")
    if body.first_due < body.start_date:
        raise HTTPException(422, "The first instalment cannot be before the loan started")
    if not body.already_running and not body.payment_mode:
        raise HTTPException(422, "Choose how the loan money was received")
    if body.emi <= L.month_interest(body.amount, body.rate):
        raise HTTPException(422, "This instalment does not cover one month's interest. Check the rate and the instalment.")

    ensure_chart(db, user.tenant_id)
    loan = Loan(
        tenant_id=user.tenant_id, project_id=body.project_id, unit_id=general, lender=body.lender.strip(),
        loan_type=body.loan_type, amount=body.amount, already_running=body.already_running, rate=body.rate,
        emi=body.emi, first_due=body.first_due, start_date=body.start_date, note=body.note, created_by=user.id,
    )
    db.add(loan)
    db.flush()
    doc = Document(
        tenant_id=user.tenant_id, unit_id=general, type="loan_received", doc_date=body.start_date, amount=body.amount,
        payment_mode=None if body.already_running else body.payment_mode,
        party_id=find_party(db, user.tenant_id, body.lender, "lender"), loan_id=loan.id, paid=True,
        note=f"{body.loan_type}{' (already running)' if body.already_running else ''}", created_by=user.id,
        money_account_id=None if body.already_running else body.money_account_id,
    )
    db.add(AuditLog(tenant_id=user.tenant_id, user_id=user.id, action="loan:create", ref=loan.id))
    save(db, doc, user, body.confirmed)
    return L.summary(db, loan, today())


@router.get("/loans")
def list_loans(project_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    unit_ids = project_units(db, user, project_id)
    # loans belong to the project as a whole (its General unit); staff limited to one unit do not see them
    whole_project = db.scalar(select(Unit.id).where(Unit.id.in_(unit_ids), Unit.kind == "general"))
    rows = L.project_loans(db, user.tenant_id, [project_id], today()) if whole_project else []
    return {"overview": L.overview(rows), "loans": rows}


@router.get("/loans/{loan_id}")
def loan_detail(loan_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    loan = _get(db, user, loan_id)
    out = L.summary(db, loan, today())
    out["payments"] = [
        {"id": p.id, "date": p.doc_date.isoformat(), "amount": L.money(p.amount), "interest": L.money(p.interest),
         "principal": L.money(p.amount - p.interest)}
        for p in reversed(L.payments(db, loan))
    ]
    # what the next instalments will look like if paid on time
    plan, bal, n = [], Decimal(out["outstanding"]), out["instalments_paid"]
    while bal > 0 and len(plan) < 12:
        interest = L.month_interest(bal, loan.rate)
        pay = min(loan.emi, bal + interest)
        if pay <= interest:
            break
        bal -= pay - interest
        plan.append({"date": L.add_months(loan.first_due, n + len(plan)).isoformat(), "amount": L.money(pay),
                     "interest": L.money(interest), "principal": L.money(pay - interest), "balance": L.money(bal)})
    out["plan"] = plan
    return out


class PayIn(BaseModel):
    date: Day
    amount: Decimal = Amount
    interest: Decimal | None = Field(None, ge=0, max_digits=14, decimal_places=2)  # from the lender's statement, if known
    payment_mode: Mode
    confirmed: bool = False
    money_account_id: str | None = None


@router.post("/loans/{loan_id}/pay", status_code=201)
def pay_instalment(loan_id: str, body: PayIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _keeper(user)
    loan = _get(db, user, loan_id)
    db.refresh(loan, with_for_update=True)  # one instalment at a time per loan (PostgreSQL)
    now = L.summary(db, loan, today())
    if now["status"] != "active":
        raise HTTPException(409, "This loan is not active")
    if body.date > today() or body.date < loan.start_date:
        raise HTTPException(422, "The date must be between the loan's start and today")
    outstanding = Decimal(now["outstanding"])
    interest = body.interest if body.interest is not None else min(Decimal(now["next_interest"]), body.amount)
    if interest > body.amount:
        raise HTTPException(422, "The interest part cannot be more than the amount paid")
    if body.amount - interest > outstanding:
        raise HTTPException(409, f"Only {L.money(outstanding)} of the loan is left. With interest of "
                                 f"{L.money(interest)}, the most to pay is {L.money(outstanding + interest)}.")
    doc = Document(
        tenant_id=user.tenant_id, unit_id=loan.unit_id, type="loan_payment", doc_date=body.date, amount=body.amount,
        interest=interest, payment_mode=body.payment_mode, loan_id=loan.id,
        party_id=find_party(db, user.tenant_id, loan.lender, "lender"), created_by=user.id,
        money_account_id=body.money_account_id,
    )
    saved = save(db, doc, user, body.confirmed)
    return {"payment": {**saved, "interest": L.money(interest), "principal": L.money(body.amount - interest)},
            "loan": L.summary(db, loan, today())}
