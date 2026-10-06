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
                       _ev("2607", "2025-10-07", "par_change", 0.1, "fm_par")])
    r = sa.resolve_events(ev)
    assert len(r) == 2 and r["multi_class"].all()      # 除息＋面額變更：兩種都套（減資＋除息才只套減資，見下方測試）


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


# ───────── 2026-10-06 新增：融資恆等式（中位數）、跨市場重複、前日餘額、重抓窗口 ─────────
def _margin_frame(days=20, bad_days=(), bad_frac=0.5, n=40, swap_all=False):
    rows = []
    rng = np.random.default_rng(0)
    bal = {f"{1000 + i}": 1000.0 for i in range(n)}
    for k in range(days):
        d = pd.Timestamp("2026-09-01") + pd.Timedelta(days=k)
        for i, t in enumerate(bal):
            buy, sell, red = float(rng.integers(0, 50)), float(rng.integers(0, 50)), float(rng.integers(0, 10))
            new = bal[t] + buy - sell - red
            if k in bad_days and i < n * bad_frac:
                new += 7                    # 官方隔日調帳：前日餘額與昨日今日餘額不連續
            rows.append({"date": d, "ticker": t, "market": "TW", "margin_balance": new,
                         "margin_buy": sell if swap_all else buy, "margin_sell": buy if swap_all else sell,
                         "margin_redeem": red})
            bal[t] = new
    return pd.DataFrame(rows)


def test_閘門_融資恆等式_單日調帳只警告不擋():
    errs, warns = sg.content_checks("margin", _margin_frame(bad_days=(10,)))
    assert not errs and any("隔日調帳" in w for w in warns)


def test_閘門_融資恆等式_欄位對調要擋():
    errs, _ = sg.content_checks("margin", _margin_frame(swap_all=True))
    assert any("融資餘額恆等式" in e for e in errs)


def test_閘門_融資恆等式_正常資料不報():
    assert sg.content_checks("margin", _margin_frame()) == ([], [])


def test_merge_跨市場同日重複_留當日實價所在市場(tmp_path, monkeypatch):
    import selfhost_merge as sm
    px = pd.DataFrame({"date": [_ts("2017-09-07")], "ticker": ["4739"], "market": ["TWO"]})
    px.to_parquet(tmp_path / "raw_prices.parquet")
    monkeypatch.setattr(sm, "SH", tmp_path)
    df = pd.DataFrame({"date": [_ts("2017-09-07")] * 2 + [_ts("2017-09-08")], "ticker": ["4739", "4739", "4739"],
                       "market": ["TW", "TWO", "TW"], "margin_balance": [1.0, 1.0, 2.0]})
    out = sm._drop_cross_market_dups(df)
    assert len(out) == 2 and set(out["market"][out["date"] == _ts("2017-09-07")]) == {"TWO"}


def test_merge_跨市場重複_兩邊都沒實價_不動(tmp_path, monkeypatch):
    import selfhost_merge as sm
    pd.DataFrame({"date": [_ts("2020-01-02")], "ticker": ["9999"], "market": ["TW"]}).to_parquet(tmp_path / "raw_prices.parquet")
    monkeypatch.setattr(sm, "SH", tmp_path)
    df = pd.DataFrame({"date": [_ts("2017-09-07")] * 2, "ticker": ["4739"] * 2, "market": ["TW", "TWO"], "margin_balance": [1.0, 1.0]})
    assert len(sm._drop_cross_market_dups(df)) == 2


def test_融資券解析_含前日餘額(monkeypatch):
    j = {"stat": "OK", "date": "20260930", "tables": [{"fields": [str(i) for i in range(16)], "data": [
        ["2330", "台積電", "1073", "498", "13", "30134", "30696", "x", "1", "4", "0", "15", "18", "x", "1", "x"]]}]}
    monkeypatch.setattr(sc, "_get", lambda *a, **k: j)
    df = sc.margin_twse(_date(2026, 9, 30))
    r = df.iloc[0]
    assert r["margin_prev"] == 30134 and r["margin_balance"] == 30696 and r["short_prev"] == 15 and r["short_balance"] == 18
    assert r["margin_prev"] + r["margin_buy"] - r["margin_sell"] - r["margin_redeem"] == r["margin_balance"]


