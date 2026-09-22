"""讀 `scripts/fetch_global_macro.py` 產出的國際指數/美股總經快照。純讀檔，
不發網路請求（同 `reference/index_proxy.py` 的原則——雲端 app 本身一律不即時抓資料）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
GLOBAL_MACRO = _REPO / "data" / "reference" / "global_macro.parquet"
GLOBAL_MACRO_META = GLOBAL_MACRO.with_name("global_macro_meta.json")


# latest_change 現在被台股卡跟國際指數卡共用，搬到 market_status.py（更中性的位置）——
# 這裡保留 re-export，舊的呼叫點跟測試都不用改。
from reference.market_status import latest_change  # noqa: E402,F401


def load_close(symbol: str) -> pd.Series:
    """單一 symbol 的收盤序列，index=date，由舊到新。查無資料回空序列。"""
    if not GLOBAL_MACRO.exists():
        return pd.Series(dtype="float64")
    df = pd.read_parquet(GLOBAL_MACRO, filters=[("symbol", "==", symbol)])
    if df.empty:
        return pd.Series(dtype="float64")
    return df.set_index("date")["close"].sort_index()


def load_stale_map() -> dict[str, dict]:
    """`fetch_global_macro.py::_check_staleness()` 寫進 meta 的「部分過期」清單，
    轉成 `{symbol: {"latest": "YYYY-MM-DD", "lag_days": int}}`。

    這批 symbol 有拿到資料、parquet 裡看起來正常（不是空的），只是比同批次
    其他 symbol 舊——畫面上如果不特別標，使用者看到卡片有數字會以為是新的
    （2026-09-22 使用者問「台股清單有更新，美股是舊的卻看不出來」）。
    """
    if not GLOBAL_MACRO_META.exists():
        return {}
    try:
        meta = json.loads(GLOBAL_MACRO_META.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {s["symbol"]: {"latest": s["latest"], "lag_days": s["lag_days"]}
            for s in meta.get("stale", [])}


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
