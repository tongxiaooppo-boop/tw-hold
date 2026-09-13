"""讀 `scripts/fetch_us_macro.py` 產出的美股總經快照。純讀檔，不發網路請求
（同 `reference/index_proxy.py` 的原則——雲端 app 本身一律不即時抓資料）。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
US_MACRO = _REPO / "data" / "reference" / "us_macro.parquet"


def load_close(symbol: str) -> pd.Series:
    """單一 symbol 的收盤序列，index=date，由舊到新。查無資料回空序列。"""
    if not US_MACRO.exists():
        return pd.Series(dtype="float64")
    df = pd.read_parquet(US_MACRO, filters=[("symbol", "==", symbol)])
    if df.empty:
        return pd.Series(dtype="float64")
    return df.set_index("date")["close"].sort_index()


def latest_change(close: pd.Series) -> dict | None:
    """最新一筆的現值 + 對前一筆的漲跌（絕對值與 %）。不足兩筆回 None。"""
    if len(close) < 2:
        return None
    last, prev = close.iloc[-1], close.iloc[-2]
    return {"value": last, "chg": last - prev, "chg_pct": last / prev - 1.0}


def percentile_rank(close: pd.Series, window: int = 252) -> float | None:
    """最新一筆在近 `window` 個交易日（含自己）分佈中的分位（0~1）。
    資料不足 `window` 天就用現有全部資料——分位只是輔助標註，不是判斷依據，
    暖機期給「資料還沒滿一年」的粗略值比直接不顯示更有用。"""
    if close.empty:
        return None
    tail = close.tail(window)
    if len(tail) < 2:
        return None
    return float((tail <= tail.iloc[-1]).mean())