def test_同日減資加除權息_只套減資不重複扣息():
    ev = pd.DataFrame([
        {"ticker": "9999", "date": _ts("2024-05-01"), "type": "ex_div", "factor": 0.97, "source": "twse_ex"},
        {"ticker": "9999", "date": _ts("2024-05-01"), "type": "cap_reduction", "factor": 1.5, "source": "twse_red"},
        {"ticker": "8888", "date": _ts("2024-05-01"), "type": "ex_div", "factor": 0.98, "source": "twse_ex"},
        {"ticker": "9999", "date": _ts("2024-06-03"), "type": "ex_div", "factor": 0.95, "source": "twse_ex"},
    ])
    res = sa.resolve_events(ev)
    r = res[(res.ticker == "9999") & (res.date == _ts("2024-05-01"))]
    assert list(r["cls"]) == ["red"]                                   # 同日只留減資
    assert len(res[(res.ticker == "8888")]) == 1                       # 其他檔不受影響
    assert len(res[(res.ticker == "9999") & (res.date == _ts("2024-06-03"))]) == 1   # 不同日的除息照常


# ───────── 2026-10-06 新增：無成交旁表、註記原文、停止買賣快照 ─────────
def test_rows_無成交列不進實價_改記旁表且保留零股量():
    rp.NOTRADE.clear()
    t = {"fields": ["證券代號", "開盤價", "最高價", "最低價", "收盤價", "成交股數", "成交金額"],
         "data": [["2330", "100", "101", "99", "100", "1,000", "100,000"],
                  ["6904", "--", "--", "--", "--", "2,000", "21,000"],       # 有量無價（零股成交）
                  ["9999", "--", "--", "--", "--", "0", "0"]]}
    df = rp._rows(t, {"open": "開盤價", "high": "最高價", "low": "最低價", "close": "收盤價",
                      "volume": "成交股數", "value": "成交金額"}, "TW", "20260903")
    assert list(df["ticker"]) == ["2330"]
    nt = {r["ticker"]: r for r in rp.NOTRADE}
    assert set(nt) == {"6904", "9999"} and nt["6904"]["volume"] == 2000.0 and nt["9999"]["volume"] == 0.0
    rp.NOTRADE.clear()


def test_註記_保留原文內部空白_只去全形空白與頭尾():
    assert sc._note("OX ") == "OX"
    assert sc._note("　") == ""
    assert sc._note("11    BC") == "11    BC"        # 上櫃註記是定位字串，內部空白不能動


import selfhost_stophalt as sh  # noqa: E402


def _stop_json(title="115年10月06日 停止買賣"):
    return {"stat": "ok", "tables": [{"title": title, "fields": sh.FIELDS,
                                       "data": [["1589", "永冠-KY", "第50-3條", "1.未申報\r\n2.併案", "115年04月07日"]]}]}


def test_停止買賣_解析並把民國日期轉西元():
    df, note = sh.parse(_stop_json(), "2026-10-06")
    assert df is not None and df.iloc[0]["ticker"] == "1589" and df.iloc[0]["halt_since"] == "2026-04-07"
    assert "\n" not in df.iloc[0]["reason"] and "\r" not in df.iloc[0]["reason"]


def test_停止買賣_快照日對不上就拒收():
    df, why = sh.parse(_stop_json("115年10月05日 停止買賣"), "2026-10-06")
    assert df is None and "不是今天" in why


def test_停止買賣_欄位改版拒收():
    j = _stop_json()
    j["tables"][0]["fields"] = ["證券代號", "證券名稱"]
    assert sh.parse(j, "2026-10-06")[0] is None


def test_停止買賣_累積檔只增不減(tmp_path):
    p = tmp_path / "stophalt.parquet"
    a, _ = sh.parse(_stop_json(), "2026-10-06")
    n1 = sh.merge_into(a, p)
    b, _ = sh.parse(_stop_json("115年10月07日 停止買賣"), "2026-10-07")
    n2 = sh.merge_into(b, p)
    assert (n1, n2) == (1, 2)
    assert sh.merge_into(a, p) == 2                       # 重跑冪等，不重複


