"""讀 `scripts/fetch_index_proxy.py` 產出的市場代理收盤序列。純讀檔，不發網路請求
（雲端 app 不該自己打 FinMind——PRD §8 運算量趨近 0 的原則，抓取只在 CI 跑）。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
INDEX_006201 = _REPO / "data" / "reference" / "index_006201.parquet"


def load_006201() -> pd.Series:
    """006201（元大富櫃50）收盤序列，index=date，由舊到新。檔案不存在回空序列。"""
    if not INDEX_006201.exists():
        return pd.Series(dtype="float64")
    df = pd.read_parquet(INDEX_006201)
    return df.set_index("date")["close"].sort_index()
