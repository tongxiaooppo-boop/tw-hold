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


def _setup_build(tmp_path, monkeypatch, prev_asof, margin_df=None, chips_df=None):
    """組一個最小 bundle＋上一份 short_scan.json，回傳 build() 的結果。價格最後一天是 2026-09-04。"""
    import json

    import pandas as pd
    prev = {"_meta": {"asof": prev_asof, "has_margin": True, "has_chips": True},
            "stocks": [{"ticker": "A", "name": "NA", "streak_days": 1, "first_seen": prev_asof}],
            "_prev": {}, "dropped": []}
    out = tmp_path / "short_scan.json"
    out.write_text(json.dumps(prev), encoding="utf-8")
    monkeypatch.setattr(bs, "OUT", out)
    monkeypatch.setattr(bs, "UPSTREAM", tmp_path)
    dates = pd.bdate_range("2026-06-01", periods=70)
    pd.DataFrame({"ticker": ["A"], "stock_name": ["NA"], "industry": ["x"], "in_universe": [True]})         .to_parquet((tmp_path / "fundamentals").mkdir() or tmp_path / "fundamentals" / "universe.parquet")
    pd.DataFrame({"date": dates, "ticker": "A.TW", "open": 50.0, "high": 51.0, "low": 49.0,
                  "close": 50.0, "volume": 1e6}).to_parquet(tmp_path / "prices_adj.parquet")
    if margin_df is not None:
        margin_df.to_parquet(tmp_path / "margin.parquet")
    if chips_df is not None:
        chips_df.to_parquet(tmp_path / "chips.parquet")
    monkeypatch.setattr(bs, "_active_flags", lambda: {})
    return bs.build(), dates


def test_缺料保護_檔不存在_沿用原檔且真的走到守衛(tmp_path, monkeypatch, capsys):
    # prev 的 asof 早於價格最後一天（09-04）——這樣不會因為「asof 倒退」而提早 return，才是真的測守衛
    res, _ = _setup_build(tmp_path, monkeypatch, "2026-09-03")
    assert res["_meta"]["asof"] == "2026-09-03" and res["_meta"]["has_margin"] is True   # 原檔沒被覆寫
    assert "缺／殘缺 margin、chips" in capsys.readouterr().out                            # 走的是守衛分支


def test_缺料保護_檔在但最新一天殘缺_也算缺料(tmp_path, monkeypatch, capsys):
    import pandas as pd
    dates = pd.bdate_range("2026-06-01", periods=70)
    rows = [(d, f"{i}.TW") for d in dates[:-1] for i in range(100)] + [(dates[-1], "0.TW")]   # 最後一天只剩 1 檔
    thin = pd.DataFrame(rows, columns=["date", "ticker"])
    thin["margin_balance"], thin["short_balance"] = 1, 1
    chips = thin.rename(columns={"margin_balance": "foreign_net", "short_balance": "trust_net"})
    chips["dealer_net"] = 0
    res, _ = _setup_build(tmp_path, monkeypatch, "2026-09-03", margin_df=thin, chips_df=chips)
    assert res["_meta"]["asof"] == "2026-09-03"
    assert "缺／殘缺" in capsys.readouterr().out


def test_thin_latest_判準():
    import pandas as pd
    d = pd.bdate_range("2026-08-01", periods=30)
    full = pd.DataFrame([(x, i) for x in d for i in range(100)], columns=["date", "ticker"])
    asof = str(d[-1].date())
    assert bs._thin_latest(full, asof) is False                       # 正常
    assert bs._thin_latest(None, asof) is False                       # 檔不存在另外處理
    assert bs._thin_latest(full[full["date"] != d[-1]], asof) is True  # 最新一天沒有
    part = pd.concat([full[full["date"] != d[-1]], full[(full["date"] == d[-1]) & (full["ticker"] < 57)]])
    assert bs._thin_latest(part, asof) is True                        # 只有 57%
    ok = pd.concat([full[full["date"] != d[-1]], full[(full["date"] == d[-1]) & (full["ticker"] < 97)]])
    assert bs._thin_latest(ok, asof) is False                         # 97% 仍算正常（真實正常日 ≥ 98%）