def test_未來事件不套用_最新價等於未還原價():
    res = pd.DataFrame([
        {"ticker": "2614", "date": _ts("2026-10-06"), "cls": "div", "type": "ex_both", "factor": 0.8445, "source": "twse_ex"},
        {"ticker": "2614", "date": _ts("2026-07-01"), "cls": "div", "type": "ex_div", "factor": 0.95, "source": "twse_ex"}])
    ok, fut = sa.drop_future(res, _ts("2026-10-05"))
    assert list(ok["date"]) == [_ts("2026-07-01")] and list(fut["date"]) == [_ts("2026-10-06")]
    raw = pd.DataFrame({"ticker": "2614", "date": [_ts("2026-06-30"), _ts("2026-10-05")],
                        "open": 1.0, "high": 1.0, "low": 1.0, "close": [20.0, 19.1], "volume": 1.0})
    adj = sa.adjust(raw, ok)
    assert adj["close"].iloc[-1] == 19.1                       # 最新價不動
    assert abs(adj["close"].iloc[0] - 19.0) < 1e-9             # 7/1 除息只乘在 7/1 之前


# ───────── 2026-10-06 補測：重抓窗口、休市複本守門、週六日曆（agent 審查指出「有實作沒測試」）─────────
def _fake_chips(monkeypatch, tmp_path, dataset, cal, mk_rows):
    """把 selfhost_chips.run 接到 tmp_path：假抓取器、假日曆。回傳 calls（被問過的 (市場, 日期)）。"""
    calls = []
    cols = sc.INST_COLS if dataset == "inst" else sc.MARGIN_COLS

    def mk(m):
        def f(d):
            calls.append((m, d))
            return pd.DataFrame(mk_rows(m, d), columns=cols)
        return f

    monkeypatch.setattr(sc, "SH", tmp_path)
    monkeypatch.setattr(sc, "SLEEP", 0)
    monkeypatch.setattr(sc, "_trading_calendar", lambda markets=("TW", "TWO"): cal)
    monkeypatch.setitem(sc.SOURCES, dataset, (tmp_path / f"{dataset}.parquet", cols, {"TW": mk("TW"), "TWO": mk("TWO")}))
    return calls


def _inst_row(m, d, trust=1.0):
    return [{"date": pd.Timestamp(d), "ticker": "2330" if m == "TW" else "6488", "market": m, "foreign_net": 0.0,
             "fi_prop_net": 0.0, "trust_net": trust, "dealer_net": 0.0, "total_net": trust}]


def test_chips_最近幾天每次重抓覆蓋_更早的不重抓(monkeypatch, tmp_path):
    d_old, d_new = _date(2026, 9, 1), _date(2026, 10, 5)
    cal = {d_old, d_new}
    calls = _fake_chips(monkeypatch, tmp_path, "inst", cal, lambda m, d: _inst_row(m, d, trust=2.0))
    seed = pd.concat([pd.DataFrame(_inst_row(m, d, trust=1.0), columns=sc.INST_COLS) for m in ("TW", "TWO") for d in (d_old, d_new)])
    seed.to_parquet(tmp_path / "inst.parquet")
    sc.run("inst", d_old, d_new, ("TW", "TWO"))
    asked = {d for _, d in calls}
    assert d_new in asked and d_old not in asked                       # 近 3 天重抓、更早的已有就不問
    out = pd.read_parquet(tmp_path / "inst.parquet")
    assert out[pd.to_datetime(out["date"]) == "2026-10-05"]["trust_net"].eq(2.0).all()     # 被覆蓋成最新值
    assert out[pd.to_datetime(out["date"]) == "2026-09-01"]["trust_net"].eq(1.0).all()      # 舊的原封不動


def test_chips_休市複本守門_兩市場實價都沒有的日子丟棄並記休市(monkeypatch, tmp_path):
    fri, mon = _date(2026, 10, 2), _date(2026, 10, 5)
    cal = {mon}                                         # 10-02 兩市場都沒有實價（等同颱風假）；日曆最大日 10-05 之後
    calls = _fake_chips(monkeypatch, tmp_path, "margin", cal,
                        lambda m, d: [{"date": pd.Timestamp(d), "ticker": "6488", "market": m, "margin_balance": 1.0}])
    sc.run("margin", fri, fri, ("TW", "TWO"))
    assert calls                                        # 有去問
    assert not (tmp_path / "margin.parquet").exists() or len(pd.read_parquet(tmp_path / "margin.parquet")) == 0   # 但複本沒寫
    closed = pd.read_csv(tmp_path / "margin_closed.csv")
    assert set(closed["market"]) == {"TW", "TWO"} and set(closed["date"]) == {"2026-10-02"}


