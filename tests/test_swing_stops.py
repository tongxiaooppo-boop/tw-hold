"""出場觀察表（移動停損，非持倉追蹤）——`screener/swing_stops.py`。

2026-09-14 進場口徑修正：訊號日只開 `pending_entry`，次一交易日開盤才轉正成
`candidate`（不是訊號當天收盤價，那個價格買不到）。以下測試沿這個兩階段
狀態機重寫。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from screener.swing_stops import TRAIL_ATR_MULT, update_stops


def _bars(ticker: str, closes: list[float], opens: list[float] | None = None,
         start: str = "2026-01-01") -> pd.DataFrame:
    """收盤走 `closes`（預設開盤＝收盤，除非另給 `opens`），high/low 各自 ±1% 帶出
    ATR，前面墊 20 天平盤讓 ATR14 暖機好。"""
    warmup = [closes[0]] * 20
    close_path = warmup + closes
    open_path = warmup + (opens if opens is not None else closes)
    dates = pd.date_range(start, periods=len(close_path), freq="B")
    close = pd.Series(close_path, dtype=float)
    open_ = pd.Series(open_path, dtype=float)
    hi = pd.concat([close, open_], axis=1).max(axis=1) * 1.01
    lo = pd.concat([close, open_], axis=1).min(axis=1) * 0.99
    return pd.DataFrame({"date": dates, "ticker": ticker, "open": open_,
                         "high": hi, "low": lo, "close": close,
                         "volume": 1_000_000})


def _pool_row(ticker: str, risk_stop: float) -> dict:
    return {"ticker": ticker, "risk_stop": risk_stop}


def test_signal_day_only_opens_pending_entry():
    """訊號當天不進場——那天的收盤價買不到，只記一筆待進場。"""
    px = _bars("AAA", [100.0])
    asof = px["date"].iloc[-1]
    pool = [_pool_row("AAA", risk_stop=95.0)]
    out = update_stops({}, pool, px, asof)
    rec = out["tracked"]["AAA"]
    assert rec["status"] == "pending_entry"
    assert rec["signal_date"] == asof.date().isoformat()
    assert rec["risk_stop_ref"] == 95.0
    assert "entry_price" not in rec


def test_pending_entry_becomes_candidate_next_open():
    """次一交易日才用那天的開盤價轉正進場——跟回測 next_open 一致。"""
    px = _bars("AAA", [100.0, 110.0])
    d0, d1 = px["date"].iloc[-2:]
    pool = [_pool_row("AAA", risk_stop=95.0)]
    s0 = update_stops({}, pool, px, d0)
    assert s0["tracked"]["AAA"]["status"] == "pending_entry"

    s1 = update_stops(s0, pool, px, d1)
    rec = s1["tracked"]["AAA"]
    assert rec["status"] == "candidate"
    assert rec["first_seen"] == d0.date().isoformat()
    assert rec["entry_date"] == d1.date().isoformat()
    assert rec["entry_price"] == 110.0            # 次日開盤，不是訊號日收盤 100
    assert rec["trail_stop"] == 95.0              # 進場當下＝訊號日算好的 §5.3 停損位
    assert rec["atr0"] > 0


def test_pending_entry_resolves_even_if_pool_no_longer_contains_it():
    """訊號成立後，進場與否只看次日開盤價格本身，不因為隔一天候選池條件不再
    成立就取消——跟回測一致（next_open 無條件進場）。"""
    px = _bars("AAA", [100.0, 110.0])
    d0, d1 = px["date"].iloc[-2:]
    s0 = update_stops({}, [_pool_row("AAA", risk_stop=95.0)], px, d0)
    s1 = update_stops(s0, [], px, d1)              # 第二天候選池已經沒有這檔了
    assert s1["tracked"]["AAA"]["status"] == "candidate"
    assert s1["tracked"]["AAA"]["entry_price"] == 110.0


def test_abandoned_if_next_open_already_below_stop():
    """次日開盤價已經跌破訊號日算的停損位——不合理的進場，這筆訊號放棄
    （跟回測 abandoned_below_stop 一致），不留任何紀錄。"""
    px = _bars("AAA", [100.0, 90.0], opens=[100.0, 90.0])   # 次日開盤 90 <= risk_stop 95
    d0, d1 = px["date"].iloc[-2:]
    s0 = update_stops({}, [_pool_row("AAA", risk_stop=95.0)], px, d0)
    s1 = update_stops(s0, [], px, d1)
    assert "AAA" not in s1["tracked"]


def test_trail_stop_only_rises_with_run_high():
    px = _bars("AAA", [100.0, 110.0, 120.0, 130.0])
    d0, d1, d2, d3 = px["date"].iloc[-4:]
    pool = [_pool_row("AAA", risk_stop=95.0)]
    s0 = update_stops({}, pool, px, d0)             # pending
    s1 = update_stops(s0, pool, px, d1)             # 進場（entry_price=110）
    s2 = update_stops(s1, pool, px, d2)
    s3 = update_stops(s2, pool, px, d3)
    stops = [s1["tracked"]["AAA"]["trail_stop"], s2["tracked"]["AAA"]["trail_stop"],
            s3["tracked"]["AAA"]["trail_stop"]]
    assert stops == sorted(stops)                   # 只漲不跌
    assert stops[-1] > stops[0]


def test_stop_hit_freezes_record():
    # 訊號 → 進場（100）→ 一路噴上去養出高 run_high → 單日跌破 low <= trail_stop。
    px = _bars("AAA", [100.0, 100.0, 120.0, 140.0, 90.0])
    dates = px["date"].iloc[-5:].tolist()
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
    px2 = _bars("AAA", [100.0, 100.0, 120.0, 140.0, 90.0, 200.0])
    frozen = update_stops(final, [], px2, px2["date"].iloc[-1])
    assert frozen["tracked"]["AAA"] == rec


def test_dropped_from_pool_keeps_tracking_until_stopped():
    px = _bars("AAA", [100.0, 100.0, 110.0])
    d0, d1, d2 = px["date"].iloc[-3:]
    s0 = update_stops({}, [_pool_row("AAA", risk_stop=95.0)], px, d0)      # pending
    s1 = update_stops(s0, [_pool_row("AAA", risk_stop=95.0)], px, d1)     # 進場
    assert s1["tracked"]["AAA"]["status"] == "candidate"

    # 第三天不再是候選池成員了（傳空池），但價格還沒跌破停損 → 標「已出候選池」，繼續追蹤。
    s2 = update_stops(s1, [], px, d2)
    rec = s2["tracked"]["AAA"]
    assert rec["status"] == "dropped_from_pool"
    assert rec["dropped_date"] == d2.date().isoformat()
    assert rec["run_high"] >= s1["tracked"]["AAA"]["run_high"]


def test_same_day_rerun_is_a_no_op_at_pending_stage():
    px = _bars("AAA", [100.0])
    asof = px["date"].iloc[-1]
    pool = [_pool_row("AAA", risk_stop=95.0)]
    s0 = update_stops({}, pool, px, asof)
    s1 = update_stops(s0, pool, px, asof)
    assert s1["tracked"]["AAA"] == s0["tracked"]["AAA"]


def test_same_day_rerun_is_a_no_op_at_candidate_stage():
    """2026-09-12 本機手動重跑 refresh_local.py 兩次撞到：同一個 asof 重算第二次，
    run_high 已經含當天最高價，若再跑一次遞增邏輯等於拿當天自己的高點回頭砍自己，
    4 檔無端被判定跌破停損。同一天重算兩次必須是 no-op。"""
    px = _bars("AAA", [100.0, 110.0])
    d0, d1 = px["date"].iloc[-2:]
    pool = [_pool_row("AAA", risk_stop=95.0)]
    s0 = update_stops({}, pool, px, d0)
    s1 = update_stops(s0, pool, px, d1)
    s2 = update_stops(s1, pool, px, d1)             # 同一天（d1）重跑第二次
    assert s2["tracked"]["AAA"] == s1["tracked"]["AAA"]


def test_reentry_after_stop_opens_new_pending_not_immediate_candidate():
    px = _bars("AAA", [100.0, 100.0, 140.0, 90.0, 130.0])
    dates = px["date"].iloc[-5:].tolist()
    pool = [_pool_row("AAA", risk_stop=95.0)]
    state = {}
    for d in dates[:-1]:
        state = update_stops(state, pool, px, d)
    assert state["tracked"]["AAA"]["status"] == "stopped_out"

    reentry = update_stops(state, pool, px, dates[-1])
    rec = reentry["tracked"]["AAA"]
    assert rec["status"] == "pending_entry"                     # 新一輪，一樣先排隊
    assert rec["signal_date"] == dates[-1].date().isoformat()
