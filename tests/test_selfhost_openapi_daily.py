"""官方 OpenAPI 每日收集（scripts/selfhost_openapi_daily.py）：日期斷言、解析、冪等合併、缺口偵測。"""
from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import pandas as pd

_spec = importlib.util.spec_from_file_location(
    "oa", Path(__file__).resolve().parents[1] / "scripts" / "selfhost_openapi_daily.py")
oa = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(oa)

TODAY = date(2026, 10, 7)
LM1 = pd.Timestamp("2026-10-06 15:30:05")
LM2 = pd.Timestamp("2026-10-06 21:20:42")
FETCHED = pd.Timestamp("2026-10-07 00:00:00")


def _tw(date_s="1151006", code="2330", close="1,000.00"):
    return {"Date": date_s, "Code": code, "Name": "x", "TradeVolume": "1,000", "TradeValue": "1,000,000",
            "OpeningPrice": "990.00", "HighestPrice": "1,010.00", "LowestPrice": "980.00", "ClosingPrice": close, "Change": "10.00"}


def test_roc_date():
    assert oa.roc_to_date("1151006") == date(2026, 10, 6)


def test_assert_one_date_accepts_and_rejects():
    assert oa.assert_one_date([_tw(), _tw(code="2317")], TODAY) == date(2026, 10, 6)
    assert oa.assert_one_date([_tw(), _tw("1151005")], TODAY) is None                 # 一份回應內日期不一致
    assert oa.assert_one_date([_tw("1150211")], TODAY) == date(2026, 2, 11)           # 太舊不算錯（長假官方日期停在封關日）
    assert oa.assert_one_date([_tw("1151020")], TODAY) is None                        # 未來
    assert oa.assert_one_date([{"Code": "x"}], TODAY) is None                         # 沒有 Date 欄


def test_parse_prices_twse_and_filters():
    rows = [_tw(), _tw(code="00878", close="20.00"), _tw(code="2317", close="--"), _tw(code="1101", close="")]
    df = oa.parse_prices(rows, "TW", date(2026, 10, 6), LM1, FETCHED)
    assert list(df.ticker) == ["2330"]                                                # 非 4 碼、無成交價都不進
    r = df.iloc[0]
    assert (r.open, r.high, r.low, r.close, r.volume, r.value, r.chg) == (990.0, 1010.0, 980.0, 1000.0, 1000.0, 1000000.0, 10.0)
    assert r.src == "openapi" and r.market == "TW"


def test_parse_prices_tpex_chg_dash_is_none():
    rows = [{"Date": "1151006", "SecuritiesCompanyCode": "1240", "Close": "50.0", "Change": "---", "Open": "49", "High": "51",
             "Low": "48", "TradingShares": "31,000", "TransactionAmount": "1,665,700"}]
    df = oa.parse_prices(rows, "TWO", date(2026, 10, 6), LM1, FETCHED)
    assert pd.isna(df.chg.iloc[0]) and df.volume.iloc[0] == 31000.0


def test_parse_margin_maps_columns():
    rows = [{"Date": "1151006", "SecuritiesCompanyCode": "1240", "MarginPurchaseBalancePreviousDay": "10", "MarginPurchase": "1",
             "MarginSales": "2", "CashRedemption": "0", "MarginPurchaseBalance": "9", "ShortSaleBalancePreviousDay": "5",
             "ShortConvering": "1", "ShortSale": "2", "StockRedemption": "0", "ShortSaleBalance": "6", "Offsetting": "0", "Note": " O "}]
    df = oa.parse_margin(rows, "TWO", date(2026, 10, 6), LM1, FETCHED)
    r = df.iloc[0]
    assert (r.margin_prev, r.margin_balance, r.short_balance, r.short_buy, r.note) == (10.0, 9.0, 6.0, 1.0, "O")


