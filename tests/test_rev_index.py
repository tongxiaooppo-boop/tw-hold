"""screener.rev_index：同樣本營收指數、beta、同步度（合成資料，預期值手算）。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import screener.rev_index as ri


def _rows(ticker, start, values):
    months = pd.date_range(start, periods=len(values), freq="MS")
    return [{"ticker": ticker, "month": m, "revenue": float(v)} for m, v in zip(months, values)]


def _ab(b_missing: str | None = None, a_zero: str | None = None) -> pd.DataFrame:
    """A：2023 每月 100、2024 每月 110；B：2023 每月 200、2024 每月 260。"""
    rows = _rows("A", "2023-01-01", [100] * 12 + [110] * 12) + \
        _rows("B", "2023-01-01", [200] * 12 + [260] * 12)
    d = pd.DataFrame(rows)
    if b_missing:
        d = d[~((d["ticker"] == "B") & (d["month"] == pd.Timestamp(b_missing)))]
    if a_zero:
        d.loc[(d["ticker"] == "A") & (d["month"] == pd.Timestamp(a_zero)), "revenue"] = 0.0
    return d.reset_index(drop=True)


DEC24 = pd.Timestamp("2024-12-01")


def test_同樣本成分_只收當月與去年同月都有營收():
    d = pd.DataFrame(_rows("A", "2023-01-01", [100] * 24) + _rows("B", "2024-01-01", [50] * 12))
    c = ri.same_sample_components(d)
    # A 只有 2024 的 12 個月有去年同月；B 完全沒有
    assert set(c["ticker"]) == {"A"}
    assert len(c) == 12
    row = c[c["month"] == pd.Timestamp("2024-06-01")].iloc[0]
    assert row["cur"] == 100.0 and row["prev"] == 100.0


def test_市場指數_同樣本TTM年增_手算():
    m = ri.build_market_index(_ab(), min_members=2)
    # (12×110 + 12×260) / (12×100 + 12×200) − 1 = 4440/3600 − 1
    assert m.loc[DEC24, "ttm_yoy"] == pytest.approx(4440 / 3600 - 1)
    assert m.loc[DEC24, "num12"] == pytest.approx(4440.0)
    assert m.loc[DEC24, "den12"] == pytest.approx(3600.0)
    assert m.loc[DEC24, "n_min"] == 2
    assert list(m.columns) == list(ri.INDEX_COLS)


def test_市場指數_12個月不齊_NaN():
    m = ri.build_market_index(_ab(), min_members=1)
    # 2024-11 的窗含 2023-12，其去年同月 2022-12 不存在 → 該月樣本 0 家 → n_min 0 → NaN
    assert np.isnan(m.loc[pd.Timestamp("2024-11-01"), "ttm_yoy"])
    assert m.loc[pd.Timestamp("2024-11-01"), "n_min"] == 0


def test_同樣本_新上市公司不造成假成長():
    # A 三年每月 100；B 2024 才上市、每月 1000。天真加總會算出 (1200+12000)/1200−1 ≈ 1000%
    d = pd.DataFrame(_rows("A", "2022-01-01", [100] * 36) + _rows("B", "2024-01-01", [1000] * 12))
    m = ri.build_market_index(d, min_members=1)
    assert m.loc[DEC24, "ttm_yoy"] == pytest.approx(0.0)


def test_市場指數_某月缺一家_該月只用當月同樣本():
    # B 缺 2024-06 → 2024-06 這個月只有 A：分子 1320 + 11×260 = 4180；分母 1200 + 11×200 = 3400
    # （若改成「整段 TTM 都要齊」的口徑，B 會整個被排除、得 0.10——本測試釘住逐月同樣本口徑）
    m = ri.build_market_index(_ab(b_missing="2024-06-01"), min_members=1)
    assert m.loc[DEC24, "ttm_yoy"] == pytest.approx(4180 / 3400 - 1)
    assert m.loc[DEC24, "n_min"] == 1


def test_市場指數_營收為0視為缺():
    # A 的 2023-03 營收 0 → 2024-03 這個月 A 不在樣本：分子 11×110 + 12×260 = 4330；分母 11×100 + 2400 = 3500
    m = ri.build_market_index(_ab(a_zero="2023-03-01"), min_members=1)
    assert m.loc[DEC24, "ttm_yoy"] == pytest.approx(4330 / 3500 - 1)


def test_市場指數_樣本不足_NaN():
    m = ri.build_market_index(_ab(), min_members=3)
    assert np.isnan(m.loc[DEC24, "ttm_yoy"])


def test_市場指數_重複列_報錯():
    d = _ab()
    d = pd.concat([d, d.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError):
        ri.build_market_index(d)


def _abc() -> pd.DataFrame:
    """X 產業：A 100→110、B 200→260、C 100→100；Y 產業：D 50→100。E 沒有產業。"""
    rows = (_rows("A", "2023-01-01", [100] * 12 + [110] * 12)
            + _rows("B", "2023-01-01", [200] * 12 + [260] * 12)
            + _rows("C", "2023-01-01", [100] * 24)
            + _rows("D", "2023-01-01", [50] * 12 + [100] * 12)
            + _rows("E", "2023-01-01", [10] * 24))
    return pd.DataFrame(rows)


IND = {"A": "X", "B": "X", "C": "X", "D": "Y", "E": None}


def test_產業指數_分產業計算():
    ind = ri.build_industry_index(_abc(), IND, min_members=1)
    x = ind[(ind["industry"] == "X") & (ind["month"] == DEC24)].iloc[0]
    y = ind[(ind["industry"] == "Y") & (ind["month"] == DEC24)].iloc[0]
    # X：(1320 + 3120 + 1200) / (1200 + 2400 + 1200) − 1 = 5640/4800 − 1
    assert x["ttm_yoy"] == pytest.approx(5640 / 4800 - 1)
    assert x["n_min"] == 3
    assert y["ttm_yoy"] == pytest.approx(1.0)
    assert set(ind["industry"]) == {"X", "Y"}            # E 沒產業，不建


def test_產業指數_樣本少於5家不建():
    ind = ri.build_industry_index(_abc(), IND)            # 預設 min_members=5
    assert ind["ttm_yoy"].isna().all()
    assert len(ind) > 0                                   # 仍出列


def test_排除自己的產業指數():
    ind = ri.build_industry_index(_abc(), IND, min_members=1)
    s = ri.industry_index_excluding_self(ind, _abc(), "A", "X", min_members=2)
    # 去掉 A：(3120 + 1200) / (2400 + 1200) − 1 = 0.2
    assert s.loc[DEC24] == pytest.approx(0.2)


def test_排除自己後樣本不足_NaN():
    ind = ri.build_industry_index(_abc(), IND, min_members=1)
    s = ri.industry_index_excluding_self(ind, _abc(), "A", "X", min_members=3)
    assert np.isnan(s.loc[DEC24])


def test_個股TTM年增():
    s = pd.Series([100.0] * 12 + [110.0] * 12, index=pd.date_range("2023-01-01", periods=24, freq="MS"))
    out = ri.stock_ttm_yoy(s)
    assert np.isnan(out.iloc[:23]).all()
    assert out.iloc[23] == pytest.approx(0.1)


def test_個股TTM年增_缺一個月_NaN():
    s = pd.Series([100.0] * 12 + [110.0] * 12, index=pd.date_range("2023-01-01", periods=24, freq="MS"))
    s = s.drop(s.index[5])
    assert np.isnan(ri.stock_ttm_yoy(s).iloc[-1])


def _mkt(n=60):
    idx = pd.date_range("2020-01-01", periods=n, freq="MS")
    return pd.Series(np.sin(np.arange(n) / 5.0) * 0.1, index=idx)


def test_營收beta_個股是市場兩倍():
    m = _mkt()
    assert ri.revenue_beta(2 * m + 0.01, m) == pytest.approx(2.0)


def test_營收beta_有效月不足_NaN():
    m = _mkt(30)                                           # < REV_BETA_MIN_OBS(36)
    assert np.isnan(ri.revenue_beta(2 * m, m))


def test_營收beta_市場無變異_NaN():
    m = pd.Series(0.05, index=pd.date_range("2020-01-01", periods=60, freq="MS"))
    assert np.isnan(ri.revenue_beta(m * 2, m))


def test_營收beta_只取最後window個月():
    m = _mkt(80)
    s = m.copy()
    s.iloc[:40] = -s.iloc[:40]                             # 前 40 月反向，後 40 月同向 ×1
    assert ri.revenue_beta(s, m, window=40, min_obs=36) == pytest.approx(1.0)


def test_產業同步度_完全同向():
    m = _mkt()
    assert ri.industry_sync(3 * m + 0.05, m) == pytest.approx(1.0)


def test_產業同步度_完全反向():
    m = _mkt()
    assert ri.industry_sync(-m, m) == pytest.approx(-1.0)


def test_產業同步度_只用共同非NaN月份():
    m = _mkt(80)
    s = 2 * m
    s.iloc[:10] = np.nan                                   # 70 個共同月 ≥ 36
    assert ri.industry_sync(s, m) == pytest.approx(1.0)
