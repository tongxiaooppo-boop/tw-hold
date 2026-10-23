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


def test_夜盤卡_漲跌對前一日盤結算_標時段():
    import streamlit_app as sa
    day = _close(["2026-10-14", "2026-10-15"])
    night = pd.Series([47945.0, 47366.0], index=pd.to_datetime(["2026-10-15", "2026-10-16"]))
    settle = pd.Series([48798.0, 46931.0], index=pd.to_datetime(["2026-10-14", "2026-10-15"]))
    h = sa._tx_night_card(night, day, settle)
    assert "47,366.00" in h and "+435.00" in h and "vs 10/15 日盤結算 46,931" in h
    assert "時段 10/15 15:00→10/16 05:00" in h


def test_夜盤卡_結算價0不除以0():
    """2026-10-21 10 月合約最後交易日，期交所結算價欄填 0 → App ZeroDivisionError 整頁炸。"""
    import streamlit_app as sa
    day = _close(["2026-10-20", "2026-10-21"])
    night = pd.Series([46975.0], index=pd.to_datetime(["2026-10-22"]))
    settle = pd.Series([46341.0, 0.0], index=pd.to_datetime(["2026-10-20", "2026-10-21"]))
    h = sa._tx_night_card(night, day, settle)
    assert "vs 10/20 日盤結算 46,341" in h


def test_夜盤卡_換月無同合約基準就不算漲跌():
    import streamlit_app as sa
    night = pd.Series([46975.0, 47482.0], index=pd.to_datetime(["2026-10-21", "2026-10-22"]))
    empty = pd.Series(dtype="float64")
    h = sa._tx_night_card(night, _close(["2026-10-21"]), empty, base_day=empty, rollover="202611")
    assert "47,482.00" in h and "vs " not in h and "換月（202611）" in h and "+507" not in h


def test_tx_futures_同合約篩選且結算價0視為無(monkeypatch, tmp_path):
    from reference import tx_futures
    p = tmp_path / "tx.parquet"
    pd.DataFrame({"date": pd.to_datetime(["2026-10-20", "2026-10-21", "2026-10-21", "2026-10-22"]),
                  "session": ["day", "day", "night", "night"],
                  "contract_month": ["202610", "202610", "202610", "202611"],
                  "last": [46384.0, 46648.0, 46975.0, 47482.0],
                  "settlement": [46341.0, 0.0, None, None]}).to_parquet(p)
    monkeypatch.setattr(tx_futures, "TX_FUTURES", p)
    assert tx_futures.latest_contract("night") == "202611"
    assert tx_futures.load_day_settlement("202611").empty
    assert list(tx_futures.load_day_settlement()) == [46341.0]
    assert list(tx_futures.load_session("day", "202610")) == [46384.0, 46648.0]


def test_主動ETF圖例_標出晚一天的基金():
    """中信隔天才公告，CI 晚上跑時固定晚一天（2026-10-23）。"""
    import streamlit_app as sa
    h = sa._active_legend({"_meta": {"stale_etfs": 1, "total_etfs": 6, "anchor_date": "2026-10-22",
                                     "funds": {"00981A": {"synced": True},
                                               "00406A": {"synced": False, "lagging": True}}}})
    assert "1/6 檔尚未更新（00406A 資料日晚一天" in h
