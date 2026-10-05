"""自建上游：官方實價解析、事件去重、還原引擎。"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "scripts")
import selfhost_adjust as sa  # noqa: E402
import selfhost_events as se  # noqa: E402
import selfhost_raw_prices as rp  # noqa: E402


def _ts(s):
    return pd.Timestamp(s)


# ───────── 實價解析 ─────────
def test_num_處理千分位與無成交():
    assert rp._num("1,234.50") == 1234.5
    assert rp._num("--") is None
    assert rp._num("0.00") is None
    assert rp._num("X0.00") is None


def test_rows_用欄名取欄且只留四碼代號():
    table = {"fields": ["證券代號", "證券名稱", "成交股數", "成交金額", "開盤價", "最高價", "最低價", "收盤價"],
             "data": [["2330", "台積電", "1,000", "500,000", "500", "510", "495", "505"],
                      ["00400A", "主動ETF", "1", "1", "15", "16", "14", "15"],       # 6 碼：濾掉
                      ["1101", "台泥", "0", "0", "--", "--", "--", "--"]]}             # 無成交：濾掉
    df = rp._rows(table, {"open": "開盤價", "high": "最高價", "low": "最低價", "close": "收盤價",
                          "volume": "成交股數", "value": "成交金額"}, "TW", "20261002")
    assert df["ticker"].tolist() == ["2330"]
    assert df.iloc[0]["close"] == 505 and df.iloc[0]["volume"] == 1000


# ───────── 事件去重 ─────────
def _ev(ticker, date, typ, factor, source):
    return {"ticker": ticker, "market": "TW", "date": _ts(date), "type": typ, "prev_close": 100.0,
            "ref_price": 100.0 * factor, "factor": factor, "source": source, "detail": "{}"}


def test_同日同類多來源只套用一次且標重複():
    ev = pd.DataFrame([_ev("5904", "2026-07-22", "par_change", 0.1, "fm_split"),
                       _ev("5904", "2026-07-22", "par_change", 0.1, "fm_par")])
    r = sa.resolve_events(ev)
    assert len(r) == 1 and r.iloc[0]["n_sources"] == 2 and not r.iloc[0]["conflict"]
    assert r.iloc[0]["source"] == "fm_split"            # 優先序


def test_多來源因子差異過大標_conflict():
    ev = pd.DataFrame([_ev("1234", "2026-07-01", "par_change", 0.50, "fm_split"),
                       _ev("1234", "2026-07-01", "par_change", 0.60, "fm_par")])
    assert bool(sa.resolve_events(ev).iloc[0]["conflict"])


def test_同日不同類別各自套用並標_multi_class():
    ev = pd.DataFrame([_ev("2607", "2025-10-07", "ex_div", 0.98, "twse_ex"),
                       _ev("2607", "2025-10-07", "cap_reduction", 1.714, "fm_reduction")])
    r = sa.resolve_events(ev)
    assert len(r) == 2 and r["multi_class"].all()


def test_未知類型不套用():
    ev = pd.DataFrame([_ev("1111", "2026-07-01", "ex_other:怪", 0.9, "twse_ex")])
    assert sa.resolve_events(ev).empty


# ───────── 還原引擎 ─────────
def _raw(rows):
    return pd.DataFrame([{"ticker": t, "date": _ts(d), "open": p, "high": p, "low": p, "close": p, "volume": 1}
                         for t, d, p in rows])


def test_事件日之前乘因子_事件日當天與之後不乘():
    raw = _raw([("1101", "2026-07-01", 100), ("1101", "2026-07-02", 100),
                ("1101", "2026-07-03", 90), ("1101", "2026-07-06", 90)])
    ev = sa.resolve_events(pd.DataFrame([_ev("1101", "2026-07-03", "ex_div", 0.9, "twse_ex")]))
    adj = sa.adjust(raw, ev).set_index("date")
    assert np.allclose(adj["close"].to_numpy(), [90, 90, 90, 90])      # 還原後連續
    assert np.allclose(adj["raw_close"].to_numpy(), [100, 100, 90, 90])  # 實價保留


def test_多事件因子連乘():
    raw = _raw([("1101", "2026-06-01", 100), ("1101", "2026-07-01", 90), ("1101", "2026-08-01", 81)])
    ev = sa.resolve_events(pd.DataFrame([_ev("1101", "2026-07-01", "ex_div", 0.9, "twse_ex"),
                                         _ev("1101", "2026-08-01", "ex_div", 0.9, "twse_ex")]))
    assert np.allclose(sa.adjust(raw, ev)["close"].to_numpy(), [81, 81, 81])


def test_減資因子大於一把歷史往上調():
    raw = _raw([("2607", "2025-10-06", 35), ("2607", "2025-10-07", 60)])
    ev = sa.resolve_events(pd.DataFrame([_ev("2607", "2025-10-07", "cap_reduction", 60 / 35, "fm_reduction")]))
    assert np.allclose(sa.adjust(raw, ev)["close"].to_numpy(), [60, 60])


def test_無事件的股票原樣通過():
    raw = _raw([("2330", "2026-07-01", 500)])
    assert sa.adjust(raw, sa.resolve_events(pd.DataFrame(columns=se.COLS))).iloc[0]["close"] == 500


# ───────── 事件抓取：因子定義 ─────────
def test_官方事件類型對應():
    assert {"息": "ex_div", "權": "ex_rights", "權息": "ex_both"}["息"] == "ex_div"
    assert se.COLS[:3] == ["ticker", "market", "date"]


# ───────── 閘門 ─────────
import selfhost_gate as sg  # noqa: E402


def _days(n, per_market, start="2026-09-01"):
    rows = []
    for i, d in enumerate(pd.bdate_range(start, periods=n)):
        for m, k in per_market.items():
            rows += [{"date": d, "ticker": f"{j:04d}", "market": m} for j in range(k)]
    return pd.DataFrame(rows)


def test_閘門_正常通過():
    base = _days(25, {"TW": 1000, "TWO": 800})
    live = _days(26, {"TW": 1000, "TWO": 800})
    assert sg.check_dataset("raw_prices", live, base) == []


def test_閘門_最新日單一市場檔數驟降要擋():
    live = pd.concat([_days(25, {"TW": 1000, "TWO": 800}),
                      _days(1, {"TW": 1000, "TWO": 400}, start="2026-10-06")])
    errs = sg.check_dataset("margin", live, None)
    assert any("TWO" in e for e in errs)


def test_閘門_列數變少與日期倒退要擋():
    base = _days(26, {"TW": 1000, "TWO": 800})
    live = _days(20, {"TW": 1000, "TWO": 800})
    errs = sg.check_dataset("inst", live, base)
    assert any("列數" in e for e in errs) and any("倒退" in e for e in errs)


def test_閘門_實價絕對下限():
    live = _days(3, {"TW": 100, "TWO": 100})
    assert any("絕對下限" in e for e in sg.check_dataset("raw_prices", live, None))


# ───────── 法人／融資券解析 ─────────
import selfhost_chips as sc  # noqa: E402


def test_pick_先完整比對再前綴():
    f = ["證券代號", "自營商買賣超股數", "自營商買賣超股數(自行買賣)", "自營商買賣超股數(避險)"]
    assert sc._pick(f, "自營商買賣超股數") == 1            # 取合計欄，不是子欄
    assert sc._pick(["外陸資買賣超股數(不含外資自營商)"], "外資及陸資買賣超", "外陸資買賣超股數") == 0
    assert sc._pick(["x"], "沒有") is None


def test_chips_n_處理逗號與破折號():
    assert sc._n("-1,234") == -1234.0 and sc._n("---") is None and sc._n("") is None


# ───────── 接縫偵測 ─────────
import selfhost_seam_check as ssc  # noqa: E402


def _r(vals, start="2026-07-01"):
    idx = pd.bdate_range(start, periods=len(vals))
    return pd.Series(vals, index=idx)


def test_偵測_持續階梯等於官方因子_為seam():
    # 前 5 天 r=1.0，之後掉到 0.95 並持續到 ex 前
    r = _r([1.0] * 5 + [0.95] * 6)
    ex = r.index[-1] + pd.Timedelta(days=1)
    S, step, st = ssc.detect(r, ex, 0.95)
    assert st == "seam" and S == r.index[5] and abs(step + 0.05) < 1e-9


def test_偵測_單日尖刺不算接縫():
    r = _r([1.0] * 4 + [0.95] + [1.0] * 6)          # 掉下去隔天就回來
    ex = r.index[-1] + pd.Timedelta(days=1)
    assert ssc.detect(r, ex, 0.95)[2] == "none"


def test_偵測_階梯就在ex前一天無法驗證持續_不算接縫也不算修好():
    r = _r([1.0] * 10 + [0.95])                       # 階梯在最後一天，之後沒有觀察日
    ex = r.index[-1] + pd.Timedelta(days=1)
    assert ssc.detect(r, ex, 0.95)[2] == "unverifiable"


def test_偵測_因子與官方不同但同方向_為seam_factor_diff():
    r = _r([1.0] * 5 + [0.90] * 6)                    # 上游階梯 -10%，官方因子 0.8266（-17.3%）：比值 0.58
    ex = r.index[-1] + pd.Timedelta(days=1)
    assert ssc.detect(r, ex, 0.8266)[2] == "seam_factor_diff"


def test_偵測_方向相反不算():
    r = _r([1.0] * 5 + [1.05] * 6)
    ex = r.index[-1] + pd.Timedelta(days=1)
    assert ssc.detect(r, ex, 0.95)[2] == "none"


# ───────── 事件表：build 以舊檔為底、減資輪詢順序 ─────────
def test_build_以既有corp_actions為底_不因缺歷史來源檔而退化(tmp_path, monkeypatch):
    old = pd.DataFrame([_ev("1101", "2020-06-01", "ex_div", 0.95, "twse_ex"),
                        _ev("2330", "2021-06-01", "ex_div", 0.98, "twse_ex")])
    monkeypatch.setattr(se, "SH", tmp_path)
    monkeypatch.setattr(se, "OUT", tmp_path / "corp_actions.parquet")
    monkeypatch.setattr(se, "OFFICIAL", tmp_path / "ev_official.parquet")
    monkeypatch.setattr(se, "OFFICIAL_ACT", tmp_path / "ev_official_actions.parquet")
    monkeypatch.setattr(se, "FM_SPLIT", tmp_path / "ev_fm_split.parquet")
    monkeypatch.setattr(se, "FM_RED", tmp_path / "ev_fm_reduction.parquet")
    monkeypatch.setattr(se, "FM_RED_DONE", tmp_path / "done.json")
    old.to_parquet(se.OUT)
    pd.DataFrame([_ev("1101", "2026-09-01", "ex_div", 0.97, "twse_ex")]).to_parquet(se.OFFICIAL)   # CI 只抓近期
    out = se.build()
    assert len(out) == 3                                     # 舊的 2 件＋新的 1 件，沒有被洗掉
    assert set(out["date"].dt.year) == {2020, 2021, 2026}


def test_減資輪詢_從未查過的先查_其次最久沒查的(monkeypatch, tmp_path):
    monkeypatch.setattr(se, "FM_RED", tmp_path / "r.parquet")
    monkeypatch.setattr(se, "FM_RED_DONE", tmp_path / "d.json")
    se.FM_RED_DONE.write_text('{"1101": "2026-09-01", "2330": "2026-10-01"}')
    asked = []
    monkeypatch.setattr(se, "_fm", lambda ds, **kw: asked.append(kw["data_id"]) or [])
    monkeypatch.setattr(se.time, "sleep", lambda s: None)
    se.fetch_fm_reduction(["2330", "1101", "9999"], max_calls=2)
    assert asked == ["9999", "1101"]                         # 未查過 → 最久沒查


# ───────── 法人／融資：歷年欄名、失敗判定 ─────────
from datetime import date as _date  # noqa: E402


def _fake_get(payload):
    return lambda url, retries=3: payload


def test_T86_2015年16欄_外資買賣超股數也能解析(monkeypatch):
    fields = ["證券代號", "證券名稱", "外資買進股數", "外資賣出股數", "外資買賣超股數", "投信買進股數", "投信賣出股數",
              "投信買賣超股數", "自營商買賣超股數", "自營商買進股數(自行買賣)", "自營商賣出股數(自行買賣)",
              "自營商買賣超股數(自行買賣)", "自營商買進股數(避險)", "自營商賣出股數(避險)", "自營商買賣超股數(避險)", "三大法人買賣超股數"]
    row = ["2330", "台積電", "1", "1", "1,000", "0", "0", "-200", "300", "0", "0", "0", "0", "0", "0", "1,100"]
    monkeypatch.setattr(sc, "_get", _fake_get({"stat": "OK", "date": "20150105", "fields": fields, "data": [row]}))
    df = sc.inst_twse(_date(2015, 1, 5))
    assert df is not None and len(df) == 1
    r = df.iloc[0]
    assert r["foreign_net"] == 1000 and r["trust_net"] == -200 and r["dealer_net"] == 300 and r["total_net"] == 1100
    assert pd.isna(r["fi_prop_net"])                      # 16 欄時代不拆外資自營商


def test_T86_日期不符_丟棄為失敗(monkeypatch):
    monkeypatch.setattr(sc, "_get", _fake_get({"stat": "OK", "date": "20260930", "fields": ["x"], "data": [["1"]]}))
    assert sc.inst_twse(_date(2026, 10, 2)) is None


def test_MI_MARGN_stat_OK但找不到個股表_算失敗不是休市(monkeypatch):
    monkeypatch.setattr(sc, "_get", _fake_get({"stat": "OK", "date": "20261002", "tables": [{"fields": ["a"], "data": [["1"]]}]}))
    assert sc.margin_twse(_date(2026, 10, 2)) is None


def test_MI_MARGN_休市stat非OK_回空表(monkeypatch):
    monkeypatch.setattr(sc, "_get", _fake_get({"stat": "很抱歉，沒有符合條件的資料"}))
    r = sc.margin_twse(_date(2026, 9, 25))
    assert r is not None and r.empty


def test_TPEx法人_欄數不是24_丟棄(monkeypatch):
    monkeypatch.setattr(sc, "_get", _fake_get({"date": "20261002", "tables": [{"fields": ["a"] * 20, "data": [["1101"] + ["0"] * 19]}]}))
    assert sc.inst_tpex(_date(2026, 10, 2)) is None


def test_偵測_階梯在ex前兩日_標unverifiable而非healed():
    r = _r([1.0] * 9 + [0.95, 0.95])                  # 階梯日之後只剩 2 個官方日
    ex = r.index[-1] + pd.Timedelta(days=1)
    assert ssc.detect(r, ex, 0.95)[2] == "unverifiable"


def test_TPEx法人_2018前16欄格式在tables1也能解析(monkeypatch):
    fields16 = ["代號", "名稱", "外資及陸資買股數", "外資及陸資賣股數", "外資及陸資淨買股數", "投信買進股數", "投信賣股數", "投信淨買股數",
                "自營淨買股數", "a", "b", "c", "d", "e", "f", "三大法人買賣超股數"]
    row = ["6201", "元大富櫃50", "0", "0", "1,000", "0", "0", "-200", "40,000", "0", "0", "0", "0", "0", "0", "40,800"]
    monkeypatch.setattr(sc, "_get", _fake_get({"date": "20170601", "tables": [
        {"fields": [], "data": []}, {"fields": fields16, "data": [row]}]}))
    df = sc.inst_tpex(_date(2017, 6, 1))
    r = df.iloc[0]
    assert len(df) == 1 and r["foreign_net"] == 1000 and r["trust_net"] == -200 and r["dealer_net"] == 40000 and r["total_net"] == 40800


def test_TPEx法人_兩種格式都沒資料_回空表不是None(monkeypatch):
    monkeypatch.setattr(sc, "_get", _fake_get({"date": "20260928", "tables": [{"fields": [], "data": []}]}))
    r = sc.inst_tpex(_date(2026, 9, 28))
    assert r is not None and r.empty


def test_build_FM_RED在_done舊_不重複併入(tmp_path, monkeypatch):
    monkeypatch.setattr(se, "SH", tmp_path)
    for k, f in (("OUT", "corp_actions.parquet"), ("OFFICIAL", "ev_official.parquet"), ("OFFICIAL_ACT", "ev_oa.parquet"),
                 ("FM_SPLIT", "ev_fm_split.parquet"),
                 ("FM_RED", "ev_fm_reduction.parquet"), ("FM_RED_DONE", "done.json")):
        monkeypatch.setattr(se, k, tmp_path / f)
    pd.DataFrame([_ev("2607", "2025-10-07", "cap_reduction", 60 / 35, "fm_reduction")]).to_parquet(se.FM_RED)
    se.FM_RED_DONE.write_text("{}")                          # done 沒標記該檔
    out = se.build()
    assert int((out["source"] == "fm_reduction").sum()) == 1


# ───────── 官方減資／面額變更表 ─────────
def test_roc_支援民國7碼緊湊格式():
    assert se._roc("1140113") == pd.Timestamp("2025-01-13")
    assert se._roc("114/02/12") == pd.Timestamp("2025-02-12")


_TWTAUU_FIELDS = ["恢復買賣日期", "股票代號", "名稱", "停止買賣前收盤價格", "恢復買賣參考價", "漲停價格", "跌停價格",
                  "開盤競價基準", "除權參考價", "減資原因", "詳細資料"]


def test_官方減資_純減資用恢復買賣參考價():
    t = {"fields": _TWTAUU_FIELDS, "data": [["114/02/12", "2025", "千興", "10.50", "17.09", "18.75", "15.40", "17.10", "--", "彌補虧損", "x"]]}
    r = se._parse_action_table(t, "twse_red", "cap_reduction", "TW", ("除權參考價", "恢復買賣參考價"))
    assert len(r) == 1 and abs(r[0]["factor"] - 17.09 / 10.5) < 1e-9 and r[0]["date"] == pd.Timestamp("2025-02-12")


def test_官方減資_併現金增資時優先用除權參考價():
    t = {"fields": _TWTAUU_FIELDS, "data": [["107/04/10", "3312", "弘穎", "6.54", "8.48", "9", "7", "8.5", "8.34", "彌補虧損", "x"]]}
    r = se._parse_action_table(t, "twse_red", "cap_reduction", "TW", ("除權參考價", "恢復買賣參考價"))
    assert abs(r[0]["factor"] - 8.34 / 6.54) < 1e-9


def test_官方減資_欄名對不上_整張丟棄不靜默錯位():
    assert se._parse_action_table({"fields": ["a", "b"], "data": [["1", "2"]]}, "twse_red", "cap_reduction", "TW", ("除權參考價",)) == []


def test_官方面額變更_千元級價格含逗號():
    f = ["恢復買賣日期", "股票代號", "名稱", "停止買賣前收盤價格", "恢復買賣參考價", "漲停價格", "跌停價格", "開盤競價基準", "詳細資料"]
    t = {"fields": f, "data": [["115/09/07", "6949", "沛爾生醫-創", "1,490.00", "74.50", "81.90", "67.10", "74.50", "x"]]}
    r = se._parse_action_table(t, "twse_par", "par_change", "TW", ("恢復買賣參考價",))
    assert abs(r[0]["factor"] - 74.5 / 1490) < 1e-9


def test_gate_content_checks_catch_blank_dealer_and_ohlc():
    """列數／檔數都正常、但某市場自營整欄空白或 OHLC 錯位 → 閘門要紅（2026-08-27 事件）。"""
    d = pd.date_range("2026-09-01", periods=5)
    rows = [{"date": x, "ticker": f"T{i}", "market": "TWO", "foreign_net": 100, "trust_net": 10,
             "dealer_net": None, "total_net": 115} for x in d for i in range(10)]
    e, _ = sg.content_checks("inst", pd.DataFrame(rows))
    assert any("自營缺值" in x for x in e)
    rows = [{**r, "dealer_net": 5} for r in rows]
    assert sg.content_checks("inst", pd.DataFrame(rows))[0] == []
    rows[0]["dealer_net"] = 5000
    px = pd.DataFrame([{"date": x, "ticker": "A", "market": "TW", "open": 10, "high": 9, "low": 8, "close": 10}
                       for x in d])   # high < open/close → 全違反
    assert any("OHLC" in x for x in sg.content_checks("raw_prices", px)[0])
    ok = px.assign(high=11)
    assert sg.content_checks("raw_prices", ok)[0] == []
