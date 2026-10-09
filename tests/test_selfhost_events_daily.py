"""B6：每日官方事件結果表窗口——抓取（fetch_recent）、累積併入（openapi_daily.merge_events／collect_events）、
與週收集事件表的合併（daily_merge.merge_events）與 events_through。全部不碰網路。"""
from __future__ import annotations

import json
import sys
from datetime import date

import pandas as pd

sys.path.insert(0, "scripts")
import selfhost_daily_merge as dm  # noqa: E402
import selfhost_events as se  # noqa: E402
import selfhost_openapi_daily as od  # noqa: E402

COLS = se.COLS


def _ev(rows, **extra):
    df = pd.DataFrame(rows, columns=["ticker", "market", "date", "type", "prev_close", "ref_price", "source"])
    df["factor"] = df["ref_price"] / df["prev_close"]
    df["detail"] = "{}"
    df["date"] = pd.to_datetime(df["date"])
    for k, v in extra.items():
        df[k] = v
    return df[COLS + list(extra)]


# ───────────── openapi_daily.merge_events ─────────────
def test_merge_events_新鍵新增_同鍵值變才覆蓋_舊列保留():
    old = _ev([("2330", "TW", "2026-10-05", "ex_div", 100.0, 99.0, "twse_ex"),
               ("1101", "TW", "2026-10-06", "ex_div", 50.0, 49.0, "twse_ex")])
    old["fetched_at"] = pd.Timestamp("2026-10-06 10:00")
    new = _ev([("2330", "TW", "2026-10-05", "ex_div", 100.0, 98.5, "twse_ex"),     # 官方更正：參考價變了
               ("2412", "TW", "2026-10-07", "ex_div", 120.0, 119.0, "twse_ex")])   # 新事件
    out, rep = od.merge_events(old, new, pd.Timestamp("2026-10-07 20:00"))
    assert rep == {"added": 1, "replaced": 1}
    assert len(out) == 3                                                            # 1101 沒出現在新窗口也要保留（只增不刪）
    row = out[out["ticker"] == "2330"].iloc[0]
    assert row["ref_price"] == 98.5 and row["fetched_at"] == pd.Timestamp("2026-10-07 20:00")
    assert out[out["ticker"] == "1101"].iloc[0]["fetched_at"] == pd.Timestamp("2026-10-06 10:00")


def test_merge_events_內容沒變_原表回傳_冪等():
    old = _ev([("2330", "TW", "2026-10-05", "ex_div", 100.0, 99.0, "twse_ex")])
    old["fetched_at"] = pd.Timestamp("2026-10-06 10:00")
    out, rep = od.merge_events(old, old[COLS].copy(), pd.Timestamp("2026-10-07 20:00"))
    assert rep == {"added": 0, "replaced": 0}
    assert out is old                                                               # 沒變化＝呼叫端不重傳檔


def test_merge_events_空舊表直接用新的():
    new = _ev([("2330", "TW", "2026-10-05", "ex_div", 100.0, 99.0, "twse_ex")])
    out, rep = od.merge_events(None, new, pd.Timestamp("2026-10-07 20:00"))
    assert rep == {"added": 1, "replaced": 0} and "fetched_at" in out.columns


# ───────────── openapi_daily.collect_events ─────────────
def test_events_through_依抓取時段():
    d = date(2026, 10, 8)
    assert od.events_through(d, 23) == d                                            # 16:00 後抓＝今天
    assert od.events_through(d, 16) == d
    assert od.events_through(d, 4) == date(2026, 10, 7)                             # 隔日清晨保守算到昨天


def test_events_window_ok():
    assert od.events_window_ok(23) and od.events_window_ok(4) and od.events_window_ok(16)
    assert not od.events_window_ok(8) and not od.events_window_ok(12) and not od.events_window_ok(15)


def test_collect_events_時段外不請求(monkeypatch):
    monkeypatch.setattr(se, "fetch_recent", lambda a, b: (_ for _ in ()).throw(AssertionError("不該被呼叫")))
    t, changed, meta = od.collect_events(date(2026, 10, 8), pd.Timestamp("2026-10-08 05:00"), None, hour=12)
    assert t is None and not changed and meta is None


def test_collect_events_成功_寫meta_窗口是前5天到今天(monkeypatch, tmp_path):
    seen = {}

    def fake(a, b):
        seen["win"] = (a, b)
        return _ev([("2330", "TW", "2026-10-08", "ex_div", 100.0, 99.0, "twse_ex")])
    monkeypatch.setattr(se, "fetch_recent", fake)
    monkeypatch.setattr(od, "LOG", tmp_path / "log.jsonl")
    monkeypatch.setattr(od, "SH", tmp_path)
    t, changed, meta = od.collect_events(date(2026, 10, 8), pd.Timestamp("2026-10-08 15:30"), None, hour=23)
    assert changed and len(t) == 1
    assert seen["win"] == (pd.Timestamp("2026-10-03"), pd.Timestamp("2026-10-08"))
    assert meta["through"] == "2026-10-08" and meta["rows"] == 1


def test_collect_events_沒有事件也算成功_through前進(monkeypatch, tmp_path):
    monkeypatch.setattr(se, "fetch_recent", lambda a, b: pd.DataFrame(columns=COLS))
    monkeypatch.setattr(od, "LOG", tmp_path / "log.jsonl")
    monkeypatch.setattr(od, "SH", tmp_path)
    t, changed, meta = od.collect_events(date(2026, 10, 8), pd.Timestamp("2026-10-08 15:30"), None, hour=23)
    assert not changed and meta is not None and meta["through"] == "2026-10-08"


