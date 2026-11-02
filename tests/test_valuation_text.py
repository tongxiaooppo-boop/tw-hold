"""估值卡文字不能自相矛盾（2026-10-30 使用者：「不讓使用者看起來字互相矛盾」；sol 審查補）。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import valuation as va  # noqa: E402


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
