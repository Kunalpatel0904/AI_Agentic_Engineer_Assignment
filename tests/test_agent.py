import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from adjustment_agent import AdjustmentAgent  # noqa: E402
from data_loader import load_inputs  # noqa: E402
from main import run  # noqa: E402


@pytest.fixture
def agent():
    inp = load_inputs(ROOT / "inputs")
    return AdjustmentAgent(inp["coa"], inp["fx"], "2024-Q4", "USD")


def je(id="T1", lines=None, **over):
    e = {"id": id, "description": "test", "date": "2024-12-31", "source": "unit test",
         "lines": lines or [{"account": "6100", "debit": 100.0, "credit": 0.0},
                            {"account": "2120", "debit": 0.0, "credit": 100.0}]}
    e.update(over)
    return e


def decide(agent, e):
    return agent.process_entry(e, 0)["decision"]


def test_valid_balanced_entry_accepted(agent):
    assert decide(agent, je()) == "ACCEPT"


def test_unbalanced_rejected(agent):
    e = je(lines=[{"account": "6100", "debit": 100, "credit": 0}, {"account": "2120", "debit": 0, "credit": 90}])
    r = agent.process_entry(e, 0)
    assert r["decision"] == "REJECT" and "do not equal" in r["explanation"]


def test_invalid_account_rejected(agent):
    e = je(lines=[{"account": "6315", "debit": 5, "credit": 0}, {"account": "2120", "debit": 0, "credit": 5}])
    assert decide(agent, e) == "REJECT"


def test_header_account_rejected(agent):
    e = je(lines=[{"account": "6000", "debit": 5, "credit": 0}, {"account": "2120", "debit": 0, "credit": 5}])
    assert decide(agent, e) == "REJECT"


def test_missing_required_field_quarantined(agent):
    e = je()
    del e["source"]
    assert decide(agent, e) == "QUARANTINE"


def test_duplicate_id_rejected_and_same_content_quarantined(agent):
    assert decide(agent, je("A")) == "ACCEPT"
    assert decide(agent, je("A")) == "REJECT"
    assert decide(agent, je("B")) == "QUARANTINE"


@pytest.mark.parametrize("bad", ["abc", -5, None, float("nan"), True])
def test_invalid_amount_rejected(agent, bad):
    e = je(lines=[{"account": "6100", "debit": bad, "credit": 0}, {"account": "2120", "debit": 0, "credit": 100}])
    assert decide(agent, e) == "REJECT"


def test_missing_fx_rate_quarantined(agent):
    # GBP has no period_end rate in fx_rates.csv
    e = je(lines=[{"account": "6100", "debit": 5, "credit": 0, "currency": "GBP"},
                  {"account": "2120", "debit": 0, "credit": 5}])
    r = agent.process_entry(e, 0)
    assert r["decision"] == "QUARANTINE" and "GBP" in r["explanation"]


def test_fx_account_entry_quarantined(agent):
    e = je(lines=[{"account": "1110", "debit": 10, "credit": 0}, {"account": "7310", "debit": 0, "credit": 10}])
    assert decide(agent, e) == "QUARANTINE"


def test_tbd_cashflow_account_quarantined(agent):
    e = je(lines=[{"account": "1150", "debit": 10, "credit": 0}, {"account": "2120", "debit": 0, "credit": 10}])
    assert decide(agent, e) == "QUARANTINE"


def test_circular_entry_rejected(agent):
    e = je(lines=[{"account": "2110", "debit": 10, "credit": 0}, {"account": "2110", "debit": 0, "credit": 10}])
    assert decide(agent, e) == "REJECT"


def test_out_of_period_rejected_and_bad_date_quarantined(agent):
    assert decide(agent, je("P1", date="2025-01-02")) == "REJECT"
    assert decide(agent, je("P2", date="31/12/2024")) == "QUARANTINE"


@pytest.mark.parametrize("bad", [None, "text", 42, {}, {"id": "X", "lines": []}, {"id": "Y", "lines": "no"},
                                 {"id": "Z", "lines": [1, 2]}])
def test_malformed_input_never_crashes(agent, bad):
    assert decide(agent, bad) in ("REJECT", "QUARANTINE")


def test_reject_beats_quarantine(agent):
    e = je(lines=[{"account": "1150", "debit": 10, "credit": 0}, {"account": "2120", "debit": 0, "credit": 9}])
    assert decide(agent, e) == "REJECT"


def test_end_to_end_outputs(tmp_path):
    results, summary = run(ROOT / "inputs", tmp_path)
    assert sum(summary.values()) == len(results) == 10
    for f in ("validation_results.csv", "decisions.json", "audit_log.json", "data_quality_report.json"):
        assert (tmp_path / f).exists()
    assert set(pd.read_csv(tmp_path / "validation_results.csv").entry_id) == {r["entry_id"] for r in results}
