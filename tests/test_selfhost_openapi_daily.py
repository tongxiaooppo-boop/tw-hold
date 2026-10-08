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
    monkeypatch.setattr(oa, "FORECAST", tmp_path / "forecast.jsonl")
    monkeypatch.setattr(oa, "INST", tmp_path / "inst.parquet")
    monkeypatch.setattr(oa._retry.time, "sleep", lambda n: None)                  # 重試不真的等（個別測試要檢查等待秒數時自行覆蓋）
    monkeypatch.setattr(oa, "PRICES", tmp_path / "prices.parquet")
    monkeypatch.setattr(oa, "MARGIN", tmp_path / "margin.parquet")


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
    assert oa.margin_candidates(date(2026, 10, 7), 23) == [date(2026, 10, 7), date(2026, 10, 6)]   # 週三 23 點：今天＋昨天
    assert oa.margin_candidates(date(2026, 10, 5), 23) == [date(2026, 10, 5), date(2026, 10, 2)]   # 週一：前一個平日是週五
    assert oa.margin_candidates(date(2026, 10, 3), 23) == [date(2026, 10, 2)]                      # 週六：只試週五


def test_margin_today_not_tried_before_22():
    for h in (4, 16, 18, 20, 21):
        assert oa.margin_candidates(date(2026, 10, 7), h) == [date(2026, 10, 6)]                  # 融資還沒公布：不打今天
    assert oa.margin_candidates(date(2026, 10, 7), 22)[0] == date(2026, 10, 7)


def test_collect_twse_margin_added_then_not_refetched(monkeypatch):
    calls = []

    def fake(d):
        calls.append(d)
        return _margin_df(d) if d == date(2026, 10, 6) else pd.DataFrame(columns=_margin_df(d).columns)   # 今天還沒公布
    _fake_chips(monkeypatch, fake)
    t, ch = oa.collect_twse_margin(date(2026, 10, 7), FETCHED, _empty_margin(), 23)
    assert ch and len(t) == 400 and set(t.src) == {oa.SRC_WEB_MARGN} and set(t.market) == {"TW"}
    assert list(t.columns) == oa.MARGIN_COLS
    calls.clear()
    late = pd.Timestamp("2026-10-07 02:00:00")                       # 10/6 的資料在 10/7 台北 10:00 抓過（過了隔日 00:00 窗口）
    t["fetched_at"] = late
    t2, ch2 = oa.collect_twse_margin(date(2026, 10, 7), pd.Timestamp("2026-10-07 08:00:00"), t)
    assert calls == [date(2026, 10, 7)] and not ch2 and len(t2) == 400                          # 過窗口的 10/6 不重打


def test_collect_twse_margin_failure_and_thin_do_not_store(monkeypatch, capsys):
    _fake_chips(monkeypatch, lambda d: None)
    t, ch = oa.collect_twse_margin(date(2026, 10, 7), FETCHED, _empty_margin(), 23)
    assert not ch and len(t) == 0 and "::warning::" in capsys.readouterr().err
    _fake_chips(monkeypatch, lambda d: _margin_df(d, n=50))
    t, ch = oa.collect_twse_margin(date(2026, 10, 7), FETCHED, _empty_margin(), 23)
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


def test_collect_twse_margin_before_22_never_requests_today(monkeypatch):
    calls = []
    _fake_chips(monkeypatch, lambda d: calls.append(d) or pd.DataFrame())
    for h in (8, 16, 18, 20, 21):                                                                  # 08:00～22:00 整段不請求
        t, ch = oa.collect_twse_margin(date(2026, 10, 7), FETCHED, _empty_margin(), h)
        assert not ch and len(t) == 0
    assert calls == []
    oa.collect_twse_margin(date(2026, 10, 7), FETCHED, _empty_margin(), 4)                         # 隔日 04:00 清晨班：只補前一晚
    assert calls == [date(2026, 10, 6)]
    calls.clear()
    oa.collect_twse_margin(date(2026, 10, 7), FETCHED, _empty_margin(), 23)                       # 23:00 那班
    assert calls == [date(2026, 10, 7), date(2026, 10, 6)]


