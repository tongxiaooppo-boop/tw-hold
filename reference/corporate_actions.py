"""已知公司行動對照表——手動維護的股票分割 / 面額變更清單。

## 為什麼要這張表

上游 `data_pack` 的還原引擎有還原**除權息**，但**沒處理面額變更 / 股票分割**
（1 股拆 N 股）。結果 bundle 的 `prices_adj` 在分割日會有一道 ~Nx 的斷崖，
而財報的每股 EPS / 每股股利在分割日之前仍是舊基準 → normalized_EPS 隱含 PE
被灌到遠低於市場 PE，價值清單 verdict 被 `eps_basis_suspect` 擋成「資料不足」。

台股一年就幾檔分割，這裡手動列、明確可稽核，不做啟發式偵測（500 檔亂猜會誤傷）。

## 慣例

`factor` = 新股數 ÷ 舊股數。
  - 面額變更 / 分割（1 股 → N 股）：factor = N（> 1）
  - 減資（每千股換回 M 股）：factor = M/1000（< 1）
基準日**當天（含）之後**為新基準；基準日**之前**的每股數字（還原股價 OHLC、
每股 EPS、每股股利）一律 ÷ factor，搬到新基準（減資時 factor < 1 → 等於放大舊價，
符合減資後股價往上跳）。同一檔多次事件 → 依序累乘。

## 維護

新增一檔：查 TWSE 公告的「減資基準日 / 面額變更基準日」與換股比例，加一列。
真出問題先查該檔 `prices_adj` 有沒有非除息日的大跳空。
"""
from __future__ import annotations

import pandas as pd

#: {ticker: [{"date": 分割基準日, "factor": 拆股倍數}, ...]}
SPLITS: dict[str, list[dict]] = {
    # 寶雅 面額 10 元 → 1 元（1 股拆 10 股），基準日 2026-07-21。
    # prices_adj 2026-07-20 收 611 → 07-21 收 63.3。
    "5904": [{"date": "2026-07-21", "factor": 10}],
}


def _events(ticker: str) -> list[tuple[pd.Timestamp, float]]:
    return [(pd.Timestamp(e["date"]), float(e["factor"]))
            for e in SPLITS.get(str(ticker).split(".")[0], [])]


def adjust_per_share(df: pd.DataFrame, cols, date_col: str = "date",
                     ticker_col: str = "ticker") -> pd.DataFrame:
    """把 `cols`（每股數字）在各自分割日之前的列 ÷ factor，搬到最新股本基準。

    非破壞性：回傳 copy。`df` 缺欄或沒有已知分割 → 原樣返回。
    """
    if df is None or df.empty or ticker_col not in df.columns \
            or date_col not in df.columns:
        return df
    have = [c for c in cols if c in df.columns]
    if not have or not any(str(t).split(".")[0] in SPLITS
                           for t in df[ticker_col].unique()):
        return df
    d = df.copy()
    dates = pd.to_datetime(d[date_col])
    tk = d[ticker_col].astype(str).str.split(".").str[0]
    for t in tk.unique():
        evs = _events(t)
        if not evs:
            continue
        for ex_date, factor in evs:
            mask = (tk == t) & (dates < ex_date)
            if mask.any():
                d.loc[mask, have] = d.loc[mask, have] / factor
    return d
