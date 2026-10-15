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


# ── 無成交日沿用前一個還原收盤（2026-10-13）──
D3, D4 = pd.Timestamp("2026-10-05"), pd.Timestamp("2026-10-06")


def _nt(rows):
    return pd.DataFrame(rows, columns=["ticker", "market", "date", "volume", "value", "src"])


def test_fill_no_trade_carries_previous_adjusted_close_and_odd_lot_volume():
    adj, _, _, _ = _frames()
    nt = _nt([("2330", "TW", D3, 608.0, 0.0, "official")])
    out, n = dp.fill_no_trade(adj, nt)
    assert n == 1
    r = out[(out["ticker"] == "2330") & (out["date"] == D3)].iloc[0]
    assert (r["open"], r["high"], r["low"], r["close"]) == (102.0, 102.0, 102.0, 102.0)     # 前一筆（D2）收盤
    assert r["volume"] == 608.0


def test_fill_no_trade_skips_days_that_already_have_a_price_and_tickers_without_history():
    adj, _, _, _ = _frames()
    nt = _nt([("2330", "TW", D2, 5.0, 0.0, "official"),          # 那天已有實價 → 不重複補
              ("9999", "TWO", D3, 0.0, 0.0, "official")])        # 之前沒有任何實價 → 不補
    out, n = dp.fill_no_trade(adj, nt)
    assert n == 0 and len(out) == len(adj)


def test_fill_no_trade_chains_over_consecutive_days_and_ignores_missing_table():
    adj, _, _, _ = _frames()
    nt = _nt([("2330", "TW", D3, 0.0, 0.0, "official"), ("2330", "TW", D4, 0.0, 0.0, "official")])
    out, n = dp.fill_no_trade(adj, nt)
    assert n == 2
    assert out[(out["ticker"] == "2330") & (out["date"] == D4)]["close"].iloc[0] == 102.0     # 連續無成交：仍是最後一筆實價
    assert dp.fill_no_trade(adj, None) == (adj, 0)
    assert dp.fill_no_trade(adj, _nt([]))[1] == 0


def test_fill_no_trade_after_event_uses_adjusted_level_not_raw():
    # 減資恢復買賣：前一筆還原收盤已是參考價水位（12.1 × 1.2884 ≈ 15.59），沿用它就不會出現假跳空
    adj = pd.DataFrame({"ticker": ["3085"], "date": [D1], "open": [15.59], "high": [15.59], "low": [15.59],
                        "close": [15.59], "volume": [100.0], "raw_close": [12.1]})
    out, n = dp.fill_no_trade(adj, _nt([("3085", "TWO", D4, 1855.0, 27917.0, "official")]))
    assert n == 1 and out.iloc[-1]["close"] == 15.59            # zip 不輸出 raw_close，只看還原水位


def test_build_writes_filled_rows_into_csv_and_reports_count(tmp_path):
    nt = _nt([("6488", "TWO", D3, 1200.0, 0.0, "official")])
    out, st = _build(tmp_path, notrade=nt)
    df = pd.read_csv(zipfile.ZipFile(out).open("data/6488.TWO.csv"))
    assert st["no_trade_filled"] == 1
    assert df["Date"].tolist()[-1] == "2026-10-05" and df["Close"].iloc[-1] == 52.0 and df["Volume"].iloc[-1] == 1200
    (tmp_path / "b").mkdir()
    _, st0 = _build(tmp_path / "b")
    assert st0["no_trade_filled"] == 0                                                          # 不給旁表＝跟舊行為一樣


def test_fill_no_trade_tolerates_mixed_datetime_precision():
    # merge_asof 兩邊 ns／us 精度不同會直接 MergeError（pandas 3）；兩種輸入都要能補
    adj, _, _, _ = _frames()
    adj["date"] = adj["date"].astype("datetime64[ns]")
    nt = _nt([("2330", "TW", D3, 10.0, 0.0, "official")])
    nt["date"] = nt["date"].astype("datetime64[us]")
    out, n = dp.fill_no_trade(adj, nt)
    assert n == 1 and out[(out["ticker"] == "2330") & (out["date"] == D3)]["close"].iloc[0] == 102.0
    nt["date"] = nt["date"].astype("datetime64[ns]")
    adj["date"] = adj["date"].astype("datetime64[us]")
    assert dp.fill_no_trade(adj, nt)[1] == 1


def test_stock_list_carry_universe拿不到時沿用上一包的名稱與產業別():
    import pandas as pd
    from selfhost_to_datapack import stock_list_frame
    codes = {"2330": "TW", "6488": "TWO", "9999": "TW"}
    carry = pd.DataFrame({"code": ["2330", "6488"], "name": ["台積電", "環球晶"], "sector": ["半導體業", "半導體業"]})
    out = dp.stock_list_frame(codes, None, None, carry).set_index("code")
    assert out.loc["2330", "sector"] == "半導體業" and out.loc["6488", "name"] == "環球晶"
    assert out.loc["9999", "sector"] == ""                      # 新股沒有任何來源 → 空，由閘門的覆蓋率把關


def test_stock_list_universe優先於carry_且名稱產業別各自獨立補():
    import pandas as pd
    from selfhost_to_datapack import stock_list_frame
    uni = pd.DataFrame({"ticker": ["2330.TW"], "stock_name": ["台積電"], "industry": [""]})   # 產業別空
    carry = pd.DataFrame({"code": ["2330"], "name": ["舊名"], "sector": ["半導體業"]})
    out = dp.stock_list_frame({"2330": "TW"}, None, uni, carry).iloc[0]
    assert out["name"] == "台積電" and out["sector"] == "半導體業"


def test_stock_list_只有carry時產業別數量不變():
    import pandas as pd
    codes = {f"{1000 + i}": "TW" for i in range(50)}
    carry = pd.DataFrame({"code": list(codes), "name": ["n"] * 50, "sector": ["電子"] * 50})
    out = dp.stock_list_frame(codes, None, None, carry)
    assert (out["sector"] != "").sum() == 50 and (out["name"] != "").sum() == 50


def test_新上市個股沒有產業別_補未分類_ETF_DR_已下市不補():
    import pandas as pd
    sl = pd.DataFrame({
        "ticker": ["7856.TWO", "0050.TW", "9105.TW", "1234.TW", "2330.TW"],
        "code": ["7856", "0050", "9105", "1234", "2330"],
        "name": ["", "", "", "", "台積電"], "market": ["上櫃", "上市", "上市", "上市", "上市"],
        "sector": ["", "", "", "", "半導體業"]})
    adj = pd.DataFrame({
        "ticker": ["7856", "0050", "9105", "1234", "2330"],
        "date": pd.to_datetime(["2026-10-14", "2026-10-14", "2026-10-14", "2025-01-02", "2026-10-14"])})
    out, n = dp.classify_new_listings(sl, adj)
    got = dict(zip(out["code"], out["sector"]))
    assert n == 1 and got["7856"] == dp.UNCLASSIFIED
    assert got["0050"] == "" and got["9105"] == "" and got["1234"] == "" and got["2330"] == "半導體業"


def test_stock_list_carry不沿用補位標籤_讓它每次由classify重標():
    carry = pd.DataFrame({"code": ["2330", "7856"], "name": ["台積電", "某新股"], "sector": ["半導體業", dp.UNCLASSIFIED]})
    out = dp.stock_list_frame({"2330": "TW", "7856": "TW"}, None, None, carry).set_index("code")
    assert out.loc["2330", "sector"] == "半導體業"
    assert out.loc["7856", "sector"] == ""          # 不是 UNCLASSIFIED；是否重標由 classify_new_listings 看近況決定
