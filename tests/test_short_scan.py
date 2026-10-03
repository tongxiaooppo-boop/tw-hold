"""short_scan 進榜追蹤（`build_short_scan._track_entry`）＋ 卡片排序（`_sort_rows`）。"""
from __future__ import annotations

import sys

sys.path.insert(0, "app")

import build_short_scan as bs  # noqa: E402


def _stocks(*tks):
    return [{"ticker": t, "name": f"N{t}"} for t in tks]


def _file(asof, stocks, prev=None):
    return {"_meta": {"asof": asof}, "_prev": prev or {}, "stocks": stocks}


def test_第一天全部streak1_無掉出():
    s = _stocks("A", "B")
    base, dropped = bs._track_entry(s, "2026-10-02", None)
    assert [x["streak_days"] for x in s] == [1, 1] and dropped == []
    assert all(x["first_seen"] == "2026-10-02" for x in s)


def test_隔天累加_新進1_掉出列名():
    d1 = _stocks("A", "B")
    bs._track_entry(d1, "2026-10-02", None)
    s = _stocks("A", "C")
    base, dropped = bs._track_entry(s, "2026-10-05", _file("2026-10-02", d1))
    by = {x["ticker"]: x for x in s}
    assert by["A"]["streak_days"] == 2 and by["A"]["first_seen"] == "2026-10-02"
    assert by["C"]["streak_days"] == 1 and by["C"]["first_seen"] == "2026-10-05"
    assert dropped == [{"ticker": "B", "name": "NB"}]


def test_掉出再回來_重算1():
    d1 = _stocks("A")
    bs._track_entry(d1, "2026-10-02", None)
    d2 = _stocks("B")                                  # A 掉出
    bs._track_entry(d2, "2026-10-05", _file("2026-10-02", d1))
    d3 = _stocks("A")
    bs._track_entry(d3, "2026-10-06", _file("2026-10-05", d2))
    assert d3[0]["streak_days"] == 1 and d3[0]["first_seen"] == "2026-10-06"


def test_同日重跑_不污染基準():
    d1 = _stocks("A")
    bs._track_entry(d1, "2026-10-02", None)
    d2 = _stocks("A", "B")
    base, _ = bs._track_entry(d2, "2026-10-05", _file("2026-10-02", d1))
    f2 = _file("2026-10-05", d2, prev=base)
    d2b = _stocks("A", "B")                            # 同一天再跑一次
    bs._track_entry(d2b, "2026-10-05", f2)
    assert {x["ticker"]: x["streak_days"] for x in d2b} == {"A": 2, "B": 1}


def test_日期倒退_不更新():
    f = _file("2026-10-05", _stocks("A"))
    base, dropped = bs._track_entry(_stocks("A"), "2026-10-02", f)
    assert base is None and dropped == []


def test_sort_rows_進榜日期新到舊_同日市值大到小_缺值最後():
    import streamlit_app as sa
    rows = [{"ticker": "old", "first_seen": "2026-09-01", "market_cap": 9},
            {"ticker": "new_small", "first_seen": "2026-10-02", "market_cap": 1},
            {"ticker": "new_big", "first_seen": "2026-10-02", "market_cap": 5},
            {"ticker": "none"}]
    assert [r["ticker"] for r in sa._sort_rows(rows, "first_seen")] == \
        ["new_big", "new_small", "old", "none"]
    # 上榜天數仍由小到大
    r2 = [{"ticker": "a", "streak_days": 5}, {"ticker": "b", "streak_days": 1}]
    assert [r["ticker"] for r in sa._sort_rows(r2, "streak_days")] == ["b", "a"]
