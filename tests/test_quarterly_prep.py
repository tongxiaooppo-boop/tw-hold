"""screener.quarterly_prep：現金流單季化、TTM、產業分組（合成資料，預期值手算）。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import screener.quarterly_prep as qp


def _cf(rows):
    """rows: [(ticker, 'YYYY-MM-DD', ocf_ytd), ...]"""
    return pd.DataFrame([{"ticker": t, "period_end": pd.Timestamp(d), "ocf": v} for t, d, v in rows])


def test_現金流累計差分_Q1不差分():
    q = _cf([("A", "2024-03-31", 10.0), ("A", "2024-06-30", 25.0), ("A", "2024-09-30", 45.0),
             ("A", "2024-12-31", 70.0), ("A", "2025-03-31", 12.0)])
    out = qp.to_single_quarter_cashflow(q)
    # 10；25−10；45−25；70−45；新年度 Q1 不差分＝12
    assert out["ocf"].tolist() == [10.0, 15.0, 20.0, 25.0, 12.0]
    assert out["ocf_ytd"].tolist() == [10.0, 25.0, 45.0, 70.0, 12.0]


def test_現金流缺Q2_Q3為NaN_Q4照算():
    q = _cf([("A", "2024-03-31", 10.0), ("A", "2024-09-30", 45.0), ("A", "2024-12-31", 70.0)])
    out = qp.to_single_quarter_cashflow(q)
    assert out["ocf"].iloc[0] == 10.0
    assert np.isnan(out["ocf"].iloc[1])          # 前一季 Q2 不存在，不往前跳到 Q1
    assert out["ocf"].iloc[2] == 25.0            # 70 − 45


def test_現金流前季值為NaN_本季NaN():
    q = _cf([("A", "2024-03-31", 10.0), ("A", "2024-06-30", np.nan), ("A", "2024-09-30", 45.0)])
    out = qp.to_single_quarter_cashflow(q)
    assert out["ocf"].iloc[0] == 10.0
    assert np.isnan(out["ocf"].iloc[1])
    assert np.isnan(out["ocf"].iloc[2])


def test_現金流多檔分開算且排序():
    q = _cf([("B", "2024-06-30", 9.0), ("A", "2024-06-30", 25.0),
             ("B", "2024-03-31", 4.0), ("A", "2024-03-31", 10.0)])
    out = qp.to_single_quarter_cashflow(q)
    assert out["ticker"].tolist() == ["A", "A", "B", "B"]
    assert out["ocf"].tolist() == [10.0, 15.0, 4.0, 5.0]


def test_現金流跨年不差分():
    # 2024Q4 → 2025Q2，2025Q1 缺：2025Q2 的前一季（同年 Q1）不存在 → NaN，不拿 2024Q4 去減
    q = _cf([("A", "2024-12-31", 70.0), ("A", "2025-06-30", 30.0)])
    out = qp.to_single_quarter_cashflow(q)
    assert np.isnan(out["ocf"].iloc[1])


def test_現金流只處理存在的欄位():
    q = _cf([("A", "2024-03-31", 10.0)])
    out = qp.to_single_quarter_cashflow(q)
    assert "icf" not in out.columns and "icf_ytd" not in out.columns


def test_現金流可為負值原樣保留():
    q = _cf([("A", "2024-03-31", 10.0), ("A", "2024-06-30", 4.0)])
    out = qp.to_single_quarter_cashflow(q)
    assert out["ocf"].tolist() == [10.0, -6.0]


def test_現金流不改動輸入():
    q = _cf([("A", "2024-03-31", 10.0), ("A", "2024-06-30", 25.0)])
    before = q.copy()
    qp.to_single_quarter_cashflow(q)
    pd.testing.assert_frame_equal(q, before)


def test_現金流非季末日期_報錯():
    q = _cf([("A", "2024-04-30", 10.0)])
    with pytest.raises(ValueError):
        qp.to_single_quarter_cashflow(q)


def test_現金流重複期別_報錯():
    q = _cf([("A", "2024-03-31", 10.0), ("A", "2024-03-31", 11.0)])
    with pytest.raises(ValueError):
        qp.to_single_quarter_cashflow(q)


def test_現金流缺ticker欄_KeyError():
    q = pd.DataFrame({"period_end": [pd.Timestamp("2024-03-31")], "ocf": [1.0]})
    with pytest.raises(KeyError):
        qp.to_single_quarter_cashflow(q)


# ── ttm ──────────────────────────────────────────────

def _s(vals, start="2024-03-31", idx=None):
    if idx is None:
        idx = pd.date_range(start, periods=len(vals), freq="QE")
    return pd.Series(vals, index=pd.DatetimeIndex(idx), dtype=float, name="x")


def test_ttm_連續四季加總():
    out = qp.ttm(_s([1, 2, 3, 4, 5]))
    assert np.isnan(out.iloc[:3]).all()
    assert out.iloc[3:].tolist() == [10.0, 14.0]       # 1+2+3+4；2+3+4+5
    assert out.name == "x"


def test_ttm_缺曆季_涵蓋到的都NaN():
    idx = ["2024-03-31", "2024-06-30", "2024-12-31", "2025-03-31", "2025-06-30",
           "2025-09-30", "2025-12-31"]                    # 缺 2024Q3
    out = qp.ttm(_s([1, 1, 1, 1, 1, 1, 1], idx=idx))
    # 2024Q4..2025Q2 的 4 曆季窗都含 2024Q3 → NaN；2025Q3 窗＝2024Q4..2025Q3 → 4
    assert np.isnan(out.iloc[:5]).all()
    assert out.iloc[5] == 4.0 and out.iloc[6] == 4.0


def test_ttm_含NaN_NaN():
    out = qp.ttm(_s([1, np.nan, 3, 4, 5, 6, 7]))
    assert np.isnan(out.iloc[3]) and np.isnan(out.iloc[4])
    assert out.iloc[5] == 18.0                          # 3+4+5+6


def test_ttm_n可調():
    out = qp.ttm(_s([1, 2, 3]), n=2)
    assert np.isnan(out.iloc[0])
    assert out.iloc[1:].tolist() == [3.0, 5.0]


def test_ttm_索引不遞增_報錯():
    with pytest.raises(ValueError):
        qp.ttm(_s([1, 2], idx=["2024-06-30", "2024-03-31"]))


def test_ttm_n小於1_報錯():
    with pytest.raises(ValueError):
        qp.ttm(_s([1, 2]), n=0)


# ── 產業 ─────────────────────────────────────────────

@pytest.mark.parametrize("name,expected", [
    ("金融保險", "financial"),
    ("金融業", "financial"),
    (" 金融業 ", "financial"),
    ("生技醫療業", "biotech"),
    ("化學生技醫療", "other"),      # 混合分類，不算生技（Opus 審後決定）
    ("建材營造", "construction"),
    ("半導體業", "other"),
    ("其他", "other"),
    ("其他金融", "other"),          # 不做模糊比對
    ("", "other"),
    (None, "other"),
    (float("nan"), "other"),
    (123, "other"),
])
def test_產業分組對照(name, expected):
    assert qp.industry_group(name) == expected


@pytest.mark.parametrize("name,expected", [
    ("創新版股票", "創新板股票"),
    ("其他電子類", "其他電子業"),
    ("觀光事業", "觀光餐旅"),
    ("金融業", "金融保險"),
    (" 半導體業 ", "半導體業"),     # 表外原樣（去空白）
    ("", None),
    (None, None),
    (float("nan"), None),
])
def test_產業名正規化(name, expected):
    assert qp.normalize_industry(name) == expected
