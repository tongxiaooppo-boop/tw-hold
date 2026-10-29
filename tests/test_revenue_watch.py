"""`screener/revenue_watch.py`（純函式層）與 `build_revenue_watch.py` 的單元測試。

全部餵 DataFrame / dict 測，不連網、不讀 bundle parquet（除了
`test_preloaded_reader_matches_original` 用 `tmp_path` 造一小張 parquet 驗證
preloaded reader 與原 `bundle_data._read` 行為一致）。
"""
from __future__ import annotations

import pytest
import pandas as pd


# ── periods_to_show ────────────────────────────────────────────────
def test_periods_to_show():
    from screener import revenue_watch as rw
    assert [str(p) for p in rw.periods_to_show(pd.Timestamp("2026-10-29"))] == ["2026-09", "2026-08"]
    assert [str(p) for p in rw.periods_to_show(pd.Timestamp("2026-11-03"))] == ["2026-10", "2026-09"]
    assert [str(p) for p in rw.periods_to_show(pd.Timestamp("2027-01-05"))] == ["2026-12", "2026-11"]


# ── ratio ──────────────────────────────────────────────────────────
def test_ratio():
    from screener import revenue_watch as rw
    assert rw.ratio(110, 100) == pytest.approx(0.1)
    assert rw.ratio(90, 100) == pytest.approx(-0.1)
    assert rw.ratio(None, 100) is None
    assert rw.ratio(1, None) is None
    assert rw.ratio(1, 0) is None
    assert rw.ratio(1, -5) is None


# ── yoy_streak ─────────────────────────────────────────────────────
def test_yoy_streak():
    from screener import revenue_watch as rw
    months = pd.period_range("2025-01", "2026-09", freq="M")
    rev = [100.0] * 12 + [90.0] * 6 + [120.0] * 3  # 2026-07~09 年增才轉正
    hist = pd.DataFrame({"month": [m.to_timestamp() for m in months], "revenue": rev})
    assert rw.yoy_streak(hist, pd.Period("2026-09", freq="M")) == 3
    assert rw.yoy_streak(hist, pd.Period("2026-06", freq="M")) == 0
    # 缺去年同月 → 斷在缺的那一格
    hist2 = hist[hist["month"] != pd.Timestamp("2025-08-01")].reset_index(drop=True)
    assert rw.yoy_streak(hist2, pd.Period("2026-09", freq="M")) == 1


# ── record_high ────────────────────────────────────────────────────
def test_record_high():
    from screener import revenue_watch as rw
    base_months = list(pd.period_range("2025-09", "2026-08", freq="M"))

    def build(last):
        m = base_months + [pd.Period("2026-09", freq="M")]
        r = [100.0] * 12 + [last]
        return pd.DataFrame({"month": [x.to_timestamp() for x in m], "revenue": r})

    assert rw.record_high(build(150.0), pd.Period("2026-09", freq="M")) is True
    assert rw.record_high(build(99.0), pd.Period("2026-09", freq="M")) is False
    assert rw.record_high(build(100.0), pd.Period("2026-09", freq="M")) is True  # ≥ 即成立
    # 更早月份少於 12 → False
    short = pd.DataFrame({"month": [m.to_timestamp() for m in pd.period_range("2026-03", "2026-09", freq="M")],
                          "revenue": [100.0] * 7})
    assert rw.record_high(short, pd.Period("2026-09", freq="M")) is False


# ── ma_status ──────────────────────────────────────────────────────
def test_ma_status():
    from screener import revenue_watch as rw
    px = pd.DataFrame({"date": pd.date_range("2026-01-01", periods=60, freq="D"),
                       "close": list(range(1, 61))})
    s = rw.ma_status(px)
    assert s["price"] == 60
    assert s["ma20"] == pytest.approx(50.5)   # 41..60 平均
    assert s["ma60"] == pytest.approx(30.5)   # 1..60 平均
    assert s["above_ma20"] is True
    assert s["above_ma60"] is True

    s19 = rw.ma_status(px.head(19))
    assert s19["price"] == 19
    assert s19["ma20"] is None and s19["above_ma20"] is None
    assert s19["ma60"] is None and s19["above_ma60"] is None

    empty = rw.ma_status(pd.DataFrame(columns=["date", "close"]))
    for k in ("price", "ma20", "ma60", "above_ma20", "above_ma60", "price_date"):
        assert empty[k] is None


