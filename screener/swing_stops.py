"""長波段候選池「出場觀察表」——移動停損，不是持倉追蹤（2026-09-12，使用者要求）。

**不需要使用者輸入買入日期/價格。** 系統用「這檔第一次通過候選池六條件的那天」
當進場代理（跟 `research/backtest_longswing.py` 回測用的定義一致），之後逐日追蹤：

    停損 = max(進場當天算好的 §5.3 停損位, 進場後最高價 − TRAIL_ATR_MULT × 進場當天 ATR14)

只漲不跌（比照 tw-swing `H2-trailatr2`：`run_high - trail_atr × 進場日 ATR14`，
`atr0` 固定在進場那天，之後不重算——2026-09-12 實測過，若拿 §5.3 那條含 50MA 的
公式每週重算來當移動停損，正常拉回就會讓公式瞬間跳到現價之上、幾乎必然秒殺，
所以移動的只有 `run_high`，不是整條公式）。

**候選池把它移除（六條件不再全過）不會讓這裡的追蹤立刻停止**——移動停損繼續用
價格走勢更新，直到真的跌破停損價才算「出場」，這樣才看得到「被移除之後接下來
怎麼走」。停損觸發後那筆紀錄凍結，不再更新（除非之後重新達標，開新一輪追蹤）。

只是觀察用的參考數字，跟 §5.3 本身一樣「不回答會不會賺」，不是買賣建議。
"""
from __future__ import annotations

import pandas as pd

from screener.candidate_pool import _bare, atr14

TRAIL_ATR_MULT = 2.0   # 比照 tw-swing H2-trailatr2


def _today_ohlc(prices_adj: pd.DataFrame, asof: pd.Timestamp) -> pd.DataFrame:
    d = prices_adj.copy()
    d["date"] = pd.to_datetime(d["date"])
    d["ticker"] = _bare(d["ticker"])
    d = d[d["date"] == pd.Timestamp(asof)]
    return d.drop_duplicates("ticker", keep="last").set_index("ticker")[
        ["open", "high", "low", "close"]]


def update_stops(prev: dict, pool: list[dict], prices_adj: pd.DataFrame,
                 asof: pd.Timestamp) -> dict:
    """`prev` = 上次的 `data/derived/swing_stops.json`（沒有就傳 `{}`）。回傳新版全量。"""
    asof = pd.Timestamp(asof).normalize()
    today = _today_ohlc(prices_adj, asof)
    atr_today = atr14(prices_adj, asof)
    pool_by_tk = {p["ticker"]: p for p in pool}
    tracked = dict(prev.get("tracked", {}))
    out: dict[str, dict] = {}

    # 1) 既有追蹤中的（含已出候選池但還在看的）：更新 run_high / 停損 / 是否觸發
    today_str = asof.date().isoformat()
    for tk, rec in tracked.items():
        if rec.get("status") == "stopped_out":
            out[tk] = rec                    # 已出場的凍結，不再更新
            continue
        if rec.get("last_update") == today_str:
            # 🔴 同一天重算過一次了（本機手動重跑常見；正式排程一天只跑一次不會踩到）——
            # 不能再跑一次遞增邏輯，run_high 已經含當天最高價，再跑會把「進場當天不套
            # 移動停損」這條規則繞過去，拿當天自己的高點回頭砍自己（2026-09-12 實測抓到：
            # 本機同一個 trading_date 重跑兩次，4 檔無端被判定跌破停損）。
            out[tk] = rec
            continue
        if tk not in today.index:
            out[tk] = rec                    # 今天沒價格資料（停牌等）→ 原樣保留
            continue
        row = today.loc[tk]
        # 🔴 「收盤後才更新」（比照 tw-swing engine.py）：今天的停損檢查要用「昨天收盤
        # 為止」建立好的停損位，不能拿今天自己的最高價現算現抬、回頭砍今天自己的最低價
        # ——那是未來函數（今天盤中創高、當天又拉回，不該反過來變成今天被自己打停損的
        # 理由）。今天的高點只用來墊高「明天要用」的停損位，順序不能反。
        effective_stop = rec["trail_stop"]
        still_candidate = tk in pool_by_tk
        base = {**rec, "last_close": round(float(row["close"]), 2), "last_update": today_str}
        if float(row["low"]) <= effective_stop:
            out[tk] = {**base, "status": "stopped_out",
                      "exit_date": asof.date().isoformat(), "exit_price": round(effective_stop, 2)}
        else:
            run_high = max(rec["run_high"], float(row["high"]))
            new_trail = max(effective_stop, run_high - TRAIL_ATR_MULT * rec["atr0"])
            dropped_date = (None if still_candidate
                           else rec.get("dropped_date") or asof.date().isoformat())
            out[tk] = {**base, "run_high": run_high, "trail_stop": round(new_trail, 2),
                      "status": "candidate" if still_candidate else "dropped_from_pool",
                      "dropped_date": dropped_date}

    # 2) 新進候選（沒追蹤過，或前一輪已經 stopped_out、現在重新達標）→ 開新一輪。
    # 🔴 剛剛在上面第 1 步同一天觸發停損的不算「重新達標」——同一天沒有「先停損出場、
    # 又立刻重新進場」這種事，至少要等到下一個交易日（跟回測 open_pos 的邏輯一致：
    # 一週最多處理一次進場，不會同一天出場又進場）。
    for tk, p in pool_by_tk.items():
        existing = out.get(tk)
        if existing is not None:
            if existing.get("status") != "stopped_out":
                continue
            if existing.get("exit_date") == today_str:
                continue
        if tk not in today.index:
            continue
        a0 = atr_today.get(tk)
        if pd.isna(a0):
            continue                          # ATR 還在暖機，開不了新一輪（跟回測同條件）
        row = today.loc[tk]
        out[tk] = {
            "first_seen": asof.date().isoformat(),
            "entry_price": round(float(row["close"]), 2),
            "atr0": round(float(a0), 4),
            "run_high": float(row["high"]),
            "trail_stop": round(float(p.get("risk_stop") or row["close"]), 2),
            "last_close": round(float(row["close"]), 2), "last_update": today_str,
            "status": "candidate", "dropped_date": None,
            "exit_date": None, "exit_price": None,
        }

    return {
        "_meta": {"asof": asof.date().isoformat(), "trail_atr_mult": TRAIL_ATR_MULT,
                 "note": "移動停損觀察表，不是持倉追蹤、不是買賣建議——見 app 頁尾說明。"},
        "tracked": out,
    }
