"""Load the original input files (read-only) and report data-quality issues found in them."""
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd


def load_inputs(inputs_dir):
    d = Path(inputs_dir)
    coa = pd.read_csv(d / "chart_of_accounts.csv", dtype={"account_code": str, "parent_code": str}).fillna("")
    fx = pd.read_csv(d / "fx_rates.csv")
    tb = pd.read_csv(d / "trial_balance.csv", dtype={"account_code": str})
    prior = pd.read_csv(d / "prior_period_tb.csv", dtype={"account_code": str})
    with open(d / "manual_adjustments.json", encoding="utf-8") as f:
        adj = json.load(f)
    if not isinstance(adj, dict) or not isinstance(adj.get("entries"), list):
        raise ValueError("manual_adjustments.json must be an object with an 'entries' list")
    return {"coa": coa, "fx": fx, "tb": tb, "prior": prior, "adjustments": adj}


def data_quality_report(inp):
    """Facts about the inputs (not entry decisions). Everything is computed, nothing hardcoded."""
    coa, fx, tb, prior = inp["coa"], inp["fx"], inp["tb"], inp["prior"]
    rep = {}
    codes = set(coa.account_code)
    for name, df in (("trial_balance", tb), ("prior_period_tb", prior)):
        rep[f"{name}_orphan_accounts"] = sorted(set(df.account_code) - codes)
        keys = df.groupby(["account_code", "currency"]).size()
        rep[f"{name}_duplicate_account_currency_rows"] = [f"{a}/{c}" for (a, c), n in keys.items() if n > 1]
        rep[f"{name}_raw_debit_minus_credit"] = round(float(df.debit.sum() - df.credit.sum()), 2)
    rate = {(r.currency, r.rate_type): r.rate for r in fx.itertuples()}
    rep["currencies_missing_period_end_rate"] = sorted(
        {c for c in set(inp["tb"].currency) | set(inp["prior"].currency) if (c, "period_end") not in rate})
    rep["coa_ambiguous_cash_flow_category"] = coa[coa.cf_category == "TBD"].account_code.tolist()
    parents = set(coa.parent_code)
    rep["coa_header_nodes_without_children"] = coa[(coa.account_type == "Header")
                                                  & ~coa.account_code.isin(parents)].account_code.tolist()
    return rep


def to_decimal(v):
    """Strict amount parse: only int/float/numeric str; bool, None, NaN, inf rejected (ValueError)."""
    if isinstance(v, bool) or v is None:
        raise ValueError(f"not a number: {v!r}")
    try:
        d = Decimal(str(v).strip())
    except InvalidOperation:
        raise ValueError(f"not a number: {v!r}")
    if not d.is_finite():
        raise ValueError(f"not finite: {v!r}")
    return d
