"""新季現金流未公布時，現金流類因子沿用上一季（factors.quarterly_factors）。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from factors.factors import quarterly_factors


def _panel(n: int = 9) -> pd.DataFrame:
    pe = pd.date_range("2024-03-31", periods=n, freq="QE")
    return pd.DataFrame({
        "ticker": "1215", "period_end": pe,
        "revenue": 100.0, "eps": 1.0, "net_income": 10.0, "gross_profit": 30.0,
        "op_income": 15.0, "pretax_income": 12.0,
        "ocf": 20.0, "ocf_net": 20.0, "capex": -5.0, "cash": 50.0,
        "equity_parent": 200.0, "total_assets": 500.0, "total_liabilities": 300.0,
        "current_assets": 150.0, "current_liabilities": 100.0, "capital_stock": 100.0,
    })


def _no_cash(df: pd.DataFrame, pos: int) -> pd.DataFrame:
    df = df.copy()
    df.loc[df.index[pos], ["ocf", "ocf_net", "capex", "cash"]] = np.nan
    return df


def test_latest_quarter_without_cash_carries_previous():
    out = quarterly_factors(_no_cash(_panel(), -1))
    full = quarterly_factors(_panel())
    last, base = out.iloc[-1], full.iloc[-2]
    assert bool(last["cash_carried"])
    for c in ("ttm_ocf", "ttm_capex", "ttm_fcf", "cash", "f_ocf", "f_accrual"):
        assert last[c] == base[c], c
    assert last["ttm_revenue"] == 400.0


def test_f_score_not_scaled_when_carried():
    out = quarterly_factors(_no_cash(_panel(), -1))
    assert out.iloc[-1]["f_score_partial"] == quarterly_factors(_panel()).iloc[-1]["f_score_partial"]


def test_full_quarter_not_carried():
    assert not quarterly_factors(_panel())["cash_carried"].any()


def test_historical_gap_stays_nan():
    out = quarterly_factors(_no_cash(_panel(), 6))
    assert not out["cash_carried"].any()
    assert np.isnan(out.iloc[6]["ttm_ocf"])
    assert np.isnan(out.iloc[6]["cash"])


def test_previous_quarter_also_missing_not_carried():
    out = quarterly_factors(_no_cash(_no_cash(_panel(), -1), -2))
    assert not out.iloc[-1]["cash_carried"]
    assert np.isnan(out.iloc[-1]["ttm_ocf"])


def test_nonadjacent_previous_quarter_not_carried():
    df = _no_cash(_panel().drop(index=7), -1)
    out = quarterly_factors(df)
    assert not out.iloc[-1]["cash_carried"]
    assert np.isnan(out.iloc[-1]["ttm_ocf"])