# ───────── 預告表快照（上市 TWT48U_ALL＋上櫃 tpex_exright_prepost）─────────
class _Resp:
    headers = {}
    def __init__(self, j): self._j = j; self.status_code = 200
    def raise_for_status(self): pass
    def json(self): return self._j


_TW = [{"Date": "1151008", "Code": "2330", "Name": "台積電", "Exdividend": "息", "StockDividendRatio": "", "SubscriptionRatio": "",
        "SubscriptionPricePerShare": "", "CashDividend": "4.5"}]
_TWO = [{"ExRrightsExDividendDate": "1151008", "SecuritiesCompanyCode": "8440", "CompanyName": "綠電", "ExRrightsExDividend": "除息",
         "StockDividendRatio": "0.00000000", "SubscriptionRatioToNewSharesIssued": "0.00000000", "SubscriptionPricePerShare": "0.00",
         "CashDividend": "0.35000000"}]


def _fake_get(tw=_TW, two=_TWO):
    def get(url, **kw):
        if "TWT48U" in url:
            return _Resp(tw)
        if "tpex_exright_prepost" in url:
            return _Resp(two)
        raise AssertionError(url)
    return get


def test_normalize_forecast_both_markets():
    a = oa.normalize_forecast(_TW, "TW")[0]
    assert (a["code"], a["ex"], a["kind"], a["cash"], a["stock_ratio"]) == ("2330", "2026-10-08", "息", 4.5, None)   # 空字串＝待公告＝None
    b = oa.normalize_forecast(_TWO, "TWO")[0]
    assert (b["code"], b["ex"], b["kind"], b["cash"], b["sub_ratio"]) == ("8440", "2026-10-08", "除息", 0.35, 0.0)


def test_collect_forecasts_dedupes_and_throttles(monkeypatch):
    monkeypatch.setattr(oa.requests, "get", _fake_get())
    t0 = pd.Timestamp("2026-10-07 08:00:00")
    recs, ch = oa.collect_forecasts(t0, [])
    assert ch and len(recs) == 2 and {r["market"] for r in recs} == {"TW", "TWO"} and all(r["rows"] for r in recs)
    recs, ch = oa.collect_forecasts(t0 + pd.Timedelta(hours=1), recs)                        # 間隔不足 3 小時：不請求
    assert not ch and len(recs) == 2
    recs, ch = oa.collect_forecasts(t0 + pd.Timedelta(hours=4), recs)                        # 內容相同：記抓取時間、rows 記 None
    assert ch and len(recs) == 4 and recs[-1]["rows"] is None and recs[-1]["same_as"] == str(t0)
    monkeypatch.setattr(oa.requests, "get", _fake_get(tw=_TW + [dict(_TW[0], Code="2317")]))
    recs, ch = oa.collect_forecasts(t0 + pd.Timedelta(hours=8), recs)                        # 內容有變：存新 rows
    tw_last = [r for r in recs if r["market"] == "TW"][-1]
    assert len(tw_last["rows"]) == 2 and tw_last["same_as"] is None


def test_collect_forecasts_failure_only_warns(monkeypatch, capsys):
    def boom(url, **kw): raise RuntimeError("down")
    monkeypatch.setattr(oa.requests, "get", boom)
    recs, ch = oa.collect_forecasts(pd.Timestamp("2026-10-07 08:00:00"), [])
    assert not ch and recs == [] and "::warning::" in capsys.readouterr().err


