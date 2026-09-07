"""剔除門檻 + 綜合排序。**這一層產「候選 + 為什麼」，不產「建議」**（買入價、
要不要買是 tw-hold + 人 + AI 的事）。

M0.3 從 `tw-swing/src/twswing/value/screen.py` 搬走（tw-swing 端已刪除）。
純函式，只依賴 numpy / pandas。

## 為什麼是「先剔除、再排序」不是「一個總分」

STATUS 紀律：一個由高到低排好的總分，配上「某支看起來不錯」，就會變成
「把第一名買下去」。價值陷阱（便宜但在衰退）與配息陷阱（高息但要減配）
必須是**硬門檻剔除**，不是被其他分項的高分蓋過去。
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _latest_per_ticker(qf: pd.DataFrame, asof: pd.Timestamp) -> pd.DataFrame:
    """每檔取「`disclosure_date` <= asof 的最新一期」。"""
    v = qf[qf["disclosure_date"] <= asof]
    return (v.sort_values(["ticker", "period_end"])
             .groupby("ticker", sort=False).tail(1).reset_index(drop=True))


def _last_n_eps_positive(qf: pd.DataFrame, asof: pd.Timestamp, n: int = 4) -> pd.Series:
    v = qf[qf["disclosure_date"] <= asof].sort_values(["ticker", "period_end"])
    tail = v.groupby("ticker", sort=False).tail(n)
    cnt = tail.groupby("ticker")["eps"].count()
    pos = tail.assign(_p=tail["eps"] > 0).groupby("ticker")["_p"].sum()
    return (pos == n) & (cnt == n)


def _cyclical_penalty(qf: pd.DataFrame, asof: pd.Timestamp) -> pd.Series:
    """近 12 季 rev_yoy 的標準差 + gross_margin 標準差 → 分位數 → 懲罰乘數
    （波動大 = 景氣循環 → 乘 0.7；波動小 → 乘 1.0）。"""
    v = (qf[qf["disclosure_date"] <= asof].sort_values(["ticker", "period_end"])
           .groupby("ticker", sort=False).tail(12))
    vol = v.groupby("ticker").agg(ry=("rev_yoy", "std"), gm=("gross_margin", "std"))
    z = vol.rank(pct=True).mean(axis=1)          # 0..1，越大越循環
    return (1.0 - 0.3 * z).reindex().rename("cyclical_penalty")


def _rank_avg(df: pd.DataFrame, cols: dict[str, int]) -> pd.Series:
    """cols: {欄位: 方向}，方向 +1 = 越大越好、-1 = 越小越好。回傳 0–1 rank 平均。"""
    parts = []
    for c, d in cols.items():
        if c in df.columns:
            parts.append(df[c].rank(pct=True, ascending=(d > 0)))
    return pd.concat(parts, axis=1).mean(axis=1) if parts else pd.Series(np.nan, index=df.index)


def _market_cap(row_capital_stock: pd.Series, close: pd.Series) -> pd.Series:
    """市值 = 收盤 × 在外流通股數；股數 = 股本 ÷ 10（面額）。"""
    return close * (row_capital_stock / 10.0)


def screen_deposit(qf: pd.DataFrame, divf: pd.DataFrame,
                   prices: pd.DataFrame | None = None,
                   vol: pd.DataFrame | None = None,
                   asof: pd.Timestamp | None = None) -> pd.DataFrame:
    """定存區篩選。

    prices: `[ticker, close]`（最新收盤）；vol: `[ticker, ann_vol]`（年化週報酬標準差）。
    兩者沒給 → 相關因子留 NaN、排序退化但仍可跑。
    """
    asof = pd.Timestamp(asof or pd.Timestamp.now()).normalize()
    d = _latest_per_ticker(qf, asof).merge(divf, on="ticker", how="left")
    d = d.set_index("ticker")

    eps4 = _last_n_eps_positive(qf, asof)
    d["eps_4q_positive"] = eps4.reindex(d.index).fillna(False)
    d["cyclical_penalty"] = _cyclical_penalty(qf, asof).reindex(d.index).fillna(1.0)

    if prices is not None:
        px = prices.set_index("ticker")["close"]
        d["close"] = px.reindex(d.index)
        d["market_cap"] = _market_cap(d.get("capital_stock", np.nan), d["close"])
        shares = d.get("capital_stock", np.nan) / 10.0
        d["fcf_cover"] = d["ttm_fcf"] / (d["last_cash_dividend"] * shares)
        d["fcf_yield"] = d["ttm_fcf"] / d["market_cap"]
    else:
        d["market_cap"] = d["fcf_cover"] = d["fcf_yield"] = np.nan
    if vol is not None:
        d["ann_vol"] = vol.set_index("ticker")["ann_vol"].reindex(d.index)
    else:
        d["ann_vol"] = np.nan

    # ── 硬門檻（剔除）────────────────────────────────────────
    reasons: dict[str, pd.Series] = {
        "eps 近4季非全正": ~d["eps_4q_positive"],
        "連續配息 < 5 年": d["div_years"].fillna(0) < 5,
        "近5年有減配": d["div_cut_5y"].fillna(False),
        "FCF 不覆蓋股利": d["fcf_cover"].notna() & (d["fcf_cover"] < 1.0),
        "配息主要來自公積": d["earnings_div_ratio"].notna() & (d["earnings_div_ratio"] < 0.5),
        "負債比 > 0.75": d["debt_ratio"] > 0.75,
    }
    d["reject_reason"] = _first_reason(reasons, d.index)
    d["passes"] = d["reject_reason"].isna()

    # ── 存股安全分（過門檻的才排）──────────────────────────
    ok = d[d["passes"]].copy()
    ok["safety_score"] = _rank_avg(ok, {
        "fcf_yield": +1, "ann_vol": -1, "roe": +1,
        "div_years": +1, "payout_ratio_ttm": -1,
    }) * ok["cyclical_penalty"]
    ok = ok.sort_values("safety_score", ascending=False)
    d = d.join(ok["safety_score"])
    return d.reset_index().sort_values(
        ["passes", "safety_score"], ascending=[False, False])


def screen_value(qf: pd.DataFrame, prices: pd.DataFrame | None = None,
                 asof: pd.Timestamp | None = None) -> pd.DataFrame:
    """價值區篩選。品質門檻 Piotroski F-Score ≥ 6 + 剔除價值陷阱，
    再按 Magic Formula 精神 rank(品質) + rank(便宜)。"""
    asof = pd.Timestamp(asof or pd.Timestamp.now()).normalize()
    d = _latest_per_ticker(qf, asof).set_index("ticker")

    # 營收 YoY 走弱：近 3 季 rev_yoy 都 < 0
    ry3 = (qf[qf["disclosure_date"] <= asof].sort_values(["ticker", "period_end"])
             .groupby("ticker", sort=False).tail(3))
    weak_rev = ry3.assign(_n=ry3["rev_yoy"] < 0).groupby("ticker")["_n"].sum() == 3
    # 毛利率 5 年趨勢向下：現在的 gross_margin < 5 年（20 季）前
    gm_now = d["gross_margin"]
    gm_old = (qf[qf["disclosure_date"] <= asof].sort_values(["ticker", "period_end"])
                .groupby("ticker", sort=False).nth(-20))
    gm_old = gm_old.set_index("ticker")["gross_margin"] if "ticker" in gm_old.columns \
        else gm_old["gross_margin"]

    if prices is not None:
        px = prices.set_index("ticker")["close"]
        d["close"] = px.reindex(d.index)
        d["market_cap"] = d["close"] * (d.get("capital_stock", np.nan) / 10.0)
        d["norm_pe"] = d["close"] / d["normalized_eps"]
        d["norm_ey"] = d["normalized_eps"] / d["close"]          # normalized 盈餘殖利率
        d["fcf_yield"] = d["ttm_fcf"] / d["market_cap"]
        ev = d["market_cap"] + d["total_liabilities"] - d.get("cash", 0.0)
        d["ev_ebit"] = ev / d["ttm_op_income"]
        d["net_cash_to_mktcap"] = (d.get("cash", np.nan) - d["total_liabilities"]) / d["market_cap"]
    else:
        for c in ["market_cap", "norm_pe", "norm_ey", "fcf_yield", "ev_ebit",
                  "net_cash_to_mktcap"]:
            d[c] = np.nan

    reasons = {
        "F-Score < 6": d["f_score"] < 6,
        "營收連3季衰退": weak_rev.reindex(d.index).fillna(False),
        "毛利率5年下滑": (gm_now.reindex(d.index) < gm_old.reindex(d.index)),
        "FCF 為負": d["ttm_fcf"] < 0,
    }
    d["reject_reason"] = _first_reason(reasons, d.index)
    d["passes"] = d["reject_reason"].isna()

    ok = d[d["passes"]].copy()
    quality = _rank_avg(ok, {"f_score": +1, "roe": +1})
    cheap = _rank_avg(ok, {"norm_ey": +1, "fcf_yield": +1, "ev_ebit": -1,
                           "net_cash_to_mktcap": +1})
    # 沒有股價時（M0a：bundle 只有 U1a）便宜度算不出來 → 只用品質排序，
    # 不要讓整個 value_score 變 NaN（那樣清單就完全無序）。
    ok["value_score"] = np.where(cheap.isna(), quality, (quality + cheap) / 2.0)
    d = d.join(ok["value_score"])
    return d.reset_index().sort_values(
        ["passes", "value_score"], ascending=[False, False])


def _first_reason(reasons: dict[str, pd.Series], index: pd.Index) -> pd.Series:
    """每一列取「第一個成立的剔除理由」，都不成立 → NaN。"""
    out = pd.Series(np.nan, index=index, dtype="object")
    for label, mask in reasons.items():
        m = mask.reindex(index).fillna(False).astype(bool)
        out = out.where(out.notna() | ~m, label)
    return out
