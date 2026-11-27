"""ETF 分頁（2026-11-27 框架，Opus 定；預期值手算，實作者不得改預期值，覺得錯就停下回報）。"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

import pandas as pd
import pytest

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")
import build_etf as b  # noqa: E402
from app import etf_view as v  # noqa: E402

T = pd.Timestamp


def _px(code: str, dates, closes, opens=None) -> pd.DataFrame:
    opens = closes if opens is None else opens
    return pd.DataFrame({"ticker": code, "date": pd.to_datetime(list(dates)), "open": opens, "high": closes,
                         "low": closes, "close": closes, "volume": 1000.0, "source": "t"})


def _ev(rows) -> pd.DataFrame:
    cols = ["ticker", "date", "type", "cash", "prev_close", "ref_price", "factor", "source"]
    df = pd.DataFrame(rows, columns=cols)
    df["date"] = pd.to_datetime(df["date"])
    return df


EMPTY_EV = _ev([])


# ---------- 還原 ----------
def test_adjust_div_backward():
    p = _px("X", ["2026-01-05", "2026-01-06"], [100.0, 97.0])
    e = _ev([("X", "2026-01-06", "div", 2.0, 100.0, 98.0, 0.98, "t")])
    a = b.adjust(p, e)
    assert a["tr_close"].tolist() == pytest.approx([98.0, 97.0])
    assert a["sp_close"].tolist() == pytest.approx([100.0, 97.0])


def test_adjust_split():
    p = _px("X", ["2026-01-05", "2026-01-06"], [200.0, 50.5])
    e = _ev([("X", "2026-01-06", "split", None, None, None, 0.25, "manual")])
    a = b.adjust(p, e)
    assert a["tr_close"].tolist() == pytest.approx([50.0, 50.5])
    assert a["sp_close"].tolist() == pytest.approx([50.0, 50.5])
    assert a["sp_open"].tolist() == pytest.approx([50.0, 50.5])


def test_adjust_ignores_events_after_last_price():
    p = _px("X", ["2026-01-05", "2026-01-06"], [100.0, 101.0])
    e = _ev([("X", "2026-07-07", "split", None, None, None, 1 / 24, "manual")])
    a = b.adjust(p, e)
    assert a["tr_close"].tolist() == pytest.approx([100.0, 101.0])
    assert a["sp_close"].tolist() == pytest.approx([100.0, 101.0])


def test_check_jumps_flags_unregistered_split():
    p = _px("X", ["2026-01-05", "2026-01-06"], [200.0, 50.5])
    msgs = b.check_jumps(b.adjust(p, EMPTY_EV))
    assert len(msgs) == 1 and msgs[0].startswith("X 2026-01-06")


def test_check_jumps_ok_with_registered_split():
    p = _px("X", ["2026-01-05", "2026-01-06"], [200.0, 50.5])
    e = _ev([("X", "2026-01-06", "split", None, None, None, 0.25, "manual")])
    assert b.check_jumps(b.adjust(p, e)) == []


# ---------- 均線、報酬 ----------
def test_ma_position():
    s = pd.Series([float(i) for i in range(1, 61)])
    assert b.ma_position(s, 60) == pytest.approx(60 / 30.5 - 1)
    assert b.ma_position(s, 120) is None


def test_ret_1y():
    s = pd.Series([10.0, 11.0, 12.0], index=pd.to_datetime(["2025-11-20", "2025-11-27", "2026-11-27"]))
    assert b.ret_1y(s, T("2026-11-27")) == pytest.approx(12 / 11 - 1)      # 基準＝2025-11-27（恰好 365 天前）
    s2 = s.iloc[1:]
    assert b.ret_1y(s2, T("2026-11-27")) == pytest.approx(12 / 11 - 1)
    s3 = pd.Series([10.0, 12.0], index=pd.to_datetime(["2025-12-01", "2026-11-27"]))
    assert b.ret_1y(s3, T("2026-11-27")) is None


# ---------- 配息率 ----------
def _monthly_divs(code="D"):
    dates = ["2025-11-27"] + ["2025-11-28"] + [f"{y}-{m:02d}-27" for y, m in
                                                [(2025, 12)] + [(2026, k) for k in range(1, 12)]]
    return _ev([(code, d, "div", 0.1, 10.0, 9.9, 0.99, "t") for d in dates])   # 14 筆，第 1 筆在區間外


def test_trailing_yield_counts_13_by_date_window():
    rate, n = b.trailing_yield(_monthly_divs(), 10.0, T("2026-11-27"), T("2020-01-02"))
    assert n == 13
    assert rate == pytest.approx(1.3 / 10.0)


def test_trailing_yield_none_if_listed_under_1y():
    assert b.trailing_yield(_monthly_divs(), 10.0, T("2026-11-27"), T("2026-01-02")) == (None, None)


def test_trailing_yield_zero_events():
    assert b.trailing_yield(EMPTY_EV, 10.0, T("2026-11-27"), T("2020-01-02")) == (0.0, 0)


def test_trailing_yield_split_adjusts_cash():
    e = _ev([("X", "2026-01-10", "div", 4.0, 200.0, 196.0, 0.98, "t"),
             ("X", "2026-06-01", "split", None, None, None, 0.25, "manual")])
    rate, n = b.trailing_yield(e, 50.0, T("2026-11-27"), T("2020-01-02"))
    assert n == 1 and rate == pytest.approx(1.0 / 50.0)


def test_cash_in_current_units():
    e = _ev([("X", "2025-01-10", "div", 4.0, 200.0, 196.0, 0.98, "t"),
             ("X", "2026-06-01", "split", None, None, None, 0.25, "manual"),
             ("X", "2026-07-10", "div", 1.0, 50.0, 49.0, 0.98, "t")])
    s = b.cash_in_current_units(e)
    assert s.tolist() == pytest.approx([1.0, 1.0])


def test_yearly_yields_partial_flags():
    sp = pd.Series([25.0, 30.0, 20.0, 22.0, 40.0],
                   index=pd.to_datetime(["2024-03-01", "2024-12-31", "2025-01-02", "2025-12-31", "2026-01-02"]))
    e = _ev([("D", "2024-09-10", "div", 1.0, 1, 1, 1, "t"),
             ("D", "2025-04-10", "div", 0.5, 1, 1, 1, "t"),
             ("D", "2025-10-10", "div", 0.5, 1, 1, 1, "t"),
             ("D", "2026-04-10", "div", 2.0, 1, 1, 1, "t")])
    y = b.yearly_yields(sp, e, T("2026-11-27"), years=6)
    assert set(y) == {"2024", "2025", "2026"}
    assert y["2024"] == {"rate": pytest.approx(1.0 / 25.0), "partial": True}
    assert y["2025"] == {"rate": pytest.approx(1.0 / 20.0), "partial": False}
    assert y["2026"] == {"rate": pytest.approx(2.0 / 40.0), "partial": True}


# ---------- 定期定額 ----------
def _flat(code="X", start="2025-01-02", end="2026-03-31", price=10.0):
    d = pd.bdate_range(start, end)
    p = _px(code, d, [price] * len(d))
    return b.adjust(p, EMPTY_EV)


def test_xirr_known():
    assert b.xirr([(T("2025-01-01"), -100.0), (T("2026-01-01"), 110.0)]) == pytest.approx(0.10, abs=1e-6)


def test_dca_reinvest_flat_price():
    r = b.dca(_flat(), EMPTY_EV, T("2026-03-31"), reinvest=True)
    assert r["buys"] == 14                       # 2025-02 ～ 2026-03
    assert r["start"] == "2025-02-04"            # 2/3 是 2 月第一個交易日（bdate），隔一個交易日
    assert r["end"] == "2026-03-31"
    assert r["invested"] == pytest.approx(140_000)
    assert r["value"] == pytest.approx(140_000)
    assert r["irr"] == pytest.approx(0.0, abs=1e-6)
    assert r["worst"] == pytest.approx(0.0, abs=1e-9)


def test_dca_cash_dividend_accumulates():
    e = _ev([("X", "2025-03-20", "div", 1.0, 10.0, 9.0, 0.9, "t")])
    r = b.dca(_flat(), e, T("2026-03-31"), reinvest=False)
    # 2/4、3/4 兩次買進共 2000 單位 → 3/20 除息領 2000 元；sp 價恆 10（合成資料除息日不跌）
    assert r["value"] == pytest.approx(140_000 + 2_000)


def test_dca_none_when_under_12_buys():
    assert b.dca(_flat(end="2025-10-31"), EMPTY_EV, T("2025-10-31"), reinvest=True) is None


def test_dca_worst_after_drop():
    d = pd.bdate_range("2025-01-02", "2026-03-31")
    closes = [10.0 if x <= T("2025-02-04") else 5.0 for x in d]
    a = b.adjust(_px("X", d, closes), EMPTY_EV)
    r = b.dca(a, EMPTY_EV, T("2026-03-31"), reinvest=True)
    assert r["worst"] == pytest.approx(-0.5)


def test_dca_start_month_override():
    r = b.dca(_flat(), EMPTY_EV, T("2026-03-31"), reinvest=True, start_month="2025-04")
    assert r["buys"] == 12 and r["start"] == "2025-04-02"


# ---------- build ----------
def test_build_schema_and_missing():
    a = _px("0050", pd.bdate_range("2024-01-02", "2026-03-31"), 10.0)
    c = _px("0056", pd.bdate_range("2024-01-02", "2026-03-31"), 20.0)
    out = b.build(pd.concat([a, c], ignore_index=True), EMPTY_EV, now=datetime(2026, 3, 31, tzinfo=timezone.utc))
    assert out["asof"] == "2026-03-31"
    assert [r["code"] for r in out["rows"]] == ["0050", "0056"]
    assert "00878" in out["missing"] and "0050" not in out["missing"]
    r0 = out["rows"][0]
    assert set(r0) == {"code", "name", "group", "close", "last_date", "first_date", "ma", "ret_1y",
                       "yield_1y", "yield_1y_n"}
    assert set(r0["ma"]) == {"60", "120", "240"}
    assert r0["yield_1y"] is None                       # 市值型不算配息率
    assert out["rows"][1]["yield_1y"] == 0.0 and out["rows"][1]["yield_1y_n"] == 0
    assert set(out["yearly"]) == {"0056"}
    assert out["dca"]["0050"]["bench_reinvest"] is None
    assert out["dca"]["0056"]["bench_reinvest"]["start"] == out["dca"]["0056"]["reinvest"]["start"]


def test_build_raises_on_unregistered_jump():
    p = _px("0056", ["2026-01-05", "2026-01-06"], [200.0, 50.0])
    with pytest.raises(ValueError, match="0056 2026-01-06"):
        b.build(p, EMPTY_EV)


# ---------- etf_track ----------
def test_raw_prices_keep_default_unchanged():
    import selfhost_raw_prices as rp
    t = {"fields": ["證券代號", "名稱", "成交股數", "成交金額", "開盤價", "最高價", "最低價", "收盤價"],
         "data": [["2330", "台積電", "1,000", "1,000,000", "1,000", "1,010", "990", "1,005"],
                  ["0050", "元大台灣50", "2,000", "100,000", "50", "51", "49", "50.5"],
                  ["00878", "國泰永續高股息", "3,000", "60,000", "20", "21", "19", "20.5"]]}
    idx = {"open": "開盤價", "high": "最高價", "low": "最低價", "close": "收盤價",
           "volume": "成交股數", "value": "成交金額"}
    assert rp._rows(t, idx, "TW", "20261127")["ticker"].tolist() == ["2330", "0050"]
    got = rp._rows(t, idx, "TW", "20261127", keep=lambda c: c == "00878")
    assert got["ticker"].tolist() == ["00878"] and got["close"].tolist() == [20.5]


def test_split_events_from_table():
    import etf_track as et
    s = et.split_events()
    assert list(s.columns) == et.EVENT_COLS
    r = s[s["ticker"] == "0050"].iloc[0]
    assert r["type"] == "split" and r["factor"] == pytest.approx(0.25) and r["date"] == T("2025-06-18")


def test_upsert_new_wins():
    import etf_track as et
    old = pd.DataFrame({"ticker": ["A", "A"], "date": pd.to_datetime(["2026-01-01", "2026-01-02"]), "close": [1.0, 2.0]})
    new = pd.DataFrame({"ticker": ["A"], "date": pd.to_datetime(["2026-01-02"]), "close": [9.0]})
    got = et.upsert(old, new, ["ticker", "date"])
    assert got["close"].tolist() == [1.0, 9.0] and list(got.index) == [0, 1]


# ---------- etf_view ----------
def _row(code, ma240=None, y=None, n=None, ret=None, group="div"):
    return {"code": code, "name": code + "名", "group": group, "close": 1234.5, "last_date": "2026-11-26",
            "first_date": "2020-01-02", "ma": {"60": 0.031, "120": None, "240": ma240},
            "ret_1y": ret, "yield_1y": y, "yield_1y_n": n}


def test_fmt():
    assert v.fmt_pos(0.031) == "+3.1%" and v.fmt_pos(-0.02) == "-2.0%" and v.fmt_pos(None) == "—"
    assert v.fmt_rate(0.068) == "6.8%" and v.fmt_rate(None) == "—"


def test_sort_rows_none_last():
    rows = [_row("00919", y=0.05), _row("0056", y=None), _row("00878", y=0.07)]
    assert [r["code"] for r in v.sort_rows(rows, "yield_1y")] == ["00878", "00919", "0056"]
    assert [r["code"] for r in v.sort_rows(rows, None)] == ["0056", "00878", "00919"]
    rows2 = [_row("A", ma240=-0.1), _row("B", ma240=0.2)]
    assert [r["code"] for r in v.sort_rows(rows2, "ma240")] == ["B", "A"]


def test_page_slice_and_count():
    rows = [_row(f"{i:05d}") for i in range(20)]
    assert len(v.page_slice(rows, 1)) == 8 and len(v.page_slice(rows, 3)) == 4 and v.page_slice(rows, 4) == []
    assert v.page_count(20) == 3 and v.page_count(0) == 1


def test_table_rows_div():
    body = v.table_rows([_row("00878", ma240=-0.05, y=0.068, n=4)], "div")
    assert body == [[("00878", "00878名"), "00878名", "1,234.50", "+3.1%", "—", "-5.0%", "6.8%", "4"]]


def test_table_rows_cap():
    body = v.table_rows([_row("0050", ret=0.32, group="cap")], "cap")
    assert body == [[("0050", "0050名"), "0050名", "1,234.50", "+3.1%", "—", "—", "+32.0%"]]


def test_yearly_table():
    y = {"0056": {"2025": {"rate": 0.05, "partial": False}, "2026": {"rate": 0.06, "partial": True}},
         "00919": {"2026": {"rate": 0.1, "partial": True}}}
    head, body = v.yearly_table(y, ["0056", "00919"], {"0056": "元大高股息", "00919": "群益"})
    assert head == ["代號", "2025", "2026"]
    assert body == [[("0056", "元大高股息"), "5.0%", "6.0%*"], [("00919", "群益"), "—", "10.0%*"]]


def test_dca_table():
    d = {"start": "2020-02-04", "end": "2026-11-26", "buys": 82, "invested": 820_000.0, "value": 1_234_000.0,
         "irr": 0.112, "worst": -0.153}
    dc = {"start": "2020-02-04", "end": "2026-11-26", "buys": 82, "invested": 820_000.0, "value": 1_100_000.0,
          "irr": 0.09, "worst": -0.2}
    dca = {"00878": {"reinvest": d, "cash": dc, "bench_reinvest": {**d, "irr": 0.15}, "bench_cash": None},
           "00940": {"reinvest": None, "cash": None, "bench_reinvest": None, "bench_cash": None}}
    body = v.dca_table(dca, ["00878", "00940"], {"00878": "國泰"})
    assert body == [[("00878", "國泰"), "2020-02～2026-11", "82", "82.0 萬", "123.4 萬", "+11.2%", "-15.3%",
                     "110.0 萬", "+9.0%", "+15.0%"]]
