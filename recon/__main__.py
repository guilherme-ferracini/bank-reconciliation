"""python -m recon samples/bank_statement.csv samples/ledger.csv [--provider mock|anthropic|openai] [--out out/]"""

from __future__ import annotations

import argparse
import csv
from decimal import Decimal
from pathlib import Path

from .llm import LLMClient
from .matcher import llm_judge, load_bank, load_ledger, reconcile, similarity, similarity_judge


def main() -> None:
    p = argparse.ArgumentParser(description="Bank statement vs. ledger reconciliation")
    p.add_argument("bank", type=Path)
    p.add_argument("ledger", type=Path)
    p.add_argument("--provider", default=None, help="mock (default, similarity rule), anthropic or openai")
    p.add_argument("--model", default=None)
    p.add_argument("--window", type=int, default=3, help="max days between bank and ledger dates")
    p.add_argument("--out", type=Path, default=None, help="folder for matches.csv and exceptions.csv")
    a = p.parse_args()

    bank, ledger = load_bank(a.bank), load_ledger(a.ledger)
    client = LLMClient(a.provider, a.model, mock_fn=lambda s, p: "{}")
    judge = similarity_judge if client.provider == "mock" else llm_judge(client)
    res = reconcile(bank, ledger, judge, a.window)

    by_id = {b.id: b for b in bank}
    print(f"Matched {len(res.matches)} of {len(bank)} bank lines\n")
    for m in res.matches:
        print(f"  {m.bank_id} <-> {m.ledger_id}  {m.method:<6}  conf {m.confidence:.2f}  "
              f"R$ {by_id[m.bank_id].amount:>10}  {m.note}")
    print("\nExceptions for review")
    for b in res.unmatched_bank:
        hint = max(res.unmatched_ledger, key=lambda l: similarity(b.description, l.description), default=None)
        if hint is not None and similarity(b.description, hint.description) < 0.6:
            hint = None
        extra = f" | possible match with different amount: {hint.id} {hint.description} R$ {hint.amount}" if hint else ""
        print(f"  BANK   {b.id} {b.date} {b.description} R$ {b.amount}{extra}")
    for l in res.unmatched_ledger:
        print(f"  LEDGER {l.id} {l.date} {l.description} R$ {l.amount}")
    diff = sum((b.amount for b in res.unmatched_bank), Decimal(0)) - sum((l.amount for l in res.unmatched_ledger), Decimal(0))
    print(f"\nNet difference still open: R$ {diff}")

    if a.out:
        a.out.mkdir(parents=True, exist_ok=True)
        with (a.out / "matches.csv").open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["bank_id", "ledger_id", "method", "confidence", "note"])
            w.writerows([[m.bank_id, m.ledger_id, m.method, m.confidence, m.note] for m in res.matches])
        with (a.out / "exceptions.csv").open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["side", "id", "date", "description", "amount"])
            w.writerows([["bank", b.id, b.date, b.description, b.amount] for b in res.unmatched_bank])
            w.writerows([["ledger", l.id, l.date, l.description, l.amount] for l in res.unmatched_ledger])
        print(f"Files written to {a.out}")


if __name__ == "__main__":
    main()
