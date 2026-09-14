"""長波段模擬單（PRD 外掛，2026-09-14 使用者要求「仿照 tw-swing 跑模擬單」）。

**輕量版 plus**——不是複製 tw-swing 那整套（每日不可修改證據 + 限價/次日開盤
多口徑對照 + G1~G5 統計顯著性門檻 + 跨規則分桶 + 權益曲線）。tw-hold 長波段
只有一組規則（CANSLIM ∩ 趨勢模板 ∩ 市況門檻），沒有 tw-swing 那種「橫向比較
五六條規則」的需求，那整套工程量對單一規則不成比例。

做的事：`screener/swing_stops.py` 的出場觀察表（`tracked`）本來就用「候選首次
達標日」當進場代理、逐日追蹤到跌破移動停損——這裡只是在它每次判定
`stopped_out` 的那一刻，把這筆「已實現」的結果**另外存一份不會被蓋掉的歷史**
（`tracked` 同一檔之後重新達標會開新一輪、蓋掉舊的出場資訊，見
`swing_stops.py` docstring），再算勝率/期望值，跟回測基準對照。

**plus 的兩件事**：
1. 跟回測基準（`docs/reports/backtest_longswing_20260914.md` 採用格：排除空頭
   週 + 移動ATR停損，491 筆完成交易、勝率 43%）對照——差太多要講出來，不是
   只丟數字。
2. 月度分解（出場月）——使用者說要看 2 個月，月度表比單一累積數字更看得出
   「這兩個月到底在幹嘛」。

**跟回測不是同一份程式碼、也不是同一個口徑**：回測是全歷史模擬（PRD §5.2.4／
`research/backtest_longswing.py`），這裡是真實市場價格逐日累積出來的實際結果，
用「訊號日收盤成交」這個最樂觀的進場假設（跟 `swing_stops.py` 進場代理一致，
沒有另外做限價/次日開盤對照——樣本量小時做多口徑對照沒意義，先求有再求全）。
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

# 往返成本（手續費兩次 + 證交稅）——同市場機制，沿用跟 tw-swing 一樣的假設，
# 不是巧合也不是抄，是台股實際交易成本本來就這個數。
DEFAULT_COST = 0.00585
N_MIN = 10          # 樣本 < 此值 → 勝率/期望值一律顯示「—」（待驗），不給假象

#: 回測基準（採用格，見 docs/reports/backtest_longswing_20260914.md 最後一格
#: 「排除空頭週 + 移動ATR停損」）——只有一組規則，寫死在這裡不是脫節風險，
#: 回測報告改了要記得一起改（跟 tw-swing 讀 rules.yaml 結構化欄位不同，
#: 這裡沒有等價的結構化來源，用註解自己盯）。
BACKTEST_BASELINE = {
    "win_rate": 0.43,
    "n_trades": 491,
    "source": "docs/reports/backtest_longswing_20260914.md（排除空頭週+移動ATR停損，2026-09-14）",
}
#: 勝率跟基準差超過這個百分點才示警——單一規則、樣本小的時候本來就會抖動，
#: 抖動 5pp 以內不值得每天喊一次「背離」。
DIVERGE_PP = 15.0


def find_new_exits(prev_tracked: dict, new_tracked: dict) -> list[dict]:
    """比對 `update_stops()` 前後的 `tracked`，找出**這一次新出現**的
    `stopped_out`（用 `exit_date` 變化判定，同一筆出場只會被抓到一次，即使
    之後同一檔重新達標又開新一輪、把 `tracked` 裡的舊出場資訊蓋掉）。"""
    out = []
    for tk, rec in new_tracked.items():
        if rec.get("status") != "stopped_out":
            continue
        prev = prev_tracked.get(tk)
        if prev is not None and prev.get("exit_date") == rec.get("exit_date"):
            continue                          # 上次已經記過這筆
        entry = rec.get("entry_price")
        exitp = rec.get("exit_price")
        if entry is None or exitp is None or entry <= 0:
            continue
        out.append({
            "ticker": tk,
            "name": rec.get("name", ""),
            "entry_date": rec.get("first_seen"),
            "entry_price": entry,
            "exit_date": rec.get("exit_date"),
            "exit_price": exitp,
            "ret_pct": round(exitp / entry - 1.0, 6),
        })
    return out


def merge_history(prev_trades: list[dict], new_trades: list[dict]) -> list[dict]:
    """append-only，用 (ticker, entry_date) 去重——同一輪重跑 `build_lists.py`
    不會把同一筆出場疊加兩次。"""
    seen = {(t["ticker"], t["entry_date"]) for t in prev_trades}
    merged = list(prev_trades)
    for t in new_trades:
        key = (t["ticker"], t["entry_date"])
        if key not in seen:
            merged.append(t)
            seen.add(key)
    return merged


def _month(d: str) -> str:
    return d[:7] if d else ""


def compute_stats(history: list[dict], cost: float = DEFAULT_COST) -> dict:
    """整體 + 月度（出場月）統計。樣本 < `N_MIN` 時整體勝率/期望值顯示 None
    （呼叫端畫成「—」），月度表不受這個門檻——月度本來就是給人看趨勢，
    不是給機器判斷「能不能信」。"""
    n = len(history)
    if n == 0:
        return {"n": 0, "win_rate": None, "avg_ret_gross": None,
                "expectancy_net": None, "vs_backtest": None, "by_month": []}

    df = pd.DataFrame(history)
    df["ret_net"] = df["ret_pct"] - cost
    win_rate = float((df["ret_pct"] > 0).mean())
    avg_gross = float(df["ret_pct"].mean())
    expectancy_net = float(df["ret_net"].mean())

    enough = n >= N_MIN
    gap_pp = (win_rate - BACKTEST_BASELINE["win_rate"]) * 100 if enough else None
    vs_backtest = {
        "backtest_win_rate": BACKTEST_BASELINE["win_rate"],
        "gap_pp": gap_pp,
        "diverging": bool(enough and abs(gap_pp) >= DIVERGE_PP),
    }

    df["exit_month"] = df["exit_date"].map(_month)
    by_month = []
    for ym, g in df.groupby("exit_month", sort=True):
        by_month.append({
            "ym": ym, "n": int(len(g)),
            "win_rate": float((g["ret_pct"] > 0).mean()),
            "avg_ret_net": float(g["ret_net"].mean()),
        })

    return {
        "n": n,
        "win_rate": win_rate if enough else None,
        "avg_ret_gross": avg_gross if enough else None,
        "expectancy_net": expectancy_net if enough else None,
        "n_min": N_MIN,
        "vs_backtest": vs_backtest if enough else None,
        "by_month": by_month,
    }


def build(prev_payload: dict, prev_tracked: dict, new_tracked: dict,
         cost: float = DEFAULT_COST) -> dict:
    """`prev_payload` = 上次的 `data/derived/swing_paper.json`（沒有就傳 `{}`）。
    回傳新版全量（`trades` 歷史 + `stats`）。"""
    prev_trades = prev_payload.get("trades") or []
    new_exits = find_new_exits(prev_tracked, new_tracked)
    trades = merge_history(prev_trades, new_exits)
    stats = compute_stats(trades, cost)
    return {
        "_meta": {
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "cost": cost,
            "note": "長波段模擬單（輕量版）——真實市場價格逐日累積的已實現結果，"
                    "不是回測。進場口徑＝訊號日收盤成交（同 swing_stops.py 的進場代理）。",
        },
        "trades": trades,
        "stats": stats,
    }
