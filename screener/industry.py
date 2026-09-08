"""產業逆風旗標（PRD §9 待定「產業逆風判定」，M2 未做 → v1 收尾補）。

## 定位

**只顯示、不進 verdict、不剔除**——比照循環高峰旗標（`cyclical_peak_flag`）。
被動框架不做擇時，這面旗只是提醒「這檔所屬產業整體在走弱，買進前多看一眼」。

## 判定

同產業成分股近 `MONTHS` 個月報酬的**中位數**當產業動能代理（PRD §9：
「用同產業其他股票動能中位數當代理」）。旗標條件（兩個都要）：

1. 產業動能中位數 < `ABS_CUT`（絕對走弱）
2. 且落後全市場中位數 `REL_CUT` 以上（不是大盤一起跌）

產業成分股 < `MIN_N` 檔 → 不判（樣本太小，中位數沒意義）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MONTHS = 6
ABS_CUT = -0.10          # 6 個月中位報酬低於這個 = 絕對走弱
REL_CUT = -0.08          # 且比全市場中位數再差這麼多
MIN_N = 3               # 產業至少要這麼多檔才判


def _six_month_return(price_hist: pd.DataFrame, asof: pd.Timestamp,
                      months: int = MONTHS) -> pd.Series:
    """每檔近 `months` 個月的還原報酬 → index=ticker。缺任一端點的檔留 NaN。"""
    if price_hist is None or price_hist.empty:
        return pd.Series(dtype=float)
    d = price_hist.copy()
    d["date"] = pd.to_datetime(d["date"])
    d["ticker"] = d["ticker"].astype(str).str.split(".").str[0]
    asof = pd.Timestamp(asof).normalize()
    start = asof - pd.DateOffset(months=months)
    d = d[d["date"] <= asof].sort_values("date")

    def _ret(g: pd.DataFrame) -> float:
        past = g[g["date"] <= start]
        if past.empty or g.empty:
            return np.nan
        p0, p1 = past["close"].iloc[-1], g["close"].iloc[-1]
        return p1 / p0 - 1.0 if p0 and p0 > 0 else np.nan

    return d.groupby("ticker").apply(_ret, include_groups=False).rename("ret_6m")


def industry_headwind(price_hist: pd.DataFrame, ind_map: dict[str, str],
                      asof: pd.Timestamp) -> dict[str, dict]:
    """回傳 `{產業: {"median_ret": x, "n": k, "vs_market": x - 市場中位}}`，
    **只含判定為逆風的產業**。呼叫端拿 key 去比對個股的 industry。"""
    ret = _six_month_return(price_hist, asof)
    if ret.empty:
        return {}
    df = pd.DataFrame({"ret": ret})
    df["industry"] = df.index.map(lambda t: ind_map.get(t))
    df = df.dropna(subset=["ret", "industry"])
    if df.empty:
        return {}
    market_median = df["ret"].median()

    out = {}
    for ind, g in df.groupby("industry"):
        if len(g) < MIN_N:
            continue
        med = float(g["ret"].median())
        if med < ABS_CUT and (med - market_median) < REL_CUT:
            out[ind] = {"median_ret": round(med, 4), "n": int(len(g)),
                        "vs_market": round(med - market_median, 4)}
    return out


def add_industry_headwind(df: pd.DataFrame, price_hist: pd.DataFrame,
                          ind_map: dict[str, str], asof: pd.Timestamp) -> pd.DataFrame:
    """在清單 df 上加 `industry_headwind`（bool）+ `industry_ret_6m`（float，逆風時才填）。"""
    hw = industry_headwind(price_hist, ind_map, asof)
    d = df.copy()
    d["industry_headwind"] = d["industry"].map(lambda i: i in hw)
    d["industry_ret_6m"] = d["industry"].map(
        lambda i: hw[i]["median_ret"] if i in hw else np.nan)
    return d
