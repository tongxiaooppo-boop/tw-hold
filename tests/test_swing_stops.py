"""出場觀察表（移動停損，非持倉追蹤）——`screener/swing_stops.py`。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from screener.swing_stops import TRAIL_ATR_MULT, update_stops


def _prices(ticker: str, closes: list[float], start: str = "2026-01-01") -> pd.DataFrame:
    """收盤走 `closes`，high/low 各自 ±1% 帶出 ATR，前面墊 20 天平盤讓 ATR14 暖機好。"""
    warmup = [closes[0]] * 20
    path = warmup + closes
    dates = pd.date_range(start, periods=len(path), freq="B")
    close = pd.Series(path, dtype=float)
    return pd.DataFrame({"date": dates, "ticker": ticker, "open": close,
                         "high": close * 1.01, "low": close * 0.99, "close": close,
                         "volume": 1_000_000})


def _pool_row(ticker: str, risk_stop: float) -> dict:
    return {"ticker": ticker, "risk_stop": risk_stop}


def test_new_candidate_opens_tracking():
    px = _prices("AAA", [100.0])
    asof = px["date"].iloc[-1]
    pool = [_pool_row("AAA", risk_stop=95.0)]
    out = update_stops({}, pool, px, asof)
    rec = out["tracked"]["AAA"]
    assert rec["status"] == "candidate"
    assert rec["entry_price"] == 100.0
    assert rec["trail_stop"] == 95.0          # 進場當下＝§5.3 停損位（run_high-2*atr0 還沒超過它）
    assert rec["atr0"] > 0


def test_trail_stop_only_rises_with_run_high():
    px = _prices("AAA", [100.0, 110.0, 120.0])
    d0, d1, d2 = px["date"].iloc[-3:]
    pool = [_pool_row("AAA", risk_stop=95.0)]
    s0 = update_stops({}, pool, px, d0)
    s1 = update_stops(s0, pool, px, d1)
    s2 = update_stops(s1, pool, px, d2)
    stops = [s0["tracked"]["AAA"]["trail_stop"], s1["tracked"]["AAA"]["trail_stop"],
            s2["tracked"]["AAA"]["trail_stop"]]
    assert stops == sorted(stops)              # 只漲不跌
    assert stops[-1] > stops[0]


def test_stop_hit_freezes_record():
    # 一路噴上去養出高 run_high，接著單日跌破 low <= trail_stop。
    px = _prices("AAA", [100.0, 120.0, 140.0, 90.0])
    dates = px["date"].iloc[-4:].tolist()
    pool = [_pool_row("AAA", risk_stop=95.0)]
    state = {}
    for d in dates[:-1]:
        state = update_stops(state, pool, px, d)
    assert state["tracked"]["AAA"]["status"] == "candidate"
    stop_before = state["tracked"]["AAA"]["trail_stop"]

    final = update_stops(state, pool, px, dates[-1])
    rec = final["tracked"]["AAA"]
    assert rec["status"] == "stopped_out"
    assert rec["exit_price"] == stop_before
    assert rec["exit_date"] == dates[-1].date().isoformat()

    # 之後再餵更多天，只要沒有重新達標（不在候選池），凍結不變。
    px2 = _prices("AAA", [100.0, 120.0, 140.0, 90.0, 200.0])
    frozen = update_stops(final, [], px2, px2["date"].iloc[-1])
    assert frozen["tracked"]["AAA"] == rec


def test_dropped_from_pool_keeps_tracking_until_stopped():
    px = _prices("AAA", [100.0, 110.0])
    d0, d1 = px["date"].iloc[-2:]
    s0 = update_stops({}, [_pool_row("AAA", risk_stop=95.0)], px, d0)
    assert s0["tracked"]["AAA"]["status"] == "candidate"

    # 第二天不再是候選池成員了（傳空池），但價格還沒跌破停損 → 標「已出候選池」，繼續追蹤。
    s1 = update_stops(s0, [], px, d1)
    rec = s1["tracked"]["AAA"]
    assert rec["status"] == "dropped_from_pool"
    assert rec["dropped_date"] == d1.date().isoformat()
    assert rec["run_high"] >= s0["tracked"]["AAA"]["run_high"]


def test_reentry_after_stop_starts_new_cycle():
    px = _prices("AAA", [100.0, 140.0, 90.0, 130.0])
    dates = px["date"].iloc[-4:].tolist()
    pool = [_pool_row("AAA", risk_stop=95.0)]
    state = {}
    for d in dates[:-1]:
        state = update_stops(state, pool, px, d)
    assert state["tracked"]["AAA"]["status"] == "stopped_out"

    reentry = update_stops(state, pool, px, dates[-1])
    rec = reentry["tracked"]["AAA"]
    assert rec["status"] == "candidate"
    assert rec["first_seen"] == dates[-1].date().isoformat()   # 新一輪，不是延續舊的
