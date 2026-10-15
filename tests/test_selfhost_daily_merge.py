"""B4 每日併入：週收集優先、只補週收集沒有的日子、只發佈完整日。"""
from __future__ import annotations

import json
import sys

import pandas as pd

sys.path.insert(0, "scripts")
import selfhost_daily_merge as dm  # noqa: E402


def _px(rows):
    df = pd.DataFrame(rows, columns=["ticker", "market", "date", "close"])
    df["date"] = pd.to_datetime(df["date"])
    for c in ("open", "high", "low"):
        df[c] = df["close"]
    df["volume"], df["value"], df["chg"] = 1000.0, 1.0, 0.0
    return df[["ticker", "market", "date", "open", "high", "low", "close", "volume", "value", "chg"]]


def test_週收集有的日子用週收集_只補沒有的日子_重疊不一致要記():
    w = _px([("2330", "TW", "2026-10-05", 100.0), ("2330", "TW", "2026-10-06", 101.0)])
    d = _px([("2330", "TW", "2026-10-06", 999.0), ("2330", "TW", "2026-10-07", 102.0)])
    d["src"], d["next_ref"] = "openapi", float("nan")                       # 每日表的額外欄位要丟掉
    out, rep = dm.merge_table(w, d, ["close"])
    assert list(out["close"]) == [100.0, 101.0, 102.0]                       # 10/6 用週收集，不被每日表蓋掉
    assert list(out.columns) == list(w.columns)
    assert rep["appended"] == {"TW 2026-10-07": 1}
    assert rep["overlap"]["TW 2026-10-06"]["value_diff"] == {"close": 1}     # 不一致要講出來


def test_重跑冪等():
    w = _px([("2330", "TW", "2026-10-05", 100.0)])
    d = _px([("2330", "TW", "2026-10-06", 101.0)])
    once, _ = dm.merge_table(w, d, ["close"])
    twice, rep = dm.merge_table(once, d, ["close"])
    assert len(twice) == 2 and rep["appended"] == {}


def test_完整日取六項最小_缺任何一項就不決定():
    lasts = {"raw_prices.TW": "2026-10-08", "raw_prices.TWO": "2026-10-08", "inst.TW": "2026-10-08",
             "inst.TWO": "2026-10-08", "margin.TW": "2026-10-07", "margin.TWO": "2026-10-08"}
    assert dm.complete_day(lasts) == pd.Timestamp("2026-10-07")             # 融資還沒到 → 只發佈到 10/7
    assert dm.complete_day({**lasts, "margin.TW": None}) is None


def test_main_完整日之後不收_事件缺口要講(tmp_path):
    w, dd, o = tmp_path / "w", tmp_path / "d", tmp_path / "o"
    w.mkdir(), dd.mkdir()
    days = ["2026-10-06", "2026-10-07"]
    _px([(t, mk, x, 10.0) for t, mk in (("2330", "TW"), ("6129", "TWO")) for x in days[:1]]).to_parquet(w / "raw_prices.parquet")
    _px([(t, mk, x, 10.0) for t, mk in (("2330", "TW"), ("6129", "TWO")) for x in days[1:]]).to_parquet(dd / "openapi_prices.parquet")
    for name, dname, cols in (("inst", "openapi_inst", ["foreign_net", "fi_prop_net", "trust_net", "dealer_net", "total_net"]),
                              ("margin", "openapi_margin", ["margin_balance", "margin_buy", "margin_sell", "margin_redeem",
                                                            "short_balance", "short_buy", "short_sell", "short_redeem", "offset"])):
        base = pd.DataFrame({"date": pd.to_datetime(days[0]), "ticker": ["2330", "6129"], "market": ["TW", "TWO"],
                             **{c: 1.0 for c in cols}})
        base.to_parquet(w / f"{name}.parquet")
        # 每日表：法人兩市場都有 10/7；融資只有上櫃 10/7（上市融資還沒到）
        nxt = base.assign(date=pd.to_datetime(days[1]))
        (nxt if name == "inst" else nxt[nxt["market"] == "TWO"]).to_parquet(dd / f"{dname}.parquet")
    pd.DataFrame({"ticker": ["2330"], "date": pd.to_datetime(["2026-09-01"])}).to_parquet(w / "corp_actions.parquet")

    assert dm.main(["--weekly-dir", str(w), "--daily-dir", str(dd), "--out-dir", str(o)]) == 0
    man = json.loads((o / "merge_manifest.json").read_text(encoding="utf-8"))
    assert man["complete_day"] == "2026-10-06"                               # 上市融資缺 10/7 → 整天不發佈
    assert pd.read_parquet(o / "raw_prices.parquet")["date"].max() == pd.Timestamp("2026-10-06")
    assert "TW 2026-10-07" in man["pending_after_complete_day"]["raw_prices"]
    assert man["events_gap_days"] == []                                      # 完整日沒超過週收集日 → 無事件缺口