def test_merge_day_idempotent_and_replace_on_newer_last_modified():
    a = oa.parse_prices([_tw()], "TW", date(2026, 10, 6), LM1, FETCHED)
    empty = pd.DataFrame(columns=oa.PRICE_COLS).astype({"date": "datetime64[ns]"})
    t, act = oa.merge_day(empty, a, oa.PRICE_COLS)
    assert act == "added" and len(t) == 1
    t2, act = oa.merge_day(t, a, oa.PRICE_COLS)
    assert act == "skipped" and len(t2) == 1                                          # 重跑冪等
    b = oa.parse_prices([_tw(close="1,005.00")], "TW", date(2026, 10, 6), LM2, FETCHED)
    t3, act = oa.merge_day(t2, b, oa.PRICE_COLS)
    assert act == "replaced" and len(t3) == 1 and t3.close.iloc[0] == 1005.0          # 官方事後更正 → 整天覆蓋
    older = oa.parse_prices([_tw(close="999.00")], "TW", date(2026, 10, 6), LM1, FETCHED)
    t4, act = oa.merge_day(t3, older, oa.PRICE_COLS)
    assert act == "skipped" and t4.close.iloc[0] == 1005.0                            # 較舊的不能蓋掉新的


def test_merge_day_markets_independent():
    a = oa.parse_prices([_tw()], "TW", date(2026, 10, 6), LM1, FETCHED)
    t, _ = oa.merge_day(pd.DataFrame(columns=oa.PRICE_COLS).astype({"date": "datetime64[ns]"}), a, oa.PRICE_COLS)
    b = oa.parse_prices([{"Date": "1151006", "SecuritiesCompanyCode": "1240", "Close": "50", "Open": "49", "High": "51", "Low": "48",
                          "TradingShares": "1", "TransactionAmount": "1", "Change": "1"}], "TWO", date(2026, 10, 6), LM1, FETCHED)
    t2, act = oa.merge_day(t, b, oa.PRICE_COLS)
    assert act == "added" and set(t2.market) == {"TW", "TWO"}


def test_missing_trading_days():
    have = {date(2026, 10, 2), date(2026, 10, 6)}
    closed = {date(2026, 10, 1)}
    miss = oa.missing_trading_days(have, TODAY, closed)
    assert date(2026, 10, 5) in miss and date(2026, 10, 2) not in miss and date(2026, 10, 3) not in miss   # 週六不算
    assert date(2026, 10, 1) not in miss                                                                    # 休市不算
    assert date(2026, 10, 7) not in miss                                                                    # 今天還沒公布，不算缺


def test_merge_day_shrunk_newer_file_does_not_overwrite():
    rows = [_tw(code=str(1000 + i)) for i in range(100)]
    full = oa.parse_prices(rows, "TW", date(2026, 10, 6), LM1, FETCHED)
    t, _ = oa.merge_day(pd.DataFrame(columns=oa.PRICE_COLS).astype({"date": "datetime64[ns]"}), full, oa.PRICE_COLS)
    half = oa.parse_prices(rows[:50], "TW", date(2026, 10, 6), LM2, FETCHED)
    t2, act = oa.merge_day(t, half, oa.PRICE_COLS)
    assert act == "shrunk" and len(t2) == 100                                         # 半成品不能換掉完整的一天
    nearly = oa.parse_prices(rows[:95], "TW", date(2026, 10, 6), LM2, FETCHED)
    assert oa.merge_day(t, nearly, oa.PRICE_COLS)[1] == "replaced"                    # 小幅減少（下市等）仍可更正


def test_missing_days_skips_yesterday():
    miss = oa.missing_trading_days({date(2026, 10, 2)}, TODAY, set())
    assert date(2026, 10, 6) not in miss and date(2026, 10, 5) in miss


def test_atomic_parquet_roundtrip(tmp_path):
    p = tmp_path / "a.parquet"
    oa._atomic_parquet(pd.DataFrame({"x": [1, 2]}), p)
    assert list(pd.read_parquet(p).x) == [1, 2] and not (tmp_path / "a.tmp").exists()


