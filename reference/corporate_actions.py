"""股票分割 / 面額變更 / 減資的每股數字還原對照表。

## 為什麼要這張表

上游 `data_pack` 的還原引擎有還原**除權息**，但**沒處理面額變更 / 分割 / 減資**。
結果 bundle 的 `prices_adj` 在事件日會有一道 ~Nx 的斷崖，而財報的每股 EPS / 每股股利
在事件日之前仍是舊基準 → normalized_EPS 隱含 PE 被灌歪 → 價值清單 verdict 被
`eps_basis_suspect` 擋成「資料不足」；K 線 / 回測跨越事件日全錯（`me` 被 2327 國巨逼出
`price_adjuster.py` 就是這個）。

## 兩個來源

1. **`_RESOLVED`（自動）**：`scripts/resolve_splits.py` 每次 rebuild 跑——
   `build_factors.scan_price_jumps()` 掃到 bundle 跳空 → 抓 FinMind `TaiwanStockSplitPrice`
   / `TaiwanStockCapitalReductionReferencePrice`（免費）→ **FinMind 給 factor、偵測器給日期**
   → 寫進 `corporate_actions_resolved.json`（版控）。
2. **`_MANUAL`（手動覆寫）**：FinMind 也沒有、或自動解錯時，手動釘死。衝突時**手動贏**。

`IGNORE_JUMPS`：偵測器掃到、FinMind 查無事件、判定是資料雜訊 → 列這裡讓偵測器閉嘴。

## 慣例

`factor` = 新股數 ÷ 舊股數（= 事件前股價 ÷ 事件後股價）。
  - 分割 / 面額變更（1 股 → N 股）：factor = N（> 1）
  - 減資：factor < 1
事件日**當天（含）之後**為新基準；之前的每股數字（還原股價 OHLC、每股 EPS、每股股利）
一律 ÷ factor 搬到新基準。同一檔多次事件 → 依序累乘。

⚠️ **日期用 bundle `prices_adj` 實際跳空那天**（跑 `scan_price_jumps()` 拿），
   不是 FinMind 事件日、也不是 TWSE 官方新股上市日——三者常差幾天，用錯會把
   已經是新基準的那幾天再 ÷factor 一次。
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

_RESOLVED_PATH = Path(__file__).with_name("corporate_actions_resolved.json")

#: 手動覆寫層（FinMind 沒有 / 自動解錯時用）。衝突時蓋掉 _RESOLVED。
_MANUAL: dict[str, list[dict]] = {
    # 5904 寶雅 面額 10→1。FinMind factor 10（720/72）；bundle 2026-07-20 收 611 → 07-21 收 63.3。
    "5904": [{"date": "2026-07-21", "factor": 10}],
    # 6949 沛爾生醫 面額 10→0.5（factor 20）。bundle 跳空 2026-09-07（資料尾端只一根新價，
    #   比例略偏 ×0.045）。bundle 累積完整後回頭校日期。
    "6949": [{"date": "2026-09-07", "factor": 20}],
}


def _load_resolved() -> dict[str, list[dict]]:
    if not _RESOLVED_PATH.exists():
        return {}
    try:
        raw = json.loads(_RESOLVED_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {str(tk): [{"date": e["date"], "factor": float(e["factor"])} for e in evs]
            for tk, evs in raw.get("splits", {}).items() if evs}


def _merge() -> dict[str, list[dict]]:
    out = _load_resolved()
    out.update(_MANUAL)            # 手動贏
    return out


#: {ticker(裸): [{"date": "YYYY-MM-DD", "factor": float}, ...]}
SPLITS: dict[str, list[dict]] = _merge()

#: 偵測器掃到、FinMind 查無事件、判定資料雜訊 → 不再每次 build 報。
IGNORE_JUMPS: dict[str, str] = {
    "2380": "2026-06-05 ×3.46（漲）——FinMind SplitPrice/CapitalReduction 皆無事件，資料雜訊",
    "4950": "2025-11-03 ×2.62（漲）——FinMind 兩張表皆無事件，資料雜訊",
    "5314": "2026-08-06 ×0.25——世紀 1 拆 20 是 2025-03-31（data_pack 已還原）；"
            "FinMind 對這筆 2026 跳空無事件，資料雜訊",
    "7772": "2026-04-20 ×1.85（漲）——FinMind 兩張表皆無事件，資料雜訊",
}


def reload() -> None:
    """重讀 `corporate_actions_resolved.json`（`resolve_splits.py --write` 後、同進程內生效）。"""
    global SPLITS
    SPLITS = _merge()


def _events(ticker: str) -> list[tuple[pd.Timestamp, float]]:
    return [(pd.Timestamp(e["date"]), float(e["factor"]))
            for e in SPLITS.get(str(ticker).split(".")[0], [])]


def adjust_per_share(df: pd.DataFrame, cols, date_col: str = "date",
                     ticker_col: str = "ticker") -> pd.DataFrame:
    """把 `cols`（每股數字）在各自事件日之前的列 ÷ factor，搬到最新股本基準。

    非破壞性：回傳 copy。`df` 缺欄或沒有已知事件 → 原樣返回。
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
