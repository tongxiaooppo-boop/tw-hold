"""screen 股數／市值改用淨股本（股本−預收股本）。"""
import numpy as np
import pandas as pd
import pytest

from screener import screen as sc

ASOF = pd.Timestamp("2026-11-02")


def test_market_cap_fallback_uses_capital_net():
    d = pd.DataFrame({"capital_stock": [1000.0, 1000.0, 1000.0],
                      "capital_net": [400.0, np.nan, 400.0]}, index=["a", "b", "c"])
    close = pd.Series([10.0, 10.0, 10.0], index=d.index)
    mc = sc._market_cap(sc._cap_basis(d), close)
    assert mc["a"] == pytest.approx(10.0 * 400.0 / 10.0)
    assert np.isnan(mc["b"])                       # NaN 不退回 capital_stock
    # 沒有 capital_net 欄 → 用 capital_stock
    assert sc._cap_basis(d[["capital_stock"]]).iloc[0] == 1000.0


def test_screen_deposit_market_cap_uses_capital_net():
    q = pd.DataFrame({"ticker": ["2330"], "period_end": [pd.Timestamp("2026-06-30")],
                      "disclosure_date": [pd.Timestamp("2026-07-01")],
                      "capital_stock": [1000.0], "capital_net": [400.0],
                      "eps": [1.0], "ttm_fcf": [100.0],
                      "gross_margin": [30.0], "rev_yoy": [0.1],
                      "total_assets": [5000.0], "equity_parent": [2000.0], "debt_ratio": [0.3],
                      "roe": [0.1]})
    divf = pd.DataFrame({"ticker": ["2330"], "last_cash_dividend": [1.0], "div_years": [10], "div_cut_5y": [False],
                         "earnings_div_ratio": [1.0], "payout_ratio_ttm": [0.5]})
    prices = pd.DataFrame({"ticker": ["2330"], "close": [10.0]})
    out = sc.screen_deposit(q, divf, prices=prices, asof=ASOF)
    assert out["market_cap"].iloc[0] == pytest.approx(400.0)
