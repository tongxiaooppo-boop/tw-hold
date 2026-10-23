"""讀 `scripts/fetch_tx_futures.py` 產出的台指期（TX）近月合約日盤／夜盤收盤。
純讀檔，不發網路請求（同 `reference/global_macro.py` 的原則）。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
TX_FUTURES = _REPO / "data" / "reference" / "tx_futures.parquet"


def _read(session: str, contract_month: str | None) -> pd.DataFrame:
    if not TX_FUTURES.exists():
        return pd.DataFrame()
    df = pd.read_parquet(TX_FUTURES, filters=[("session", "==", session)])
    if contract_month is not None and not df.empty:
        df = df[df["contract_month"] == contract_month]
    return df


def load_session(session: str, contract_month: str | None = None) -> pd.Series:
    """`session`："day"（日盤）或 "night"（夜盤）。收盤序列，index=date，由舊到新。
    `contract_month` 給了就只留該合約月份（夜盤基準要同合約，換月時才不會拿舊合約比）。
    查無資料回空序列。"""
    df = _read(session, contract_month)
    if df.empty:
        return pd.Series(dtype="float64")
    return df.set_index("date")["last"].sort_index()


def load_day_settlement(contract_month: str | None = None) -> pd.Series:
    """日盤結算價序列（index=date）。夜盤漲跌的官方基準＝前一個日盤的結算價。
    只留 > 0 的值：最後交易日期交所 CSV 的結算價欄填 0（2026-10-21 10 月合約，App 除以 0 整頁炸）。"""
    df = _read("day", contract_month)
    if df.empty or "settlement" not in df:
        return pd.Series(dtype="float64")
    s = df.set_index("date")["settlement"].dropna().sort_index()
    return s[s > 0]


def latest_contract(session: str) -> str | None:
    """該時段最新一列的合約月份；查無資料回 None。"""
    df = _read(session, None)
    if df.empty or "contract_month" not in df:
        return None
    return str(df.sort_values("date")["contract_month"].iloc[-1])