def test_輸入雜湊_內容一樣就一樣_更正就變(tmp_path):
    w, dd = tmp_path / "w", tmp_path / "d"
    w.mkdir(), dd.mkdir()
    _px([("2330", "TW", "2026-10-06", 10.0), ("6129", "TWO", "2026-10-06", 10.0)]).to_parquet(w / "raw_prices.parquet")
    for name, cols in (("inst", ["foreign_net", "fi_prop_net", "trust_net", "dealer_net", "total_net"]),
                       ("margin", ["margin_balance", "margin_buy", "margin_sell", "short_balance", "short_sell"])):
        pd.DataFrame({"date": pd.to_datetime("2026-10-06"), "ticker": ["2330", "6129"], "market": ["TW", "TWO"],
                      **{c: 1.0 for c in cols}}).to_parquet(w / f"{name}.parquet")
    def run(o):
        assert dm.main(["--weekly-dir", str(w), "--daily-dir", str(dd), "--out-dir", str(o)]) == 0
        return json.loads((o / "merge_manifest.json").read_text(encoding="utf-8"))["input_hash"]
    h1, h2 = run(tmp_path / "o1"), run(tmp_path / "o2")
    assert h1 == h2                                                          # 同樣輸入 → 同樣雜湊（workflow 才能跳過）
    _px([("2330", "TW", "2026-10-06", 10.5), ("6129", "TWO", "2026-10-06", 10.0)]).to_parquet(w / "raw_prices.parquet")
    assert run(tmp_path / "o3") != h1                                       # 舊日子被更正 → 雜湊變 → 重做


def _tbl(rows):
    return _px(rows)


def test_中間缺日要被發現_整齊時沒有洞():
    full = {"raw_prices": _tbl([("2330", "TW", "2026-10-06", 1.0), ("2330", "TW", "2026-10-07", 1.0), ("6488", "TWO", "2026-10-06", 1.0), ("6488", "TWO", "2026-10-07", 1.0)])}
    assert dm.find_gaps(full, pd.Timestamp("2026-10-07")) == {}
    hole = {"raw_prices": _tbl([("2330", "TW", "2026-10-07", 1.0), ("6488", "TWO", "2026-10-06", 1.0), ("6488", "TWO", "2026-10-07", 1.0)])}
    assert dm.find_gaps(hole, pd.Timestamp("2026-10-07")) == {"raw_prices.TW": ["2026-10-06"]}   # 上市 10/6 漏了，完整日仍是 10/7


def test_窗口外的舊洞不算():
    old = {"raw_prices": _tbl([("2330", "TW", "2026-09-01", 1.0), ("6488", "TWO", "2026-09-01", 1.0), ("6488", "TWO", "2026-09-02", 1.0),
                               ("2330", "TW", "2026-10-07", 1.0), ("6488", "TWO", "2026-10-07", 1.0)])}
    assert dm.find_gaps(old, pd.Timestamp("2026-10-07")) == {}


def test_跨表缺日_raw有inst沒有要報洞():
    raw = _tbl([("2330", "TW", "2026-10-06", 1.0), ("2330", "TW", "2026-10-07", 1.0), ("6488", "TWO", "2026-10-06", 1.0), ("6488", "TWO", "2026-10-07", 1.0)])
    inst = _tbl([("2330", "TW", "2026-10-07", 1.0), ("6488", "TWO", "2026-10-06", 1.0), ("6488", "TWO", "2026-10-07", 1.0)])
    gaps = dm.find_gaps({"raw_prices": raw, "inst": inst}, pd.Timestamp("2026-10-07"))
    assert gaps == {"inst.TW": ["2026-10-06"]}


# ── 無成交旁表：週收集 ∪ 每日表（2026-10-13）──
def _nt(rows):
    return pd.DataFrame(rows, columns=["ticker", "market", "date", "volume", "value", "src"]).assign(date=lambda d: pd.to_datetime(d["date"]))


def test_notrade_聯集_週收集優先_只留完整日以前():
    w = _nt([("2718", "TWO", "2026-10-07", 100.0, 1.0, "official")])
    d = _nt([("2718", "TWO", "2026-10-07", 999.0, 9.0, "openapi"),        # 同鍵：以週收集為準
             ("5276", "TWO", "2026-10-08", 191.0, 3.0, "openapi"),
             ("5276", "TWO", "2026-10-12", 0.0, 0.0, "openapi")])         # 完整日之後：不收
    m = dm.merge_notrade(w, d, pd.Timestamp("2026-10-08"))
    assert len(m) == 2
    assert m[m["ticker"] == "2718"]["volume"].iloc[0] == 100.0
    assert dm.merge_notrade(None, None, pd.Timestamp("2026-10-08")) is None
    assert len(dm.merge_notrade(None, d, pd.Timestamp("2026-10-12"))) == 3       # 只有每日表也行（週表還沒涵蓋到的新日子）


