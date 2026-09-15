"""產業逆風旗標（screener.industry）——只顯示、不進 verdict。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from screener.industry import (add_industry_headwind, add_peer_comparison,
                               industry_headwind, industry_rotation)

_ASOF = pd.Timestamp("2026-09-07")


def _price_hist(spec: dict[str, float]) -> pd.DataFrame:
    """spec: {ticker: 6個月總報酬} → 線性爬升的還原價序列。"""
    dates = pd.date_range("2026-02-20", _ASOF, freq="B")
    rows = []
    for tk, ret in spec.items():
        for i, d in enumerate(dates):
            rows.append((d, tk, 100.0 * (1 + ret) ** (i / (len(dates) - 1))))
    return pd.DataFrame(rows, columns=["date", "ticker", "close"])


def test_絕對走弱又落後大盤_才判逆風():
    ph = _price_hist({"1": -0.22, "2": -0.18, "3": -0.25,   # A：崩
                      "4": 0.03, "5": -0.02, "6": 0.06,      # B：持平
                      "7": 0.10})                            # C：漲（n<3 不判）
    im = {"1": "A", "2": "A", "3": "A", "4": "B", "5": "B", "6": "B", "7": "C"}
    hw = industry_headwind(ph, im, _ASOF)
    assert set(hw) == {"A"}
    assert hw["A"]["n"] == 3 and hw["A"]["median_ret"] < -0.10


def test_全市場一起跌_不算逆風():
    ph = _price_hist({str(i): -0.15 for i in range(6)})   # 所有產業一起 -15%
    im = {"0": "A", "1": "A", "2": "A", "3": "B", "4": "B", "5": "B"}
    assert industry_headwind(ph, im, _ASOF) == {}          # 落後大盤 0 → 不判


def test_add_欄位_bool加float():
    ph = _price_hist({"1": -0.3, "2": -0.3, "3": -0.3, "4": 0.1, "5": 0.1, "6": 0.1})
    im = {"1": "A", "2": "A", "3": "A", "4": "B", "5": "B", "6": "B"}
    df = pd.DataFrame({"ticker": ["1", "4"], "industry": ["A", "B"]})
    out = add_industry_headwind(df, ph, im, _ASOF)
    assert out.loc[0, "industry_headwind"] and not out.loc[1, "industry_headwind"]
    assert out.loc[0, "industry_ret_6m"] < 0 and np.isnan(out.loc[1, "industry_ret_6m"])


def test_無價格歷史_不炸():
    out = add_industry_headwind(pd.DataFrame({"ticker": ["1"], "industry": ["A"]}),
                                None, {"1": "A"}, _ASOF)
    assert out.loc[0, "industry_headwind"] == False        # noqa: E712


def test_族群動向_排序由高到低_且沿用逆風判定():
    ph = _price_hist({"1": -0.22, "2": -0.18, "3": -0.25,   # A：崩（逆風）
                      "4": 0.03, "5": -0.02, "6": 0.06,      # B：持平
                      "7": 0.30, "8": 0.28, "9": 0.32})      # C：噴出
    im = {"1": "A", "2": "A", "3": "A", "4": "B", "5": "B", "6": "B",
          "7": "C", "8": "C", "9": "C"}
    rot = industry_rotation(ph, im, _ASOF)
    assert [r["industry"] for r in rot] == ["C", "B", "A"]
    by_ind = {r["industry"]: r for r in rot}
    assert by_ind["A"]["headwind"] is True
    assert by_ind["B"]["headwind"] is False and by_ind["C"]["headwind"] is False
    assert by_ind["A"]["n"] == 3


def test_族群動向_樣本太小的產業不列():
    ph = _price_hist({"1": 0.1, "2": 0.1, "3": 0.1, "4": -0.1, "5": -0.1})
    im = {"1": "A", "2": "A", "3": "A", "4": "B", "5": "C"}   # B/C 各只有 1 檔
    rot = industry_rotation(ph, im, _ASOF)
    assert [r["industry"] for r in rot] == ["A"]


def test_同業比較_名次與中位數():
    df = pd.DataFrame({
        "ticker": ["1", "2", "3", "4"],
        "industry": ["A", "A", "A", "B"],
        "roe": [0.20, 0.10, 0.05, 0.30],   # B 只有 1 檔（< MIN_N），A 有 3 檔
    })
    out = add_peer_comparison(df, metric="roe")
    a = out.set_index("ticker")
    assert a.loc["1", "peer_rank"] == 1 and a.loc["1", "peer_n"] == 3
    assert a.loc["3", "peer_rank"] == 3
    assert a.loc["1", "peer_metric_median"] == 0.10
    assert np.isnan(a.loc["4", "peer_rank"])          # B 樣本太小 → 不比


def test_同業比較_垃圾桶分類不比():
    df = pd.DataFrame({
        "ticker": ["1", "2", "3"],
        "industry": ["其他", "其他", "其他"],
        "roe": [0.20, 0.10, 0.05],
    })
    out = add_peer_comparison(df, metric="roe")
    assert out["peer_rank"].isna().all()


def test_同業比較_缺metric欄不炸():
    df = pd.DataFrame({"ticker": ["1"], "industry": ["A"]})
    out = add_peer_comparison(df, metric="roe")
    assert np.isnan(out.loc[0, "peer_rank"])