def test_normalize_forecast_tolerates_bad_rows_keeps_raw_and_sorts(capsys):
    rows = [dict(_TW[0], Code="2317", Date="1151009", CashDividend="待公告"),
            dict(_TW[0], Code="9999", Date="壞掉"),                                                    # 日期壞 → 跳過
            {"Name": "缺欄"},                                                                          # 缺 Code → 跳過
            dict(_TW[0], Code="1101", Date="1151008", CashDividend="")]
    out = oa.normalize_forecast(rows, "TW")
    assert [r["code"] for r in out] == ["1101", "2317"]                                                # 依 (ex, code) 排序、壞列跳過
    assert out[1]["cash"] is None and out[1]["cash_raw"] == "待公告" and out[0]["cash_raw"] == ""      # 原字串保留，分得出待公告
    assert "2 列解析失敗" in capsys.readouterr().err
    with pytest.raises(ValueError):
        oa.normalize_forecast([{"x": 1}], "TW")                                                        # 整份壞（欄名改版）→ 拋


def test_forecast_dedupe_ignores_row_order(monkeypatch):
    a, b = dict(_TW[0]), dict(_TW[0], Code="2317")
    monkeypatch.setattr(oa.requests, "get", _fake_get(tw=[a, b]))
    t0 = pd.Timestamp("2026-10-07 08:00:00")
    recs, _ = oa.collect_forecasts(t0, [])
    monkeypatch.setattr(oa.requests, "get", _fake_get(tw=[b, a]))                                       # 官方只換排列
    recs, _ = oa.collect_forecasts(t0 + pd.Timedelta(hours=4), recs)
    assert [r for r in recs if r["market"] == "TW"][-1]["rows"] is None


def test_load_forecast_skips_truncated_line(tmp_path, capsys):
    ok = '{"_fetched": "2026-10-07 08:00:00", "market": "TW", "rows": []}'
    oa.FORECAST.write_text(ok + "\n" + '{"_fetched": "2026-10-0', encoding="utf-8")
    assert len(oa._load_forecast()) == 1 and "壞掉" in capsys.readouterr().err                         # 壞行不讓之後每班都失敗


def test_main_writes_forecast_changed_output(monkeypatch, tmp_path):
    monkeypatch.setattr(oa.requests, "get", _fake_get())
    monkeypatch.setattr(oa, "fetch", lambda url: (None, None, None, "x"))                              # 三個 OpenAPI 端點都失敗
    monkeypatch.setattr(oa, "collect_twse_margin", lambda today, fetched, table, hour=24: (table, False))
    monkeypatch.setattr(oa, "collect_inst", lambda today, fetched, table, hour=24: (table, False))      # 不讓 main 測試連到真網站
    out = tmp_path / "gh_out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    oa.main()
    assert "forecast_changed=true" in out.read_text(encoding="utf-8") and oa.FORECAST.exists()


# ───────── 每日三大法人（網站端點帶日期）＋上櫃次日參考價 ─────────
def test_parse_prices_tpex_next_reference_price():
    row = dict(_tpex_row(code="2947", close="62.60"), NextReferencePrice="61.60", NextLimitUp="67.7", NextLimitDown="55.5")
    df = oa.parse_prices([row], "TWO", date(2026, 10, 6), LM1, FETCHED)
    assert (df.next_ref.iloc[0], df.next_limit_up.iloc[0], df.next_limit_down.iloc[0]) == (61.6, 67.7, 55.5)
    tw = oa.parse_prices([_tw()], "TW", date(2026, 10, 6), LM1, FETCHED)
    assert pd.isna(tw.next_ref.iloc[0])                                                              # 上市沒有這欄＝NaN


def test_inst_candidates_window():
    d = date(2026, 10, 7)                                                                            # 週三
    for h in (8, 12, 16, 17):
        assert oa.inst_candidates(d, h) == []                                                        # 18:00 前整段不請求
    assert oa.inst_candidates(d, 18) == [d] and oa.inst_candidates(d, 23) == [d]
    assert oa.inst_candidates(d, 4) == [date(2026, 10, 6)]                                           # 隔日清晨班：只補前一個平日
    assert oa.inst_candidates(date(2026, 10, 5), 4) == [date(2026, 10, 2)]                           # 週一清晨補週五
    assert oa.inst_candidates(date(2026, 10, 10), 20) == []                                          # 週六不試今天


