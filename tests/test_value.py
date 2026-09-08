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


def test_缺資產負債表的被剔除_不會因離群roe排前面():
    good = _synth_quarterly("GOOD", growing=True)
    # NOBAL：只有損益，資產負債表欄位全 NaN（bundle 抓取有洞時的實況，如 1103）
    nobal = _synth_quarterly("NOBAL", growing=True)
    for c in ["total_assets", "total_liabilities", "current_assets",
              "current_liabilities", "equity_parent"]:
        nobal[c] = np.nan
    qf = factors.quarterly_factors(_panel(good, nobal))
    for fn in (screen.screen_value, screen.screen_deposit):
        kw = {} if fn is screen.screen_value else {"divf": factors.dividend_factors(
            pd.DataFrame([dict(ticker="NOBAL", year=y, cash_dividend=2.0, cash_earnings=2.0)
                          for y in range(2017, 2025)]))}
        res = fn(qf, asof=pd.Timestamp("2024-06-30"), **kw) if kw else fn(qf, asof=pd.Timestamp("2024-06-30"))
        r = res.set_index("ticker")
        assert r.loc["NOBAL", "passes"] == False
        assert "財報不完整" in r.loc["NOBAL", "reject_reason"]


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


# ── 金融軌（金控進定存清單）──────────────────────────────────

def _synth_fin_quarterly(ticker: str, start_year: int = 2021, n_years: int = 6,
                         q_ni: float = 100.0, ytd_from_2026: bool = True,
                         eps_nan_from_2026: bool = True) -> pd.DataFrame:
    """金控口徑：2026 起損益表 YTD 累計、近期沒有 EPS、資產負債表沒有 capital_stock。"""
    rows = []
    start = pd.Timestamp(f"{start_year}-03-31")
    for i in range(n_years * 4):
        pe = start + pd.DateOffset(months=3 * i)
        qtr = i % 4
        ytd = ytd_from_2026 and pe.year >= 2026
        ni = q_ni * (qtr + 1) if ytd else q_ni
        eps = np.nan if (eps_nan_from_2026 and pe.year >= 2026) else 1.0
        rows.append(dict(
            ticker=ticker, period_end=pe,
            revenue=np.nan, eps=eps,
            net_income=ni, gross_profit=np.nan, op_income=np.nan,
            pretax_income=ni * 1.2,
            total_assets=100000.0, equity=8000.0, equity_parent=np.nan,
            total_liabilities=92000.0, current_assets=np.nan,
            current_liabilities=np.nan,
            ocf=np.nan, ocf_net=np.nan, capex=np.nan,
            capital_stock=np.nan,
        ))
    return pd.DataFrame(rows)


def test_金融軌_2026起YTD淨利還原單季_歷史不動():
    q = _panel(_synth_fin_quarterly("FIN1", q_ni=100.0))
    qf = factors.quarterly_factors(q, fin_tickers={"FIN1"}).sort_values("period_end")
    g = qf[qf["ticker"] == "FIN1"]
    pre = g[g["period_end"].dt.year < 2026]["net_income"]
    post = g[g["period_end"].dt.year >= 2026]["net_income"]
    assert np.allclose(pre.values, 100.0)           # 單季歷史沒被動
    assert np.allclose(post.values, 100.0)          # 2026 YTD 還原成單季 100
    # 非金融即使在 2026 也不動
    qf2 = factors.quarterly_factors(_panel(_synth_fin_quarterly("NF1", q_ni=100.0)),
                                    fin_tickers=set()).sort_values("period_end")
    g2 = qf2[qf2["ticker"] == "NF1"]
    post2 = g2[g2["period_end"].dt.year == 2026]["net_income"].tolist()
    assert post2[:2] == [100.0, 200.0]


def test_金融軌_2026缺EPS從淨利股數推算後過門檻():
    q = _panel(_synth_fin_quarterly("FIN2", q_ni=100.0))
    qf = factors.quarterly_factors(q, fin_tickers={"FIN2"}, shares={"FIN2": 50.0})
    g = qf[(qf["ticker"] == "FIN2") & (qf["period_end"].dt.year >= 2026)]
    assert (g["eps"] > 0).all()                     # 100/50 = 2.0
    divf = factors.dividend_factors(pd.DataFrame([
        dict(ticker="FIN2", year=y, cash_dividend=2.0, cash_earnings=2.0,
             cash_surplus=0.0) for y in range(2020, 2026)]))
    res = screen.screen_deposit(qf, divf, asof=pd.Timestamp("2026-09-30"))
    assert res.set_index("ticker").loc["FIN2", "eps_4q_positive"]


def test_負債比_金融業採產業相對門檻():
    fin = _synth_fin_quarterly("FINBK", q_ni=100.0, eps_nan_from_2026=False)
    steel = _synth_quarterly("STEEL", growing=True)
    steel["total_liabilities"] = 4000.0        # debt_ratio = 0.8
    qf = factors.quarterly_factors(_panel(fin, steel), fin_tickers={"FINBK"},
                                   shares={"FINBK": 50.0})
    divf = factors.dividend_factors(pd.DataFrame([
        dict(ticker=t, year=y, cash_dividend=2.0, cash_earnings=2.0, cash_surplus=0.0)
        for t in ("FINBK", "STEEL") for y in range(2018, 2026)]))
    ind = pd.Series({"FINBK": "金融保險", "STEEL": "鋼鐵工業"})
    res = screen.screen_deposit(qf, divf, asof=pd.Timestamp("2025-09-30"),
                                industry=ind).set_index("ticker")
    # 金融保險：debt_ratio 0.92，產業中位數 0.92 × 1.5 = 1.38 → 不剔除
    assert res.loc["FINBK", "reject_reason"] != "負債比過高"
    # 鋼鐵：0.8 > max(0.75, 0.8×1.5=1.2) → 0.8 > 0.75 → 剔除
    assert res.loc["STEEL", "reject_reason"] == "負債比過高"


def test_cut5y_減配後回復創高不算():
    # 4 年前砍一刀、之後逐年回升並創高 → 不算減配
    yrs = {2018: 3.0, 2019: 3.5, 2020: 1.5, 2021: 2.5, 2022: 3.6, 2023: 4.0}
    div = pd.DataFrame([dict(ticker="REC", year=y, cash_dividend=v,
                             cash_earnings=v, cash_surplus=0.0)
                        for y, v in yrs.items()])
    out = factors.dividend_factors(div).set_index("ticker")
    assert out.loc["REC", "div_cut_5y"] == False


def test_cut5y_近3年減配仍算():
    yrs = {2018: 3.0, 2019: 3.2, 2020: 3.4, 2021: 3.5, 2022: 3.6, 2023: 2.0}
    div = pd.DataFrame([dict(ticker="CUT", year=y, cash_dividend=v,
                             cash_earnings=v, cash_surplus=0.0)
                        for y, v in yrs.items()])
    out = factors.dividend_factors(div).set_index("ticker")
    assert out.loc["CUT", "div_cut_5y"] == True
