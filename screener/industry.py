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


def _lookback_return(price_hist: pd.DataFrame, asof: pd.Timestamp,
                     offset: pd.DateOffset, label: str) -> pd.Series:
    """每檔近 `offset` 的還原報酬 → index=ticker。缺任一端點的檔留 NaN。"""
    if price_hist is None or price_hist.empty:
        return pd.Series(dtype=float)
    d = price_hist.copy()
    d["date"] = pd.to_datetime(d["date"])
    d["ticker"] = d["ticker"].astype(str).str.split(".").str[0]
    asof = pd.Timestamp(asof).normalize()
    start = asof - offset
    d = d[d["date"] <= asof].sort_values("date")

    def _ret(g: pd.DataFrame) -> float:
        past = g[g["date"] <= start]
        if past.empty or g.empty:
            return np.nan
        p0, p1 = past["close"].iloc[-1], g["close"].iloc[-1]
        return p1 / p0 - 1.0 if p0 and p0 > 0 else np.nan

    return d.groupby("ticker").apply(_ret, include_groups=False).rename(label)


def _six_month_return(price_hist: pd.DataFrame, asof: pd.Timestamp,
                      months: int = MONTHS) -> pd.Series:
    return _lookback_return(price_hist, asof, pd.DateOffset(months=months), "ret_6m")


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


def industry_rotation(price_hist: pd.DataFrame, ind_map: dict[str, str],
                      asof: pd.Timestamp) -> list[dict]:
    """族群動向：每個產業近1週/1月中位報酬排行，由高到低。

    跟 `industry_headwind()` 是同一份底層資料的兩種呈現層次——這裡給全貌
    （所有產業都列），逆風只是排行墊底、又符合那兩條件（6個月夠差＋落後大盤
    夠多）的那幾個，用既有判定結果標一個文字欄位，不重新發明門檻。
    """
    if price_hist is None or price_hist.empty:
        return []
    w1 = _lookback_return(price_hist, asof, pd.DateOffset(weeks=1), "ret_1w")
    m1 = _lookback_return(price_hist, asof, pd.DateOffset(months=1), "ret_1m")
    df = pd.concat([w1, m1], axis=1)
    df["industry"] = df.index.map(lambda t: ind_map.get(t))
    df = df.dropna(subset=["industry"])
    if df.empty:
        return []
    hw = industry_headwind(price_hist, ind_map, asof)

    out = []
    for ind, g in df.groupby("industry"):
        n = int(g["ret_1m"].notna().sum())
        if n < MIN_N:
            continue
        out.append({
            "industry": ind, "n": n,
            "ret_1w": None if g["ret_1w"].isna().all() else round(float(g["ret_1w"].median()), 4),
            "ret_1m": None if g["ret_1m"].isna().all() else round(float(g["ret_1m"].median()), 4),
            "headwind": ind in hw,
        })
    out.sort(key=lambda r: (r["ret_1m"] is None, -(r["ret_1m"] or 0)))
    return out


def _trailing_value_sum(chips: pd.DataFrame, price_hist: pd.DataFrame,
                        asof: pd.Timestamp, n_days: int) -> pd.Series:
    """每檔近 `n_days` 個交易日「三大法人合計買賣超股數 × 當日收盤價」加總（元）
    → index=ticker。用還原收盤價換算——近幾天的還原價幾乎等於原始成交價（除權息
    調整是往回推算歷史，不影響最近幾天），拿來估買賣超金額的排行夠用，不是
    精確的結算金額。"""
    if chips is None or chips.empty or price_hist is None or price_hist.empty:
        return pd.Series(dtype=float)
    c = chips.copy()
    c["date"] = pd.to_datetime(c["date"])
    c["ticker"] = c["ticker"].astype(str).str.split(".").str[0]
    c = c[c["date"] <= pd.Timestamp(asof)]

    p = price_hist[["date", "ticker", "close"]].copy()
    p["date"] = pd.to_datetime(p["date"])
    p["ticker"] = p["ticker"].astype(str).str.split(".").str[0]

    m = c.merge(p, on=["date", "ticker"], how="inner").sort_values(["ticker", "date"])
    m["value"] = m["total_net"].fillna(0) * m["close"]
    return (m.groupby("ticker")["value"]
             .apply(lambda s: s.tail(n_days).sum())
             .rename(f"net_value_{n_days}d"))