def _inst_df(d, market, n=600, bad=False):
    rows = [{"date": pd.Timestamp(d), "ticker": str(1000 + i), "market": market, "foreign_net": 100.0, "fi_prop_net": 10.0,
             "trust_net": 20.0, "dealer_net": 30.0, "total_net": 999.0 if bad else 160.0} for i in range(n)]
    return pd.DataFrame(rows, columns=["date", "ticker", "market", "foreign_net", "fi_prop_net", "trust_net", "dealer_net", "total_net"])


def _fake_chips_inst(monkeypatch, tw, tpex):
    m = _types.ModuleType("selfhost_chips")
    m.inst_twse, m.inst_tpex, m.margin_twse = tw, tpex, (lambda d: pd.DataFrame())
    monkeypatch.setitem(_sys.modules, "selfhost_chips", m)


def _empty_inst():
    return pd.DataFrame(columns=oa.INST_OA_COLS).astype({"date": "datetime64[ns]"})


def test_collect_inst_added_then_stops_when_got(monkeypatch):
    calls = []
    _fake_chips_inst(monkeypatch, lambda d: calls.append(("TW", d)) or _inst_df(d, "TW"), lambda d: calls.append(("TWO", d)) or _inst_df(d, "TWO", 400))
    t, ch = oa.collect_inst(date(2026, 10, 7), FETCHED, _empty_inst(), 18)
    assert ch and len(t) == 1000 and set(t.market) == {"TW", "TWO"} and set(t.src) == {"web_t86", "web_tpex_insti"}
    assert list(t.columns) == oa.INST_OA_COLS
    calls.clear()
    t2, ch2 = oa.collect_inst(date(2026, 10, 7), FETCHED, t, 20)                                     # 取到就停：同一天不再請求
    assert not ch2 and calls == [] and len(t2) == 1000


def test_collect_inst_not_published_failure_thin_and_identity(monkeypatch, capsys):
    empty = pd.DataFrame(columns=["date", "ticker", "market", "foreign_net", "fi_prop_net", "trust_net", "dealer_net", "total_net"])
    _fake_chips_inst(monkeypatch, lambda d: empty, lambda d: None)                                   # 上市沒資料、上櫃失敗
    t, ch = oa.collect_inst(date(2026, 10, 7), FETCHED, _empty_inst(), 18)
    assert not ch and len(t) == 0 and "::warning::" in capsys.readouterr().err
    _fake_chips_inst(monkeypatch, lambda d: _inst_df(d, "TW", n=50), lambda d: _inst_df(d, "TWO", bad=True, n=400))
    t, ch = oa.collect_inst(date(2026, 10, 7), FETCHED, _empty_inst(), 18)
    assert not ch and len(t) == 0                                                                    # 太少列、恆等式全不符 → 都不存
    err = capsys.readouterr().err
    assert "只有 50 列" in err and "恆等式不符" in err


def test_collect_inst_quiet_hours_never_request(monkeypatch):
    calls = []
    _fake_chips_inst(monkeypatch, lambda d: calls.append(d) or _inst_df(d, "TW"), lambda d: calls.append(d) or _inst_df(d, "TWO", 400))
    for h in (8, 12, 16, 17):
        oa.collect_inst(date(2026, 10, 7), FETCHED, _empty_inst(), h)
    assert calls == []


def test_inst_saturday_early_run_fills_friday():
    assert oa.inst_candidates(date(2026, 10, 10), 4) == [date(2026, 10, 9)]                           # 真正會發生的班次：週六 04:00 補週五


