"""screener.rev_momentum：g3/g12/A/D/h3、噪音門檻、四種名稱與確認（合成資料，預期值手算）。"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

import screener.rev_momentum as rm


def _rev(drop: str | None = None, zero_prev: bool = False) -> pd.Series:
    """2022、2023 每月 100；2024 一～九月 120、十～十二月 150。"""
    vals = [100.0] * 24 + [120.0] * 9 + [150.0] * 3
    s = pd.Series(vals, index=pd.date_range("2022-01-01", periods=36, freq="MS"))
    if zero_prev:
        s.loc["2023-10-01":"2023-12-01"] = 0.0
    if drop:
        s = s.drop(pd.Timestamp(drop))
    return s


DEC24 = pd.Timestamp("2024-12-01")
SEP24 = pd.Timestamp("2024-09-01")


def test_g3_g12_h3_A_D_手算():
    m = rm.momentum_metrics(_rev())
    r = m.loc[DEC24]
    assert r["g3"] == pytest.approx(450 / 300 - 1)                   # 0.5
    assert r["g12"] == pytest.approx((9 * 120 + 450) / 1200 - 1)       # 0.275
    assert r["h3"] == pytest.approx(math.sqrt(450 / 300) - 1)         # 兩年前同期 300
    assert m.loc[SEP24, "g3"] == pytest.approx(0.2)                   # 360/300 − 1
    assert r["A"] == pytest.approx(0.5 - 0.2)
    assert r["D"] == pytest.approx(0.5 - 0.275)
    assert list(m.columns) == list(rm.METRIC_COLS)


def test_資料不足_前段為NaN():
    m = rm.momentum_metrics(_rev())
    assert np.isnan(m.loc[pd.Timestamp("2022-12-01"), "g3"])          # 去年同期不存在
    assert np.isnan(m.loc[pd.Timestamp("2024-02-01"), "h3"])          # 兩年前同期含 2021-12，不存在
    assert not np.isnan(m.loc[pd.Timestamp("2024-03-01"), "h3"])      # 2022-01..03 齊了


def test_g3缺月_NaN且A也NaN():
    m = rm.momentum_metrics(_rev(drop="2024-11-01"))
    assert pd.Timestamp("2024-11-01") in m.index                      # 缺月補列
    assert np.isnan(m.loc[DEC24, "g3"]) and np.isnan(m.loc[DEC24, "A"])


def test_去年同期合計為0_NaN():
    m = rm.momentum_metrics(_rev(zero_prev=True))
    assert np.isnan(m.loc[DEC24, "g3"])


def test_節慶旗標_只含一二月其中一個才標():
    m = rm.momentum_metrics(_rev())
    flags = {mo: bool(m.loc[pd.Timestamp(f"2024-{mo:02d}-01"), "holiday_flag"]) for mo in range(1, 13)}
    assert [mo for mo, f in flags.items() if f] == [1, 4]
    aflags = [mo for mo in range(1, 13) if m.loc[pd.Timestamp(f"2024-{mo:02d}-01"), "A_holiday_flag"]]
    assert aflags == [1, 4, 7]


def test_index不遞增_報錯():
    s = _rev().iloc[::-1]
    with pytest.raises(ValueError):
        rm.momentum_metrics(s)


# ── 噪音門檻 ─────────────────────────────────────────

def _A(vals, start="2021-01-01"):
    return pd.Series(vals, index=pd.date_range(start, periods=len(vals), freq="MS"), dtype=float)


def test_噪音門檻_MAD手算_不含當月():
    a = _A([0.0, 0.04] * 18 + [1.0])            # 當月 1.0 不得進窗
    r = rm.noise_threshold(a)
    # median＝0.02，|偏差| 全是 0.02 → MAD 0.02 → σ＝1.4826×0.02；H＝1.5σ＝0.044478 > 3pp
    assert r["n"] == 36
    assert r["sigma"] == pytest.approx(1.4826 * 0.02)
    assert r["H"] == pytest.approx(1.5 * 1.4826 * 0.02)


def test_噪音小_門檻取下限3pp():
    r = rm.noise_threshold(_A([0.01] * 37))
    assert r["sigma"] == pytest.approx(0.0)
    assert r["H"] == pytest.approx(0.03)


def test_噪音_只看前36個月():
    a = _A([5.0] * 10 + [0.01] * 37)            # 前 10 個大值在窗外
    r = rm.noise_threshold(a)
    assert r["n"] == 36 and r["sigma"] == pytest.approx(0.0)


def test_噪音_無歷史_σ為NaN_H為3pp():
    r = rm.noise_threshold(_A([0.2]))
    assert np.isnan(r["sigma"]) and r["H"] == pytest.approx(0.03) and r["n"] == 0


# ── 標籤 ─────────────────────────────────────────────

def _met(tail_A=(0.10, 0.10), g3=0.2, h3=None, n=40, start="2021-03-01",
         hist=lambda i: 0.005 * (-1) ** i, nan_head=0) -> pd.DataFrame:
    """逐月 metrics；A 歷史在 ±0.005 交錯（σ≈0.0074 → H＝3pp），最後幾個月換成 tail_A。
    預設 n=40、最後一月 2024-06；h3 預設逐月遞增（不觸發基期註記）。"""
    idx = pd.date_range(start, periods=n, freq="MS")
    A = [hist(i) for i in range(n)]
    for k, v in enumerate(tail_A):
        A[n - len(tail_A) + k] = v
    for i in range(nan_head):
        A[i] = np.nan
    h = list(np.linspace(0.0, 0.1, n)) if h3 is None else h3
    return pd.DataFrame({
        "g3": g3, "g12": 0.1, "A": A, "D": g3 - 0.1, "h3": h,
        "holiday_flag": [d.month in (1, 4) for d in idx],
        "A_holiday_flag": [d.month in (1, 4, 7) for d in idx],
    }, index=idx)


def test_正成長加速_連兩月成立_確認():
    r = rm.momentum_label(_met())
    assert r["H"] == pytest.approx(0.03)
    assert r["direction"] == "accel"
    assert r["label"] == "正成長加速"
    assert r["confirmed"] is True
    assert r["month"] == pd.Timestamp("2024-06-01")


def test_只有一個月成立_候選未確認():
    r = rm.momentum_label(_met(tail_A=(0.0, 0.10)))
    assert r["label"] == "正成長加速" and r["confirmed"] is False


def test_衰退收斂():
    r = rm.momentum_label(_met(g3=-0.1))
    assert r["label"] == "衰退收斂" and r["confirmed"] is True


def test_正成長減速():
    r = rm.momentum_label(_met(tail_A=(-0.10, -0.10), g3=0.1))
    assert r["label"] == "正成長減速" and r["direction"] == "decel"


def test_衰退擴大():
    r = rm.momentum_label(_met(tail_A=(-0.10, -0.10), g3=-0.1))
    assert r["label"] == "衰退擴大"


def test_g3等於0歸衰退側():
    r = rm.momentum_label(_met(g3=0.0))
    assert r["label"] == "衰退收斂"


def test_A在門檻內_無標籤():
    r = rm.momentum_label(_met(tail_A=(0.02, 0.02)))
    assert r["direction"] is None and r["label"] is None and r["confirmed"] is False


def test_前月反向_不確認():
    r = rm.momentum_label(_met(tail_A=(-0.10, 0.10)))
    assert r["label"] == "正成長加速" and r["confirmed"] is False


def test_歷史A不足24筆_不下確認標籤():
    # 最後一月的窗＝前 36 個月（idx 3..38）；idx 0..18 設 NaN → 窗內只剩 idx 19..38 共 20 筆
    r = rm.momentum_label(_met(nan_head=19))
    assert r["n_hist"] == 20
    assert r["label"] == "正成長加速"          # 候選仍給
    assert r["confirmed"] is False


def test_門檻用1點5σ_噪音大時():
    # 歷史 ±0.04 → MAD 0.04 → σ＝0.059304 → H＝0.088956；A＝0.08 不到門檻
    r = rm.momentum_label(_met(tail_A=(0.08,), hist=lambda i: 0.04 * (-1) ** i))
    assert r["H"] == pytest.approx(1.5 * 1.4826 * 0.04)
    assert r["direction"] is None


def test_g3加速但h3沒改善_標低基期():
    r = rm.momentum_label(_met(h3=[0.05] * 40))          # h3(m) == h3(m−3)
    assert r["direction"] == "accel"
    assert r["base_note"] == "可能主要來自去年低基期"


def test_g3減速但h3仍改善_標高基期():
    r = rm.momentum_label(_met(tail_A=(-0.10, -0.10)))   # h3 遞增
    assert r["base_note"] == "可能只是去年高基期"


def test_加速且h3改善_無基期註記():
    r = rm.momentum_label(_met())
    assert r["base_note"] is None


def test_節慶月_帶旗標():
    m = _met(n=40, start="2020-10-01")                   # 最後一月 2024-01
    r = rm.momentum_label(m)
    assert r["month"] == pd.Timestamp("2024-01-01")
    assert r["holiday_flag"] is True and r["A_holiday_flag"] is True


def test_asof不在index_KeyError():
    with pytest.raises(KeyError):
        rm.momentum_label(_met(), asof=pd.Timestamp("2030-01-01"))


def test_指定asof():
    m = _met(tail_A=(0.10, 0.10, 0.0))                   # 倒數第 2 月仍是確認加速
    r = rm.momentum_label(m, asof=m.index[-2])
    assert r["label"] == "正成長加速" and r["confirmed"] is True
