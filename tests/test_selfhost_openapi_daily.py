"""官方 OpenAPI 每日收集（scripts/selfhost_openapi_daily.py）：日期斷言、解析、冪等合併、缺口偵測。"""
from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

_spec = importlib.util.spec_from_file_location(
    "oa", Path(__file__).resolve().parents[1] / "scripts" / "selfhost_openapi_daily.py")
oa = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(oa)

@pytest.fixture(autouse=True)
def _isolate_log(tmp_path, monkeypatch):
    """測試不能寫進真實的 data/selfhost/openapi_fetch_log.jsonl（那份是官方更新時間的實測紀錄）。"""
    monkeypatch.setattr(oa, "SH", tmp_path)
    monkeypatch.setattr(oa, "LOG", tmp_path / "log.jsonl")


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


# ───────── 上市融資 MI_MARGN（網站端點，帶日期）─────────
import sys as _sys
import types as _types


def _margin_df(d, n=400):
    cols = ["date", "ticker", "market", "margin_balance", "margin_buy", "margin_sell", "margin_redeem",
            "short_balance", "short_buy", "short_sell", "short_redeem", "offset", "margin_prev", "short_prev", "note"]
    rows = [{"date": pd.Timestamp(d), "ticker": str(1000 + i), "market": "TW", "margin_balance": 9.0, "margin_buy": 1.0,
             "margin_sell": 2.0, "margin_redeem": 0.0, "short_balance": 6.0, "short_buy": 1.0, "short_sell": 2.0,
             "short_redeem": 0.0, "offset": 0.0, "margin_prev": 10.0, "short_prev": 5.0, "note": ""} for i in range(n)]
    return pd.DataFrame(rows, columns=cols)


def _fake_chips(monkeypatch, fn):
    m = _types.ModuleType("selfhost_chips")
    m.margin_twse = fn
    monkeypatch.setitem(_sys.modules, "selfhost_chips", m)


def _empty_margin():
    return pd.DataFrame(columns=oa.MARGIN_COLS).astype({"date": "datetime64[ns]"})


def test_margin_candidates_skip_weekend():
    assert oa.margin_candidates(date(2026, 10, 7)) == [date(2026, 10, 7), date(2026, 10, 6)]       # 週三：今天＋昨天
    assert oa.margin_candidates(date(2026, 10, 5)) == [date(2026, 10, 5), date(2026, 10, 2)]       # 週一：前一個平日是週五
    assert oa.margin_candidates(date(2026, 10, 3)) == [date(2026, 10, 2)]                          # 週六：只試週五


def test_collect_twse_margin_added_then_not_refetched(monkeypatch):
    calls = []

    def fake(d):
        calls.append(d)
        return _margin_df(d) if d == date(2026, 10, 6) else pd.DataFrame(columns=_margin_df(d).columns)   # 今天還沒公布
    _fake_chips(monkeypatch, fake)
    t, ch = oa.collect_twse_margin(date(2026, 10, 7), FETCHED, _empty_margin())
    assert ch and len(t) == 400 and set(t.src) == {oa.SRC_WEB_MARGN} and set(t.market) == {"TW"}
    assert list(t.columns) == oa.MARGIN_COLS
    calls.clear()
    late = pd.Timestamp("2026-10-07 02:00:00")                       # 10/6 的資料在 10/7 台北 10:00 抓過（過了隔日 00:00 窗口）
    t["fetched_at"] = late
    t2, ch2 = oa.collect_twse_margin(date(2026, 10, 7), pd.Timestamp("2026-10-07 08:00:00"), t)
    assert calls == [date(2026, 10, 7)] and not ch2 and len(t2) == 400                          # 過窗口的 10/6 不重打


def test_collect_twse_margin_failure_and_thin_do_not_store(monkeypatch, capsys):
    _fake_chips(monkeypatch, lambda d: None)
    t, ch = oa.collect_twse_margin(date(2026, 10, 7), FETCHED, _empty_margin())
    assert not ch and len(t) == 0 and "::warning::" in capsys.readouterr().err
    _fake_chips(monkeypatch, lambda d: _margin_df(d, n=50))
    t, ch = oa.collect_twse_margin(date(2026, 10, 7), FETCHED, _empty_margin())
    assert not ch and len(t) == 0                                                               # 殘缺不存


def test_web_margin_does_not_collide_with_tpex_rows(monkeypatch):
    _fake_chips(monkeypatch, lambda d: _margin_df(d) if d == date(2026, 10, 6) else pd.DataFrame())
    tpex = oa.parse_margin([{"Date": "1151006", "SecuritiesCompanyCode": "1240", "MarginPurchaseBalance": "9"}],
                           "TWO", date(2026, 10, 6), LM1, FETCHED)
    t, ch = oa.collect_twse_margin(date(2026, 10, 7), FETCHED, _tbl(tpex))
    assert ch and set(t.market) == {"TW", "TWO"}                                                # 同一天上櫃已存，上市仍會加（以市場分開）


def test_collect_twse_margin_refetch_inside_window_replaces_only_on_change(monkeypatch):
    d6 = date(2026, 10, 6)
    first = lambda d: _margin_df(d) if d == d6 else pd.DataFrame()
    _fake_chips(monkeypatch, first)
    t, _ = oa.collect_twse_margin(date(2026, 10, 6), pd.Timestamp("2026-10-06 13:00:00"), _empty_margin())   # 台北 21:00 首次抓（窗口內）
    # 窗口內重打：內容相同 → 只更新抓取時間
    t, ch = oa.collect_twse_margin(date(2026, 10, 7), pd.Timestamp("2026-10-06 20:00:00"), t)                # 台北 04:00 那班
    assert ch and len(t) == 400 and t.fetched_at.max() == pd.Timestamp("2026-10-06 20:00:00")
    # 過了窗口（抓取時間 ≥ D 16:00 UTC）就不再打
    calls = []
    _fake_chips(monkeypatch, lambda d: calls.append(d) or pd.DataFrame())
    oa.collect_twse_margin(date(2026, 10, 7), pd.Timestamp("2026-10-07 08:00:00"), t)
    assert d6 not in calls
    # 官方調帳：窗口內重打內容有差 → 整天替換
    t["fetched_at"] = pd.Timestamp("2026-10-06 13:00:00")
    changed = lambda d: _margin_df(d).assign(margin_prev=99.0) if d == d6 else pd.DataFrame()
    _fake_chips(monkeypatch, changed)
    t2, ch = oa.collect_twse_margin(date(2026, 10, 7), pd.Timestamp("2026-10-06 20:00:00"), t)
    assert ch and len(t2) == 400 and (t2.margin_prev == 99.0).all()
    # 重打縮水 → 不覆蓋
    t["fetched_at"] = pd.Timestamp("2026-10-06 13:00:00")
    _fake_chips(monkeypatch, lambda d: _margin_df(d, n=330) if d == d6 else pd.DataFrame())
    t3, ch = oa.collect_twse_margin(date(2026, 10, 7), pd.Timestamp("2026-10-06 20:00:00"), t)
    assert len(t3) == 400


def test_margin_cols_match_selfhost_chips():
    sys_path = str(Path(__file__).resolve().parents[1] / "scripts")
    if sys_path not in _sys.path:
        _sys.path.insert(0, sys_path)
    _sys.modules.pop("selfhost_chips", None)
    import selfhost_chips as sc
    assert set(oa.MARGIN_COLS) - {"src", "last_modified", "fetched_at"} <= set(sc.MARGIN_COLS) | {"src"}
