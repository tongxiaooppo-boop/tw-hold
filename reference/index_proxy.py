"""讀 `scripts/fetch_index_proxy.py` 產出的市場代理收盤序列。純讀檔，不發網路請求
（雲端 app 不該自己打 FinMind——PRD §8 運算量趨近 0 的原則，抓取只在 CI 跑）。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
INDEX_006201 = _REPO / "data" / "reference" / "index_006201.parquet"
INDEX_0050 = _REPO / "data" / "reference" / "index_0050.parquet"


def load_006201() -> pd.Series:
    """006201（元大富櫃50）收盤序列，index=date，由舊到新。檔案不存在回空序列。"""
    if not INDEX_006201.exists():
        return pd.Series(dtype="float64")
    df = pd.read_parquet(INDEX_006201)
    return df.set_index("date")["close"].sort_index()


def load_0050() -> pd.Series:
    """0050 收盤序列，index=date，由舊到新。

    來源：`scripts/promote_index_0050.py` 從 tw-swing bundle 本來就有發佈的專用小檔
    （`index_0050.parquet`，遠比整包 `prices_adj.parquet` 小）驗證後複製進來，
    2026-09-16 加——原本總經導航這張卡是吃 `bundle_data.prices("0050")`，逼整頁
    等一顆大 bundle 下載完才能顯示，跟 006201 同一頁卻走兩套速度天差地遠的路。

    檔案不存在／是空的就回空序列，呼叫端（`app/streamlit_app.py` 的 `_TW_LOADERS`）
    會退回原本吃 bundle 的 `_bundle_close("0050")` 當備援，不會因為這個小檔案缺
    就讓 0050 卡直接消失或顯示錯的資料。"""
    if not INDEX_0050.exists():
        return pd.Series(dtype="float64")
    df = pd.read_parquet(INDEX_0050)
    return df.set_index("date")["close"].sort_index()