def test_main_有旁表就輸出且進雜湊_沒有就不輸出(tmp_path):
    w, dd = tmp_path / "w", tmp_path / "d"
    w.mkdir(), dd.mkdir()
    _px([("2330", "TW", "2026-10-06", 10.0), ("6129", "TWO", "2026-10-06", 10.0)]).to_parquet(w / "raw_prices.parquet")
    for name, cols in (("inst", ["foreign_net", "fi_prop_net", "trust_net", "dealer_net", "total_net"]),
                       ("margin", ["margin_balance", "margin_buy", "margin_sell", "short_balance", "short_sell"])):
        pd.DataFrame({"date": pd.to_datetime("2026-10-06"), "ticker": ["2330", "6129"], "market": ["TW", "TWO"],
                      **{c: 1.0 for c in cols}}).to_parquet(w / f"{name}.parquet")
    def run(o):
        assert dm.main(["--weekly-dir", str(w), "--daily-dir", str(dd), "--out-dir", str(o)]) == 0
        return json.loads((o / "merge_manifest.json").read_text(encoding="utf-8"))["input_hash"]
    h0 = run(tmp_path / "o0")
    assert not (tmp_path / "o0" / "notrade.parquet").exists()
    _nt([("6129", "TWO", "2026-10-06", 5.0, 1.0, "official")]).to_parquet(dd / "openapi_notrade.parquet")
    h1 = run(tmp_path / "o1")
    assert len(pd.read_parquet(tmp_path / "o1" / "notrade.parquet")) == 1
    assert h1 != h0                                                          # 旁表變了 → 雜湊變 → zip 會重做


def _cnt_tbl(counts: dict[str, int], mk="TW"):
    rows = [{"ticker": f"{1000 + i}", "market": mk, "date": pd.Timestamp(d)} for d, n in counts.items() for i in range(n)]
    return pd.DataFrame(rows)


def test_列數殘缺的最後一天要退回_不是通過():
    ok = {"2026-10-01": 100, "2026-10-02": 100, "2026-10-05": 101, "2026-10-06": 100, "2026-10-07": 100}
    tw = _cnt_tbl({**ok, "2026-10-08": 100}, "TW")
    two_bad = _cnt_tbl({**ok, "2026-10-08": 45}, "TWO")            # 上櫃只回 45%
    merged = {"raw_prices": pd.concat([tw, two_bad], ignore_index=True)}
    cday, why = dm.rowcount_complete_day(merged, pd.Timestamp("2026-10-08"))
    assert cday == pd.Timestamp("2026-10-07") and "raw_prices.TWO" in why


def test_列數正常或小幅波動不退回():
    base = {"2026-10-01": 100, "2026-10-02": 100, "2026-10-05": 101, "2026-10-06": 99, "2026-10-07": 100}
    merged = {"inst": _cnt_tbl({**base, "2026-10-08": 97}, "TW")}              # 97% ≥ 95%
    cday, why = dm.rowcount_complete_day(merged, pd.Timestamp("2026-10-08"))
    assert cday == pd.Timestamp("2026-10-08") and not why


def test_連續兩天殘缺退到最後一個正常日():
    ok = {"2026-10-01": 100, "2026-10-02": 100, "2026-10-05": 100, "2026-10-06": 100}
    merged = {"margin": _cnt_tbl({**ok, "2026-10-07": 30, "2026-10-08": 30}, "TW")}
    cday, _ = dm.rowcount_complete_day(merged, pd.Timestamp("2026-10-08"))
    assert cday == pd.Timestamp("2026-10-06")


def test_可比日不足3天視為正常():
    merged = {"raw_prices": _cnt_tbl({"2026-10-07": 100, "2026-10-08": 10}, "TW")}
    cday, why = dm.rowcount_complete_day(merged, pd.Timestamp("2026-10-08"))
    assert cday == pd.Timestamp("2026-10-08") and not why


def test_cday_rows_寫出完整日各表各市場列數():
    merged = {"raw_prices": pd.concat([_cnt_tbl({"2026-10-08": 7}, "TW"), _cnt_tbl({"2026-10-08": 3}, "TWO")])}
    r = dm.cday_rows(merged, pd.Timestamp("2026-10-08"))
    assert r["raw_prices.TW"] == 7 and r["raw_prices.TWO"] == 3
