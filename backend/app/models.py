import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

Money = Numeric(14, 2)


def uid() -> str:
    return str(uuid.uuid4())


def now() -> datetime:
    return datetime.now(timezone.utc)


class Tenant(Base):
    """One customer account. Every other row belongs to exactly one tenant, which may run many projects."""

    __tablename__ = "tenant"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(200))


class Project(Base):
    """One venture the account manages, such as a hospital. Has its own units, expenses and investments."""

    __tablename__ = "project"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenant.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    gstin: Mapped[str | None] = mapped_column(String(15), nullable=True)


UNIT_KINDS = ("general", "hospital", "diagnostics", "path_lab", "pharmacy", "other")


class Unit(Base):
    __tablename__ = "unit"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenant.id"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("project.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20))


ROLES = ("owner", "accountant", "unit_incharge", "cashier", "auditor")


class User(Base):
    __tablename__ = "app_user"
    __table_args__ = (UniqueConstraint("phone"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenant.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str] = mapped_column(String(15))
    pin_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserUnit(Base):
    """Which units a non-owner, non-accountant user may see."""

    __tablename__ = "user_unit"
    user_id: Mapped[str] = mapped_column(ForeignKey("app_user.id"), primary_key=True)
    unit_id: Mapped[str] = mapped_column(ForeignKey("unit.id"), primary_key=True)


ACCOUNT_TYPES = ("asset", "liability", "income", "expense", "equity")


class Account(Base):
    __tablename__ = "account"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenant.id"), index=True)
    code: Mapped[str] = mapped_column(String(10))
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(20))


class Category(Base):
    """What the user picks ("Medical supplies"). Maps to an account behind the screen."""

    __tablename__ = "category"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenant.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    account_id: Mapped[str] = mapped_column(ForeignKey("account.id"))


PARTY_KINDS = ("vendor", "payer", "doctor")


class Party(Base):
    __tablename__ = "party"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenant.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20))


DOC_TYPES = ("collection", "expense", "vendor_payment", "claim", "claim_settlement", "investment",
             "loan_received", "loan_payment", "transfer", "opening_balance",
             "advance_received", "advance_adjusted", "advance_refund")
DOC_STATUS = ("posted", "needs_attention", "reversed")
PAYMENT_MODES = ("cash", "upi", "card", "bank")


class Document(Base):
    """A plain-language record a user creates. The posting engine turns it into ledger lines."""

    __tablename__ = "document"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenant.id"), index=True)
    unit_id: Mapped[str] = mapped_column(ForeignKey("unit.id"), index=True)
    type: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="posted")
    doc_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Money)
    deduction: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    payment_mode: Mapped[str | None] = mapped_column(String(10), nullable=True)
    paid: Mapped[bool] = mapped_column(Boolean, default=True)
    category_id: Mapped[str | None] = mapped_column(ForeignKey("category.id"), nullable=True)
    party_id: Mapped[str | None] = mapped_column(ForeignKey("party.id"), nullable=True)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("document.id"), nullable=True)
    loan_id: Mapped[str | None] = mapped_column(ForeignKey("loan.id"), nullable=True, index=True)
    # which cash box or bank account the money moved through; empty means the project's default for the mode
    money_account_id: Mapped[str | None] = mapped_column(ForeignKey("money_account.id"), nullable=True, index=True)
    to_money_account_id: Mapped[str | None] = mapped_column(ForeignKey("money_account.id"), nullable=True)  # transfers
    interest: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))  # interest part of a loan instalment
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    attachment_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class JournalEntry(Base):
    __tablename__ = "journal_entry"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenant.id"), index=True)
    entry_date: Mapped[date] = mapped_column(Date, index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("document.id"), index=True)
    reverses_id: Mapped[str | None] = mapped_column(ForeignKey("journal_entry.id"), nullable=True)
    memo: Mapped[str] = mapped_column(String(300))
    created_by: Mapped[str] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    lines: Mapped[list["JournalLine"]] = relationship(back_populates="entry")


