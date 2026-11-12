"""The bookkeeper agent, as a LangGraph graph:

    parse  ->  classify  ->  check

parse     plain code: split the input, find amounts, dates, direction, payment mode
classify  language model (Groq) or keyword rules: who was paid, which category, which unit
check     plain code: throw away anything not on the allowed lists, look for duplicates,
          cap the confidence when something is unclear

The graph only produces suggestions. Writing to the ledger happens later, in the
posting engine, after a person approves.
"""

import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Document
from .extractors import Extractor, Guess, RuleExtractor
from .parse import Item, parse_bank_csv, parse_notes

log = logging.getLogger("nexeaglefin.agents")


class State(TypedDict, total=False):
    source: str  # "text" or "bank_csv"
    content: str
    today: date
    categories: list[str]
    units: list[str]
    existing: list[tuple]  # (amount, date, direction) of entries already in the books
    items: list[Item]
    guesses: dict[int, Guess]
    read_by: str
    drafts: list[dict]


def build_graph(extractor: Extractor):
    def parse(state: State) -> State:
        reader = parse_bank_csv if state["source"] == "bank_csv" else parse_notes
        return {"items": reader(state["content"], state["today"])}

    def classify(state: State) -> State:
        items = state["items"]
        ask = [i for i in items if i.needs_model]
        guesses: dict[int, Guess] = {
            i.index: Guess(index=i.index, kind="income", confidence=0.8, reason="Patient payment received.")
            for i in items if not i.needs_model
        }
        read_by = extractor.name
        if ask:
            try:
                found = extractor.classify(ask, state["categories"], state["units"])
            except Exception:
                log.exception("Extractor %s failed; using keyword rules", extractor.name)
                found = RuleExtractor().classify(ask, state["categories"], state["units"])
                read_by = "rules"
            wanted = {i.index for i in ask}
            guesses.update({g.index: g for g in found if g.index in wanted})
        return {"guesses": guesses, "read_by": read_by}

    def check(state: State) -> State:
        categories = {c.lower(): c for c in state["categories"]}
        units = {u.lower(): u for u in state["units"]}
        drafts = []
        for item in state["items"]:
            g = state["guesses"].get(item.index) or Guess(index=item.index, confidence=0.2, reason="Could not be read.")
            flags = list(item.flags)
            confidence = g.confidence

            # direction comes from the parser, never from the model
            if item.direction == "out":
                doc_type = "expense"
            else:
                doc_type = "investment" if g.kind == "investment" else "collection"

            category = categories.get((g.category or "").strip().lower()) if doc_type == "expense" else None
            if doc_type == "expense" and not category:
                flags.append("no_category")
                confidence = min(confidence, 0.5)
            unit = units.get((g.unit or "").strip().lower())
            if not unit:  # a unit named in the line itself needs no model to spot
                low = item.raw.lower()
                unit = next((name for key, name in units.items() if key != "general" and key in low), None)

            if "amount_unclear" in flags:
                confidence = min(confidence, 0.2)
            if item.amount is not None and _already_recorded(item, state["existing"]):
                flags.append("possible_duplicate")
                confidence = min(confidence, 0.3)
            if "cash_deposit" in flags:
                confidence = min(confidence, 0.3)

            drafts.append({
                "raw_text": item.raw[:1000],
                "doc_type": doc_type,
                "doc_date": item.doc_date,
                "amount": item.amount,
                "payment_mode": item.mode,
                "paid": item.paid,
                "party_name": (g.party or "").strip()[:200] or None if doc_type == "expense" else None,
                "category": category,
                "unit": unit,
                "confidence": Decimal(str(round(confidence, 2))),
                "reason": (g.reason or "")[:300],
                "flags": flags,
            })
        return {"drafts": drafts}

    graph = StateGraph(State)
    graph.add_node("parse", parse)
    graph.add_node("classify", classify)
    graph.add_node("check", check)
    graph.add_edge(START, "parse")
    graph.add_edge("parse", "classify")
    graph.add_edge("classify", "check")
    graph.add_edge("check", END)
    return graph.compile()


def _already_recorded(item: Item, existing: list[tuple]) -> bool:
    window = timedelta(days=3)
    return any(
        amount == item.amount and direction == item.direction and abs(when - item.doc_date) <= window
        for amount, when, direction in existing
    )


_IN_TYPES = ("collection", "investment", "claim_settlement", "loan_received", "advance_received")
_OUT_TYPES = ("expense", "vendor_payment", "loan_payment", "advance_refund")


def existing_entries(db: Session, tenant_id: str, unit_ids: list[str], since: date) -> list[tuple]:
    """Cash movements already in the books, for the duplicate check."""
    rows = db.execute(
        select(Document.amount, Document.doc_date, Document.type, Document.paid).where(
            Document.tenant_id == tenant_id, Document.unit_id.in_(unit_ids),
            Document.status != "reversed", Document.doc_date >= since,
        )
    ).all()
    out = []
    for amount, when, type_, paid in rows:
        if type_ in _IN_TYPES:
            out.append((amount, when, "in"))
        elif type_ in _OUT_TYPES and (type_ != "expense" or paid):
            out.append((amount, when, "out"))
    return out
