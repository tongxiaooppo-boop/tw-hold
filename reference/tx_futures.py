"""讀 `scripts/fetch_tx_futures.py` 產出的台指期（TX）近月合約日盤／夜盤收盤。
純讀檔，不發網路請求（同 `reference/global_macro.py` 的原則）。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
TX_FUTURES = _REPO / "data" / "reference" / "tx_futures.parquet"


def load_session(session: str) -> pd.Series:
    """`session`："day"（日盤）或 "night"（夜盤）。收盤序列，index=date，由舊到新。
    查無資料回空序列。"""
    if not TX_FUTURES.exists():
        return pd.Series(dtype="float64")
    df = pd.read_parquet(TX_FUTURES, filters=[("session", "==", session)])
    if df.empty:
        return pd.Series(dtype="float64")
    return df.set_index("date")["last"].sort_index()


def load_day_settlement() -> pd.Series:
    """日盤結算價序列（index=date）。夜盤漲跌的官方基準＝前一個日盤的結算價。"""
    if not TX_FUTURES.exists():
        return pd.Series(dtype="float64")
    df = pd.read_parquet(TX_FUTURES, filters=[("session", "==", "day")])
    if df.empty or "settlement" not in df:
        return pd.Series(dtype="float64")
    return df.set_index("date")["settlement"].dropna().sort_index()