def test_chips_週六只在實價日曆有該日時才問(monkeypatch, tmp_path):
    sat = _date(2026, 9, 12)
    calls = _fake_chips(monkeypatch, tmp_path, "inst", {sat}, lambda m, d: _inst_row(m, d))
    sc.run("inst", sat, sat, ("TW", "TWO"))
    assert {d for _, d in calls} == {sat}               # 補班週六（日曆有）→ 問
    calls.clear()
    monkeypatch.setattr(sc, "_trading_calendar", lambda markets=("TW", "TWO"): {_date(2026, 9, 11)})
    sc.run("inst", sat, sat, ("TW", "TWO"))
    assert calls == []                                  # 一般週六（日曆沒有）→ 不問


def _fake_raw(monkeypatch, tmp_path, volume):
    calls = []

    def fake(d, market="both"):
        calls.append(d)
        return pd.DataFrame([{"ticker": "2330", "market": "TW", "date": pd.Timestamp(d), "open": 1.0, "high": 1.0,
                              "low": 1.0, "close": 1.0, "volume": volume, "value": 1.0}], columns=rp.COLS)

    monkeypatch.setattr(rp, "OUT", tmp_path / "raw_prices.parquet")
    monkeypatch.setattr(rp, "collect_day", fake)
    return calls


def test_實價_最近幾天重抓覆蓋(monkeypatch, tmp_path):
    calls = _fake_raw(monkeypatch, tmp_path, volume=2.0)
    pd.DataFrame([{"ticker": "2330", "market": "TW", "date": pd.Timestamp("2026-10-05"), "open": 1.0, "high": 1.0,
                   "low": 1.0, "close": 1.0, "volume": 1.0, "value": 1.0}], columns=rp.COLS).to_parquet(tmp_path / "raw_prices.parquet")
    rp.main(["--start", "2026-10-05", "--end", "2026-10-05"])
    assert calls == [_date(2026, 10, 5)]
    out = pd.read_parquet(tmp_path / "raw_prices.parquet")
    assert len(out) == 1 and out["volume"].iloc[0] == 2.0


def test_實價_週六要問_週日不問(monkeypatch, tmp_path):
    calls = _fake_raw(monkeypatch, tmp_path, volume=1.0)
    rp.main(["--start", "2026-09-12", "--end", "2026-09-13"])          # 週六、週日
    assert calls == [_date(2026, 9, 12)]                                # 補行上班的週六股市照常交易，不能用 weekday<5


# ───────── 事件簿與月檢查 ─────────
import selfhost_ledger as sl  # noqa: E402
import selfhost_monthly_review as smr  # noqa: E402


def _raw_series(t, closes, start="2026-01-05"):
    d = pd.bdate_range(start, periods=len(closes))
    return pd.DataFrame({"ticker": t, "date": d, "close": closes})


def test_事件簿_無事件的大跳動標flag_有事件的歸因():
    closes = [10.0] * 10 + [14.0] + [14.0] * 5          # 第 11 天 +40%
    raw = pd.concat([_raw_series("1111", closes), _raw_series("2222", closes)], ignore_index=True)
    day = pd.bdate_range("2026-01-05", periods=16)[10]
    ca = pd.DataFrame([{"ticker": "2222", "date": day, "type": "cap_reduction", "prev_close": 10.0, "ref_price": 14.0,
                        "factor": 1.4, "source": "twse_red", "detail": "{}"}])
    led = sl.build(raw, ca, None, None, None, None, None)
    j = led[led["kind"] == "jump"].set_index("ticker")
    assert j.loc["1111", "level"] == "flag" and j.loc["2222", "level"] == "info"


def test_事件簿_新上市前幾日跳動不算flag_ETF不查():
    raw = pd.concat([_raw_series("3333", [10.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0]),
                     _raw_series("0050", [10.0, 20.0] + [20.0] * 10)], ignore_index=True)
    led = sl.build(raw, pd.DataFrame(columns=["ticker", "date", "type", "prev_close", "ref_price", "factor", "source", "detail"]),
                   None, None, None, None, None)
    assert (led[led["kind"] == "jump"]["level"] == "flag").sum() == 0


