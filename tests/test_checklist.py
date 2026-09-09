"""三軌體檢——檢核列產生器。門檻對得上、金融業跳過對得上、缺資料不炸。"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "app")
import checklist as cl  # noqa: E402


def _states(rows):
    return {r["項目"]: r["狀態"] for r in rows}


def test_value_checks_門檻():
    r = {"industry": "半導體業", "name": "X", "close": 100.0, "cheap_threshold": 120.0,
         "valuation_ceiling": 150.0, "upside_pct": 0.5,
         "roe": 0.20, "gross_margin": 0.45, "ttm_eps": 12.0, "rev_yoy": 0.15,
         "debt_ratio": 0.30, "current_ratio": 2.5, "ttm_fcf": 5e9, "ttm_ocf": 8e9,
         "f_score": 8.0, "pe_p30": 10.0}
    s = _states(cl.value_checks(r))
    assert s["現價未過估值上緣"] == cl._OK        # 100 <= 150
    assert s["現價落在便宜區（參考）"] == cl._OK   # 100 <= 120
    assert s["ROE（TTM）≥ 10%"] == cl._OK
    assert s["負債比 ≤ 45%"] == cl._OK
    assert s["TTM 自由現金流為正"] == cl._OK


def test_value_checks_金融業跳過財務安全():
    r = {"industry": "金融業", "name": "某金", "close": 50.0, "cheap_threshold": 40.0,
         "valuation_ceiling": 45.0, "upside_pct": -0.1,
         "roe": 0.12, "gross_margin": np.nan, "ttm_eps": 5.0, "rev_yoy": 0.02,
         "debt_ratio": 0.92, "current_ratio": np.nan, "ttm_fcf": np.nan,
         "ttm_ocf": np.nan, "f_score": 7.0, "pe_p30": 9.0}
    rows = cl.value_checks(r)
    s = _states(rows)
    assert s["現價未過估值上緣"] == cl._NG        # 50 > 45
    # 金融業：負債比 / 流動比 / 現金流 一律「無資料（不適用）」而不是未達
    assert s["負債比 ≤ 45%"] == cl._NA
    assert "金融業不適用" in next(x["門檻"] for x in rows if x["項目"] == "負債比 ≤ 45%")


def test_deposit_checks_門檻與缺值():
    r = {"industry": "食品工業", "name": "大統益", "div_years": 12.0, "cur_yield": 0.055,
         "yield_floor": 0.05, "div_cut_5y": False, "payout_ratio_ttm": 0.80,
         "fcf_cover": 1.5, "fill_rate": 0.9, "ret3y_incl": 0.2, "debt_ratio": 0.40,
         "roe": 0.25, "ann_vol": 0.14, "yield_pctile_5y": 0.7}
    s = _states(cl.deposit_checks(r))
    assert s["連續配息 ≥ 7 年"] == cl._OK
    assert s["現價殖利率 ≥ 5.0%"] == cl._OK
    assert s["近 5 年無實質減配"] == cl._OK
    assert s["自由現金流覆蓋股利"] == cl._OK


def test_checks_傳None_不炸():
    assert cl.value_checks(None) == []
    assert cl.deposit_checks(None) == []
    assert cl.swing_checks({}) != []          # 會回「資料不足」列，不丟例外


def test_swing_checks_基本流程():
    months = pd.date_range("2022-01-01", periods=30, freq="MS")
    rev = pd.DataFrame({"month": months,
                        "revenue": np.linspace(1e8, 2e8, 30)})
    dates = pd.date_range("2023-01-01", periods=260, freq="B")
    px = pd.DataFrame({"date": dates, "open": 100.0, "high": 101.0, "low": 99.0,
                       "close": np.linspace(80, 130, 260), "volume": 1000})
    per = pd.DataFrame({"date": dates, "per": np.linspace(20, 10, 260),
                        "pbr": np.linspace(3, 1.5, 260),
                        "dividend_yield": np.linspace(2, 4, 260)})
    chips = pd.DataFrame({"date": dates[-40:], "foreign": 100.0, "trust": 50.0,
                          "dealer": 10.0})
    qcols = pd.date_range("2020-03-31", periods=24, freq="QE")
    qf = pd.DataFrame({"ticker": "9999", "period_end": qcols,
                       "eps": np.linspace(1, 4, 24),
                       "ttm_eps": np.linspace(4, 12, 24),
                       "roe": np.linspace(0.1, 0.25, 24),
                       "gross_margin": np.linspace(0.3, 0.45, 24),
                       "debt_ratio": np.linspace(0.5, 0.35, 24)})
    d = {"qf": qf, "rev": rev, "px": px, "per": per, "chips": chips}
    rows = cl.swing_checks(d)
    s = _states(rows)
    assert s["月營收 YoY > 0"] == cl._OK
    assert s["法人 20 日淨買超 > 0"] == cl._OK
    assert "Minervini 趨勢模板" in s
    assert any(r["項目"] == "PE 位於自身歷史低檔" for r in rows)
