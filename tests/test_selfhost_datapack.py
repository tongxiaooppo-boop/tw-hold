"""自建 → data_pack 轉接層（scripts/selfhost_to_datapack.py）：zip 結構、欄位、單位、市場別、股票清單。"""
from __future__ import annotations

import importlib.util
import io
import zipfile
from pathlib import Path

import pandas as pd
import pytest

_spec = importlib.util.spec_from_file_location(
    "dp", Path(__file__).resolve().parents[1] / "scripts" / "selfhost_to_datapack.py")
dp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dp)

D1, D2 = pd.Timestamp("2026-10-01"), pd.Timestamp("2026-10-02")


def _frames():
    adj = pd.DataFrame({
        "ticker": ["2330", "2330", "6488", "6488", "00400A"],
        "date": [D1, D2, D1, D2, D1],
        "open": [100.0, 101.0, 50.0, 51.0, 10.0], "high": [102.0, 103.0, 52.0, 53.0, 11.0],
        "low": [99.0, 100.0, 49.0, 50.0, 9.0], "close": [101.0, 102.0, 51.0, 52.0, 10.5],
        "volume": [1000.0, 2000.0, 300.0, float("nan"), 5.0], "raw_close": [101.0, 102.0, 51.0, 52.0, 10.5]})
    raw = pd.DataFrame({"ticker": ["2330", "2330", "6488", "6488", "00400A"], "market": ["TW", "TW", "TWO", "TWO", "TW"],
                        "date": [D1, D2, D1, D2, D1]})
    inst = pd.DataFrame({"date": [D1, D2, D2], "ticker": ["2330", "2330", "6488"], "market": ["TW", "TW", "TWO"],
                         "foreign_net": [10.0, -5.0, 3.0], "fi_prop_net": [0.0, 0.0, 0.0], "trust_net": [1.0, 2.0, 0.0],
                         "dealer_net": [3.0, 4.0, 1.0], "total_net": [14.0, 1.0, 4.0]})
    margin = pd.DataFrame({"date": [D1, D2], "ticker": ["2330", "2330"], "market": ["TW", "TW"],
                           "margin_balance": [100.0, 110.0], "margin_buy": [20.0, 30.0], "margin_sell": [10.0, 15.0],
                           "margin_redeem": [1.0, 5.0], "short_balance": [5.0, 6.0], "short_buy": [0.0, 1.0],
                           "short_sell": [1.0, 2.0], "short_redeem": [0.0, 0.0], "offset": [0.0, 1.0],
                           "margin_prev": [90.0, 100.0], "short_prev": [4.0, 5.0], "note": ["", "X"]})
    return adj, raw, inst, margin


def _build(tmp_path, **kw):
    adj, raw, inst, margin = _frames()
    sl = pd.DataFrame({"ticker": ["2330.TW", "6488.TWO"], "code": ["2330", "6488"], "name": ["台積電", "環球晶"],
                       "market": ["上市", "上櫃"], "sector": ["半導體業", "半導體業"]})
    out = tmp_path / "x.zip"
    st = dp.build(out, adj, raw, inst, margin, stock_list=sl, **kw)
    return out, st


def test_zip_structure_and_market_suffix(tmp_path):
    out, st = _build(tmp_path)
    names = set(zipfile.ZipFile(out).namelist())
    assert {"data/2330.TW.csv", "data/6488.TWO.csv", "data/institutional/2330_inst.csv", "data/margin/2330_margin.csv",
            "data/stock_list.csv"} <= names
    assert not any("00400A" in n for n in names)                       # 預設只轉 4 碼
    assert st["price_files"] == 2 and st["inst_files"] == 2 and st["margin_files"] == 1


def test_price_csv_columns_and_volume_int(tmp_path):
    out, _ = _build(tmp_path)
    df = pd.read_csv(zipfile.ZipFile(out).open("data/6488.TWO.csv"))
    assert list(df.columns) == ["Date", "Open", "High", "Low", "Close", "Volume"]
    assert df["Volume"].tolist() == [300, 0]                            # NaN 量補 0（與 data_pack 匯入的處理一致）
    assert df["Date"].tolist() == ["2026-10-01", "2026-10-02"]


