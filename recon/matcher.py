"""Bank reconciliation in passes, from strict to fuzzy.

Pass 1  exact      same amount, same date, and the ledger document appears in the bank text
Pass 2  window     same amount, dates within N days, exactly one candidate
Pass 3  judged     several candidates (or a description-only hint): an LLM, or the
                   similarity rule in demo mode, picks one or says "none"
Everything left is reported as unmatched, with the closest candidate as a hint.
Amounts must always match exactly: the judge never matches different amounts.
"""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable, Dict, List, Optional


@dataclass
class BankLine:
    id: str
    date: date
    description: str
    amount: Decimal


@dataclass
class LedgerEntry:
    id: str
    date: date
    description: str
    document: str
    amount: Decimal


@dataclass
class Match:
    bank_id: str
    ledger_id: str
    method: str          # exact | window | judged
    confidence: float
    note: str = ""


@dataclass
class Reconciliation:
    matches: List[Match] = field(default_factory=list)
    unmatched_bank: List[BankLine] = field(default_factory=list)
    unmatched_ledger: List[LedgerEntry] = field(default_factory=list)


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]+", " ", text)


def similarity(a: str, b: str) -> float:
    """Token-overlap and sequence similarity, so word order and noise matter less."""
    ta, tb = set(_norm(a).split()), set(_norm(b).split())
    overlap = len(ta & tb) / max(1, min(len(ta), len(tb)))
    return round(max(overlap, SequenceMatcher(None, _norm(a), _norm(b)).ratio()), 3)


def load_bank(path: Path) -> List[BankLine]:
    with path.open(encoding="utf-8") as f:
        return [BankLine(r["bank_id"], date.fromisoformat(r["date"]), r["description"], Decimal(r["amount"]))
                for r in csv.DictReader(f)]


def load_ledger(path: Path) -> List[LedgerEntry]:
    with path.open(encoding="utf-8") as f:
        return [LedgerEntry(r["entry_id"], date.fromisoformat(r["date"]), r["description"], r["document"],
                            Decimal(r["amount"])) for r in csv.DictReader(f)]


Judge = Callable[[BankLine, List[LedgerEntry]], Optional[str]]


def similarity_judge(bank: BankLine, candidates: List[LedgerEntry], threshold: float = 0.34) -> Optional[str]:
    """Demo-mode judge: best description similarity, if it is clearly better than the rest."""
    scored = sorted(((similarity(bank.description, c.description + " " + c.document), c) for c in candidates),
                    key=lambda x: (-x[0], abs((x[1].date - bank.date).days)))
    if not scored or scored[0][0] < threshold:
        return None
    if len(scored) > 1 and scored[0][0] == scored[1][0] and \
            abs((scored[0][1].date - bank.date).days) == abs((scored[1][1].date - bank.date).days):
        return None   # a genuine tie: leave it for a person
    return scored[0][1].id


def llm_judge(client) -> Judge:
    """Judge backed by an LLM client exposing complete(system, prompt) -> str."""
    system = ("You reconcile a bank statement line against candidate ledger entries of the SAME amount. "
              "Choose the entry that is the same transaction, using descriptions, documents and dates. "
              "Reply ONLY with JSON: {\"ledger_id\": \"<id>\" or null, \"reason\": \"...\"}. "
              "Return null if you are not sure.")

    def judge(bank: BankLine, candidates: List[LedgerEntry]) -> Optional[str]:
        payload = {
            "bank_line": {"date": str(bank.date), "description": bank.description, "amount": str(bank.amount)},
            "candidates": [{"ledger_id": c.id, "date": str(c.date), "description": c.description,
                            "document": c.document} for c in candidates],
        }
        raw = client.complete(system, json.dumps(payload))
        try:
            choice = json.loads(raw[raw.find("{"): raw.rfind("}") + 1]).get("ledger_id")
        except (ValueError, AttributeError):
            return None
        return choice if choice in {c.id for c in candidates} else None

    return judge


def reconcile(bank: List[BankLine], ledger: List[LedgerEntry], judge: Judge = similarity_judge,
              window_days: int = 3) -> Reconciliation:
    result = Reconciliation()
    open_bank: Dict[str, BankLine] = {b.id: b for b in bank}
    open_ledger: Dict[str, LedgerEntry] = {l.id: l for l in ledger}

    def take(b: BankLine, l: LedgerEntry, method: str, conf: float, note: str = "") -> None:
        result.matches.append(Match(b.id, l.id, method, conf, note))
        open_bank.pop(b.id)
        open_ledger.pop(l.id)

    # Pass 1: exact (amount + date + document reference)
    for b in list(open_bank.values()):
        for l in list(open_ledger.values()):
            if l.amount == b.amount and l.date == b.date and l.document and \
                    _norm(l.document).replace(" ", "") in _norm(b.description).replace(" ", ""):
                take(b, l, "exact", 1.0, f"document {l.document}")
                break

    def candidates(b: BankLine) -> List[LedgerEntry]:
        return [l for l in open_ledger.values()
                if l.amount == b.amount and abs((l.date - b.date).days) <= window_days]

    # Pass 2: unique candidate within the date window
    for b in list(open_bank.values()):
        cands = candidates(b)
        if len(cands) == 1 and len([x for x in open_bank.values() if x.amount == b.amount
                                    and abs((x.date - cands[0].date).days) <= window_days]) == 1:
            days = abs((cands[0].date - b.date).days)
            take(b, cands[0], "window", round(0.95 - 0.05 * days, 2), f"{days} day(s) apart")

    # Pass 3: several candidates -> judge
    for b in sorted(open_bank.values(), key=lambda x: x.date):
        cands = candidates(b)
        if not cands:
            continue
        chosen = judge(b, cands)
        if chosen:
            l = open_ledger[chosen]
            take(b, l, "judged", 0.8, f"chosen among {len(cands)} candidate(s)")

    result.unmatched_bank = sorted(open_bank.values(), key=lambda x: x.date)
    result.unmatched_ledger = sorted(open_ledger.values(), key=lambda x: x.date)
    return result
