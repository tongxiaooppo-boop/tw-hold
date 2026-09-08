"""M4：個股查詢的圖 + F-Score 表（合成資料，不打網路）。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app import charts as ch


def _px(n: int = 300):
    d = pd.date_range("2024-01-01", periods=n, freq="B")
    close = 100 + np.cumsum(np.random.default_rng(0).normal(0.1, 1, n))
    return pd.DataFrame({"date": d, "open": close, "high": close + 1,
                         "low": close - 1, "close": close, "volume": 1e6})


def _qf(n: int = 20):
    pe = pd.date_range("2021-03-31", periods=n, freq="QE")
    return pd.DataFrame({
        "period_end": pe, "eps": np.linspace(1, 3, n), "ttm_eps": np.linspace(4, 10, n),
        "revenue": 1000.0, "op_income": 200.0, "net_income": 150.0,
        "gross_margin": np.linspace(0.3, 0.4, n), "ocf": 250.0, "ocf_net": 250.0,
        "capex": 80.0,
        **{k: 1 for k in ch.F_LABELS}, "f_turnover": 0,
    })


def test_kline_有均線():
    fig = ch.kline(_px(), "測試")
    names = {t.name for t in fig.data}
    assert "還原K線" in names and "季線" in names and "年線" in names


def test_pe_river_空_per_不爆():
    fig = ch.pe_river(_px(), pd.DataFrame(columns=["date", "per"]), "測試")
    assert "無 per 資料" in fig.layout.title.text


def test_pe_river_有河道():
    px = _px()
    per = pd.DataFrame({"date": px["date"], "per": 15.0})
    fig = ch.pe_river(px, per, "測試")
    assert len(fig.data) >= 6                       # 5 河道 + 收盤


def test_fscore_table_9項_不加總():
    t = ch.fscore_table(_qf())
    assert len(t) == 9
    assert set(t["狀態"]) <= {"✓", "✗"}
    assert "總分" not in t["項目"].values and "分數" not in "".join(t["項目"])


def test_margins_三率():
    fig = ch.margins(_qf(), "測試")
    assert {t.name for t in fig.data} == {"毛利率", "營益率", "稅後淨利率"}
