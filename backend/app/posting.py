"""The posting engine: turns a plain document into balanced ledger lines.

Screens never deal in debits and credits. They create a Document; this module
decides which accounts move. Every rule lives here so a chartered accountant
can review the whole of the bookkeeping logic in one file.
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Account, AuditLog, Category, Document, JournalEntry, JournalLine, MoneyAccount, Period, Unit, User

# System account codes (seeded for every tenant in seed.py)
CASH = "1000"
BANK = "1010"
RECEIVABLE = "1200"
PAYABLE = "2000"
CAPITAL = "3000"
ADVANCES = "2200"
LOANS = "2100"
OPENING = "3900"
LOAN_INTEREST = "5800"
CLAIM_DEDUCTIONS = "5900"
UNSORTED_EXPENSE = "5999"
INCOME_BY_UNIT_KIND = {
    "general": "4090",
    "hospital": "4000",
    "diagnostics": "4010",
    "path_lab": "4020",
    "pharmacy": "4030",
    "other": "4090",
}

ZERO = Decimal("0")


class PostingError(Exception):
    pass


@dataclass
class Line:
    code: str | None  # system account code, or
    account_id: str | None  # an explicit account
    debit: Decimal = ZERO
    credit: Decimal = ZERO
    party_id: str | None = None


def dr(code=None, amount=ZERO, account_id=None, party_id=None) -> Line:
    return Line(code, account_id, debit=amount, party_id=party_id)


def cr(code=None, amount=ZERO, account_id=None, party_id=None) -> Line:
    return Line(code, account_id, credit=amount, party_id=party_id)


def money_account(mode: str | None) -> str:
    return CASH if mode == "cash" else BANK


def money_line(db: Session, doc: Document, side: str, amount: Decimal, account_id: str | None = None) -> Line:
    """The cash box or bank account a document moved money through: the one chosen, else the default for its mode."""
    chosen = account_id if account_id is not None else doc.money_account_id
    ledger = db.scalar(select(MoneyAccount.account_id).where(MoneyAccount.id == chosen)) if chosen else None
    code = None if ledger else money_account(doc.payment_mode)
    return dr(code, amount, account_id=ledger) if side == "dr" else cr(code, amount, account_id=ledger)


def lines_for(db: Session, doc: Document) -> list[Line]:
    """The rules. One branch per document type."""
    amt = doc.amount

    if doc.type == "collection":
        unit = db.get(Unit, doc.unit_id)
        income = INCOME_BY_UNIT_KIND[unit.kind]
        return [money_line(db, doc, "dr", amt), cr(income, amt)]

    if doc.type == "expense":
        if doc.category_id:
            cat = db.get(Category, doc.category_id)
            debit = dr(account_id=cat.account_id, amount=amt)
        else:
            # "Save now, sort later": cash is right today, category fixed later.
            debit = dr(UNSORTED_EXPENSE, amt)
        if doc.paid:
            return [debit, money_line(db, doc, "cr", amt)]
        return [debit, cr(PAYABLE, amt, party_id=doc.party_id)]

    if doc.type == "vendor_payment":
        return [dr(PAYABLE, amt, party_id=doc.party_id), money_line(db, doc, "cr", amt)]

    if doc.type == "claim":
        # Always book the full billed amount, never just what the insurer approves.
        unit = db.get(Unit, doc.unit_id)
        income = INCOME_BY_UNIT_KIND[unit.kind]
        return [dr(RECEIVABLE, amt, party_id=doc.party_id), cr(income, amt)]

    if doc.type == "claim_settlement":
        out = [money_line(db, doc, "dr", amt)]
        if doc.deduction > ZERO:
            out.append(dr(CLAIM_DEDUCTIONS, doc.deduction))
        out.append(cr(RECEIVABLE, amt + doc.deduction, party_id=doc.party_id))
        return out

    if doc.type == "investment":
        # Money the owners put into the project. Not income.
        return [money_line(db, doc, "dr", amt), cr(CAPITAL, amt)]

    if doc.type == "loan_received":
        # A new loan puts money in the bank. A loan that was already running when the books
        # started here has no money movement, so it is set against opening balances.
        debit = money_line(db, doc, "dr", amt) if doc.payment_mode else dr(OPENING, amt)
        return [debit, cr(LOANS, amt, party_id=doc.party_id)]

    if doc.type == "loan_payment":
        # One instalment, two parts: interest is a cost, the rest reduces what is owed.
        out = [dr(LOANS, amt - doc.interest, party_id=doc.party_id)] if amt > doc.interest else []
        if doc.interest > ZERO:
            out.append(dr(LOAN_INTEREST, doc.interest))
        out.append(money_line(db, doc, "cr", amt))
        return out

    if doc.type == "transfer":
        return [money_line(db, doc, "dr", amt, account_id=doc.to_money_account_id),
                money_line(db, doc, "cr", amt, account_id=doc.money_account_id)]

    if doc.type == "opening_balance":
        # money that was already in the account when these books started
        return [money_line(db, doc, "dr", amt), cr(OPENING, amt)]

    if doc.type == "advance_received":
        # a patient's deposit is the patient's money until the final bill: owed, not earned
        return [money_line(db, doc, "dr", amt), cr(ADVANCES, amt)]

    if doc.type == "advance_adjusted":
        unit = db.get(Unit, doc.unit_id)
        return [dr(ADVANCES, amt), cr(INCOME_BY_UNIT_KIND[unit.kind], amt)]

    if doc.type == "advance_refund":
        return [dr(ADVANCES, amt), money_line(db, doc, "cr", amt)]

    raise PostingError(f"No posting rule for document type '{doc.type}'")


def _check_period_open(db: Session, doc: Document) -> None:
    """Months are closed per project, so one project's close never blocks another."""
    month = doc.doc_date.strftime("%Y-%m")
    unit = db.get(Unit, doc.unit_id)
    period = db.get(Period, (doc.tenant_id, unit.project_id, month))
    if period and period.locked:
        raise PostingError(f"{month} is closed for this project. Ask the owner to reopen it.")