def test_事件簿_減資換發停牌的缺日歸因為info():
    d = pd.bdate_range("2026-01-05", periods=30)
    keep = list(range(0, 10)) + list(range(18, 30))       # 缺第 10~17 天（8 天）
    raw = pd.concat([pd.DataFrame({"ticker": "4444", "date": d[keep], "close": 10.0}),
                     pd.DataFrame({"ticker": "5555", "date": d, "close": 10.0})], ignore_index=True)   # 5555 提供完整交易日曆
    ca = pd.DataFrame([{"ticker": "4444", "date": d[18], "type": "cap_reduction", "prev_close": 10.0, "ref_price": 10.0,
                        "factor": 1.0, "source": "twse_red", "detail": "{}"}])
    led = sl.build(raw, ca, None, None, None, None, None)
    g = led[(led["kind"] == "gap") & (led["ticker"] == "4444")]
    assert len(g) == 1 and g["level"].iloc[0] == "info" and "換發" in g["title"].iloc[0]


def test_月檢查_事件對帳_官方有我們沒有_與反向():
    off = pd.DataFrame([{"ticker": "1101", "date": "2026-09-10", "type": "ex_div", "source": "twse_ex"},
                        {"ticker": "2330", "date": "2026-09-11", "type": "cap_reduction", "source": "twse_red"}])
    ours = pd.DataFrame([{"ticker": "1101", "date": "2026-09-10", "type": "ex_both", "source": "x"},     # 詞彙不同但同類別 → 對上
                         {"ticker": "9999", "date": "2026-09-12", "type": "par_change", "source": "fm_par"}])
    miss, extra = smr.diff_events(off, ours)
    assert list(miss["ticker"]) == ["2330"] and list(extra["ticker"]) == ["9999"]


def test_月檢查_前一個月():
    assert smr.prev_month(_date(2026, 10, 6)) == "2026-09" and smr.prev_month(_date(2026, 1, 3)) == "2025-12"


def test_漲跌欄_上市X與上櫃除息記進旁表_一般漲跌記chg():
    rp.REFMARK.clear()
    t = {"fields": ["證券代號", "開盤價", "最高價", "最低價", "收盤價", "成交股數", "成交金額", "漲跌(+/-)", "漲跌價差"],
         "data": [["1418", "4.03", "4.03", "4.03", "4.03", "5,001", "20,154", "<p>X</p>", "0.00"],
                  ["2330", "2375", "2395", "2290", "2290", "1,000", "100", "<p style= color:green>-</p>", "180.00"],
                  ["1101", "30", "31", "30", "31", "1,000", "100", "<p style= color:red>+</p>", "1.00"]]}
    df = rp._rows(t, {"open": "開盤價", "high": "最高價", "low": "最低價", "close": "收盤價", "volume": "成交股數", "value": "成交金額",
                      "sign": "漲跌(+/-)", "diff": "漲跌價差"}, "TW", "20260717").set_index("ticker")
    assert [(r["ticker"], r["mark"]) for r in rp.REFMARK] == [("1418", "X")]
    assert pd.isna(df.loc["1418", "chg"]) and df.loc["2330", "chg"] == -180.0 and df.loc["1101", "chg"] == 1.0
    rp.REFMARK.clear()
    t2 = {"fields": ["代號", "收盤", "漲跌", "開盤", "最高", "最低", "成交股數", "成交金額(元)"],
          "data": [["8358", "398.50", "除息 ", "415.5", "420", "395", "8,273,189", "3,363,820,272"],
                   ["1240", "54.70", "-0.80 ", "55.5", "55.5", "54.7", "17,079", "938,806"]]}
    d2 = rp._rows(t2, {"open": "開盤", "high": "最高", "low": "最低", "close": "收盤", "volume": "成交股數", "value": "成交金額(元)",
                       "sign": "漲跌"}, "TWO", "20260717").set_index("ticker")
    assert [(r["ticker"], r["mark"]) for r in rp.REFMARK] == [("8358", "除息")] and d2.loc["1240", "chg"] == -0.8
    rp.REFMARK.clear()


def test_事件簿_官方標記日無事件_標flag_轉板首日例外():
    d = pd.bdate_range("2026-01-05", periods=10)
    raw = pd.concat([pd.DataFrame({"ticker": "6001", "market": "TW", "date": d, "close": 10.0, "chg": 0.0}),
                     pd.DataFrame({"ticker": "6002", "market": ["TWO"] * 5 + ["TW"] * 5, "date": d, "close": 10.0, "chg": 0.0})], ignore_index=True)
    rmk = pd.DataFrame([{"ticker": "6001", "market": "TW", "date": d[4], "mark": "X", "chg": None, "src": "official"},
                        {"ticker": "6002", "market": "TW", "date": d[5], "mark": "X", "chg": None, "src": "official"}])
    led = sl.build(raw, pd.DataFrame(columns=["ticker", "date", "type", "prev_close", "ref_price", "factor", "source", "detail"]),
                   None, None, None, None, None, None, rmk)
    assert list(led[led["kind"] == "refmark_no_event"]["ticker"]) == ["6001"]
    assert list(led[led["kind"] == "refmark"]["ticker"]) == ["6002"]