def test_main_inst_disabled_skips_collect_but_runs_others(monkeypatch, capsys):
    monkeypatch.setenv("INST_DISABLED", "1")
    monkeypatch.setattr(oa.requests, "get", _fake_get())
    monkeypatch.setattr(oa, "fetch", lambda url: (None, None, None, "x"))
    monkeypatch.setattr(oa, "collect_twse_margin", lambda today, fetched, table, hour=24: (table, False))
    called = []
    monkeypatch.setattr(oa, "collect_inst", lambda *a, **k: called.append(1) or (a[2], False))
    oa.main()
    assert called == [] and "已停用" in capsys.readouterr().err and oa.FORECAST.exists()            # 法人停用，預告表照存


def test_main_writes_inst_parquet_and_output(monkeypatch, tmp_path):
    monkeypatch.setattr(oa.requests, "get", _fake_get())
    monkeypatch.setattr(oa, "fetch", lambda url: (None, None, None, "x"))
    monkeypatch.setattr(oa, "collect_twse_margin", lambda today, fetched, table, hour=24: (table, False))
    monkeypatch.setattr(oa, "collect_inst", lambda today, fetched, table, hour=24: (_inst_df(date(2026, 10, 7), "TW").assign(src="web_t86", fetched_at=FETCHED)[oa.INST_OA_COLS], True))
    out = tmp_path / "gh_out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    oa.main()
    assert "inst_changed=true" in out.read_text(encoding="utf-8") and oa.INST.exists()


def test_parse_prices_next_cols_are_float_even_when_all_none():
    df = oa.parse_prices([_tw()], "TW", date(2026, 10, 6), LM1, FETCHED)
    assert str(df.next_ref.dtype) == "float64"


# ───────── fetch 重試（官方偶爾回截斷的大 JSON）─────────
class _Bad:
    status_code = 200
    headers = {}
    def raise_for_status(self): pass
    def json(self): raise ValueError("Unterminated string")          # 截斷的 JSON


class _Ok(_Resp):
    pass


class _Http:
    def __init__(self, code): self.status_code, self.headers = code, {}
    def raise_for_status(self):
        e = oa.requests.HTTPError(f"{self.status_code}")
        e.response = self
        raise e


def test_fetch_retries_truncated_json_then_succeeds(monkeypatch):
    seq = [_Bad(), _Bad(), _Ok([{"a": 1}])]
    sleeps = []
    monkeypatch.setattr(oa.requests, "get", lambda url, **kw: seq.pop(0))
    monkeypatch.setattr(oa._retry.time, "sleep", lambda n: sleeps.append(n))
    rows, lm, st, err = oa.fetch("http://x")
    assert rows == [{"a": 1}] and err == "" and sleeps == [10, 20]            # 前兩次截斷、第三次成功


def test_fetch_gives_up_after_three_and_does_not_retry_4xx(monkeypatch):
    n = []
    monkeypatch.setattr(oa._retry.time, "sleep", lambda s: None)
    monkeypatch.setattr(oa.requests, "get", lambda url, **kw: n.append(1) or _Bad())
    rows, _, _, err = oa.fetch("http://x")
    assert rows is None and len(n) == 3 and "Unterminated" in err
    n.clear()
    monkeypatch.setattr(oa.requests, "get", lambda url, **kw: n.append(1) or _Http(404))
    rows, _, st, _ = oa.fetch("http://x")
    assert rows is None and len(n) == 1 and st == 404                        # 4xx 不重試


def test_endpoint_windows():
    for h in (8, 12, 15):
        assert not oa.endpoint_window_ok("twse_day", h) and not oa.endpoint_window_ok("tpex_day", h)          # 日線 16:00 前不請求
    for h in (16, 18, 23, 0, 4, 7):
        assert oa.endpoint_window_ok("twse_day", h) and oa.endpoint_window_ok("tpex_day", h)
    for h in (8, 16, 20, 21):
        assert not oa.endpoint_window_ok("tpex_margin", h)                                                    # 融資 22:00 前不請求（08:00～22:00）
    for h in (22, 23, 0, 4, 7):
        assert oa.endpoint_window_ok("tpex_margin", h)


