"""回測資料載入（Claude 寫，sol 不得修改；格式已實測）。

load_all() → dict：
  qf[t]      DataFrame：該檔季報（已過 quarterly_factors＝EPS 已依股數事件調整），欄位至少
             period_end(Timestamp 季末)、revenue、gross_profit、op_income、pretax_income、net_income、
             ni_parent、eps、capital_stock、equity_parent；依 period_end 遞增。**沒有可信的公告日欄，不准用 disclosure_date**。
  monthly[t] pd.Series，index＝月初 Timestamp、值＝月營收（元），遞增。
  per[t]     DataFrame[date, per, pbr]（交易所原值；PER 在配股後有一段沿用舊股數，**這裡沒修**）。
  px[t]      DataFrame[date, open, high, low, close]：**含息還原**價（2023-07-18 起；已實測除息日 ratio 跳變）。
  idx0050    DataFrame[date, close]（2015 起；到 2026-10-19）。
  events[t]  list[(Timestamp, m)]：股數事件（reference.corporate_actions._events）。
t 一律是裸代號字串（'2330'）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "app"))
UP = REPO / "data" / "upstream"

# 法定公布期限（月, 日）；季末月 → 期限（年報在隔年）
DEADLINE = {3: (5, 15), 6: (8, 14), 9: (11, 14), 12: (3, 31)}


def report_deadline(period_end: pd.Timestamp) -> pd.Timestamp:
    """該季財報的法定公布期限（Q4 為隔年 3/31）。"""
    m, d = DEADLINE[period_end.month]
    y = period_end.year + (1 if period_end.month == 12 else 0)
    return pd.Timestamp(y, m, d)


def revenue_deadline(month_start: pd.Timestamp) -> pd.Timestamp:
    """該月營收的法定公布期限（次月 10 日）。"""
    nxt = month_start + pd.offsets.MonthBegin(1)
    return pd.Timestamp(nxt.year, nxt.month, 10)


def _bare(s: pd.Series) -> pd.Series:
    return s.astype(str).str.split(".").str[0]


def load_all() -> dict:
    from factors.factors import quarterly_factors
    from reference.corporate_actions import _events
    from reference.loader import load_quarterly

    q = load_quarterly()
    q["ticker"] = _bare(q["ticker"])
    qf = quarterly_factors(q.copy())
    qf["ticker"] = _bare(qf["ticker"])
    qf["period_end"] = pd.to_datetime(qf["period_end"])
    qd = {t: g.sort_values("period_end").reset_index(drop=True) for t, g in qf.groupby("ticker")}

    r = pd.read_parquet(UP / "revenue.parquet")
    r["ticker"] = _bare(r["ticker"])
    r["month"] = pd.to_datetime(r["month"]).dt.to_period("M").dt.to_timestamp()
    md = {}
    for t, g in r.groupby("ticker"):
        s = pd.Series(g["revenue"].to_numpy(dtype=float), index=g["month"])
        md[t] = s[~s.index.duplicated(keep="last")].dropna().sort_index()

    p = pd.read_parquet(UP / "per.parquet", columns=["ticker", "date", "per", "pbr"])
    p["ticker"] = _bare(p["ticker"])
    p["date"] = pd.to_datetime(p["date"])
    pd_ = {t: g.sort_values("date").reset_index(drop=True) for t, g in p.groupby("ticker")}

    x = pd.read_parquet(UP / "prices_adj.parquet", columns=["ticker", "date", "open", "high", "low", "close"])
    x["ticker"] = _bare(x["ticker"])
    x["date"] = pd.to_datetime(x["date"])
    xd = {t: g.sort_values("date").reset_index(drop=True) for t, g in x.groupby("ticker")}

    idx = pd.read_parquet(UP / "index_0050.parquet")
    idx["date"] = pd.to_datetime(idx["date"])
    ev = {t: _events(t) for t in qd}
    return {"qf": qd, "monthly": md, "per": pd_, "px": xd, "idx0050": idx.sort_values("date").reset_index(drop=True),
            "events": ev}