def test_collect_events_抓取例外不拋_不給meta(monkeypatch, tmp_path):
    def boom(a, b):
        raise RuntimeError("官方掛了")
    monkeypatch.setattr(se, "fetch_recent", boom)
    monkeypatch.setattr(od, "LOG", tmp_path / "log.jsonl")
    monkeypatch.setattr(od, "SH", tmp_path)
    old = _ev([("2330", "TW", "2026-10-05", "ex_div", 100.0, 99.0, "twse_ex")])
    t, changed, meta = od.collect_events(date(2026, 10, 8), pd.Timestamp("2026-10-08 15:30"), old, hour=23)
    assert t is old and not changed and meta is None                                # 失敗不前進 through


# ───────────── selfhost_events.fetch_recent（假官方回應）─────────────
TWSE_EX = {"stat": "OK", "fields": ["資料日期", "股票代號", "股票名稱", "除權息前收盤價", "除權息參考價", "權值+息值", "權/息", "漲停價格"],
           "data": [["115年10月08日", "2330", "台積電", "1,000.00", "995.00", "5.00", "息", "1,090.00"]]}
TPEX_EX = {"tables": [{"fields": ["除權息日期", "代號", "名稱", "除權息前收盤價", "除權息參考價", "權值+息值", "權/息",
                                 "現金股利", "每仟股無償配股", "現金增資股數", "現金增資認購價"],
                       "data": [["115/10/08", "6129", "普格", "15.00", "14.11", "0.89", "權息", "0.5", "0", "1000", "12.0"]]}]}
TWSE_RED = {"stat": "OK", "fields": ["恢復買賣日期", "股票代號", "股票名稱", "停止買賣前收盤價格", "恢復買賣參考價", "減資原因"],
            "data": [["115年10月08日", "2323", "中環", "10.00", "12.50", "彌補虧損"]]}


def test_fetch_recent_併三類事件_且已enrich(monkeypatch):
    def fake_http(url, retries=0):
        if "TWT49U" in url:
            return TWSE_EX
        if "exDailyQ" in url:
            return TPEX_EX
        if "TWTAUU" in url:
            return {**TWSE_RED, "fields": ["恢復買賣日期", "股票代號", "股票名稱", "停止買賣前收盤價格", "恢復買賣參考價", "減資原因"]}
        return {"stat": "ERR", "tables": [{"fields": [], "data": []}]}              # 其餘來源這個窗口沒資料
    monkeypatch.setattr(se, "_http_json", fake_http)
    monkeypatch.setattr(se.time, "sleep", lambda s: None)
    monkeypatch.setattr(se, "_record_meta", lambda *a, **k: None)
    ev = se.fetch_recent(pd.Timestamp("2026-10-03"), pd.Timestamp("2026-10-08"))
    got = {(r.ticker, r.type, r.source) for r in ev.itertuples()}
    assert ("2330", "ex_div", "twse_ex") in got and ("6129", "ex_both", "tpex_ex") in got
    assert ("2323", "cap_reduction", "twse_red") in got
    assert "event" in ev.columns and "div_ref" in ev.columns                        # 已 enrich，欄位跟 corp_actions 一致
    r = ev[ev["ticker"] == "2330"].iloc[0]
    assert abs(r["factor"] - 0.995) < 1e-9


# ───────────── daily_merge.merge_events／events_through ─────────────
def test_daily_merge_events_沒有weekly_asof時週收集優先_每日只補沒有的():
    w = _ev([("2330", "TW", "2026-10-05", "ex_div", 100.0, 99.0, "twse_ex")], event="除息", div_ref=pd.NA)
    d = _ev([("2330", "TW", "2026-10-05", "ex_div", 100.0, 50.0, "twse_ex"),        # 同鍵但值不同、沒給週收集時間 → 週收集贏
             ("2412", "TW", "2026-10-08", "ex_div", 120.0, 119.0, "twse_ex")], event="除息", div_ref=pd.NA)
    d["fetched_at"] = pd.Timestamp("2026-10-08 20:00")                              # 每日表多的欄位要丟掉
    out, st = dm.merge_events(w, d)
    assert st["from_daily"] == 1 and len(out) == 2 and st["conflicts"] == 1 and st["weekly_won"] == 1
    assert out[out["ticker"] == "2330"].iloc[0]["ref_price"] == 99.0
    assert list(out.columns) == list(w.columns)


def test_daily_merge_events_沒有每日表_原樣():
    w = _ev([("2330", "TW", "2026-10-05", "ex_div", 100.0, 99.0, "twse_ex")])
    out, st = dm.merge_events(w, None)
    assert out is w and st["from_daily"] == 0
    out2, st2 = dm.merge_events(None, None)
    assert out2 is None and st2["from_daily"] == 0


def test_daily_merge_events_週收集沒有_全部取每日():
    d = _ev([("2412", "TW", "2026-10-08", "ex_div", 120.0, 119.0, "twse_ex")])
    d["fetched_at"] = pd.Timestamp("2026-10-08 20:00")
    out, st = dm.merge_events(None, d)
    assert st["from_daily"] == 1 and "fetched_at" not in out.columns
