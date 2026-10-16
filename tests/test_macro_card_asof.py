"""總經導航每張卡都標自己的資料日（2026-10-16：頁頂只有彙總，看不出美股還停在前一天）。"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _close(days):
    return pd.Series([100.0 + i for i in range(len(days))], index=pd.to_datetime(days))


def test_數字卡_正常時標資料日():
    import streamlit_app as sa
    h = sa._gz_card("NVDA", "NVIDIA", _close(["2026-10-14", "2026-10-15"]), show_pct=False)
    assert 'class="gz-asof">資料日 10-15<' in h and "gz-stale" not in h


def test_數字卡_過期時只顯示警示不重複資料日():
    import streamlit_app as sa
    h = sa._gz_card("MU", "美光", _close(["2026-10-13", "2026-10-14"]), show_pct=False,
                    stale={"lag_days": 1, "latest": "2026-10-14"})
    assert "資料落後 1 天" in h and "gz-asof" not in h


def test_數字卡_沒資料不炸也不標日期():
    import streamlit_app as sa
    h = sa._gz_card("X", "X", pd.Series(dtype="float64"))
    assert "gz-asof" not in h


def test_市場卡_帶資料日():
    import streamlit_app as sa
    h = sa._mc_card("^DJI", "道瓊", {}, None, windows=("ma200",), asof=pd.Timestamp("2026-10-15"))
    assert 'class="mc-asof">資料日 10-15<' in h
    assert "mc-asof" not in sa._mc_card("^DJI", "道瓊", {}, None, windows=("ma200",))


def test_抓取時間轉台北():
    import streamlit_app as sa
    s = sa._snapshot_fetched_line({"fetched_at": "2026-10-15T23:59:00+00:00"})
    assert "抓取於 10-16 07:59（台北）" in s
    assert sa._snapshot_fetched_line({}) == ""


def test_夜盤標實際時段_歸屬下一交易日():
    import streamlit_app as sa
    day = _close(["2026-10-08", "2026-10-12", "2026-10-13"])           # 10/09 國慶補假
    assert sa._night_window(pd.Timestamp("2026-10-12"), day) == "10/08 15:00→10/12 05:00"
    assert sa._night_window(pd.Timestamp("2026-10-13"), day) == "10/12 15:00→10/13 05:00"
    h = sa._gz_card("TX", "夜盤收盤（前一晚）", _close(["2026-10-12", "2026-10-13"]), show_pct=False,
                    asof_text="時段 10/12 15:00→10/13 05:00")
    assert "時段 10/12 15:00→10/13 05:00" in h and "資料日" not in h