class JournalLine(Base):
    __tablename__ = "journal_line"
    __table_args__ = (
        CheckConstraint("debit >= 0 AND credit >= 0", name="ck_line_non_negative"),
        CheckConstraint("(debit = 0) <> (credit = 0)", name="ck_line_one_side"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenant.id"), index=True)
    entry_id: Mapped[str] = mapped_column(ForeignKey("journal_entry.id"), index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("account.id"), index=True)
    unit_id: Mapped[str] = mapped_column(ForeignKey("unit.id"), index=True)
    party_id: Mapped[str | None] = mapped_column(ForeignKey("party.id"), nullable=True)
    debit: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    credit: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    entry: Mapped[JournalEntry] = relationship(back_populates="lines")


class Period(Base):
    """A month that has been closed for one project. No posting is allowed into it."""

    __tablename__ = "period"
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenant.id"), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("project.id"), primary_key=True)
    month: Mapped[str] = mapped_column(String(7), primary_key=True)  # YYYY-MM
    locked: Mapped[bool] = mapped_column(Boolean, default=True)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenant.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("app_user.id"))
    action: Mapped[str] = mapped_column(String(50))
    ref: Mapped[str | None] = mapped_column(String(36), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


PROPOSAL_STATUS = ("pending", "approved", "rejected")


class Proposal(Base):
    """An entry suggested by an agent. Nothing reaches the ledger until a person approves it."""

    __tablename__ = "proposal"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenant.id"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("project.id"), index=True)
    unit_id: Mapped[str] = mapped_column(ForeignKey("unit.id"))
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    agent: Mapped[str] = mapped_column(String(30))
    source: Mapped[str] = mapped_column(String(20))  # text | bank_csv
    raw_text: Mapped[str] = mapped_column(Text)
    doc_type: Mapped[str] = mapped_column(String(20))  # expense | collection | investment
    doc_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    payment_mode: Mapped[str | None] = mapped_column(String(10), nullable=True)
    paid: Mapped[bool] = mapped_column(Boolean, default=True)
    party_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    category_id: Mapped[str | None] = mapped_column(ForeignKey("category.id"), nullable=True)
    confidence: Mapped[Decimal] = mapped_column(Numeric(3, 2))
    reason: Mapped[str] = mapped_column(String(300))
    flags: Mapped[str] = mapped_column(String(200), default="")  # comma separated
    read_by: Mapped[str] = mapped_column(String(20))  # groq | rules
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    document_id: Mapped[str | None] = mapped_column(ForeignKey("document.id"), nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("app_user.id"))
    decided_by: Mapped[str | None] = mapped_column(ForeignKey("app_user.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


LOAN_TYPES = (
    "Term loan", "Equipment loan", "Vehicle loan", "Building or property loan", "Working capital or overdraft",
    "Personal or unsecured loan", "Loan from partner or family", "Gold loan", "Other",
)


class Loan(Base):
    """Money borrowed for a project. What is still owed is worked out from its payments, never stored."""

    __tablename__ = "loan"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenant.id"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("project.id"), index=True)
    unit_id: Mapped[str] = mapped_column(ForeignKey("unit.id"))
    lender: Mapped[str] = mapped_column(String(200))
    loan_type: Mapped[str] = mapped_column(String(40))
    amount: Mapped[Decimal] = mapped_column(Money)  # principal owed on the day it entered these books
    already_running: Mapped[bool] = mapped_column(Boolean, default=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(5, 2))  # yearly interest, percent
    emi: Mapped[Decimal] = mapped_column(Money)  # monthly instalment
    first_due: Mapped[date] = mapped_column(Date)  # first instalment date after it entered these books
    start_date: Mapped[date] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | cancelled
    created_by: Mapped[str] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ChatAction(Base):
    """A change the assistant has prepared in chat. It does nothing until the same person confirms it."""

    __tablename__ = "chat_action"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenant.id"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("project.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("app_user.id"))
    kind: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(200))
    params: Mapped[str] = mapped_column(Text)  # JSON: exactly what will be done
    rows: Mapped[str] = mapped_column(Text)  # JSON: what the person was shown
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | done | cancelled | failed
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MoneyAccount(Base):
    """A cash box or bank account of a project. Each has its own ledger account, so balances never mix."""

    __tablename__ = "money_account"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenant.id"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("project.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(10))  # cash | bank
    account_id: Mapped[str] = mapped_column(ForeignKey("account.id"))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
