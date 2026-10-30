"""估值卡文字不能自相矛盾（2026-10-30 使用者：「不讓使用者看起來字互相矛盾」；sol 審查補）。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import valuation as va  # noqa: E402


def _buy(price, growth, fair=90.0):
    return va.buy_range(price, fair, growth)


def test_買進門檻_差一點未達_不會看起來像過了():
    import streamlit_app as sa
    b = _buy(100.0, 111.10)                            # 上限 99.99，成長 11.10% < 11.11%
    assert b["state"] == "above"
    line, _ = sa._buy_lines(b)
    assert "目前 +11%，差一點未達" in line
    line, _ = sa._buy_lines(_buy(100.0, 105.0))       # 明顯沒過 → 不加「差一點」
    assert "目前 +5%）" in line and "差一點" not in line


def test_買進文字_不寫預估獲利成長_跟成長價括號同一個數():
    """EPS 卡「年增」比去年全年；這裡比的是成長價/現價，不能都叫「成長」（2353：+24% vs −5%）。"""
    import streamlit_app as sa
    b = va.buy_range(32.0, 33.3, 30.4, nonop_high=True)
    line, _ = sa._buy_lines(b)
    assert b["state"] == "none" and "預估獲利成長" not in line
    assert "成長價需比現價高 25%，目前 -5%" in line


def _hd(**kw):
    base = {"line": 74.0, "hh": 82.0, "since": "10/16", "watr": 4.0, "price": 80.0, "dist": 74 / 80 - 1,
            "state": "above", "reset": True, "brk_line": 94.0, "brk_date": "10/16", "under_now": False}
    base.update(kw)
    return base


def _rk(hd):
    return {"buyable": False, "stop": None, "hold": hd, "no_growth": False, "price": hd["price"],
            "watr": 4.0, "support": None, "sup_px": None, "sup_far": False, "at": None,
            "resist": None, "res_px": None, "high": 100.0}


def test_剛跌破_週中又跌破新線_新線數字照樣顯示():
    import streamlit_app as sa
    card, _ = sa._risk_lines(_rk(_hd(state="new", price=70.0, dist=74 / 70 - 1)))
    assert "跌破持股停損 94" in card and "新參考線 **74.0**" in card and "現價已在線下" in card


def test_暫無狀態_說的是上週收盤_不是現價():
    import streamlit_app as sa
    card, how = sa._risk_lines(_rk(_hd(state="na", line=85.0, price=90.0, dist=85 / 90 - 1)))
    assert "仍高於上週收盤" in card and "現價上方" not in card


def test_跌破日跟起算日不同_分開講():
    import streamlit_app as sa
    _, how = sa._risk_lines(_rk(_hd(since="09/18", brk_date="10/16")))
    assert "最近一次跌破：10/16" in how and "從 09/18 那次跌破起算" in how


def _old_weekly_atr(w: pd.DataFrame, weeks: int = 14) -> float:
    """改寫前的 weekly_atr 本體（逐字照抄），拿來對照 _watr_series。"""
    pc = w["close"].shift()
    tr = pd.concat([w["high"] - w["low"], (w["high"] - pc).abs(), (w["low"] - pc).abs()],
                   axis=1).max(axis=1).iloc[1:].to_numpy()
    a = float(tr[:weeks].mean())
    for x in tr[weeks:]:
        a = (a * (weeks - 1) + float(x)) / weeks
    return a


def test_週ATR序列_每一週都等於舊公式():
    rng = np.random.default_rng(7)
    n = 400
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, n)))
    d = pd.DataFrame({"date": pd.bdate_range(end="2026-10-23", periods=n), "close": c,
                      "high": c * (1 + rng.uniform(0, .03, n)), "low": c * (1 - rng.uniform(0, .03, n))})
    w = va._weekly_bars(d)
    s = va._watr_series(w)
    assert s.iloc[:14].isna().all()
    for k in range(15, len(w) + 1):
        assert s.iloc[k - 1] == pytest_approx(_old_weekly_atr(w.iloc[:k]))


def pytest_approx(v):
    import pytest
    return pytest.approx(v, rel=1e-12)


def test_最近一次跌破_第22週也找得到():
    """跌破發生在倒數第 22 週，之後都在線上 → brk_date 要找得到（sol：原本只找 21 週）。"""
    n = 300
    c = np.full(n, 100.0)
    d = pd.DataFrame({"date": pd.bdate_range(end="2026-10-23", periods=n), "close": c,
                      "high": c + 2, "low": c - 2})
    w = va._weekly_bars(d)
    wk = w.index[-22]                                  # 讓那一週收盤 80（跌破 94），下一週起回 100
    m = (d["date"] > wk - pd.Timedelta(days=7)) & (d["date"] <= wk)
    d.loc[m, ["close"]] = 80.0
    d.loc[m, "high"], d.loc[m, "low"] = 82.0, 78.0
    hd = va.hold_stop(d)
    assert hd["brk_date"] == wk.strftime("%m/%d")