# ── valuation_fields ───────────────────────────────────────────────
def test_valuation_fields_not_ok():
    from screener import revenue_watch as rw
    v = rw.valuation_fields({"ok": False, "reason": "財報不足 4 季，不做試算。"}, 100.0)
    assert v["est_ok"] is False
    assert v["est_reason"] == "財報不足 4 季，不做試算。"
    assert v["band_mid"] is None
    assert v["upside_mid"] is None
    assert v["at_valuation"] is None
    assert v["warns"] == []


def test_valuation_fields_ok():
    from screener import revenue_watch as rw
    est = {"ok": True, "reason": None,
           "band": {"low": 80, "mid": 100, "high": 120}, "growth_price": 150,
           "eps": {"run_ex": 5.0}, "year": {"est": 6.0},
           "cycle": {"pct": 0.85}, "warns": ["a"], "infos": ["b"]}
    v = rw.valuation_fields(est, 70.0)
    assert v["est_ok"] is True
    assert v["upside_mid"] == pytest.approx(0.428571, abs=1e-5)
    assert v["upside_growth"] == pytest.approx(1.142857, abs=1e-5)
    assert v["at_valuation"] is False
    assert v["cyclical"] is True
    assert v["warns"] == ["a", "b"]
    assert v["run_eps"] == 5.0
    assert v["est_eps"] == 6.0
    assert v["band_low"] == 80 and v["band_high"] == 120

    assert rw.valuation_fields(est, 100.0)["at_valuation"] is True  # price >= mid

    est3 = {"ok": True, "reason": None, "band": None, "year": None, "cycle": None}
    v3 = rw.valuation_fields(est3, 100.0)
    assert v3["band_low"] is None and v3["band_mid"] is None and v3["band_high"] is None
    assert v3["upside_mid"] is None
    assert v3["at_valuation"] is None
    assert v3["est_eps"] is None
    assert v3["cyclical"] is False



# ── make_row ───────────────────────────────────────────────────────
def test_make_row():
    from screener import revenue_watch as rw
    hist = pd.DataFrame({"month": [pd.Timestamp("2026-09-01")], "revenue": [1e9]})
    base = {"code": "2330", "name": "台積電", "industry": "半導體", "market_cap": 1e12,
            "revenue": 1.2e9, "revenue_prev_month": 1.0e9, "revenue_last_year": 1.1e9,
            "revenue_cum": 9e9, "revenue_cum_last_year": 8e9, "note": "-",
            "first_seen_at": pd.Timestamp("2026-11-03 18:47"), "revised": False}
    ma = {"price": 100.0, "ma20": 95.0, "ma60": 90.0, "above_ma20": True, "above_ma60": True}
    val = {"est_ok": True, "est_reason": None, "run_eps": 5.0, "est_eps": 6.0,
           "band_low": 80.0, "band_mid": 100.0, "band_high": 120.0, "growth_price": 150.0,
           "upside_mid": 0.0, "upside_growth": 0.5, "at_valuation": True,
           "cyclical": False, "pe_wide": False, "warns": []}
    row = rw.make_row(base, hist, pd.Period("2026-09", freq="M"), ma, val)
    assert row["first_seen_at"] == "2026-11-03 18:47"
    assert row["note"] == ""                    # "-" → ""
    assert row["mom"] == pytest.approx(0.2)
    assert row["yoy"] == pytest.approx(0.090909, abs=1e-5)
    assert row["cum_yoy"] == pytest.approx(0.125)
    assert row["low_base"] is False
    assert row["yoy_streak"] == 0
    assert row["record_high"] is False
    assert list(row.keys()) == [
        "code", "name", "industry", "market_cap", "revenue", "revenue_prev_month",
        "revenue_last_year", "mom", "yoy", "cum_yoy", "note", "first_seen_at", "revised",
        "yoy_streak", "record_high", "low_base",
        "price", "ma20", "ma60", "above_ma20", "above_ma60",
        "est_ok", "est_reason", "run_eps", "est_eps",
        "band_low", "band_mid", "band_high", "growth_price",
        "upside_mid", "upside_growth", "at_valuation", "cyclical", "pe_wide", "warns",
    ]