def test_事件簿_官方參考價下漲跌幅合法_不標flag():
    d = pd.bdate_range("2026-01-05", periods=8)
    close = [10.0, 10.0, 10.0, 10.0, 12.5, 12.5, 12.5, 12.5]            # 缺日後 +25%，但官方漲跌價差 0.5（參考價 12.0）
    raw = pd.concat([pd.DataFrame({"ticker": "7001", "market": "TW", "date": d[[0, 1, 2, 3, 6, 7]], "close": [10.0] * 4 + [12.5] * 2,
                                   "chg": [0.0, 0.0, 0.0, 0.0, 0.5, 0.0]}),
                     pd.DataFrame({"ticker": "7002", "market": "TW", "date": d, "close": 10.0, "chg": 0.0})], ignore_index=True)
    led = sl.build(raw, pd.DataFrame(columns=["ticker", "date", "type", "prev_close", "ref_price", "factor", "source", "detail"]),
                   None, None, None, None, None)
    j = led[(led["ticker"] == "7001") & (led["kind"] == "jump")]
    assert len(j) == 1 and j["level"].iloc[0] == "info" and "官方" in j["title"].iloc[0]


def test_enrich_事件名稱用官方原詞_並展開官方基準價欄位():
    ev = pd.DataFrame([
        {"ticker": "2614", "market": "TW", "date": _ts("2026-10-06"), "type": "ex_both", "prev_close": 19.1, "ref_price": 16.13,
         "factor": 0.8445, "source": "twse_ex",
         "detail": '{"value": "2.96", "open_base": 17.3, "div_ref": 17.31, "limit_up": 19.0, "limit_down": 14.55}'},
        {"ticker": "3536", "market": "TW", "date": _ts("2015-03-20"), "type": "cap_reduction", "prev_close": 6.58, "ref_price": 13.06,
         "factor": 1.98, "source": "twse_red", "detail": '{"reason": "彌補虧損", "open_base": 13.35, "limit_up": 14.25, "limit_down": 12.15}'},
        {"ticker": "1109", "market": "TW", "date": _ts("2015-10-30"), "type": "cap_reduction", "prev_close": 10.45, "ref_price": 10.5,
         "factor": 1.0048, "source": "fm_reduction",
         "detail": '{"ReasonforCapitalReduction": "Cash refund", "OpeningReferencePrice": 10.5, "LimitUp": 11.55, "LimitDown": 9.45, "ExrightReferencePrice": -1.0}'}])
    out = se.enrich(ev).set_index("ticker")
    assert out.loc["2614", "event"] == "除權息" and out.loc["2614", "open_base"] == 17.3 and out.loc["2614", "div_ref"] == 17.31
    assert out.loc["3536", "event"] == "減資" and out.loc["3536", "reason"] == "彌補虧損" and out.loc["3536", "limit_up"] == 14.25
    assert out.loc["1109", "reason"] == "Cash refund" and out.loc["1109", "open_base"] == 10.5 and out.loc["1109", "limit_down"] == 9.45


# ───────── 停牌缺口閘門／官方 notes 保存（2026-10-06）─────────
def _gap_raw(rows):
    return pd.DataFrame(rows, columns=["ticker", "date", "close"]).assign(date=lambda d: pd.to_datetime(d["date"]))


def _gap_ev(ticker, date, prev_close, cls="red"):
    return pd.DataFrame([{"ticker": ticker, "date": pd.Timestamp(date), "cls": cls, "type": "cap_reduction",
                          "factor": 2.0, "source": "twse_red", "prev_close": prev_close}])


def test_gap_gate_rejects_fake_event_without_halt_and_price_mismatch():
    # 事件日 01-09 前一交易日 01-08 就有實價（沒停牌），且收盤 10 vs 官方停止買賣前收盤 20 → 假事件（日期打錯）
    raw = _gap_raw([("1111", "2026-01-07", 10), ("1111", "2026-01-08", 10), ("1111", "2026-01-09", 10),
                    ("2222", "2026-01-07", 5), ("2222", "2026-01-08", 5), ("2222", "2026-01-09", 5)])
    ok, bad, warn = sa.stop_gap_gate(_gap_ev("1111", "2026-01-09", 20.0), raw)
    assert len(ok) == 0 and len(bad) == 1 and len(warn) == 0


