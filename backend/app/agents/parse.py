"""Deterministic reading of notes and bank statements.

Everything numeric (amounts, dates, direction of money) is worked out here by
plain code. The language model never sees a job that involves arithmetic and
never gets to choose an amount.
"""

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

MAX_ITEMS = 200

_DATE_PATTERNS = [
    (re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b"), "ymd"),
    (re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b"), "dmy"),
    (re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2})\b"), "dmy2"),
]
_AMOUNT = re.compile(
    r"(?P<cur>₹|\brs\.?|\binr)?\s*(?P<num>\d[\d,]*(?:\.\d{1,2})?)\s*(?P<unit>k\b|lakhs?\b|lacs?\b|crores?\b|cr\b)?",
    re.IGNORECASE,
)
_MULTIPLIER = {"k": 1_000, "lakh": 100_000, "lakhs": 100_000, "lac": 100_000, "lacs": 100_000,
               "crore": 10_000_000, "crores": 10_000_000, "cr": 10_000_000}
_MODES = [
    ("upi", re.compile(r"\b(upi|gpay|google pay|phonepe|paytm|bhim)\b", re.I)),
    ("card", re.compile(r"\b(card|pos|swipe)\b", re.I)),
    ("bank", re.compile(r"\b(neft|rtgs|imps|cheque|chq|bank transfer|transfer|net ?banking)\b", re.I)),
    ("cash", re.compile(r"\bcash\b", re.I)),
]
_INFLOW = re.compile(r"\b(received|receive|collection|collected|deposit(ed)?|income|got)\b", re.I)
_UNPAID = re.compile(r"\b(unpaid|to pay|pay later|on credit|credit bill|udhaar|udhar|not paid)\b", re.I)
# phone, account and card numbers: 9 digits or more. Amounts typed without commas (162000, 2500000) are shorter.
_LONG_NUMBER = re.compile(r"\d{9,}")
_EMAIL = re.compile(r"\S+@\S+")


@dataclass
class Item:
    index: int
    raw: str
    doc_date: date
    amount: Decimal | None
    direction: str  # "in" or "out"
    mode: str | None
    paid: bool = True
    flags: list[str] = field(default_factory=list)

    @property
    def safe_text(self) -> str:
        """What a language model is allowed to see: no account, phone or card numbers, no emails."""
        return _EMAIL.sub("[email]", _LONG_NUMBER.sub("[number]", self.raw))[:300]

    @property
    def needs_model(self) -> bool:
        # Money received by UPI, cash or card is a patient paying. The narration holds a
        # person's name and adds nothing, so it is never sent to a model.
        return not (self.direction == "in" and self.mode in ("upi", "cash", "card"))


def _money(text: str) -> Decimal | None:
    try:
        value = Decimal(text.replace(",", "").strip())
    except InvalidOperation:
        return None
    return value.quantize(Decimal("0.01")) if value > 0 else None


def find_date(text: str, today: date) -> tuple[date | None, str]:
    """Returns the date found (if any) and the text with that date removed."""
    for pattern, kind in _DATE_PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        a, b, c = (int(x) for x in m.groups())
        try:
            found = date(a, b, c) if kind == "ymd" else date(c + (2000 if kind == "dmy2" else 0), b, a)
        except ValueError:
            continue
        return found, text[: m.start()] + " " + text[m.end():]
    low = text.lower()
    if "yesterday" in low or "kal " in low + " ":
        return today - timedelta(days=1), text
    return None, text


def find_amount(text: str) -> tuple[Decimal | None, bool]:
    """Returns (amount, clear). Not clear when there is no number or several candidates."""
    found = []
    for m in _AMOUNT.finditer(_LONG_NUMBER.sub(" ", text)):
        value = _money(m.group("num"))
        if value is None:
            continue
        unit = (m.group("unit") or "").lower()
        if unit:
            value = (value * _MULTIPLIER[unit]).quantize(Decimal("0.01"))
        found.append((value, bool(m.group("cur") or unit)))
    if not found:
        return None, False
    marked = [v for v, has_marker in found if has_marker]
    if len(found) == 1:
        return found[0][0], True
    if len(marked) == 1:
        return marked[0], True
    return None, False


def find_mode(text: str) -> str | None:
    for mode, pattern in _MODES:
        if pattern.search(text):
            return mode
    return None


def parse_notes(text: str, today: date) -> list[Item]:
    """One entry per non-empty line, as someone would type or forward on WhatsApp."""
    items = []
    for line in text.splitlines():
        line = line.strip(" \t-•*")
        if len(line) < 3:
            continue
        found_date, rest = find_date(line, today)
        amount, clear = find_amount(rest)
        direction = "in" if _INFLOW.search(line) else "out"
        paid = not (direction == "out" and _UNPAID.search(line))
        mode = find_mode(line) if paid else None
        item = Item(len(items), line, found_date or today, amount, direction, mode, paid)
        if not clear:
            item.flags.append("amount_unclear")
        if paid and not mode:
            item.flags.append("mode_unclear")
        if item.doc_date > today:
            item.doc_date = today
            item.flags.append("date_unclear")
        items.append(item)
        if len(items) >= MAX_ITEMS:
            break
    return items


_BANK_DATE_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y", "%d-%m-%y", "%d-%b-%Y", "%d %b %Y", "%d-%b-%y")


def _bank_date(text: str) -> date | None:
    text = text.strip()
    for fmt in _BANK_DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def _column(header: list[str], *names: str) -> int | None:
    for i, h in enumerate(header):
        if any(n in h for n in names):
            return i
    return None


class StatementError(ValueError):
    pass


def parse_bank_csv(text: str, today: date) -> list[Item]:
    """Reads a bank statement saved as CSV. Finds the columns by their headings."""
    rows = [r for r in csv.reader(io.StringIO(text)) if any(c.strip() for c in r)]
    start = cols = None
    for n, row in enumerate(rows[:30]):
        header = [c.strip().lower() for c in row]
        d = _column(header, "date")
        text_col = _column(header, "narration", "description", "particular", "remark", "detail")
        debit = _column(header, "debit", "withdraw", "dr amount", "paid out")
        credit = _column(header, "credit", "deposit", "cr amount", "paid in")
        if d is not None and text_col is not None and debit is not None and credit is not None:
            start, cols = n + 1, (d, text_col, debit, credit)
            break
    if cols is None:
        raise StatementError(
            "Could not find the columns. The statement needs headings for date, narration, debit (withdrawal) "
            "and credit (deposit)."
        )
    d, text_col, debit, credit = cols
    items = []
    for row in rows[start:]:
        if max(cols) >= len(row):
            continue
        when = _bank_date(row[d])
        out, into = _money(row[debit]), _money(row[credit])
        if when is None or (out is None) == (into is None):
            continue  # totals rows, opening balance, or a line with both sides filled
        narration = " ".join(row[text_col].split())
        mode = find_mode(narration)
        item = Item(len(items), narration, min(when, today), out or into, "out" if out else "in",
                    "upi" if mode == "upi" else "bank")
        if mode == "cash" and item.direction == "in":
            item.flags.append("cash_deposit")  # cash already counted as collected; this only moved it to the bank
        items.append(item)
        if len(items) >= MAX_ITEMS:
            break
    if not items:
        raise StatementError("No transactions found in this statement.")
    return items