def industry_money_flow(chips: pd.DataFrame, price_hist: pd.DataFrame,
                        ind_map: dict[str, str], asof: pd.Timestamp) -> dict[str, dict]:
    """族群資金排行：每個產業近1週/1月三大法人合計買賣超金額（億元）加總，
    跟 `industry_rotation()` 的漲跌幅排行是互補視角——資金看「錢往哪個產業去」，
    不是「哪個產業漲最多」，兩者常常不同步（資金流入不一定馬上反映在報酬上）。

    回傳 `{產業: {"net_1w": 億元, "net_1m": 億元, "n": 檔數}}`，缺 chips 或
    join 不到價格的檔不列入。跟 `industry_rotation()` 分開算，呼叫端自己合併。
    """
    w1 = _trailing_value_sum(chips, price_hist, asof, 5)
    m1 = _trailing_value_sum(chips, price_hist, asof, 21)
    df = pd.concat([w1, m1], axis=1)
    df.columns = ["net_1w", "net_1m"]
    df["industry"] = df.index.map(lambda t: ind_map.get(t))
    df = df.dropna(subset=["industry"])
    if df.empty:
        return {}

    out = {}
    for ind, g in df.groupby("industry"):
        if len(g) < MIN_N:
            continue
        out[ind] = {
            "n": int(len(g)),
            "net_1w": round(float(g["net_1w"].sum()) / 1e8, 2),
            "net_1m": round(float(g["net_1m"].sum()) / 1e8, 2),
        }
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


#: 分類太雜的垃圾桶產業——樣本夠大也不該互相比較（放在一起的公司彼此不是
#: 真的同業），比 MIN_N 的樣本數門檻更根本的一種「不適用」。
_JUNK_INDUSTRIES = {"其他", "其他電子業", "其他電子類"}


def add_peer_comparison(df: pd.DataFrame, metric: str = "roe",
                        min_n: int = MIN_N) -> pd.DataFrame:
    """同業比較（只顯示、不進 verdict／value_score——比照 `industry_headwind`，
    2026-09-15 補：單一 ROE 數字沒有同業基準，看不出高低）。

    在 `df`（已有 `industry` 欄）上加：
      - `peer_metric_median`：同產業 `metric` 中位數
      - `peer_rank` / `peer_n`：產業內名次（1 = 最好）／產業檔數
    產業檔數 < `min_n`，或落在垃圾桶分類（`其他`/`其他電子業`/`其他電子類`，
    裡面的公司彼此根本不是真的同業）→ 該產業整組留 NaN，不強行比較。
    """
    d = df.copy()
    d["peer_metric_median"] = np.nan
    d["peer_rank"] = np.nan
    d["peer_n"] = np.nan
    if metric not in d.columns or "industry" not in d.columns:
        return d

    valid = d["industry"].notna() & ~d["industry"].isin(_JUNK_INDUSTRIES) & d[metric].notna()
    sub = d.loc[valid]
    g = sub.groupby("industry")[metric]
    counts = g.transform("size")
    idx = sub.index[counts >= min_n]
    if len(idx) == 0:
        return d

    d.loc[idx, "peer_metric_median"] = g.transform("median").loc[idx]
    # 名次：同產業內由大到小排（越大越好），1 = 最好
    d.loc[idx, "peer_rank"] = g.rank(ascending=False, method="min").loc[idx]
    d.loc[idx, "peer_n"] = counts.loc[idx]
    return d
