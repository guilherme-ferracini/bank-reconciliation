# Bank Reconciliation

[![tests](https://github.com/guilherme-ferracini/bank-reconciliation/actions/workflows/tests.yml/badge.svg)](https://github.com/guilherme-ferracini/bank-reconciliation/actions)

Matches a **bank statement** against the **accounting ledger** in passes, from strict to fuzzy, and sends only the genuinely ambiguous cases to an LLM (Claude or OpenAI). Whatever cannot be matched with confidence becomes a short **exception list** for a person to review.

## Why this exists

Bank reconciliation is one of the most repetitive tasks in an accounting firm, and one where a wrong automatic match is worse than no match. The design follows that:

- **Rules first, AI last.** Most lines match by amount, date and document number. The LLM only sees the few lines where several entries are plausible, which keeps cost low and behaviour predictable.
- **Amounts are sacred.** Nothing is ever matched across different amounts, not even by the AI. A R$ 12,000 receipt against a R$ 12,500 invoice is an exception (a discount? a partial payment?), not a match.
- **The model cannot invent.** The LLM's answer is accepted only if it picks one of the candidates it was given. Anything else is discarded.
- **Every line is accounted for.** Each line is matched (with method and confidence) or listed as an exception, and the tests check that.

## Passes

| Pass | Rule | Confidence |
|---|---|---|
| exact | same amount, same date, ledger document (e.g. `NF 4512`) found in the bank text | 1.00 |
| window | same amount, dates within N days (default 3), exactly one candidate | 0.95 − 0.05 per day |
| judged | several same-amount candidates → LLM (or similarity rule in demo mode) picks one or none | 0.80 |
| exception | anything left, with a "possible match with a different amount" hint when the descriptions are close | — |

## Quickstart

```bash
pip install -r requirements.txt

# Demo mode: the judge is a description-similarity rule, no API key needed
python -m recon samples/bank_statement.csv samples/ledger.csv --out out/

# LLM judge for ambiguous lines
export LLM_PROVIDER=anthropic ANTHROPIC_API_KEY=...      # or openai
python -m recon samples/bank_statement.csv samples/ledger.csv
```

Result on the fictional sample ([full report](samples/sample_output/report.txt)): **12 of 15 bank lines matched**, including two identical R$ 4,200.00 PIX receipts on the same day, matched to the right invoices. The exceptions list looks like this:

```
BANK   B11 PIX RECEBIDO DELTA ENGENHARIA  R$ 12000.00 | possible match with different amount: L11 R$ 12500.00
BANK   B13 RENDIMENTO APLICACAO AUTOMATICA R$ 312.18     (interest not yet booked)
BANK   B15 PIX RECEBIDO EPSILON LTDA       R$ 3150.00    (receipt with no invoice)
LEDGER L14 Receipt - Zeta Comercio         R$ 2980.00    (invoice not yet paid)
```

## Input format

```
bank_statement.csv: bank_id, date, description, amount
ledger.csv:         entry_id, date, description, document, amount
```

Most banks export CSV or OFX; an OFX loader maps to the same `BankLine` model.

## Tests

```bash
python -m pytest -q
```

## License

MIT