def test_main_skips_openapi_endpoints_outside_window(monkeypatch):
    import datetime as _dt
    class _FakeDT(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return _dt.datetime(2026, 10, 7, 12, 0, tzinfo=tz)                                                # 台北 12:00
    monkeypatch.setattr(oa, "datetime", _FakeDT)
    called = []
    monkeypatch.setattr(oa, "fetch", lambda url: called.append(url) or (None, None, None, "x"))
    monkeypatch.setattr(oa.requests, "get", _fake_get())
    monkeypatch.setattr(oa, "collect_twse_margin", lambda today, fetched, table, hour=24: (table, False))
    monkeypatch.setattr(oa, "collect_inst", lambda today, fetched, table, hour=24: (table, False))
    oa.main()
    assert called == []                                                                                       # 12:00：日線與上櫃融資一個都不請求


def test_forecast_uses_same_retry_rule(monkeypatch):
    seq = [_Bad(), _Bad(), _Ok(_TW)]
    sleeps = []
    monkeypatch.setattr(oa._retry.time, "sleep", lambda n: sleeps.append(n))
    def get(url, **kw):
        if "TWT48U" in url:
            return seq.pop(0)
        return _Ok(_TWO)
    monkeypatch.setattr(oa.requests, "get", get)
    recs, ch = oa.collect_forecasts(pd.Timestamp("2026-10-07 08:00:00"), [])
    assert ch and {r["market"] for r in recs} == {"TW", "TWO"} and sleeps == [10, 20]              # 預告表也是 3 次、等 10／20 秒


def test_price_target_與取到就停():
    from datetime import date
    assert oa.price_target(date(2026, 10, 8), 16) == date(2026, 10, 8)      # 平日 16:00 後＝今天
    assert oa.price_target(date(2026, 10, 8), 4) == date(2026, 10, 7)       # 清晨班＝前一平日
    assert oa.price_target(date(2026, 10, 12), 4) == date(2026, 10, 9)      # 週一清晨＝上週五
    assert oa.price_target(date(2026, 10, 10), 20) == date(2026, 10, 9)     # 週末＝週五
    t = pd.DataFrame({"market": ["TW", "TWO"], "date": [pd.Timestamp("2026-10-07")] * 2, "src": ["openapi", "openapi_dc"]})
    assert not oa.price_stored(t, "TW", date(2026, 10, 7))                  # 上市 OpenAPI 來源要讓位給官網版
    assert oa.price_stored(t, "TWO", date(2026, 10, 7))
    t.loc[0, "src"] = oa.SRC_WEB_MI_INDEX
    assert oa.price_stored(t, "TW", date(2026, 10, 7))
    assert not oa.price_stored(t, "TWO", date(2026, 10, 8))


def test_price_target_國定假日取最近交易日():
    from datetime import date
    closed = {date(2026, 10, 9)}                                              # 國慶補假
    assert oa.price_target(date(2026, 10, 12), 4, closed) == date(2026, 10, 8)   # 週一清晨：跳過假日週五＝上週四
    assert oa.price_target(date(2026, 10, 9), 20, closed) == date(2026, 10, 8)   # 假日當晚＝前一交易日，不是假日本身
    assert oa.price_target(date(2026, 10, 12), 4, None) == date(2026, 10, 9)     # 休市表抓不到：退回只排除週末


def test_fetch_twse_只有已知的沒有資料才算休市(monkeypatch):
    import selfhost_raw_prices as rp
    for stat in ("很抱歉，沒有符合條件的資料!", "查詢日期大於今日，請重新查詢!"):
        monkeypatch.setattr(rp, "_get", lambda url, s=stat: {"stat": s})
        out = rp.fetch_twse(date(2026, 10, 9))
        assert out is not None and out.empty                                    # 休市／未來日期：空表、不退備援
    monkeypatch.setattr(rp, "_get", lambda url: {"stat": "系統忙碌中，請稍後再試"})
    assert rp.fetch_twse(date(2026, 10, 8)) is None                             # 不認得的 stat：當失敗（退備援＋警告），不可吞成休市
