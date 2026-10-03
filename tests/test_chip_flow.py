"""外資台指期未平倉／三大法人買賣超：解析、讀檔、卡片。"""
from __future__ import annotations

import sys

import pandas as pd

sys.path.insert(0, "scripts")
sys.path.insert(0, "app")
import fetch_foreign_futures as ff  # noqa: E402
import fetch_inst_flow as fi  # noqa: E402

_HDR = ",".join(["日期", "商品名稱", "身份別"] + [f"c{i}" for i in range(3, 15)])


def _row(d, who, lo, sh, prod="臺股期貨"):
    cols = ["0"] * 15
    cols[0], cols[1], cols[2] = d, prod, who
    cols[9], cols[11], cols[13] = str(lo), str(sh), str(lo - sh)
    return ",".join(cols)


def test_parse_csv_只取外資及陸資_臺股期貨():
    t = "\n".join([_HDR, _row("2026/09/29", "自營商", 3465, 3953),
                   _row("2026/09/29", "外資及陸資", 8788, 87817),
                   _row("2026/09/29", "外資及陸資", 10, 20, prod="小型臺指期貨")])
    r = ff.parse_csv(t)
    assert len(r) == 1 and r[0]["short_oi"] == 87817 and r[0]["net_oi"] == -79029
    assert r[0]["date"] == pd.Timestamp("2026-09-29")


def test_parse_csv_錯誤頁或欄位錯位_不收():
    assert ff.parse_csv("<!DOCTYPE HTML><html>錯誤</html>") == []
    bad = _row("2026/09/29", "外資及陸資", 8788, 87817).split(",")
    bad[13] = "123"                                   # 多−空≠淨額
    assert ff.parse_csv("\n".join([_HDR, ",".join(bad)])) == []


def _bfi(foreign=2_621_799_962, fdealer=0, trust=5_768_811_349, d1=4_741_375_500, d2=-2_714_959_070):
    total = foreign + fdealer + trust + d1 + d2
    f = lambda v: f"{v:,}"  # noqa: E731
    return {"stat": "OK", "date": "20261002", "data": [
        ["自營商(自行買賣)", "0", "0", f(d1)], ["自營商(避險)", "0", "0", f(d2)],
        ["投信", "0", "0", f(trust)], ["外資及陸資(不含外資自營商)", "0", "0", f(foreign)],
        ["外資自營商", "0", "0", f(fdealer)], ["合計", "0", "0", f(total)]]}


def test_parse_bfi82u_加總對得上官方合計():
    r = fi.parse(_bfi())
    assert r["foreign"] == 2_621_799_962 and r["trust"] == 5_768_811_349
    assert r["dealer"] == 4_741_375_500 - 2_714_959_070
    assert r["total"] == r["foreign"] + r["trust"] + r["dealer"]


def test_parse_bfi82u_非OK或缺列或加總不符_回None():
    assert fi.parse({"stat": "很抱歉，沒有符合條件的資料!"}) is None
    j = _bfi(); j["data"] = j["data"][:3]
    assert fi.parse(j) is None
    j = _bfi(); j["data"][-1][3] = "1"                # 合計被改 → 對不上
    assert fi.parse(j) is None


def test_reader_沒檔或壞檔_回空表(tmp_path, monkeypatch):
    from reference import chip_flow as cf
    monkeypatch.setattr(cf, "FOREIGN_FUTURES", tmp_path / "x.parquet")
    assert cf.load_foreign_futures().empty
    bad = tmp_path / "bad.parquet"
    bad.write_text("not parquet")
    monkeypatch.setattr(cf, "INST_FLOW", bad)
    assert cf.load_inst_flow().empty


def test_外資空單卡_增減中性色_有前一日():
    import streamlit_app as sa
    df = pd.DataFrame({"date": pd.to_datetime(["2026-10-01", "2026-10-02"]),
                       "long_oi": [12373, 11893], "short_oi": [91927, 92197],
                       "net_oi": [-79554, -80304]})
    h = sa._foreign_short_card(df)
    # 淨空單 80,304 口（前日 79,554）→ 增加 750；空單/多單總量在小字
    assert "80,304 口" in h and "+750 口" in h and "空單 92,197　多單 11,893" in h and "gz-chg flat" in h
    assert "外資淨空單" in h
    one = sa._foreign_short_card(df.iloc[-1:])
    assert "尚無前一日可比" in one
    # 淨空單減少 → 負增減；翻成淨多 → 大字標「淨多」
    down = pd.DataFrame({"date": pd.to_datetime(["2026-10-01", "2026-10-02"]), "long_oi": [100, 400],
                         "short_oi": [300, 100], "net_oi": [-200, 300]})
    h2 = sa._foreign_short_card(down)
    assert "淨多 300 口" in h2 and "淨部位（多−空）+500 口" in h2 and "%" not in h2
    both = pd.DataFrame({"date": pd.to_datetime(["2026-10-01", "2026-10-02"]), "long_oi": [400, 500],
                         "short_oi": [100, 100], "net_oi": [300, 400]})
    assert "淨部位（多−空）+100 口" in sa._foreign_short_card(both)
    nan = down.copy(); nan.loc[1, "short_oi"] = None
    assert "淨多" not in sa._foreign_short_card(nan)        # NaN 列被丟掉，不炸（用前一列）


def test_三大法人卡_合計與三方():
    import streamlit_app as sa
    df = pd.DataFrame({"date": pd.to_datetime(["2026-10-02"]), "foreign": [2.62e9], "trust": [5.77e9],
                       "dealer": [2.03e9], "total": [1.042e10]})
    h = sa._inst_flow_card(df)
    assert "+104.2 億" in h and "外資 +26.2 億" in h and "投信 +57.7 億" in h and "gz-chg up" in h


def test_各卡資料日_一行列齊_缺的不列():
    import streamlit_app as sa
    d = pd.Timestamp
    line = sa._asof_line(
        {"0050": d("2026-10-02"), "006201": d("2026-10-02"),
         "idx:^DJI": d("2026-10-02"), "idx:^N225": d("2026-10-02")},
        pd.Series([1.0], index=[d("2026-10-02")]), pd.Series([1.0], index=[d("2026-10-03")]),
        pd.DataFrame({"date": [d("2026-10-02")]}), pd.DataFrame(), {"asof": "2026-10-02"})
    assert "0050 10-02／006201 10-02" in line and "國際指數 10-02" in line
    assert "日盤 10-02／夜盤 10-03" in line and "台指期" in line and "外資淨空單 10-02" in line and "族群動向 10-02" in line
    assert "三大法人" not in line            # inst 空 → 不列
    assert sa._asof_line({}, pd.Series(dtype=float), pd.Series(dtype=float),
                         pd.DataFrame(), pd.DataFrame(), None) == ""
