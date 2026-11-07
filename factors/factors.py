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

from screener import quarterly_prep as qp

_FLOW = ["revenue", "eps", "net_income", "gross_profit", "op_income",
         "pretax_income", "ocf", "ocf_net", "capex"]
_STOCK_COLS = ["equity_parent", "total_assets", "total_liabilities",
               "current_assets", "current_liabilities", "capital_stock"]


def _ttm(df: pd.DataFrame, col: str) -> pd.Series:
    return qp.panel_ttm(df, col)


def _safe_div(num, den) -> pd.Series:
    """規模量分母必須為有限正數，非有限結果視為缺值。"""
    valid = den.where((den > 0) & np.isfinite(den))
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        result = num / valid
    return result.where(np.isfinite(result))



_YTD_TOL = 0.10   # net_income 與單季／累計歸母淨利的相對差容忍度


def _deaccum_ytd(q: pd.DataFrame, col: str, tickers: set[str]) -> pd.Series:
    """金融股 2026 年起的 `col`（淨利）若是「當年累計」（YTD），還原成單季值。

    **逐列明確判斷，不猜**（2026-11-02 修 D-2／D-3）：以單季歸母淨利 `ni_parent` 當尺——
    `col` 接近當年 `ni_parent` 累計（相對差 ≤ `_YTD_TOL`）且不接近該季 `ni_parent` → 判定 YTD。
    舊做法「年內單調不減就當 YTD」在 2026-10 資料改成單季後，把 25 檔金融股 Q2 誤減成 Q2−Q1
    （2881 單季 642 億 → 307 億）。
    - 判定 YTD 的列：單季＝本列 − 同年上一季（上一季須是相鄰曆季且有值，否則 NaN，不補成 Q1）。
    - Q1、判定不了（缺 `ni_parent`、累計不完整）、判定為單季的列：維持原值。
    只動 `tickers` 內、`period_end` 在 2026 年起的列；其餘原樣回傳。"""
    s = q[col].astype("float64")
    if not tickers or "ni_parent" not in q.columns:
        return s
    out = s.copy()
    pe = q["period_end"]
    for tk, idx in q.groupby("ticker", sort=False).groups.items():
        if tk not in tickers:
            continue
        g = q.loc[idx].sort_values("period_end")
        per = g["period_end"].dt.to_period("Q")
        vals = s.loc[g.index]
        npar = g["ni_parent"].astype("float64")
        for j, i in enumerate(g.index):
            p = per.iloc[j]
            if p.year < 2026 or p.quarter == 1 or pd.isna(vals.iloc[j]):
                continue
            # 同年 Q1..本季的 ni_parent 都要有，才算得出累計
            same_year = [k for k in range(j + 1) if per.iloc[k].year == p.year]
            if len(same_year) != p.quarter or npar.iloc[same_year].isna().any():
                continue
            cum, single = float(npar.iloc[same_year].sum()), float(npar.iloc[j])
            v = float(vals.iloc[j])
            near_cum = cum != 0 and abs(v / cum - 1.0) <= _YTD_TOL
            near_single = single != 0 and abs(v / single - 1.0) <= _YTD_TOL
            if not near_cum or near_single:
                continue
            prev_ok = j >= 1 and per.iloc[j - 1] == p - 1 and pd.notna(vals.iloc[j - 1])
            out.loc[i] = v - float(vals.iloc[j - 1]) if prev_ok else np.nan
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
    q = q.sort_values(["ticker", "period_end"], kind="stable").drop_duplicates(
        ["ticker", "period_end"], keep="last").reset_index(drop=True).copy()
    fin_tickers = fin_tickers or set()
    # 單檔呼叫（個股頁、月營收 build）時，上游沒給的資產負債表欄整欄不存在 → 補 NaN，
    # 讓相關因子變 NaN 而不是整檔 KeyError（2026-10-29：1709、3094 等 7 檔缺 total_assets）
    for c in _STOCK_COLS:
        if c not in q.columns:
            q[c] = np.nan

    # 股數變動（分割／面額變更／減資彌補虧損／無償配股）：財報 EPS 是公布當時的股數 →
    # 搬到最新股本基準，normalized_EPS / TTM_EPS / 年度 EPS 才跟現在的股價同一把尺；
    # 分界看財報公布時股數換了沒（見 reference.corporate_actions.adjust_eps）。
    from reference.corporate_actions import adjust_eps
    q = adjust_eps(q)

    # 金融軌：金控淨利 2026 起曾出現 YTD 累計口徑 → 逐列對照單季歸母淨利判斷後還原單季
    # （見 _deaccum_ytd；2026-10 起資料已是單季，判斷為單季的列不動）。只動 net_income——金控 revenue
    # 在現行 bundle 品質不穩，且不進任何定存門檻 / 排序項，不碰。
    if fin_tickers and "net_income" in q.columns:
        q["net_income"] = _deaccum_ytd(q, "net_income", fin_tickers)

    # 金融軌：FinMind 近期對金控完全沒給 EPS type → 用「單季淨利 ÷ 股數」補。
    # 股數來自 universe（market_cap / close），非金融不受影響。
    if fin_tickers and shares and "eps" in q.columns:
        sh = q["ticker"].map(shares)
        est_eps = _safe_div(q["net_income"], sh)
        need = q["ticker"].isin(fin_tickers) & q["eps"].isna() & sh.notna()
        q.loc[need, "eps"] = est_eps[need]

    for c in _FLOW:
        q[f"ttm_{c}"] = _ttm(q, c)
    # OCF 兩個來源（CashFlowsFromOperatingActivities / NetCashInflow…），擇有值的
    q["ttm_ocf"] = q["ttm_ocf"].fillna(q["ttm_ocf_net"])
    # 官方快線的新季沒有現金流（等每季 XBRL）：該檔最新一季且緊鄰的上一季有值時沿用上一季，
    # 不當成缺資料（否則 FCF 類因子全變 NaN、F 分數被縮放，過關名單會被打掉）。
    # 歷史上真正的缺口不動。沿用過的列標 cash_carried。
    _g = q.groupby("ticker", sort=False)
    _adjacent = (q["period_end"] - _g["period_end"].shift(1)).dt.days.le(100)
    _latest = q["period_end"].eq(_g["period_end"].transform("max"))
    q["cash_carried"] = _latest & _adjacent & q["ttm_ocf"].isna() & _g["ttm_ocf"].shift(1).notna()
    for c in ("ttm_ocf", "ttm_ocf_net", "ttm_capex", "ocf", "ocf_net", "icf", "capex"):
        if c in q.columns:
            q[c] = q[c].where(~q["cash_carried"], _g[c].shift(1))
    if "cash" in q.columns:
        _carry_bal = _latest & _adjacent & q["cash"].isna()
        q["cash"] = q["cash"].where(~_carry_bal, _g["cash"].shift(1))
    q["ttm_fcf"] = q["ttm_ocf"] - q["ttm_capex"].abs()

    q["roe"] = _safe_div(q["ttm_net_income"], q["equity_parent"])
    q["roa"] = _safe_div(q["ttm_net_income"], q["total_assets"])
    q["gross_margin"] = _safe_div(q["ttm_gross_profit"], q["ttm_revenue"])
    q["debt_ratio"] = _safe_div(q["total_liabilities"], q["total_assets"])
    q["current_ratio"] = _safe_div(q["current_assets"], q["current_liabilities"])
    q["asset_turnover"] = _safe_div(q["ttm_revenue"], q["total_assets"])
    q["rev_yoy"] = _safe_div(q["ttm_revenue"], qp.panel_lag(q, "ttm_revenue", 4)) - 1.0

    # ── Piotroski F-Score（跟去年同期比）───────────────────────
    roa_p = qp.panel_lag(q, "roa", 4)
    dr_p = qp.panel_lag(q, "debt_ratio", 4)
    cr_p = qp.panel_lag(q, "current_ratio", 4)
    gm_p = qp.panel_lag(q, "gross_margin", 4)
    at_p = qp.panel_lag(q, "asset_turnover", 4)

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
    # 現金流是上一季的，不能跟本季淨利比（窗口錯開），沿用上一季的判定。
    q["f_accrual"] = q["f_accrual"].where(~q["cash_carried"],
                                          q.groupby("ticker", sort=False)["f_accrual"].shift(1))
    q["f_leverage"] = _pt_item(q["debt_ratio"] < dr_p, q["debt_ratio"], dr_p)
    q["f_liquidity"] = _pt_item(q["current_ratio"] > cr_p, q["current_ratio"], cr_p)
    q["f_margin"] = _pt_item(q["gross_margin"] > gm_p, q["gross_margin"], gm_p)
    q["f_turnover"] = _pt_item(q["asset_turnover"] > at_p, q["asset_turnover"], at_p)
    f_cols = ["f_roa", "f_ocf", "f_droa", "f_accrual", "f_leverage",
              "f_liquidity", "f_margin", "f_turnover"]
    if "capital_stock" in q.columns:
        cs_p = qp.panel_lag(q, "capital_stock", 4)
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
    """期別年份 y 取曆年 y−5～y−1 的年度 EPS 平均，有值年度少於 3 年回傳 NaN。

    以連續曆年補齊缺年，並延伸到查表需要的 y−1；years 預設為 5。
    """
    yr = q["period_end"].dt.year - 1        # 只信「已結束」的年度
    targets = yr.groupby(q["ticker"]).max()
    lut = {}
    for ticker, g in ann.groupby("ticker", sort=False):
        annual = g.set_index("_year")["annual_eps"].sort_index()
        end = max(annual.index.max(), targets.get(ticker, annual.index.max()))
        annual = annual.reindex(range(int(annual.index.min()), int(end) + 1))
        roll = annual.rolling(years, min_periods=3).mean()
        lut.update({(ticker, year): value for year, value in roll.items()})
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
