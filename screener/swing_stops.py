"""長波段候選池「出場觀察表」——移動停損，不是持倉追蹤（2026-09-12，使用者要求）。

**不需要使用者輸入買入日期/價格。** 系統用「這檔第一次通過候選池六條件的那天」
當訊號日，**次一個交易日開盤才算進場**（2026-09-14 修正——見下方「進場口徑」），
之後逐日追蹤：

    停損 = max(訊號日算好的 §5.3 停損位, 進場後最高價 − TRAIL_ATR_MULT × 進場當天 ATR14)

只漲不跌（比照 tw-swing `H2-trailatr2`：`run_high - trail_atr × 進場日 ATR14`，
`atr0` 固定在進場那天，之後不重算——2026-09-12 實測過，若拿 §5.3 那條含 50MA 的
公式每週重算來當移動停損，正常拉回就會讓公式瞬間跳到現價之上、幾乎必然秒殺，
所以移動的只有 `run_high`，不是整條公式）。

## 🔴 進場口徑：訊號日次一交易日開盤，不是訊號當天收盤（2026-09-14 修正）

**這裡曾經直接拿「達標當天的收盤價」當進場價，那是錯的——使用者關機前一句
「模擬單依據策略買的到原則嗎」問出來的。** 訊號當天收盤後才算得出這檔達標，
不可能回頭用當天的收盤價下單，那是看得到、買不到的價格。跟 tw-swing 已經
踩過的坑一樣（`docs/paper/README.md` 系列：「訊號日收盤無條件成交」是假說
不是成交）。

`research/backtest_longswing.py` 實際採用、驗證過的格是 `entry_mode=
"next_open"`——訊號日之後下一個交易日**無條件**用開盤價進場，這才是真的
買得到的口徑。本模組現在照這個口徑走：達標當天先開一筆 `pending_entry`
（只記訊號日 + §5.3 停損參考位，還不算進場），下一個交易日用那天的開盤價
才轉正成 `candidate`（真正開始追蹤移動停損）。跟回測一樣，若次日開盤已經
跌破訊號日算的停損位，這筆訊號放棄（不合理的進場，不開倉）。

**候選池把它移除（六條件不再全過）不會讓已經進場的追蹤立刻停止**——移動停損
繼續用價格走勢更新，直到真的跌破停損價才算「出場」，這樣才看得到「被移除之後
接下來怎麼走」。停損觸發後那筆紀錄凍結，不再更新（除非之後重新達標，開新
一輪追蹤）。**還在等進場（`pending_entry`）的訊號如果候選池當天就把它移除，
一樣照計畫次日開盤進場**——跟回測一致：訊號一旦成立，進場與否只看次日開盤
價格本身（有沒有跌破停損），不會因為隔一天條件不再成立而取消。

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
    today_str = asof.date().isoformat()

    # 1) 昨天（或更早）發訊號、今天要轉正進場的 pending_entry → 用今天開盤價。
    # 跟回測 next_open 一致：訊號一旦成立就無條件次日開盤進場，不會因為今天候選池
    # 條件不再成立就取消——這裡故意不看 `pool_by_tk`。
    for tk, rec in tracked.items():
        if rec.get("status") != "pending_entry":
            continue
        if rec["signal_date"] >= today_str:
            out[tk] = rec                    # 訊號當天，還沒到「次一交易日」
            continue
        if tk not in today.index or pd.isna(today.loc[tk, "open"]):
            out[tk] = rec                     # 今天沒開盤資料（停牌等）→ 明天再試
            continue
        row = today.loc[tk]
        open_px = float(row["open"])
        stop_ref = rec["risk_stop_ref"]
        if open_px <= stop_ref:
            # 訊號日收盤到次日開盤之間已經跌破當初算的停損位——不合理的進場，
            # 跟回測 abandoned_below_stop 一致：這筆訊號放棄，不留紀錄。
            continue
        a0 = atr_today.get(tk)
        if pd.isna(a0):
            out[tk] = rec                     # ATR 還在暖機，明天再試
            continue
        out[tk] = {
            "name": rec.get("name", ""),
            "first_seen": rec["signal_date"],
            "entry_date": today_str,
            "entry_price": round(open_px, 2),
            "atr0": round(float(a0), 4),
            "run_high": float(row["high"]),
            "trail_stop": round(stop_ref, 2),
            "last_close": round(float(row["close"]), 2), "last_update": today_str,
            "status": "candidate", "dropped_date": None,
            "exit_date": None, "exit_price": None,
        }

    # 2) 已經進場、正在追蹤中的（含已出候選池但還在看的）：更新 run_high / 停損 / 是否觸發
    for tk, rec in tracked.items():
        if rec.get("status") == "pending_entry":
            continue                          # 上面 1) 已經處理過
        if rec.get("status") == "stopped_out":
            out[tk] = rec                     # 已出場的凍結，不再更新
            continue
        if tk in out:
            continue                          # 這次剛從 pending 轉正，今天不再重算
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

    # 3) 今天新達標（沒追蹤過，或前一輪已經 stopped_out、現在重新達標）→ 開 pending_entry，
    # 明天開盤才轉正（見模組 docstring「進場口徑」）。
    # 🔴 剛剛在上面第 2 步同一天觸發停損的不算「重新達標」——同一天沒有「先停損出場、
    # 又立刻重新進場」這種事，至少要等到下一個交易日（跟回測 open_pos 的邏輯一致）。
    for tk, p in pool_by_tk.items():
        existing = out.get(tk)
        if existing is not None:
            if existing.get("status") != "stopped_out":
                continue
            if existing.get("exit_date") == today_str:
                continue
        elif tk in tracked and tracked[tk].get("status") == "pending_entry":
            continue                          # 已經在排隊等進場，不用再開一筆
        if p.get("risk_stop") is None:
            continue                          # 沒有停損參考位，開不了 pending（跟回測 stop NaN 一致）
        out[tk] = {
            "name": p.get("name", ""),
            "status": "pending_entry",
            "signal_date": today_str,
            "risk_stop_ref": float(p.get("risk_stop")) if p.get("risk_stop") is not None else None,
        }

    return {
        "_meta": {"asof": asof.date().isoformat(), "trail_atr_mult": TRAIL_ATR_MULT,
                 "note": "移動停損觀察表，不是持倉追蹤、不是買賣建議——見 app 頁尾說明。"
                         "進場口徑＝訊號日次一交易日開盤（跟回測 next_open 一致）。"},
        "tracked": out,
    }
