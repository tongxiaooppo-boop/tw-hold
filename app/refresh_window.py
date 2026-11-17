"""頁尾「立即重新整理資料」按鈕的開放時段（2026-11-17：只在台北 08:00–10:00，其他時間排程自己會跑）。"""
from __future__ import annotations

import pandas as pd

OPEN_HOUR = 8    # 台北時間，含
CLOSE_HOUR = 10  # 台北時間，不含

_TZ = "Asia/Taipei"


def now_taipei() -> pd.Timestamp:
    """回傳台北時間的現在（tz-aware，Asia/Taipei）。測試會 monkeypatch 這個函式。"""
    return pd.Timestamp.now(tz=_TZ)


def is_open(now: pd.Timestamp | None = None) -> bool:
    """OPEN_HOUR:00 <= 台北時間 < CLOSE_HOUR:00 回 True。每天都適用（含週末）。
    now 為 None 時用 now_taipei()（要在函式內用模組屬性呼叫，monkeypatch 才有效）；
    now 是 tz-naive 就當成台北時間，tz-aware 就先轉成 Asia/Taipei。"""
    if now is None:
        now = now_taipei()
    now = pd.Timestamp(now)
    if now.tzinfo is None:
        now = now.tz_localize(_TZ)
    else:
        now = now.tz_convert(_TZ)
    return OPEN_HOUR <= now.hour < CLOSE_HOUR


def closed_note() -> str:
    """停用時顯示的說明。"""
    return (f"按鈕只在台北時間 {OPEN_HOUR:02d}:00–{CLOSE_HOUR:02d}:00 開放。"
            "其他時間排程會自動更新，不用手動按。")