# ── rank ───────────────────────────────────────────────────────────
def test_rank():
    from screener import revenue_watch as rw
    rows = [
        {"yoy": 0.5, "low_base": True, "market_cap": 100.0, "est_ok": True},
        {"yoy": 0.4, "low_base": False, "market_cap": 200.0, "est_ok": True},
        {"yoy": None, "low_base": False, "market_cap": 300.0, "est_ok": True},
        {"yoy": 0.3, "low_base": False, "market_cap": 400.0, "est_ok": True},
    ]
    assert [r["yoy"] for r in rw.rank(rows, "yoy")] == [0.5, 0.4, 0.3]
    assert [r["yoy"] for r in rw.rank(rows, "yoy", exclude_low_base=True)] == [0.4, 0.3]
    assert [r["yoy"] for r in rw.rank(rows, "yoy", n=1)] == [0.5]
    # 同分 → market_cap 大者在前
    tie = [{"yoy": 0.5, "market_cap": 100.0}, {"yoy": 0.5, "market_cap": 200.0}]
    assert [r["market_cap"] for r in rw.rank(tie, "yoy")] == [200.0, 100.0]
    # require：est_ok 必須為真
    rows2 = [{"yoy": 0.5, "market_cap": 100.0, "est_ok": False},
             {"yoy": 0.4, "market_cap": 200.0, "est_ok": True}]
    assert [r["yoy"] for r in rw.rank(rows2, "yoy", require=("est_ok",))] == [0.4]


# ── hold_signal ────────────────────────────────────────────────────
def test_hold_signal():
    from screener import revenue_watch as rw
    assert rw.hold_signal({"above_ma60": False, "above_ma20": True, "at_valuation": True}) == "跌破季線"
    assert rw.hold_signal({"above_ma60": True, "above_ma20": False, "at_valuation": True}) == "跌破月線"
    assert rw.hold_signal({"above_ma60": True, "above_ma20": True, "at_valuation": True}) == "已到估值"
    assert rw.hold_signal({"above_ma60": None, "above_ma20": None, "at_valuation": None}) is None


# ── preloaded reader 與原 _read 行為一致 ───────────────────────────
def test_preloaded_reader_matches_original(tmp_path, monkeypatch):
    import sys
    from pathlib import Path

    REPO = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(REPO))
    sys.path.insert(0, str(REPO / "app"))
    import bundle_data
    import build_revenue_watch as b

    df = pd.DataFrame({
        "ticker": ["2330.TW", "8069.TWO", "2330.TW", "8069.TWO"],
        "date": ["2026-10-27", "2026-10-27", "2026-10-28", "2026-10-28"],
        "close": [1000.0, 50.0, 1010.0, 51.0],
        "value": [1.0, 2.0, 3.0, 4.0],
    })
    df.to_parquet(tmp_path / "prices_adj.parquet")

    monkeypatch.setattr(bundle_data, "_dest", lambda name: tmp_path / name)

    cases = [
        ("prices_adj.parquet", "2330", False, None),                    # 裸代號 → 空
        ("prices_adj.parquet", "2330", True, None),                     # 2 列 .TW
        ("prices_adj.parquet", "8069", True, ["date", "close"]),        # 2 列 .TWO，挑欄
        ("prices_adj.parquet", "8069", False, ["close", "value"]),      # 裸代號 → 空
        ("missing.parquet", "2330", False, None),                       # 檔不存在 → 空
    ]

    orig = bundle_data._read
    b._install_preloaded_reader()
    preloaded = bundle_data._read
    for name, code, suffixed, columns in cases:
        want = orig(name, code, suffixed, columns)
        got = preloaded(name, code, suffixed, columns)
        pd.testing.assert_frame_equal(got, want)



def test_pe_wide_and_rank_exclude():
    from screener import revenue_watch as rw
    # Opus 2026-10-29 加：pe_wide 取自 estimate 的 pe.wide；rank 的 exclude 排除為真的欄位
    est = {"ok": True, "reason": None, "band": {"low": 80, "mid": 100, "high": 120},
           "pe": {"wide": True}, "warns": [], "infos": []}
    assert rw.valuation_fields(est, 70)["pe_wide"] is True
    assert rw.valuation_fields({"ok": True, "warns": [], "infos": []}, 70)["pe_wide"] is False
    rows = [{"code": "A", "u": 3.0, "cyclical": True, "pe_wide": False, "market_cap": 1},
            {"code": "B", "u": 2.0, "cyclical": False, "pe_wide": True, "market_cap": 1},
            {"code": "C", "u": 1.0, "cyclical": False, "pe_wide": False, "market_cap": 1}]
    assert [r["code"] for r in rw.rank(rows, "u", exclude=("cyclical", "pe_wide"))] == ["C"]
    assert [r["code"] for r in rw.rank(rows, "u")] == ["A", "B", "C"]
