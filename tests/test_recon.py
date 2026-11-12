from pathlib import Path

from recon.matcher import llm_judge, load_bank, load_ledger, reconcile, similarity

S = Path(__file__).parents[1] / "samples"
BANK, LEDGER = load_bank(S / "bank_statement.csv"), load_ledger(S / "ledger.csv")
RES = reconcile(BANK, LEDGER)
PAIRS = {m.bank_id: (m.ledger_id, m.method) for m in RES.matches}


def test_exact_match_uses_document_reference():
    assert PAIRS["B01"] == ("L01", "exact")


def test_date_window_match():
    assert PAIRS["B02"][0] == "L02"           # booked two days before it cleared
    assert PAIRS["B02"][1] == "window"


def test_duplicate_amounts_are_not_crossed():
    # two PIX of 4,200.00 on the same day vs. two invoices one day apart
    assert {PAIRS["B07"][0], PAIRS["B08"][0]} == {"L07", "L08"}


def test_different_amounts_never_match():
    assert "B11" not in PAIRS                 # bank 12,000 vs ledger 12,500
    assert any(l.id == "L11" for l in RES.unmatched_ledger)


def test_items_only_on_one_side_are_exceptions():
    bank_open = {b.id for b in RES.unmatched_bank}
    assert {"B13", "B15"} <= bank_open        # interest income and an unexpected receipt
    assert "L14" in {l.id for l in RES.unmatched_ledger}


def test_every_line_is_accounted_for():
    assert len(RES.matches) + len(RES.unmatched_bank) == len(BANK)
    assert len(RES.matches) + len(RES.unmatched_ledger) == len(LEDGER)


def test_similarity_ignores_case_and_accents():
    assert similarity("PIX RECEBIDO GAMA IND", "Receipt - Gama Indústria") > 0.3


class FakeLLM:
    def __init__(self, reply):
        self.reply = reply

    def complete(self, system, prompt):
        return self.reply


def test_llm_judge_rejects_ids_outside_candidates():
    judge = llm_judge(FakeLLM('{"ledger_id": "L99", "reason": "made up"}'))
    assert judge(BANK[0], [LEDGER[0]]) is None


def test_llm_judge_accepts_valid_choice():
    judge = llm_judge(FakeLLM('Sure: {"ledger_id": "L01", "reason": "same NF"}'))
    assert judge(BANK[0], [LEDGER[0]]) == "L01"