def _account_ids(db: Session, tenant_id: str) -> dict[str, str]:
    rows = db.execute(select(Account.code, Account.id).where(Account.tenant_id == tenant_id)).all()
    return {code: id_ for code, id_ in rows}


def post(db: Session, doc: Document, user: User, memo: str | None = None) -> JournalEntry:
    """Write the ledger entry for a document. Caller commits."""
    _check_period_open(db, doc)
    lines = lines_for(db, doc)

    total_dr = sum((l.debit for l in lines), ZERO)
    total_cr = sum((l.credit for l in lines), ZERO)
    if total_dr != total_cr or total_dr <= ZERO:
        raise PostingError(f"Entry does not balance: debit {total_dr}, credit {total_cr}")

    codes = _account_ids(db, doc.tenant_id)
    entry = JournalEntry(
        tenant_id=doc.tenant_id,
        entry_date=doc.doc_date,
        document_id=doc.id,
        memo=memo or f"{doc.type} {doc.reference or ''}".strip(),
        created_by=user.id,
    )
    db.add(entry)
    db.flush()
    for l in lines:
        account_id = l.account_id or codes.get(l.code)
        if not account_id:
            raise PostingError(f"Account {l.code} is missing from the chart of accounts")
        db.add(
            JournalLine(
                tenant_id=doc.tenant_id,
                entry_id=entry.id,
                account_id=account_id,
                unit_id=doc.unit_id,
                party_id=l.party_id,
                debit=l.debit,
                credit=l.credit,
            )
        )
    db.add(AuditLog(tenant_id=doc.tenant_id, user_id=user.id, action=f"post:{doc.type}", ref=doc.id))
    db.flush()
    return entry


def reverse(db: Session, doc: Document, user: User, reason: str) -> None:
    """Cancel a document's effect with mirror-image entries. Nothing is deleted."""
    _check_period_open(db, doc)
    entries = db.scalars(select(JournalEntry).where(JournalEntry.document_id == doc.id)).all()
    reversed_ids = {e.reverses_id for e in entries if e.reverses_id}
    for e in entries:
        if e.reverses_id or e.id in reversed_ids:
            continue
        mirror = JournalEntry(
            tenant_id=e.tenant_id,
            entry_date=e.entry_date,
            document_id=doc.id,
            reverses_id=e.id,
            memo=f"Reversal: {reason}"[:300],
            created_by=user.id,
        )
        db.add(mirror)
        db.flush()
        for l in e.lines:
            db.add(
                JournalLine(
                    tenant_id=l.tenant_id,
                    entry_id=mirror.id,
                    account_id=l.account_id,
                    unit_id=l.unit_id,
                    party_id=l.party_id,
                    debit=l.credit,
                    credit=l.debit,
                )
            )
    db.add(AuditLog(tenant_id=doc.tenant_id, user_id=user.id, action="reverse", ref=doc.id, detail=reason))
    db.flush()