def test_tpex_endpoint_is_daily_close_and_old_src_gets_replaced():
    assert oa.TPEX_DAY.endswith("tpex_mainboard_daily_close_quotes")                  # 舊端點量額偏低（2026-10-07 實測 860／889 檔）
    row = {"Date": "1151006", "SecuritiesCompanyCode": "1240", "Close": "50", "Open": "49", "High": "51", "Low": "48",
           "TradingShares": "31,000", "TransactionAmount": "1,665,700", "Change": "1"}
    new = oa.parse_prices([row], "TWO", date(2026, 10, 6), LM1, FETCHED)
    assert new.src.iloc[0] == oa.SRC_TPEX_DC
    old = oa.parse_prices([{**row, "TradingShares": "30,000"}], "TWO", date(2026, 10, 6), LM2, FETCHED)
    old["src"] = "openapi"                                                            # 舊端點存下的同一天，Last-Modified 還比較新
    t, act = oa.merge_day(old, new, oa.PRICE_COLS)
    assert act == "replaced" and t.volume.iloc[0] == 31000.0                          # 來源不同 → 不看 Last-Modified，用新端點覆蓋
    t2, act = oa.merge_day(t, new, oa.PRICE_COLS)
    assert act == "skipped"                                                           # 同來源重跑仍冪等


def _tpex_row(code="1240", vol="31,000", close="50", chg="+0.11"):
    return {"Date": "1151006", "SecuritiesCompanyCode": code, "Close": close, "Open": "49", "High": "51", "Low": "48",
            "TradingShares": vol, "TransactionAmount": "1,665,700", "Change": chg}


def _tbl(df):
    return df.astype({"date": "datetime64[ns]"})


def test_merge_cross_src_is_one_way_and_shrink_guard_applies():
    rows = [_tpex_row(code=str(1000 + i)) for i in range(100)]
    d = date(2026, 10, 6)
    old = oa.parse_prices(rows, "TWO", d, LM2, FETCHED); old["src"] = "openapi"
    # 新來源縮水 → 擋下（shrunk 不分來源）
    half = oa.parse_prices(rows[:50], "TWO", d, LM1, FETCHED)
    assert oa.merge_day(old, half, oa.PRICE_COLS)[1] == "shrunk"
    # 新來源 Last-Modified 為空 → 仍是單向升級，可覆蓋（列數沒縮水）
    full = oa.parse_prices(rows, "TWO", d, None, FETCHED)
    assert oa.merge_day(old, full, oa.PRICE_COLS)[1] == "replaced"
    # 反方向：舊碼的 openapi 不能蓋掉 openapi_dc
    dc = oa.parse_prices(rows, "TWO", d, LM1, FETCHED)
    assert oa.merge_day(dc, old.assign(last_modified=LM2), oa.PRICE_COLS)[1] == "skipped"


def test_merge_old_src_nan_or_missing_column_is_safe():
    rows = [_tpex_row(code=str(1000 + i)) for i in range(100)]
    d = date(2026, 10, 6)
    old = oa.parse_prices(rows, "TWO", d, LM2, FETCHED); old["src"] = None
    half = oa.parse_prices(rows[:50], "TWO", d, LM1, FETCHED)
    assert oa.merge_day(old, half, oa.PRICE_COLS)[1] == "shrunk"                      # NaN 不會繞過縮水保護
    nosrc = old.drop(columns=["src"])
    assert oa.merge_day(nosrc, oa.parse_prices(rows, "TWO", d, LM1, FETCHED), oa.PRICE_COLS)[1] == "replaced"   # 缺欄不拋 KeyError


def test_src_markers_and_margin_unchanged():
    assert oa.parse_prices([_tw()], "TW", date(2026, 10, 6), LM1, FETCHED).src.iloc[0] == "openapi"
    m = {"Date": "1151006", "SecuritiesCompanyCode": "1240", "MarginPurchaseBalance": "9"}
    assert oa.parse_margin([m], "TWO", date(2026, 10, 6), LM1, FETCHED).src.iloc[0] == "openapi"


def test_tpex_real_shape_filters_no_trade_and_non_4digit():
    rows = [_tpex_row(), _tpex_row(code="00411A"), _tpex_row(code="1241", close="---"), _tpex_row(code="030001")]
    df = oa.parse_prices(rows, "TWO", date(2026, 10, 6), LM1, FETCHED)
    assert list(df.ticker) == ["1240"] and df.chg.iloc[0] == 0.11