def test_gap_gate_keeps_real_halt_event():
    # 停牌 3 個交易日（01-08、01-09 其他檔有交易、1111 沒有），收盤接得上官方前收 → 放行
    raw = _gap_raw([("1111", "2026-01-06", 20), ("2222", "2026-01-07", 5), ("2222", "2026-01-08", 5),
                    ("2222", "2026-01-09", 5), ("1111", "2026-01-12", 10), ("2222", "2026-01-12", 5)])
    ok, bad, warn = sa.stop_gap_gate(_gap_ev("1111", "2026-01-12", 20.0), raw)
    assert len(ok) == 1 and len(bad) == 0 and len(warn) == 0


def test_gap_gate_only_price_mismatch_warns_not_rejects():
    raw = _gap_raw([("1111", "2026-01-06", 18), ("2222", "2026-01-07", 5), ("2222", "2026-01-08", 5),
                    ("1111", "2026-01-12", 10), ("2222", "2026-01-12", 5)])
    ok, bad, warn = sa.stop_gap_gate(_gap_ev("1111", "2026-01-12", 20.0), raw)
    assert len(ok) == 1 and len(bad) == 0 and len(warn) == 1


def test_gap_gate_skips_events_without_prior_price_and_non_halt_classes():
    raw = _gap_raw([("1111", "2026-01-12", 10)])
    ok, bad, warn = sa.stop_gap_gate(_gap_ev("1111", "2026-01-12", 20.0), raw)
    assert len(ok) == 1 and len(bad) == 0                    # 事件日前沒有實價 → 無從驗證，放行
    raw2 = _gap_raw([("1111", "2026-01-08", 10), ("1111", "2026-01-09", 10)])
    ok, bad, _ = sa.stop_gap_gate(_gap_ev("1111", "2026-01-09", 99.0, cls="div"), raw2)
    assert len(ok) == 1 and len(bad) == 0                    # 除權息不是停止買賣型，不查


def test_resolve_events_carries_prev_close():
    ev = pd.DataFrame([{"ticker": "1111", "market": "TW", "date": pd.Timestamp("2026-01-12"), "type": "cap_reduction",
                        "prev_close": 20.0, "ref_price": 10.0, "factor": 0.5, "source": "twse_red"}])
    assert sa.resolve_events(ev)["prev_close"].iloc[0] == 20.0


def test_meta_row_keeps_notes_hints_and_total_for_twse_and_tpex():
    twse = {"stat": "OK", "title": "減資恢復買賣參考價格", "notes": ["a", "除息併案…"], "hints": "h", "total": 2,
            "params": {"startDate": "20250101"}, "fields": ["x"], "data": [[1], [2]]}
    r = se._meta_row("twse_red", "20250101", "20251231", twse)
    assert r["n_rows"] == 2 and r["top"]["notes"] == ["a", "除息併案…"] and r["top"]["hints"] == "h" and "data" not in r["top"]
    tpex = {"stat": "ok", "tables": [{"title": "t", "notes": ["n"], "totalCount": 1, "fields": ["x"], "data": [[1]]}]}
    r2 = se._meta_row("tpex_red", "a", "b", tpex)
    assert r2["n_rows"] == 1 and r2["table"]["notes"] == ["n"] and r2["table"]["totalCount"] == 1


def test_record_meta_appends_and_never_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(se, "SH", tmp_path)
    monkeypatch.setattr(se, "META", tmp_path / "m.jsonl")
    se._record_meta("twse_ex", "a", "b", {"stat": "OK", "notes": ["n1"], "data": []})
    se._record_meta("twse_ex", "a", "b", {"stat": "OK", "notes": ["n2"], "data": []})
    lines = (tmp_path / "m.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2 and '"n2"' in lines[1]            # 只增不減（同請求兩次各記一列，因為 notes 會變）
    monkeypatch.setattr(se, "META", tmp_path / "no" / "dir" / "m.jsonl")
    monkeypatch.setattr(se, "SH", tmp_path / "no" / "dir")
    monkeypatch.setattr(se.Path, "mkdir", lambda *a, **k: (_ for _ in ()).throw(OSError("x")))
    se._record_meta("twse_ex", "a", "b", {})                 # 存檔失敗只警告、不丟例外
