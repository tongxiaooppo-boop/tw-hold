"""自建營收指數、營收 beta、產業同步度（估值分類框架，2026-11-01 Opus 定介面）。

依據：`D:\\g\\claude\\val_discuss\\估值定義定案草案.md` §1.2「自建營收指數」：
  每月取「當月與去年同月都有營收」的同樣本公司，加總算 TTM YoY（全市場一條、產業各一條，
  樣本 < 5 家不建）。beta＝個股對全市場；同步度＝個股與「排除自己的產業指數」相關。
  它是上市櫃樣本的營收景氣代理，不是 GDP beta；樣本只有現行上市櫃（存活者偏差，§8.7 第 4 點）。

純函式：不讀檔、不連網。

## 資料格式（介面，不准改）

monthly_rev（長表）：欄位 `ticker`(str)、`month`(月初 Timestamp，例 2024-06-01)、`revenue`(float，元)。
  - 呼叫端負責把 revenue.parquet 的 month 正規化成月初 Timestamp。
  - revenue ≤ 0 或 NaN 一律視為「該月無營收」。
  - 同 (ticker, month) 重複 → ValueError。

## 同樣本 TTM YoY 的算法（暫定，見回報「待決」1）

對月份 m：
  S_k＝月份 k 的同樣本＝在 k 與 k−12 個月都有營收的公司。
  num12(m)＝Σ_{k=m−11..m} Σ_{i∈S_k} rev_i(k)
  den12(m)＝Σ_{k=m−11..m} Σ_{i∈S_k} rev_i(k−12)
  n_min(m)＝min_{k=m−11..m} |S_k|
  ttm_yoy(m)＝num12/den12 − 1；若 n_min < min_members 或 den12 ≤ 0 → NaN。
（＝逐月同樣本、12 個月分子分母各自加總。新上市公司在滿 12 個月前不進樣本，
  所以不會造成假成長。）
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MIN_MEMBERS = 5                # 樣本 < 5 家不建（草案 §1.2）
REV_BETA_WINDOW = 120          # 【待決】beta／同步度用近幾個月；暫定 120（≈40 季，與 OROA 窗一致）
REV_BETA_MIN_OBS = 36          # 【待決】共同有效月數少於這個 → NaN

INDEX_COLS = ("num12", "den12", "n_min", "ttm_yoy")


def _prep(monthly_rev: pd.DataFrame) -> pd.DataFrame:
    """驗證欄位與重複；回傳 ticker/month/revenue 三欄副本。"""
    for c in ("ticker", "month", "revenue"):
        if c not in monthly_rev.columns:
            raise KeyError(c)
    d = monthly_rev[["ticker", "month", "revenue"]].copy()
    d["month"] = pd.to_datetime(d["month"])
    d["revenue"] = d["revenue"].astype(float)
    if d.duplicated(["ticker", "month"]).any():
        raise ValueError("(ticker, month) 有重複")
    return d


def _wide(d: pd.DataFrame, months: pd.DatetimeIndex) -> pd.DataFrame:
    """月份 × ticker 寬表；revenue ≤ 0 或 NaN → NaN。"""
    v = d[d["revenue"] > 0]
    w = v.pivot(index="month", columns="ticker", values="revenue")
    return w.reindex(months)


def _month_range(d: pd.DataFrame) -> pd.DatetimeIndex:
    if len(d) == 0:
        return pd.DatetimeIndex([], freq="MS")
    return pd.date_range(d["month"].min(), d["month"].max(), freq="MS")


def _index_from_wide(w: pd.DataFrame, min_members: int) -> pd.DataFrame:
    """寬表 → 同樣本指數（INDEX_COLS）。"""
    prev = w.shift(12)
    mask = w.notna() & prev.notna()
    num_k = w.where(mask).sum(axis=1)
    den_k = prev.where(mask).sum(axis=1)
    n_k = mask.sum(axis=1)
    num12 = num_k.rolling(12, min_periods=1).sum()
    den12 = den_k.rolling(12, min_periods=1).sum()
    # 窗不滿 12 個月（範圍起點之前當作沒有樣本）→ n_min＝0
    n_min = n_k.rolling(12, min_periods=12).min().fillna(0).astype(int)
    ok = (n_min >= min_members) & (den12 > 0)
    ttm_yoy = (num12 / den12.where(den12 > 0) - 1).where(ok)
    out = pd.DataFrame({"num12": num12.astype(float), "den12": den12.astype(float),
                        "n_min": n_min, "ttm_yoy": ttm_yoy.astype(float)})
    out.index.name = "month"
    return out


def same_sample_components(monthly_rev: pd.DataFrame) -> pd.DataFrame:
    """逐月同樣本成分。

    輸出長表，欄位 `ticker, month, cur, prev`：
      每一列＝某公司在某月「當月 cur 與去年同月 prev 都 > 0」才出現（否則不出列）。
      依 (month, ticker) 遞增排序、index 0..n-1。
    錯誤：缺欄位 → KeyError；(ticker, month) 重複 → ValueError。
    """
    d = _prep(monthly_rev)
    d = d[d["revenue"] > 0]
    cols = ["ticker", "month", "cur", "prev"]
    if len(d) == 0:
        return pd.DataFrame(columns=cols)
    cur = d.rename(columns={"revenue": "cur"})
    prev = d.assign(month=d["month"] + pd.DateOffset(years=1)).rename(columns={"revenue": "prev"})
    m = cur.merge(prev, on=["ticker", "month"], how="inner")
    return m[cols].sort_values(["month", "ticker"]).reset_index(drop=True)


def build_market_index(monthly_rev: pd.DataFrame,
                       min_members: int = MIN_MEMBERS) -> pd.DataFrame:
    """全市場同樣本營收指數。

    輸出：index＝month（月初 Timestamp，遞增，涵蓋輸入出現過的最早到最晚月份、每月一列），
    欄位 INDEX_COLS：
      num12, den12（float）、n_min（int；12 個月內任一月沒有樣本＝0）、
      ttm_yoy（float；算法見檔頭；資料不夠 12 個月、n_min < min_members、den12 ≤ 0 → NaN）。
    錯誤：同 same_sample_components。
    """
    d = _prep(monthly_rev)
    months = _month_range(d)
    return _index_from_wide(_wide(d, months), min_members)


def build_industry_index(monthly_rev: pd.DataFrame, industry_map: dict[str, str],
                         min_members: int = MIN_MEMBERS) -> pd.DataFrame:
    """各產業同樣本營收指數。

    industry_map：ticker → 產業名（呼叫端先用 quarterly_prep.normalize_industry 正規化；
      值為 None 或 ticker 不在表內 → 該公司不進任何產業指數，但仍可進全市場指數）。
    輸出長表：欄位 `industry, month, num12, den12, n_min, ttm_yoy`，
      依 (industry, month) 遞增；每個產業的月份範圍＝輸入全體的最早到最晚月份。
      算法同 build_market_index，只是樣本限該產業。樣本不足的產業**仍出列**，ttm_yoy＝NaN。
    """
    d = _prep(monthly_rev)
    months = _month_range(d)
    cols = ["industry", "month", *INDEX_COLS]
    parts = []
    inds = sorted({v for v in industry_map.values() if isinstance(v, str)})
    for ind in inds:
        tks = {k for k, v in industry_map.items() if v == ind}
        sub_d = d[d["ticker"].isin(tks)]
        if len(sub_d) == 0:
            continue
        idx = _index_from_wide(_wide(sub_d, months), min_members).reset_index()
        idx.insert(0, "industry", ind)
        parts.append(idx)
    if not parts:
        return pd.DataFrame(columns=cols)
    out = pd.concat(parts, ignore_index=True)[cols]
    return out.sort_values(["industry", "month"]).reset_index(drop=True)


def industry_index_excluding_self(industry_index: pd.DataFrame, monthly_rev: pd.DataFrame,
                                  ticker: str, industry: str,
                                  min_members: int = MIN_MEMBERS) -> pd.Series:
    """「排除自己」的產業指數 TTM YoY（同步度用）。

    從 build_industry_index 輸出中 industry 那一段，扣掉 ticker 自己的同樣本貢獻：
      num12' = num12 − Σ_{k=m−11..m, ticker∈S_k} rev_ticker(k)
      den12' = den12 − Σ_{k=m−11..m, ticker∈S_k} rev_ticker(k−12)
      n_min' = min_k (|S_k| − [ticker∈S_k])
      ttm_yoy' = num12'/den12' − 1；n_min' < min_members 或 den12' ≤ 0 → NaN。
    輸出：index＝month 的 float Series，name＝"ttm_yoy"。
    industry 不在 industry_index → 全 NaN 的空 Series（不丟例外）。
    """
    seg = industry_index[industry_index["industry"] == industry]
    if len(seg) == 0:
        return pd.Series(dtype=float, name="ttm_yoy")
    seg = seg.set_index("month").sort_index()
    months = seg.index
    d = _prep(monthly_rev)
    d = d[(d["ticker"] == ticker) & (d["revenue"] > 0)]
    own = d.set_index("month")["revenue"]
    cur = own.reindex(months)
    prev = own.reindex(months - pd.DateOffset(years=1))
    prev.index = months
    in_k = cur.notna() & prev.notna()
    c = cur.where(in_k, 0.0).rolling(12, min_periods=1).sum()
    p = prev.where(in_k, 0.0).rolling(12, min_periods=1).sum()
    had = in_k.astype(int).rolling(12, min_periods=1).max()
    num = seg["num12"] - c
    den = seg["den12"] - p
    # industry_index 沒有逐月樣本數，n_min' 取保守下界：窗內只要自己進過樣本就 −1
    n_min = (seg["n_min"] - had).clip(lower=0)
    ok = (n_min >= min_members) & (den > 0)
    out = (num / den.where(den > 0) - 1).where(ok).astype(float)
    out.name = "ttm_yoy"
    return out


def stock_ttm_yoy(monthly: pd.Series) -> pd.Series:
    """單一個股的月頻 TTM 營收年增。

    monthly：index＝月初 Timestamp（遞增）、值＝營收；≤0 或 NaN 視為缺。
    輸出：同 index；位置 m ＝ Σ(m−11..m) ÷ Σ(m−23..m−12) − 1，
      這 24 個**曆月**都要有營收（>0），否則 NaN。
    錯誤：index 非 DatetimeIndex 或不嚴格遞增 → ValueError。
    """
    idx = monthly.index
    if not isinstance(idx, pd.DatetimeIndex):
        raise ValueError("index 必須是 DatetimeIndex")
    if not idx.is_monotonic_increasing or not idx.is_unique:
        raise ValueError("index 必須嚴格遞增")
    if len(monthly) == 0:
        return pd.Series(dtype=float, index=idx)
    s = monthly.astype(float)
    s = s.where(s > 0)
    full = pd.date_range(idx[0], idx[-1], freq="MS")
    s = s.reindex(full)
    s12 = s.rolling(12, min_periods=12).sum()
    den = s12.shift(12)
    r = s12 / den.where(den > 0) - 1
    return r.reindex(idx).astype(float)


def revenue_beta(stock_ttm_yoy: pd.Series, market_ttm_yoy: pd.Series,
                 window: int = REV_BETA_WINDOW, min_obs: int = REV_BETA_MIN_OBS) -> float:
    """營收 beta＝個股 TTM YoY 對全市場 TTM YoY 的 OLS 斜率（含截距）。

    取兩序列 index 交集且兩者都非 NaN 的月份，再取其中最後 window 個月。
    斜率＝cov(s, m) / var(m)（樣本共變異／變異，ddof 一致即可）。
    有效月 < min_obs、或 market 在窗內變異數為 0 → NaN。不丟例外。
    """
    df = pd.concat([stock_ttm_yoy.rename("s"), market_ttm_yoy.rename("m")],
                   axis=1, join="inner").dropna().tail(window)
    if len(df) < min_obs:
        return float("nan")
    m = df["m"].to_numpy(dtype=float)
    s = df["s"].to_numpy(dtype=float)
    if m.max() == m.min():
        return float("nan")
    mc = m - m.mean()
    return float((mc * (s - s.mean())).sum() / (mc * mc).sum())


def industry_sync(stock_ttm_yoy: pd.Series, industry_index_excluding_self: pd.Series,
                  window: int = REV_BETA_WINDOW, min_obs: int = REV_BETA_MIN_OBS) -> float:
    """產業同步度＝個股 TTM YoY 與「排除自己的產業指數」TTM YoY 的 Pearson 相關係數。

    月份對齊、取窗、min_obs 規則同 revenue_beta；任一方窗內標準差為 0 → NaN。不丟例外。
    """
    df = pd.concat([stock_ttm_yoy.rename("s"), industry_index_excluding_self.rename("m")],
                   axis=1, join="inner").dropna().tail(window)
    if len(df) < min_obs:
        return float("nan")
    m = df["m"].to_numpy(dtype=float)
    s = df["s"].to_numpy(dtype=float)
    if m.max() == m.min() or s.max() == s.min():
        return float("nan")
    return float(np.corrcoef(s, m)[0, 1])
