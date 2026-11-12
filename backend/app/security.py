import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .db import get_db
from .models import Unit, User, UserUnit

ALL_UNIT_ROLES = ("owner", "accountant", "auditor")
WRITE_ROLES = ("owner", "accountant", "unit_incharge", "cashier")


def hash_pin(pin: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), 200_000).hex()
    return f"{salt}${digest}"


def verify_pin(pin: str, stored: str) -> bool:
    salt, digest = stored.split("$")
    check = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), 200_000).hex()
    return hmac.compare_digest(check, digest)


def clean_phone(typed: str) -> str:
    """One stored form for a phone number however it is typed: digits only, no +91 or leading 0."""
    digits = "".join(ch for ch in typed if ch.isdigit())
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return digits


def make_token(user: User) -> str:
    payload = {
        "sub": user.id,
        "tid": user.tenant_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=config.TOKEN_HOURS),
    }
    return jwt.encode(payload, config.SECRET_KEY, algorithm="HS256")


bearer = HTTPBearer(auto_error=False)


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)
) -> User:
    if not creds:
        raise HTTPException(401, "Please log in")
    try:
        payload = jwt.decode(creds.credentials, config.SECRET_KEY, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Session expired, please log in again")
    user = db.get(User, payload["sub"])
    if not user or not user.active or user.tenant_id != payload["tid"]:
        raise HTTPException(401, "Please log in")
    return user


def allowed_unit_ids(db: Session, user: User) -> list[str]:
    """Units this user may see. Always limited to the user's own tenant."""
    if user.role in ALL_UNIT_ROLES:
        return list(db.scalars(select(Unit.id).where(Unit.tenant_id == user.tenant_id)))
    return list(
        db.scalars(
            select(Unit.id)
            .join(UserUnit, UserUnit.unit_id == Unit.id)
            .where(UserUnit.user_id == user.id, Unit.tenant_id == user.tenant_id)
        )
    )


def require_unit(db: Session, user: User, unit_id: str) -> None:
    if unit_id not in allowed_unit_ids(db, user):
        raise HTTPException(404, "Unit not found")


def require_write(user: User) -> None:
    if user.role not in WRITE_ROLES:
        raise HTTPException(403, "Your role is read-only")
