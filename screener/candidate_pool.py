"""主動選股候選池（PRD §5，v3.1 狀態型）。

**這不是推薦清單，是候選池。** 守則（PRD §5.1）：
  1. 不給 verdict（推薦／不推薦）、不給目標價／合理價
  2. 不合成單一總分、不排名次、不配權重
  3. 🔴 每檔強制並列「支持 / 反對」——反對欄空 → 標「檢查不足」不是「完美」
  4. 必給失效條件檢查表

CANSLIM（歐尼爾）+ Minervini 趨勢模板，全部寫成**狀態**。實驗 D 驗證過
（2019+ 每週中位數 3–5 檔、空頭近空——可行）。邏輯搬自
`research/candidate_pool_survey.py`，改讀 bundle。

⚠️ **§5.3 風控推導不是估值**：停損位 / 可買上限只回答「這個進場點承擔多少風險」，
   **不回答會不會賺**——這個區間沒有回測支撐。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# CANSLIM 門檻（PRD §5.2.1）
EPS_YOY_MIN = 0.25
ROE_MIN = 0.15
FSCORE_MIN = 6
INST_WINDOW = 20           # 法人淨買超回看交易日
RS_PCTILE_MIN = 70         # Minervini ⑧
ATR_N = 14
STOP_BUFFER = 0.10         # §5.3 可買上限 = 停損位 ÷ (1 − 10%)


def _bare(s: pd.Series) -> pd.Series:
    return s.astype(str).str.split(".").str[0]


def _pivot_close(prices_adj: pd.DataFrame) -> pd.DataFrame:
    d = prices_adj.copy()
    d["date"] = pd.to_datetime(d["date"])
    d["ticker"] = _bare(d["ticker"])
    return d.pivot_table(index="date", columns="ticker", values="close").sort_index()


def trend_template(prices_adj: pd.DataFrame, index_0050: pd.DataFrame,
                   asof: pd.Timestamp) -> pd.DataFrame:
    """Minervini 八條（全狀態）+ 位置揭露。回傳 index=ticker 的 DataFrame：
    `t1..t8`（bool）、`trend_cnt`、`dist_50ma` / `dist_52w_high` / `dist_200ma`（%）。"""
    px = _pivot_close(prices_adj)
    px = px[px.index <= pd.Timestamp(asof)]
    idx = index_0050.copy()
    idx["date"] = pd.to_datetime(idx["date"])
    ic = idx.set_index("date")["close"].sort_index()
    ic = ic[ic.index <= pd.Timestamp(asof)]

    last = px.iloc[-1]
    ma50 = px.rolling(50).mean().iloc[-1]
    ma150 = px.rolling(150).mean().iloc[-1]
    ma200 = px.rolling(200).mean().iloc[-1]
    ma200_1m = px.rolling(200).mean().shift(21).iloc[-1]
    lo52 = px.rolling(252).min().iloc[-1]
    hi52 = px.rolling(252).max().iloc[-1]

    ret126 = px.iloc[-1] / px.shift(126).iloc[-1] - 1.0
    idx126 = ic.iloc[-1] / ic.iloc[-127] - 1.0 if len(ic) > 127 else np.nan
    rel = ret126 - idx126
    rs_pctile = rel.rank(pct=True) * 100

    t = pd.DataFrame(index=px.columns)
    t["t1_above_150_200"] = (last > ma150) & (last > ma200)
    t["t2_150_above_200"] = ma150 > ma200
    t["t3_200_rising"] = ma200 > ma200_1m
    t["t4_50_above_150_200"] = (ma50 > ma150) & (ma150 > ma200)
    t["t5_above_50"] = last > ma50
    t["t6_30pct_above_52w_low"] = last >= lo52 * 1.30
    t["t7_within_25pct_52w_high"] = last >= hi52 * 0.75
    t["t8_rs_above_70"] = rs_pctile > RS_PCTILE_MIN
    t["trend_cnt"] = t[[c for c in t.columns if c.startswith("t")]].sum(axis=1).astype(int)
    t["dist_50ma"] = last / ma50 - 1.0
    t["dist_52w_high"] = last / hi52 - 1.0
    t["dist_200ma"] = last / ma200 - 1.0
    t["close"] = last
    t["low_20w"] = px.rolling(100).min().iloc[-1]     # 20 週 ≈ 100 交易日
    return t


def atr14(prices_adj: pd.DataFrame, asof: pd.Timestamp) -> pd.Series:
    """ATR14（Wilder，用還原 OHLC）→ index=ticker。"""
    d = prices_adj.copy()
    d["date"] = pd.to_datetime(d["date"])
    d["ticker"] = _bare(d["ticker"])
    d = d[d["date"] <= pd.Timestamp(asof)].sort_values(["ticker", "date"])
    d["pc"] = d.groupby("ticker")["close"].shift(1)
    tr = pd.concat([
        d["high"] - d["low"],
        (d["high"] - d["pc"]).abs(),
        (d["low"] - d["pc"]).abs(),
    ], axis=1).max(axis=1)
    d["tr"] = tr
    return (d.groupby("ticker")["tr"]
             .apply(lambda s: s.tail(ATR_N).mean() if len(s) >= ATR_N else np.nan))


def institutional_net20(chips: pd.DataFrame, asof: pd.Timestamp) -> pd.Series:
    """法人（外資 + 投信）近 `INST_WINDOW` 交易日淨買超合計 → index=ticker。"""
    c = chips.copy()
    c["date"] = pd.to_datetime(c["date"])
    c["ticker"] = _bare(c["ticker"])
    c = c[c["date"] <= pd.Timestamp(asof)].sort_values(["ticker", "date"])
    c["net"] = c["foreign_net"].fillna(0) + c["trust_net"].fillna(0)
    return (c.groupby("ticker")["net"]
             .apply(lambda s: s.tail(INST_WINDOW).sum() if len(s) >= INST_WINDOW else np.nan)
             .rename("inst_net20"))


def canslim_fundamental(qf: pd.DataFrame, asof: pd.Timestamp) -> pd.DataFrame:
    """CANSLIM 基本面（PRD §5.2.1）逐檔狀態。回傳 index=ticker 的 bool 欄 + 數值。"""
    q = qf.copy()
    q["ticker"] = _bare(q["ticker"])
    q = q[q["disclosure_date"] <= pd.Timestamp(asof)].sort_values(["ticker", "period_end"])
    g = q.groupby("ticker", sort=False)
    q["eps_yoy_q"] = q["eps"] / g["eps"].shift(4) - 1.0
    q["ttm_eps_3y"] = g["ttm_eps"].shift(12)
    q["gm_p1"] = g["gross_margin"].shift(1)
    q["gm_p2"] = g["gross_margin"].shift(2)
    latest = g.tail(1).set_index("ticker")

    out = pd.DataFrame(index=latest.index)
    out["eps_yoy_q"] = latest["eps_yoy_q"]
    out["roe"] = latest["roe"]
    out["f_score"] = latest["f_score"]
    out["gross_margin"] = latest["gross_margin"]
    out["c_eps_yoy"] = latest["eps_yoy_q"] > EPS_YOY_MIN
    out["c_eps_3y_growth"] = (latest["ttm_eps"] > latest["ttm_eps_3y"]) & (latest["ttm_eps"] > 0)
    out["c_roe"] = latest["roe"] > ROE_MIN
    out["c_gm_not_deteriorating"] = ~(
        (latest["gross_margin"] < latest["gm_p1"]) & (latest["gm_p1"] < latest["gm_p2"]))
    out["c_fscore"] = latest["f_score"] >= FSCORE_MIN
    return out


def revenue_yoy(revenue: pd.DataFrame) -> pd.Series:
    """月營收 YoY（bundle 是單月快照——`revenue_accel`「加速」判定要 revenue 歷史，
    尚未進 bundle，v1 只用 YoY > 0）→ index=ticker。"""
    r = revenue.copy()
    r["ticker"] = _bare(r["ticker"])
    r = r.set_index("ticker")
    return (r["revenue"] / r["revenue_last_year"] - 1.0).rename("revenue_yoy")


def _support_oppose(rec: dict) -> tuple[list[str], list[str]]:
    """守則 3：每檔強制並列支持 / 反對——**這裡放的是「進場門檻之外」的判斷證據**，
    不是重述門檻（門檻全過才進池，重述沒資訊量）。反對空 → 呼叫端標『檢查不足』。"""
    support, oppose = [], []
    eps = rec.get("eps_yoy_q")
    rev = rec.get("revenue_yoy")
    d50 = rec.get("dist_50ma")
    d52 = rec.get("dist_52w_high")
    riskp = rec.get("risk_pct_at_close")

    if eps is not None and eps > 0.60:
        support.append(f"季 EPS YoY {eps:+.0%}（遠超 25% 門檻）")
    if rev is not None and rev > 0.20:
        support.append(f"月營收 YoY {rev:+.0%}（成長明確）")
    elif rev is not None and rev < 0.05:
        oppose.append(f"月營收 YoY 僅 {rev:+.0%}（勉強過門檻）")
    if rec.get("inst_net20") and rec["inst_net20"] > 0:
        support.append(f"法人 20 日淨買超 {rec['inst_net20']/1e3:,.0f} 張")
    if d50 is not None and 0 <= d50 <= 0.08:
        support.append(f"距 50MA 僅 {d50:+.0%}（進場點貼近支撐）")
    elif d50 is not None and d50 > 0.20:
        oppose.append(f"距 50MA {d50:+.0%}（乖離大、追漲風險）")
    if d52 is not None and d52 < -0.15:
        support.append(f"距 52 週高 {d52:+.0%}（尚有空間）")
    elif d52 is not None and d52 > -0.03:
        oppose.append(f"距 52 週高僅 {d52:+.0%}（追高風險）")
    if riskp is not None and riskp > 0.12:
        oppose.append(f"到停損位 {riskp:+.0%}（停損位遠、單筆風險高）")
    if rec.get("close") and rec["close"] > 1000:
        oppose.append(f"股價 {rec['close']:.0f} 元（高價股，零股以外難分批）")
    return support, oppose


def build_candidate_pool(qf: pd.DataFrame, prices_adj: pd.DataFrame,
                         index_0050: pd.DataFrame, chips: pd.DataFrame,
                         revenue: pd.DataFrame, universe: set[str] | None,
                         asof: pd.Timestamp | None = None) -> list[dict]:
    """候選池：CANSLIM 基本面 ∩ 月營收 YoY>0 ∩ 法人 20 日淨買超>0 ∩ 趨勢模板 8/8。
    每檔回一個 dict（狀態 + 支持/反對 + 風控 + 失效條件），**無總分、無排名、無 verdict**。
    """
    asof = pd.Timestamp(asof or pd.Timestamp.now()).normalize()
    fund = canslim_fundamental(qf, asof)
    tt = trend_template(prices_adj, index_0050, asof)
    inst = institutional_net20(chips, asof)
    atr = atr14(prices_adj, asof)
    ryoy = revenue_yoy(revenue)

    tickers = fund.index
    if universe is not None:
        tickers = [t for t in tickers if t in universe]

    pool = []
    for tk in tickers:
        if tk not in tt.index:
            continue
        f = fund.loc[tk]
        row = tt.loc[tk]
        rec = {
            "ticker": tk,
            **{k: bool(f[k]) for k in
               ["c_eps_yoy", "c_eps_3y_growth", "c_roe", "c_gm_not_deteriorating", "c_fscore"]},
            "eps_yoy_q": float(f["eps_yoy_q"]) if pd.notna(f["eps_yoy_q"]) else None,
            "roe": float(f["roe"]) if pd.notna(f["roe"]) else None,
            "f_score": float(f["f_score"]) if pd.notna(f["f_score"]) else None,
            "revenue_yoy": float(ryoy.get(tk)) if pd.notna(ryoy.get(tk, np.nan)) else None,
            "c_rev_yoy": bool(ryoy.get(tk, -1) > 0),
            "inst_net20": float(inst.get(tk)) if pd.notna(inst.get(tk, np.nan)) else None,
            "c_inst": bool(inst.get(tk, -1) > 0),
            "trend_cnt": int(row["trend_cnt"]),
            "dist_50ma": _f(row["dist_50ma"]),
            "dist_52w_high": _f(row["dist_52w_high"]),
            "dist_200ma": _f(row["dist_200ma"]),
        }
        # 全部條件都過才進候選池（狀態型，不是打分）
        if not (rec["c_eps_yoy"] and rec["c_eps_3y_growth"] and rec["c_roe"]
                and rec["c_gm_not_deteriorating"] and rec["c_fscore"]
                and rec["c_rev_yoy"] and rec["c_inst"] and rec["trend_cnt"] >= 8):
            continue

        close = float(row["close"])
        ma50 = close / (1 + row["dist_50ma"]) if pd.notna(row["dist_50ma"]) else np.nan
        # §5.3 停損參考位 = max(50MA, 20 週前低, 現價 − 2×ATR14)
        stop = float(np.nanmax([ma50, row["low_20w"],
                                close - 2 * atr.get(tk, np.nan)]))
        rec["risk_stop"] = round(stop, 2) if pd.notna(stop) else None
        rec["risk_pct_at_close"] = _f(close / stop - 1.0) if pd.notna(stop) and stop > 0 else None
        rec["max_buy"] = round(stop / (1 - STOP_BUFFER), 2) if pd.notna(stop) and stop > 0 else None
        rec["close"] = round(close, 2)

        rec["conditions"] = [
            {"項": "季 EPS YoY > 25%", "狀態": "成立"},
            {"項": "近 3 年 TTM EPS 成長", "狀態": "成立"},
            {"項": "ROE > 15%", "狀態": "成立"},
            {"項": "毛利率未連兩季惡化", "狀態": "成立"},
            {"項": "F-Score ≥ 6", "狀態": "成立"},
            {"項": "月營收 YoY > 0", "狀態": "成立"},
            {"項": "法人 20 日淨買超 > 0", "狀態": "成立"},
            {"項": "Minervini 趨勢模板", "狀態": f"{rec['trend_cnt']}/8"},
        ]
        support, oppose = _support_oppose(rec)
        rec["support"] = support
        rec["oppose"] = oppose or ["（未發現反對證據——這代表檢查不足，不代表完美）"]
        rec["invalidation"] = _invalidation(rec)
        pool.append(rec)

    pool.sort(key=lambda r: r["ticker"])          # 代號序——刻意不按任何分數排
    return pool


def _invalidation(rec: dict) -> list[dict]:
    """§5.2.3 失效條件檢查表——對候選標『目前狀態』（v3.1 不追蹤持倉）。"""
    return [
        {"條件": "收盤跌破 50MA", "目前": "已跌破" if rec["dist_50ma"] is not None
         and rec["dist_50ma"] < 0 else "未觸發"},
        {"條件": "趨勢模板 < 5/8", "目前": "已觸發" if rec["trend_cnt"] < 5 else "未觸發"},
        {"條件": "月營收 YoY 轉負", "目前": "已轉負" if (rec["revenue_yoy"] or 0) < 0
         else "未觸發（加速判定待 revenue 歷史進 bundle）"},
        {"條件": "季 EPS YoY 轉負", "目前": "已轉負" if (rec["eps_yoy_q"] or 0) < 0
         else "未觸發"},
    ]


def _f(v) -> float | None:
    return float(v) if v is not None and pd.notna(v) else None
