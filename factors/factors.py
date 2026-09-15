"""季度財報 → 因子。

M0.3 從 `tw-swing/src/twswing/value/factors.py` 搬走（tw-swing 端已刪除）。
純函式，只依賴 numpy / pandas，不讀磁碟。

## 為什麼比 4 季前、不比上一季

損益表是季度單獨值，季節性很強（Q4 常有獎金/打呆、Q1 有農曆年）。F-Score 的
「變好了沒」一律跟**去年同期（shift 4）**比，不跟上一季比。

## TTM

流量項（營收/EPS/淨利/毛利/OCF/capex）取**滾動 4 季加總**＝ TTM；存量項
（總資產/權益/負債）取當期值。TTM 不足 4 季的留 NaN——寧可缺值，不要拿
半年當一年。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

_FLOW = ["revenue", "eps", "net_income", "gross_profit", "op_income",
         "pretax_income", "ocf", "ocf_net", "capex"]


def _ttm(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(np.nan, index=df.index)
    return (df.groupby("ticker", sort=False)[col]
              .transform(lambda s: s.rolling(4, min_periods=4).sum()))


def _deaccum_ytd(q: pd.DataFrame, col: str, tickers: set[str]) -> pd.Series:
    """把「當年累計」（YTD）的損益流量項還原成單季值——同 ticker、同曆年內
    `val − 上一季 val`，曆年首季（Q1）保持原值。

    只對 `tickers` 內、`period_end` 在 2026 年起、且該 (ticker, 曆年) 序列**年內
    單調不減**的群組動手。理由：金控的 FinMind `IncomeAfterTax` 2023–2025 是單季值
    （Q4 常因獎金/提存而下降），2026 起改成 YTD 累計（實測 2881/2882 等）。限定
    2026+ 才動、又要單調不減，確保永遠不會誤傷已知正確的單季歷史。"""
    s = q[col].astype("float64")
    if not tickers:
        return s
    yr = q["period_end"].dt.year
    out = s.copy()
    for (tk, y), idx in q.groupby([q["ticker"], yr], sort=False).groups.items():
        if tk not in tickers or y < 2026 or len(idx) < 2:
            continue
        vals = s.loc[idx]
        if (vals.diff().dropna() >= 0).all():             # 年內單調不減 → 視為 YTD 累計
            out.loc[idx] = vals.diff().fillna(vals.iloc[0])
    return out


def quarterly_factors(q: pd.DataFrame, fin_tickers: set[str] | None = None,
                      shares: dict | None = None) -> pd.DataFrame:
    """輸入 `load_quarterly()` 的面板，輸出每 (ticker, period_end) 一列的因子。

    回傳欄位（除既有）：
      ttm_revenue/eps/net_income/gross_profit/ocf/capex/fcf、
      roe、roa、gross_margin、debt_ratio、current_ratio、asset_turnover、
      rev_yoy、fcf_ttm、
      f_score（0–9，缺項依算出的項數換算回 9 分制）、f_score_partial（缺幾項，
      只顯示不進門檻）、f_* 各分項（缺資料是 NaN，不是悄悄算 0 分）、
      normalized_eps（近 5 年年度 EPS 均值）。
    """
    q = q.sort_values(["ticker", "period_end"]).reset_index(drop=True).copy()
    fin_tickers = fin_tickers or set()

    # 面額變更 / 股票分割：上游沒還原 → 分割日前的每股 EPS ÷ factor，搬到最新股本
    # 基準，normalized_EPS / TTM_EPS / 年度 EPS 才跟分割後的股價同一把尺（見
    # reference.corporate_actions）。無已知分割的 ticker 完全不受影響。
    from reference.corporate_actions import adjust_per_share
    q = adjust_per_share(q, ["eps"], date_col="period_end")

    # 金融軌：金控的 FinMind 淨利 2026 起改用 YTD 累計口徑 → 還原單季
    # （見 _deaccum_ytd，限 2026+ 且年內單調不減）。只動 net_income——金控 revenue
    # 在現行 bundle 品質不穩，且不進任何定存門檻 / 排序項，不碰。
    if fin_tickers and "net_income" in q.columns:
        q["net_income"] = _deaccum_ytd(q, "net_income", fin_tickers)

    # 金融軌：FinMind 近期對金控完全沒給 EPS type → 用「單季淨利 ÷ 股數」補。
    # 股數來自 universe（market_cap / close），非金融不受影響。
    if fin_tickers and shares and "eps" in q.columns:
        sh = q["ticker"].map(shares)
        est_eps = q["net_income"] / sh
        need = q["ticker"].isin(fin_tickers) & q["eps"].isna() & sh.notna()
        q.loc[need, "eps"] = est_eps[need]

    for c in _FLOW:
        q[f"ttm_{c}"] = _ttm(q, c)
    # OCF 兩個來源（CashFlowsFromOperatingActivities / NetCashInflow…），擇有值的
    q["ttm_ocf"] = q["ttm_ocf"].fillna(q["ttm_ocf_net"])
    q["ttm_fcf"] = q["ttm_ocf"] - q["ttm_capex"].abs()

    g = q.groupby("ticker", sort=False)

    q["roe"] = q["ttm_net_income"] / q["equity_parent"]
    q["roa"] = q["ttm_net_income"] / q["total_assets"]
    q["gross_margin"] = q["ttm_gross_profit"] / q["ttm_revenue"]
    q["debt_ratio"] = q["total_liabilities"] / q["total_assets"]
    q["current_ratio"] = q["current_assets"] / q["current_liabilities"]
    q["asset_turnover"] = q["ttm_revenue"] / q["total_assets"]
    q["rev_yoy"] = q["ttm_revenue"] / g["ttm_revenue"].shift(4) - 1.0

    # ── Piotroski F-Score（跟去年同期比）───────────────────────
    roa_p = g["roa"].shift(4)
    dr_p = g["debt_ratio"].shift(4)
    cr_p = g["current_ratio"].shift(4)
    gm_p = g["gross_margin"].shift(4)
    at_p = g["asset_turnover"].shift(4)

    def _pt_item(cond: pd.Series, *sources: pd.Series) -> pd.Series:
        """Piotroski 分項：cond 轉 0.0/1.0；`sources`（比較用到的欄位）任一為 NaN
        → 整格 NaN，不能悄悄變成 0（`(NaN > x)` 在 pandas 就是 False，直接
        `.astype(float)` 會把「缺資料」跟「真的沒過」混在一起——2026-09-15 修，
        見 `f_score_partial`）。"""
        nan_mask = sources[0].isna()
        for s in sources[1:]:
            nan_mask = nan_mask | s.isna()
        return cond.astype("float").mask(nan_mask)

    q["f_roa"] = _pt_item(q["ttm_net_income"] > 0, q["ttm_net_income"])
    q["f_ocf"] = _pt_item(q["ttm_ocf"] > 0, q["ttm_ocf"])
    q["f_droa"] = _pt_item(q["roa"] > roa_p, q["roa"], roa_p)
    q["f_accrual"] = _pt_item(q["ttm_ocf"] > q["ttm_net_income"], q["ttm_ocf"], q["ttm_net_income"])
    q["f_leverage"] = _pt_item(q["debt_ratio"] < dr_p, q["debt_ratio"], dr_p)
    q["f_liquidity"] = _pt_item(q["current_ratio"] > cr_p, q["current_ratio"], cr_p)
    q["f_margin"] = _pt_item(q["gross_margin"] > gm_p, q["gross_margin"], gm_p)
    q["f_turnover"] = _pt_item(q["asset_turnover"] > at_p, q["asset_turnover"], at_p)
    f_cols = ["f_roa", "f_ocf", "f_droa", "f_accrual", "f_leverage",
              "f_liquidity", "f_margin", "f_turnover"]
    if "capital_stock" in q.columns:
        cs_p = g["capital_stock"].shift(4)
        q["f_noissue"] = _pt_item(q["capital_stock"] <= cs_p * 1.001, q["capital_stock"], cs_p)
        f_cols = f_cols + ["f_noissue"]

    # 固定 9 分制：不管實際算出幾項分項（capital_stock 整欄缺，或任一分項因
    # 缺資料變 NaN——金融業結構上沒有 gross_margin/current_ratio），一律用
    # 「算出的分數 ÷ 算出的項數 × 9」換算，換算後才跟 `< 6` 的門檻比，
    # 不會因為缺項就被拉低。`f_score_partial` 記缺幾項——只顯示、不進門檻，
    # 比照既有的 `cyclical_peak_flag`/`industry_headwind`。
    n_valid = q[f_cols].notna().sum(axis=1)
    raw = q[f_cols].sum(axis=1, min_count=1)
    q["f_score"] = (raw / n_valid * 9.0).where(n_valid > 0)
    q["f_score_partial"] = 9 - n_valid

    # 去年同期算不出來的前 4 季，F-Score 沒有意義 → NaN
    q.loc[roa_p.isna(), "f_score"] = np.nan
    q.loc[roa_p.isna(), "f_score_partial"] = np.nan

    # normalized EPS：到當期年份之前、最近 5 個完整年度的年度 EPS 均值
    q["normalized_eps"] = _normalized_eps(q, annual_eps(q))
    return q


def annual_eps(q: pd.DataFrame) -> pd.DataFrame:
    """年度 EPS = 該日曆年四季 EPS 加總（要滿 4 季才算）。
    回傳 `[ticker, _year, annual_eps]`。"""
    tmp = q[["ticker", "period_end", "eps"]].copy()
    tmp["_year"] = tmp["period_end"].dt.year
    cnt = tmp.groupby(["ticker", "_year"])["eps"].count()
    s = tmp.groupby(["ticker", "_year"])["eps"].sum()
    out = s.where(cnt >= 4).rename("annual_eps").reset_index()
    return out


def _normalized_eps(q: pd.DataFrame, ann: pd.DataFrame, years: int = 5) -> pd.Series:
    """每 (ticker, period_end) 取「該期別年份之前 `years` 個完整年度」的年度 EPS
    均值——Shiller CAPE 精神，攤平景氣循環。"""
    ann = ann.dropna(subset=["annual_eps"]).sort_values(["ticker", "_year"])
    roll = (ann.groupby("ticker")["annual_eps"]
               .transform(lambda s: s.rolling(years, min_periods=3).mean()))
    ann = ann.assign(_norm=roll)
    lut = ann.set_index(["ticker", "_year"])["_norm"].to_dict()
    yr = q["period_end"].dt.year - 1        # 只信「已結束」的年度
    return pd.Series(
        [lut.get((t, y), np.nan) for t, y in zip(q["ticker"], yr)],
        index=q.index)


def dividend_factors(div: pd.DataFrame, ann_eps: pd.DataFrame | None = None) -> pd.DataFrame:
    """股利表 → 每 ticker 一列的定存因子（用「最新一年」為基準）。

    回傳 `[ticker, div_years, div_cut_5y, last_cash_dividend, avg_cash_dividend_3y,
             earnings_div_ratio, payout_ratio_ttm]`。
    """
    div = div.sort_values(["ticker", "year"]).copy()
    rows = []
    for tk, g in div.groupby("ticker", sort=False):
        g = g[g["year"] <= g["year"].max()]
        cash = g.set_index("year")["cash_dividend"]
        # 連續配息年數：從最新年往回數「連續 > 0」
        yrs = 0
        for y in sorted(cash.index, reverse=True):
            if cash.get(y, 0) > 0:
                yrs += 1
            else:
                break
        # 減配判定（某年 < 前一年 × 0.9）。PRD 原文「近 5 年無減配」太鈍——
        # 會永久記恨一次性衝擊（金控 2022 防疫險 + 升息債損，之後逐年回升創高）。
        # 改為：近 3 年內有減配 → 一律剔除；第 4–5 年前的減配 → 只有「最新股利
        # 仍低於減配前自身高點 95%」（沒真的回復）才算數。全業種適用。
        s = cash.sort_index()
        chg = s < s.shift(1) * 0.9
        cut_recent = bool(chg.tail(3).any())
        older = chg.iloc[-5:-3] if len(chg) >= 4 else chg.iloc[0:0]
        peak6 = s.tail(6).max()
        recovered = bool(len(s) and s.iloc[-1] >= peak6 * 0.95)
        cut = cut_recent or (bool(older.any()) and not recovered)
        last = float(cash.sort_index().iloc[-1]) if len(cash) else np.nan
        avg3 = float(cash.sort_index().tail(3).mean()) if len(cash) else np.nan
        ce = g.set_index("year")["cash_earnings"].sort_index()
        cs = g.set_index("year").get("cash_surplus")
        if cs is not None:
            cs = cs.sort_index()
            tot = (ce.tail(3).sum() + cs.tail(3).sum())
            edr = float(ce.tail(3).sum() / tot) if tot > 0 else np.nan
        else:
            edr = np.nan
        rows.append({"ticker": tk, "div_years": yrs, "div_cut_5y": cut,
                     "last_cash_dividend": last, "avg_cash_dividend_3y": avg3,
                     "earnings_div_ratio": edr})
    out = pd.DataFrame(rows)
    if ann_eps is not None and not out.empty:
        latest_eps = (ann_eps.dropna(subset=["annual_eps"])
                             .sort_values("_year").groupby("ticker").tail(1)
                             .set_index("ticker")["annual_eps"])
        out["payout_ratio_ttm"] = out.apply(
            lambda r: (r["last_cash_dividend"] / latest_eps.get(r["ticker"], np.nan))
            if latest_eps.get(r["ticker"], 0) and latest_eps.get(r["ticker"]) > 0
            else np.nan, axis=1)
    return out