def test_inst_csv_uses_columns_tw_swing_normalizer_reads(tmp_path):
    out, _ = _build(tmp_path)
    df = pd.read_csv(zipfile.ZipFile(out).open("data/institutional/2330_inst.csv"), encoding="utf-8-sig")
    assert {"date", "外陸資買賣超股數(不含外資自營商)", "fi_prop_net", "it_net", "自營商買賣超股數", "total_net"} <= set(df.columns)
    assert df["外陸資買賣超股數(不含外資自營商)"].tolist() == [10.0, -5.0] and df["it_net"].tolist() == [1.0, 2.0]
    assert df["ticker"].iloc[0] == "2330.TW"


def test_margin_csv_has_import_columns_and_extras(tmp_path):
    out, _ = _build(tmp_path)
    df = pd.read_csv(zipfile.ZipFile(out).open("data/margin/2330_margin.csv"), encoding="utf-8-sig")
    need = {"date", "margin_balance", "margin_buy", "margin_sell", "margin_redeem", "short_balance", "short_buy",
            "short_sell", "short_redeem", "offset"}
    assert need <= set(df.columns) and {"margin_prev", "short_prev", "note"} <= set(df.columns)
    assert df["margin_prev"].tolist() == [90.0, 100.0]


def test_stock_list_market_from_selfhost_and_names_from_source(tmp_path):
    out, st = _build(tmp_path)
    sl = pd.read_csv(zipfile.ZipFile(out).open("data/stock_list.csv"), dtype={"code": str})
    assert list(sl.columns) == ["ticker", "code", "name", "market", "sector"]
    r = sl.set_index("code")
    assert r.loc["2330", "ticker"] == "2330.TW" and r.loc["2330", "market"] == "上市" and r.loc["2330", "name"] == "台積電"
    assert r.loc["6488", "ticker"] == "6488.TWO" and r.loc["6488", "market"] == "上櫃"
    assert st["stock_list_named"] == 2


def test_stock_list_without_source_leaves_blank_but_still_valid(tmp_path):
    adj, raw, inst, margin = _frames()
    out = tmp_path / "y.zip"
    st = dp.build(out, adj, raw, inst, margin)
    sl = pd.read_csv(zipfile.ZipFile(out).open("data/stock_list.csv"), dtype={"code": str}).fillna("")
    assert len(sl) == 2 and (sl["name"] == "").all() and st["stock_list_named"] == 0


def test_universe_fallback_fills_names(tmp_path):
    adj, raw, inst, margin = _frames()
    uni = pd.DataFrame({"ticker": ["2330"], "stock_name": ["台積電"], "industry": ["半導體業"]})
    out = tmp_path / "z.zip"
    dp.build(out, adj, raw, inst, margin, universe=uni)
    sl = pd.read_csv(zipfile.ZipFile(out).open("data/stock_list.csv"), dtype={"code": str}).fillna("").set_index("code")
    assert sl.loc["2330", "name"] == "台積電" and sl.loc["2330", "sector"] == "半導體業"


def test_tickers_and_since_filters(tmp_path):
    out, st = _build(tmp_path, tickers={"2330"}, since="2026-10-02")
    z = zipfile.ZipFile(out)
    assert [n for n in z.namelist() if n.startswith("data/") and n.endswith(".csv") and "/" not in n[5:]] == ["data/2330.TW.csv", "data/stock_list.csv"]
    assert len(pd.read_csv(z.open("data/2330.TW.csv"))) == 1


def test_market_switch_uses_latest_market(tmp_path):
    raw = pd.DataFrame({"ticker": ["4739", "4739"], "market": ["TWO", "TW"], "date": [D1, D2]})      # 轉板：上櫃 → 上市
    assert dp.latest_market(raw)["4739"] == "TW"


def test_no_partial_zip_left_on_failure(tmp_path, monkeypatch):
    adj, raw, inst, margin = _frames()
    out = tmp_path / "w.zip"
    monkeypatch.setattr(dp, "price_csv", lambda g: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        dp.build(out, adj, raw, inst, margin)
    assert not out.exists()                                            # 失敗時不留看起來存在的半截檔（只可能有 .part）
