"""價值/定存因子庫（`factors/` + `screener/`）——用合成資料測 F-Score、TTM、
normalized EPS、剔除門檻、排序。不碰上游 bundle（那是真資料、會變）。

M0.3 從 `tw-swing/tests/test_value.py` 搬走；只改 import 路徑。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from factors import factors
from screener import screen


def _synth_quarterly(ticker: str, n_years: int = 8, eps=2.0, growing=True,
                     margin=0.30) -> pd.DataFrame:
    """n_years × 4 季，數字乾淨、逐年小成長。"""
    rows = []
    start = pd.Timestamp("2016-03-31")
    for i in range(n_years * 4):
        pe = start + pd.DateOffset(months=3 * i)
        k = 1 + (0.05 * (i // 4) if growing else 0)
        rev = 1000.0 * k
        rows.append(dict(
            ticker=ticker, period_end=pe,
            revenue=rev, eps=eps * k, net_income=200.0 * k,
            gross_profit=rev * margin, op_income=rev * 0.20,
            pretax_income=rev * 0.18,
            total_assets=5000.0, equity_parent=3000.0 * k,
            total_liabilities=2000.0, current_assets=2500.0,
            current_liabilities=1000.0,
            ocf=250.0 * k, ocf_net=250.0 * k, capex=80.0,
            capital_stock=1000.0,
        ))
    return pd.DataFrame(rows)


def _panel(*frames) -> pd.DataFrame:
    q = pd.concat(frames, ignore_index=True)
    q["disclosure_date"] = q["period_end"] + pd.Timedelta(days=45)
    return q


def test_ttm_是滾動四季加總():
    q = _panel(_synth_quarterly("1111", growing=False))
    qf = factors.quarterly_factors(q)
    row = qf[qf["period_end"] == "2017-12-31"].iloc[0]
    assert abs(row["ttm_revenue"] - 4000.0) < 1e-6
    assert abs(row["ttm_eps"] - 8.0) < 1e-6
    # 前 3 季 TTM 不足 → NaN
    assert np.isnan(qf.iloc[0]["ttm_revenue"])


def test_健康成長公司_fscore高():
    q = _panel(_synth_quarterly("2222", growing=True))
    qf = factors.quarterly_factors(q)
    latest = qf.sort_values("period_end").groupby("ticker").tail(1).iloc[0]
    assert latest["f_score"] >= 6      # 成長 + 正現金流 + 無增資


def test_normalized_eps_攤平循環():
    # 循環股：EPS 在 2/8 之間跳
    rows = []
    start = pd.Timestamp("2016-03-31")
    for i in range(8 * 4):
        pe = start + pd.DateOffset(months=3 * i)
        cyc = 8.0 if (i // 4) % 2 == 0 else 2.0
        rows.append(dict(ticker="3333", period_end=pe, revenue=1000, eps=cyc / 4,
                         net_income=100, gross_profit=300, op_income=200,
                         pretax_income=180, total_assets=5000, equity_parent=3000,
                         total_liabilities=2000, current_assets=2500,
                         current_liabilities=1000, ocf=250, ocf_net=250, capex=80,
                         capital_stock=1000))
    qf = factors.quarterly_factors(_panel(pd.DataFrame(rows)))
    latest = qf.sort_values("period_end").groupby("ticker").tail(1).iloc[0]
    # normalized ≈ (8+2+8+2+8)/5 平均 ≈ 5.6，介於高低之間
    assert 3.0 < latest["normalized_eps"] < 7.0


def test_價值篩選_fscore低的被剔除():
    good = _synth_quarterly("GOOD", growing=True)
    # BAD：獲利衰退、毛利下滑、現金流轉負
    bad = _synth_quarterly("BAD", growing=False)
    bad["eps"] = np.linspace(3.0, 0.2, len(bad))
    bad["ocf"] = np.linspace(300, -50, len(bad))
    bad["ocf_net"] = bad["ocf"]
    bad["gross_profit"] = np.linspace(400, 100, len(bad))
    qf = factors.quarterly_factors(_panel(good, bad))
    res = screen.screen_value(qf, asof=pd.Timestamp("2024-06-30"))
    r = res.set_index("ticker")
    assert r.loc["BAD", "passes"] == False
    assert r.loc["BAD", "reject_reason"] is not None


def test_定存篩選_門檻與排序():
    q = _panel(_synth_quarterly("DEP1", growing=True),
               _synth_quarterly("DEP2", growing=True))
    qf = factors.quarterly_factors(q)
    div = pd.DataFrame([
        # DEP1：連續 8 年配息、無減配
        *[dict(ticker="DEP1", year=y, cash_earnings=3.0, cash_surplus=0.0,
               stock_earnings=0.0, pay_date=pd.Timestamp(f"{y}-07-01"),
               announce_date=pd.NaT, ex_date=pd.NaT, cash_dividend=3.0)
          for y in range(2017, 2025)],
        # DEP2：只配 2 年
        *[dict(ticker="DEP2", year=y, cash_earnings=1.0, cash_surplus=0.0,
               stock_earnings=0.0, pay_date=pd.Timestamp(f"{y}-07-01"),
               announce_date=pd.NaT, ex_date=pd.NaT, cash_dividend=1.0)
          for y in range(2023, 2025)],
    ])
    divf = factors.dividend_factors(div, factors.annual_eps(qf))
    res = screen.screen_deposit(qf, divf, asof=pd.Timestamp("2024-06-30"))
    r = res.set_index("ticker")
    assert r.loc["DEP1", "div_years"] == 8
    assert r.loc["DEP2", "reject_reason"] == "連續配息 < 5 年"


def test_剔除理由取第一個成立的():
    idx = pd.Index(["a", "b", "c"])
    reasons = {
        "R1": pd.Series([True, False, False], index=idx),
        "R2": pd.Series([True, True, False], index=idx),
    }
    out = screen._first_reason(reasons, idx)
    assert out["a"] == "R1" and out["b"] == "R2" and pd.isna(out["c"])
