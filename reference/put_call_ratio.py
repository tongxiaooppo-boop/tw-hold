"""讀 `scripts/fetch_put_call_ratio.py` 產出的台指選擇權 Put/Call Ratio。
純讀檔，不發網路請求（同 `reference/global_macro.py` 的原則）。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
PUT_CALL_RATIO = _REPO / "data" / "reference" / "put_call_ratio.parquet"


def load_series(field: str) -> pd.Series:
    """`field`：`put_call_volume_ratio`（量比）或 `put_call_oi_ratio`（未平倉比），
    也支援 `put_volume`/`call_volume`/`put_oi`/`call_oi` 原始口數。
    收盤序列，index=date，由舊到新。查無資料回空序列。"""
    if not PUT_CALL_RATIO.exists():
        return pd.Series(dtype="float64")
    df = pd.read_parquet(PUT_CALL_RATIO, columns=["date", field])
    if df.empty:
        return pd.Series(dtype="float64")
    return df.set_index("date")[field].sort_index()
