"""守門員（PRD §10.2）。**大聲失敗，不盡力而為。**

目前只有 G2；G1/G3 在 `fetch_bundle.py`，G5 在 `check_upstream_drift.py`。
"""
from __future__ import annotations

import pandas as pd

#: G2 抽驗名單——都是連續配息、除息幅度明顯的真個股（ETF 不放，raw 序列可能缺）。
G2_SAMPLE = ["2412", "1216", "2884", "2892"]
#: 除息當日未還原收盤相對前一日至少要掉這麼多，才算「看得到跳空」。
G2_MIN_GAP = 0.015
#: 還原序列在同一天的跌幅不得超過這個——超過表示這條「還原序列」根本沒還原。
G2_MAX_ADJ_DROP = 0.010


class GateError(RuntimeError):
    """守門員擋下——停手。"""


def assert_raw_not_adjusted(raw_hist: pd.DataFrame | None,
                            adj_hist: pd.DataFrame | None,
                            div: pd.DataFrame) -> str:
    """G2：`prices_raw_close` 若被誤填成還原序列，填息率會恆等於 100%、定存清單
    全綠、而且**沒有任何東西會報錯**（PRD §10.2）。

    抽 `G2_SAMPLE` 的除息日：
      - 未還原序列：除息當天相對前一交易日應有 ≥ `G2_MIN_GAP` 的跳空
      - 還原序列：同一天跌幅應 ≤ `G2_MAX_ADJ_DROP`（跳空被還原掉了）
    任一檔任一除息日兩條都不成立 → `GateError`。全樣本都拿不到資料 → 也 raise。

    回傳一行人看的摘要（成功時）。
    """
    if raw_hist is None:
        raise GateError("G2：沒有 prices_raw_close——填息率是定存兩道新門檻之一，不能沒有")

    raw = _pivot(raw_hist)
    adj = _pivot(adj_hist) if adj_hist is not None else None
    dv = div.copy()
    dv["ticker"] = dv["ticker"].astype(str)

    checked = 0
    lines: list[str] = []
    for tk in G2_SAMPLE:
        if tk not in raw.columns:
            continue
        s_raw = raw[tk].dropna()
        ev = dv[(dv["ticker"] == tk) & (dv["cash_dividend"] > 0)].sort_values("ex_date")
        for ex in ev["ex_date"].dropna():
            pre = s_raw[s_raw.index < ex]
            post = s_raw[s_raw.index >= ex]
            if pre.empty or post.empty:
                continue
            gap = post.iloc[0] / pre.iloc[-1] - 1.0
            if gap > -G2_MIN_GAP:
                continue  # 這次除息幅度太小（或當天剛好漲），換下一個
            checked += 1
            adj_drop = None
            if adj is not None and tk in adj.columns:
                a = adj[tk].dropna()
                a_pre, a_post = a[a.index < ex], a[a.index >= ex]
                if not a_pre.empty and not a_post.empty:
                    adj_drop = a_post.iloc[0] / a_pre.iloc[-1] - 1.0
            if adj_drop is not None and adj_drop <= -G2_MIN_GAP:
                raise GateError(
                    f"G2：{tk} 除息 {ex.date()} 還原序列也掉了 {adj_drop:.1%}"
                    "——這條『還原序列』沒有還原，或兩條檔案接反了")
            lines.append(f"{tk} {ex.date()}：raw {gap:.1%}"
                         + (f" / adj {adj_drop:+.1%}" if adj_drop is not None else ""))
            break  # 每檔驗一個除息日就夠

    if checked == 0:
        raise GateError(
            f"G2：抽樣名單 {G2_SAMPLE} 在 prices_raw_close 裡都找不到有跳空的除息日"
            "——raw 序列可能是空的、或被誤填成還原序列")
    return "G2 通過（未還原序列有除息跳空）：" + "；".join(lines)


def _pivot(hist: pd.DataFrame) -> pd.DataFrame:
    d = hist.copy()
    d["date"] = pd.to_datetime(d["date"])
    d["ticker"] = d["ticker"].astype(str).str.split(".").str[0]
    return d.pivot_table(index="date", columns="ticker", values="close").sort_index()
