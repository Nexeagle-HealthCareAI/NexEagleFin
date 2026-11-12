"""Creates a new account with a healthcare chart of accounts and default categories.

Usage:  python -m app.seed "City Care Group" 9876543210 4321
"""

import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Account, Category, MoneyAccount, Project, Tenant, Unit, User
from .security import clean_phone, hash_pin

CHART = [
    ("1000", "Cash in hand", "asset"),
    ("1010", "Bank accounts", "asset"),
    ("1200", "Receivable: insurers, schemes and corporates", "asset"),
    ("2000", "Vendor payables", "liability"),
    ("2100", "Loans payable", "liability"),
    ("2200", "Patient advances", "liability"),
    ("3000", "Owner investment", "equity"),
    ("3900", "Opening balances", "equity"),
    ("4000", "Hospital income", "income"),
    ("4010", "Diagnostics income", "income"),
    ("4020", "Path lab income", "income"),
    ("4030", "Pharmacy sales", "income"),
    ("4090", "Other income", "income"),
    ("5000", "Medical supplies", "expense"),
    ("5010", "Medicine purchases", "expense"),
    ("5020", "Lab reagents and outsourced tests", "expense"),
    ("5030", "Salaries", "expense"),
    ("5040", "Doctor payouts", "expense"),
    ("5050", "Rent", "expense"),
    ("5060", "Electricity and utilities", "expense"),
    ("5070", "Maintenance and AMC", "expense"),
    ("5080", "Marketing", "expense"),
    ("5090", "Admin and other", "expense"),
    ("5800", "Loan interest", "expense"),
    ("5900", "Claim deductions", "expense"),
    ("5999", "Unsorted expenses", "expense"),
]

# Category shown to users -> account code
CATEGORIES = [
    ("Medical supplies", "5000"),
    ("Medicines", "5010"),
    ("Lab reagents", "5020"),
    ("Salaries", "5030"),
    ("Doctor payout", "5040"),
    ("Rent", "5050"),
    ("Utilities", "5060"),
    ("Maintenance", "5070"),
    ("Marketing", "5080"),
    ("Other", "5090"),
]

def ensure_chart(db: Session, tenant_id: str) -> None:
    """Adds any account in CHART that an older account was created without."""
    have = set(db.scalars(select(Account.code).where(Account.tenant_id == tenant_id)))
    for code, name, type_ in CHART:
        if code not in have:
            db.add(Account(tenant_id=tenant_id, code=code, name=name, type=type_))
    db.flush()


UNIT_NAMES = {
    "hospital": "Hospital",
    "diagnostics": "Diagnostics",
    "path_lab": "Path lab",
    "pharmacy": "Pharmacy",
}


def seed_tenant(db: Session, name: str, owner_phone: str, owner_pin: str) -> Tenant:
    """A new account: chart of accounts, categories and the owner login. Projects are added in the app."""
    tenant = Tenant(name=name)
    db.add(tenant)
    db.flush()
    by_code = {}
    for code, acc_name, type_ in CHART:
        acc = Account(tenant_id=tenant.id, code=code, name=acc_name, type=type_)
        db.add(acc)
        by_code[code] = acc
    db.flush()
    for cat_name, code in CATEGORIES:
        db.add(Category(tenant_id=tenant.id, name=cat_name, account_id=by_code[code].id))
    db.add(
        User(tenant_id=tenant.id, name="Owner", phone=clean_phone(owner_phone), pin_hash=hash_pin(owner_pin), role="owner")
    )
    db.commit()
    return tenant


def add_project(db: Session, tenant_id: str, name: str, unit_kinds: list[str]) -> Project:
    """Every project gets a General unit for money that belongs to no one department."""
    project = Project(tenant_id=tenant_id, name=name)
    db.add(project)
    db.flush()
    db.add(Unit(tenant_id=tenant_id, project_id=project.id, name="General", kind="general"))
    for kind in dict.fromkeys(unit_kinds):
        db.add(Unit(tenant_id=tenant_id, project_id=project.id, name=UNIT_NAMES[kind], kind=kind))
    ensure_chart(db, tenant_id)
    ensure_money_accounts(db, tenant_id, project.id)
    db.flush()
    return project


def ensure_money_accounts(db: Session, tenant_id: str, project_id: str) -> None:
    """Every project starts with one cash box and one bank account (the defaults for each payment mode)."""
    have = {kind for (kind,) in db.execute(select(MoneyAccount.kind).where(
        MoneyAccount.project_id == project_id, MoneyAccount.is_default.is_(True)))}
    codes = dict(db.execute(select(Account.code, Account.id).where(Account.tenant_id == tenant_id)).all())
    for kind, code, name in (("cash", "1000", "Cash in hand"), ("bank", "1010", "Main bank account")):
        if kind not in have:
            db.add(MoneyAccount(tenant_id=tenant_id, project_id=project_id, name=name, kind=kind, account_id=codes[code], is_default=True))
    db.flush()


if __name__ == "__main__":
    from .db import SessionLocal, init_db

    if len(sys.argv) != 4:
        sys.exit(__doc__)
    init_db()
    with SessionLocal() as session:
        t = seed_tenant(session, sys.argv[1], sys.argv[2], sys.argv[3])
        print(f"Created account '{t.name}'. Log in with phone {sys.argv[2]} and add your first project.")
