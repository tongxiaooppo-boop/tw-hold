"""讀 `scripts/fetch_foreign_futures.py`／`scripts/fetch_inst_flow.py` 產出的籌碼流向小檔。
純讀檔，不發網路請求（同 `reference/tx_futures.py` 的原則）。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
FOREIGN_FUTURES = _REPO / "data" / "reference" / "foreign_futures.parquet"
INST_FLOW = _REPO / "data" / "reference" / "inst_flow.parquet"


def _load(p: Path) -> pd.DataFrame:
    if not p.exists():
        return pd.DataFrame()
    try:
        df = pd.read_parquet(p)
    except Exception:  # noqa: BLE001  壞檔 → 當沒有
        return pd.DataFrame()
    if df.empty or "date" not in df.columns:
        return pd.DataFrame()
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


def load_foreign_futures() -> pd.DataFrame:
    """外資臺股期貨未平倉：`date, long_oi, short_oi, net_oi`（口），由舊到新；沒有回空表。"""
    return _load(FOREIGN_FUTURES)


def load_inst_flow() -> pd.DataFrame:
    """上市三大法人買賣超：`date, foreign, trust, dealer, total`（元），由舊到新；沒有回空表。"""
    return _load(INST_FLOW)
