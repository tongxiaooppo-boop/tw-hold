"""法人籌碼的修補與恆等式守門（tw-hold 讀 bundle 端）。

背景（2026-10-05）：上櫃自營欄 2026-08-27 起整欄空白（tw-swing chips.py 匯入漏掉
上櫃只有自行／避險兩子欄），三欄相加遇空值當 0，上櫃 838／839 檔 5 日法人淨買超被誤判 0。
tw-swing 修好前（或某天上游又出事），讀取端也要自保：

- `fill_dealer`：自營缺、但有合計 → 自營 ＝ 合計 − 外資 − 投信（官方 TPEx 2026-09-10／10-02
  逐檔實測與官方自營 100% 一致；外資自營 fi_prop 幾乎為 0，併入自營）。
- `identity_stats`：最近 N 個交易日「外資＋投信＋自營 ≠ 合計」比例與「自營缺」比例，
  供呼叫端警示；不吞錯、不補 0。
"""
from __future__ import annotations

import pandas as pd

_TOL = 1.0  # 股；兩邊同單位即可


def fill_dealer(df: pd.DataFrame) -> pd.DataFrame:
    """回傳新表：dealer_net 缺且 total_net／foreign_net／trust_net 皆有 → 補成合計−外資−投信。
    沒有 total_net 欄就原樣返回。"""
    if "total_net" not in df.columns or "dealer_net" not in df.columns:
        return df
    d = df.copy()
    f = pd.to_numeric(d["foreign_net"], errors="coerce")
    t = pd.to_numeric(d["trust_net"], errors="coerce")
    tot = pd.to_numeric(d["total_net"], errors="coerce")
    dl = pd.to_numeric(d["dealer_net"], errors="coerce")
    can = dl.isna() & tot.notna() & f.notna() & t.notna()
    d["dealer_net"] = dl.where(~can, tot - f - t)
    return d


def identity_stats(df: pd.DataFrame, days: int = 20) -> dict:
    """最近 `days` 個交易日（有 total_net 的列）：
    dealer_missing＝自營缺的比例；mismatch＝三項加總與合計差 > 1 的比例（自營缺者不算）。"""
    if df is None or df.empty or "total_net" not in df.columns:
        return {"rows": 0, "dealer_missing": 0.0, "mismatch": 0.0}
    d = df[pd.to_numeric(df["total_net"], errors="coerce").notna()]
    if d.empty:
        return {"rows": 0, "dealer_missing": 0.0, "mismatch": 0.0}
    cut = sorted(pd.to_datetime(d["date"]).unique())[-days:][0]
    r = d[pd.to_datetime(d["date"]) >= cut]
    dl = pd.to_numeric(r["dealer_net"], errors="coerce")
    miss = dl.isna()
    s = (pd.to_numeric(r["foreign_net"], errors="coerce").fillna(0)
         + pd.to_numeric(r["trust_net"], errors="coerce").fillna(0) + dl.fillna(0))
    bad = ((s - pd.to_numeric(r["total_net"], errors="coerce")).abs() > _TOL) & ~miss
    n = len(r)
    return {"rows": n, "dealer_missing": float(miss.mean()), "mismatch": float(bad.sum() / max(1, int((~miss).sum())))}
