"""股數變動事件的每股數字還原（reference.corporate_actions）。"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import reference.corporate_actions as ca
from reference.corporate_actions import IGNORE_JUMPS, SPLITS, adjust_per_share, adjust_prices


@pytest.fixture(autouse=True)
def _fake_5904(monkeypatch):
    """舊測試用的 5904 面額變更（舊格式 {date, factor}），跟真實事件表脫鉤。"""
    monkeypatch.setitem(ca.SPLITS, "5904", [{"date": "2026-07-21", "factor": 10}])


def test_分割日前除以factor_日後不動():
    df = pd.DataFrame({
        "ticker": ["5904"] * 4,
        "date": pd.to_datetime(["2026-07-20", "2026-07-21", "2026-07-22", "2026-08-01"]),
        "close": [610.0, 63.0, 64.0, 72.0],
    })
    out = adjust_per_share(df, ["close"])
    assert out["close"].tolist() == [61.0, 63.0, 64.0, 72.0]


def test_沒有已知分割的ticker原樣返回():
    df = pd.DataFrame({"ticker": ["2330", "2330"],
                       "date": pd.to_datetime(["2020-01-01", "2026-01-01"]),
                       "close": [300.0, 1000.0]})
    out = adjust_per_share(df, ["close"])
    pd.testing.assert_frame_equal(out, df)


def test_自訂日期欄_period_end():
    df = pd.DataFrame({
        "ticker": ["5904", "5904"],
        "period_end": pd.to_datetime(["2025-12-31", "2026-09-30"]),
        "eps": [30.0, 3.0],
    })
    out = adjust_per_share(df, ["eps"], date_col="period_end")
    assert out["eps"].tolist() == [3.0, 3.0]


def test_減資_factor小於1_放大分割日前的價(monkeypatch):
    import reference.corporate_actions as ca
    monkeypatch.setitem(ca.SPLITS, "9999", [{"date": "2026-01-01", "factor": 0.5}])
    df = pd.DataFrame({"ticker": ["9999", "9999"],
                       "date": pd.to_datetime(["2025-12-31", "2026-01-02"]),
                       "close": [30.0, 60.0]})
    out = ca.adjust_per_share(df, ["close"])
    assert out["close"].tolist() == [60.0, 60.0]   # 減資後股價往上，舊價被放大


def test_對照表格式():
    for tk, events in SPLITS.items():
        assert tk.isalnum()
        for e in events:
            assert pd.Timestamp(e["date"])
            m, pf = ca._m(e), ca._pf(e)
            assert m is None or (m > 0 and m != 1)
            assert pf is None or pf > 0
            assert m is not None or pf is not None
    # 2026-10-30 起事件表涵蓋 2015～全部事件，IGNORE_JUMPS 忽略的是「另一筆」雜訊跳空
    # （例 5314：2025-03-31 真的 1 拆 20，忽略的是 2026-08-06 那筆），可以重疊
    assert all(str(t).isalnum() for t in IGNORE_JUMPS)


def test_偵測器對已登記或已忽略的跳空不再報():
    from build_factors import detect_unhandled_splits
    for line in detect_unhandled_splits():
        tk = line.split()[0]
        assert tk not in ca.price_split_tickers() and tk not in IGNORE_JUMPS


def test_adjust_prices_上游沒還原的照除():
    df = pd.DataFrame({
        "ticker": ["5904"] * 4,
        "date": pd.to_datetime(["2026-07-20", "2026-07-21", "2026-07-22", "2026-08-01"]),
        "close": [610.0, 63.0, 64.0, 72.0],
    })
    assert adjust_prices(df, ["close"])["close"].tolist() == [61.0, 63.0, 64.0, 72.0]


def test_adjust_prices_自建包已還原的不再除第二次():
    """selfhost 日線事件日前後本來就連續（61.10→63.30），不能再 ÷10 變成 6.11。"""
    df = pd.DataFrame({
        "ticker": ["5904"] * 4,
        "date": pd.to_datetime(["2026-07-20", "2026-07-21", "2026-07-22", "2026-08-01"]),
        "close": [61.1, 63.3, 64.0, 72.0],
    })
    out = adjust_prices(df, ["close"])
    pd.testing.assert_frame_equal(out, df)


def test_adjust_prices_減資已還原與未還原(monkeypatch):
    import reference.corporate_actions as ca
    monkeypatch.setitem(ca.SPLITS, "9999", [{"date": "2026-01-02", "factor": 2.0}])
    d = pd.to_datetime(["2025-12-31", "2026-01-02", "2026-01-05"])
    raw = pd.DataFrame({"ticker": ["9999"] * 3, "date": d, "close": [20.0, 10.0, 10.5]})
    adj = pd.DataFrame({"ticker": ["9999"] * 3, "date": d, "close": [10.0, 10.0, 10.5]})
    assert adjust_prices(raw, ["close"])["close"].tolist() == [10.0, 10.0, 10.5]
    assert adjust_prices(adj, ["close"])["close"].tolist() == [10.0, 10.0, 10.5]


def test_adjust_prices_沒有close欄退回舊行為():
    df = pd.DataFrame({"ticker": ["5904", "5904"],
                       "date": pd.to_datetime(["2026-07-20", "2026-07-21"]),
                       "open": [610.0, 63.0]})
    assert adjust_prices(df, ["open"])["open"].tolist() == [61.0, 63.0]


def test_adjust_prices_登記日偏一天_以實際跳空日為界(monkeypatch):
    import reference.corporate_actions as ca
    monkeypatch.setitem(ca.SPLITS, "9998", [{"date": "2026-01-07", "factor": 20.0}])
    d = pd.bdate_range("2025-12-29", periods=8)             # 12/29..1/7
    close = [200.0, 200.0, 200.0, 10.0, 10.0, 10.0, 10.0, 10.0]   # 真正跳空在 1/1 之後第一根
    df = pd.DataFrame({"ticker": "9998", "date": d, "close": close})
    out = adjust_prices(df, ["close"])
    assert out["close"].tolist() == [10.0] * 8


def test_adjust_prices_方向相反不除並留警告(monkeypatch):
    import reference.corporate_actions as ca
    monkeypatch.setitem(ca.SPLITS, "9997", [{"date": "2026-01-05", "factor": 2.0}])
    ca.PRICE_WARNINGS.clear()
    d = pd.bdate_range("2025-12-29", periods=6)
    df = pd.DataFrame({"ticker": "9997", "date": d, "close": [10.0, 10.0, 10.0, 20.0, 20.0, 20.0]})
    out = adjust_prices(df, ["close"])
    pd.testing.assert_frame_equal(out, df)
    assert any("9997" in w for w in ca.PRICE_WARNINGS)


def test_adjust_prices_事件日後沒資料不除並留警告(monkeypatch):
    import reference.corporate_actions as ca
    monkeypatch.setitem(ca.SPLITS, "9996", [{"date": "2026-06-01", "factor": 10.0}])
    ca.PRICE_WARNINGS.clear()
    df = pd.DataFrame({"ticker": "9996", "date": pd.bdate_range("2026-05-25", periods=4),
                       "close": [100.0, 100.0, 100.0, 100.0]})
    pd.testing.assert_frame_equal(adjust_prices(df, ["close"]), df)
    assert any("9996" in w for w in ca.PRICE_WARNINGS)


def test_check_adjusted_jumps_抓得到還原後殘留的斷崖(monkeypatch):
    import reference.corporate_actions as ca
    from build_factors import check_adjusted_jumps
    monkeypatch.setitem(ca.SPLITS, "9995", [{"date": "2026-01-05", "factor": 10.0}])
    d = pd.bdate_range("2025-12-29", periods=8)
    bad = pd.DataFrame({"ticker": "9995", "date": d, "close": [100.0] * 3 + [10.0] * 5})
    ok = pd.DataFrame({"ticker": "9995", "date": d, "close": [10.0] * 8})
    ca.PRICE_WARNINGS.clear()
    assert any("9995" in w for w in check_adjusted_jumps(bad))
    ca.PRICE_WARNINGS.clear()
    assert check_adjusted_jumps(ok) == []


# ── 2026-10-30 新格式：{date, type, m, pf} ───────────────────────────────

def test_新格式_配股只調每股數字不調價格(monkeypatch):
    monkeypatch.setitem(ca.SPLITS, "9990", [{"date": "2026-09-02", "type": "ex_rights",
                                             "m": 3.0, "pf": None}])
    d = pd.bdate_range("2026-08-26", periods=8)
    px = pd.DataFrame({"ticker": "9990", "date": d, "close": [7800.0] * 4 + [2600.0] * 4})
    pd.testing.assert_frame_equal(adjust_prices(px, ["close"]), px)    # 價格不碰
    eps = pd.DataFrame({"ticker": "9990", "date": d[:2], "eps": [30.0, 30.0]})
    assert adjust_per_share(eps, ["eps"])["eps"].tolist() == [10.0, 10.0]
    assert "9990" not in ca.price_split_tickers()


def test_新格式_現金減資m為None不調每股數字(monkeypatch):
    monkeypatch.setitem(ca.SPLITS, "9991", [{"date": "2026-01-05", "type": "cap_reduction",
                                             "m": None, "pf": 0.6}])
    eps = pd.DataFrame({"ticker": "9991", "date": pd.to_datetime(["2025-12-31"]), "eps": [3.0]})
    pd.testing.assert_frame_equal(adjust_per_share(eps, ["eps"]), eps)


def test_新格式_小事件不進價格還原(monkeypatch):
    monkeypatch.setitem(ca.SPLITS, "9992", [{"date": "2026-01-05", "type": "cap_reduction",
                                             "m": 0.9, "pf": 0.9}])
    assert ca._price_events("9992") == []


def _q(periods, eps, ni):
    return pd.DataFrame({"ticker": "9993", "period_end": pd.to_datetime(periods),
                         "eps": eps, "ni_parent": ni})


def test_adjust_eps_期限前事件全除_季末後不動(monkeypatch):
    monkeypatch.setitem(ca.SPLITS, "9993", [{"date": "2026-09-02", "type": "ex_rights",
                                             "m": 3.0, "pf": None}])
    # Q1 期限 5/15 遠早於 9/2 → 除；Q2 落在模糊窗（期限 8/14＋寬限）→ 看隱含股數；Q3 季末後 → 不動
    q = _q(["2026-03-31", "2026-06-30", "2026-09-30"], [30.0, 30.0, 10.0], [300.0, 300.0, 300.0])
    out = ca.adjust_eps(q)["eps"].tolist()
    assert out == [10.0, 10.0, 10.0]   # Q2 隱含股數同 Q1（10）、跟 Q3（30）差 3 倍 → 舊基準 → 除


def test_adjust_eps_模糊季已是新股數就不除(monkeypatch):
    monkeypatch.setitem(ca.SPLITS, "9993", [{"date": "2026-07-25", "type": "ex_rights",
                                             "m": 1.2, "pf": None}])
    # Q2 財報晚公布、已用新股數：隱含股數 12 跟 Q1 的 10 差 1.2、跟 Q3 一樣
    q = _q(["2026-03-31", "2026-06-30", "2026-09-30"], [1.2, 1.0, 1.0], [12.0, 12.0, 12.0])
    assert ca.adjust_eps(q)["eps"].tolist() == pytest.approx([1.0, 1.0, 1.0])


def test_adjust_eps_判不了當新基準(monkeypatch):
    monkeypatch.setitem(ca.SPLITS, "9993", [{"date": "2026-07-25", "type": "ex_rights",
                                             "m": 1.2, "pf": None}])
    q = _q(["2026-03-31", "2026-06-30"], [1.2, 1.0], [np.nan, np.nan])
    assert ca.adjust_eps(q)["eps"].tolist() == pytest.approx([1.0, 1.0])


def test_adjust_dividends_除息日當天也除(monkeypatch):
    monkeypatch.setitem(ca.SPLITS, "9994", [{"date": "2026-08-10", "type": "ex_both",
                                             "m": 1.25, "pf": None}])
    dv = pd.DataFrame({"ticker": "9994", "year": [2024, 2025, 2026],
                       "ex_date": pd.to_datetime(["2025-08-01", "2026-08-10", "2027-08-01"]),
                       "cash_earnings": [5.0, 5.0, 5.0]})
    assert ca.adjust_dividends(dv, ["cash_earnings"])["cash_earnings"].tolist() == [4.0, 4.0, 5.0]


def test_fix_per_配股後逐季混合(monkeypatch):
    monkeypatch.setitem(ca.SPLITS, "9989", [{"date": "2026-09-02", "type": "ex_rights",
                                             "m": 2.0, "pf": None}])
    q = pd.DataFrame({"ticker": "9989",
                      "period_end": pd.to_datetime(["2025-09-30", "2025-12-31", "2026-03-31",
                                                    "2026-06-30", "2026-09-30", "2026-12-31",
                                                    "2027-03-31", "2027-06-30"]),
                      "eps": [4.0, 4.0, 4.0, 4.0, 2.0, 2.0, 2.0, 2.0],
                      "ni_parent": [400.0] * 8})
    per = pd.DataFrame({"ticker": "9989",
                        "date": pd.to_datetime(["2026-09-01", "2026-10-01", "2026-11-20",
                                                "2027-09-01"]),
                        "per": [10.0, 10.0, 10.0, 10.0]})
    out = ca.fix_exchange_ratios(per, quarterly=q).set_index("date")["per"]
    assert out.loc["2026-09-01"] == pytest.approx(10.0)    # 事件前不修
    assert out.loc["2026-10-01"] == pytest.approx(20.0)    # A 組 2509~2606：raw 16、adj 8
    assert out.loc["2026-11-20"] == pytest.approx(17.5)    # 2512~2609：raw 14、adj 8
    assert out.loc["2027-09-01"] == pytest.approx(10.0)    # 2609~2706：raw 8、adj 8


def test_fix_per_提早公布挑B組(monkeypatch):
    monkeypatch.setitem(ca.SPLITS, "9989", [{"date": "2026-09-02", "type": "ex_rights",
                                             "m": 2.0, "pf": None}])
    q = pd.DataFrame({"ticker": "9989",
                      "period_end": pd.to_datetime(["2025-09-30", "2025-12-31", "2026-03-31",
                                                    "2026-06-30", "2026-09-30", "2026-12-31",
                                                    "2027-03-31", "2027-06-30"]),
                      "eps": [4.0, 4.0, 4.0, 4.0, 2.0, 2.0, 2.0, 2.0],
                      "ni_parent": [400.0] * 8})
    per = pd.DataFrame({"ticker": "9989", "date": pd.to_datetime(["2026-11-05"]),
                        "per": [10.0]})
    raw = pd.DataFrame({"ticker": "9989", "date": pd.to_datetime(["2026-11-05"]),
                        "close": [140.0]})
    # c/per = 14 = B 組 raw4 → 挑 B；不給收盤 → A
    assert ca.fix_exchange_ratios(per, quarterly=q, raw_close=raw)["per"].iloc[0] \
        == pytest.approx(17.5)
    assert ca.fix_exchange_ratios(per, quarterly=q)["per"].iloc[0] == pytest.approx(20.0)


def test_fix_per_面額變更不修(monkeypatch):
    monkeypatch.setitem(ca.SPLITS, "9988", [{"date": "2026-08-10", "type": "par_change",
                                             "m": 10, "pf": 10}])
    q = pd.DataFrame({"ticker": "9988", "period_end": pd.to_datetime(["2025-12-31", "2026-06-30"]),
                      "eps": [10.0, 10.0]})
    per = pd.DataFrame({"ticker": "9988", "date": pd.bdate_range("2026-08-10", periods=3),
                        "per": [23.0, 23.5, 24.0]})
    pd.testing.assert_frame_equal(ca.fix_exchange_ratios(per, quarterly=q), per)


def test_fix_per_pbr殖利率不動(monkeypatch):
    monkeypatch.setitem(ca.SPLITS, "9989", [{"date": "2026-09-02", "type": "ex_rights",
                                             "m": 2.0, "pf": None}])
    q = pd.DataFrame({"ticker": "9989",
                      "period_end": pd.to_datetime(["2025-09-30", "2025-12-31", "2026-03-31",
                                                    "2026-06-30", "2026-09-30", "2026-12-31",
                                                    "2027-03-31", "2027-06-30"]),
                      "eps": [4.0, 4.0, 4.0, 4.0, 2.0, 2.0, 2.0, 2.0],
                      "ni_parent": [400.0] * 8})
    per = pd.DataFrame({"ticker": "9989",
                        "date": pd.to_datetime(["2026-09-01", "2026-10-01", "2026-11-20",
                                                "2027-09-01"]),
                        "per": [10.0, 10.0, 10.0, 10.0],
                        "pbr": [1.0, 1.0, 1.0, 1.0],
                        "dividend_yield": [5.0, 5.0, 5.0, 5.0]})
    out = ca.fix_exchange_ratios(per, quarterly=q)
    assert out["pbr"].tolist() == [1.0, 1.0, 1.0, 1.0]
    assert out["dividend_yield"].tolist() == [5.0, 5.0, 5.0, 5.0]
    assert out.set_index("date")["per"].loc["2026-10-01"] == pytest.approx(20.0)


def test_fix_per_沒給quarterly原樣():
    per = pd.DataFrame({"ticker": "9989", "date": pd.to_datetime(["2026-10-01"]),
                        "per": [10.0]})
    pd.testing.assert_frame_equal(ca.fix_exchange_ratios(per), per)


# ── 2026-10-30 gpt-6.1-sol 審查後補 ─────────────────────────────────────

def test_adjust_eps_歸母淨利缺值逐列退用淨利(monkeypatch):
    monkeypatch.setitem(ca.SPLITS, "9993", [{"date": "2026-07-25", "type": "ex_rights",
                                             "m": 3.0, "pf": None}])
    q = pd.DataFrame({"ticker": "9993",
                      "period_end": pd.to_datetime(["2026-03-31", "2026-06-30", "2026-09-30"]),
                      "eps": [30.0, 30.0, 10.0], "ni_parent": [np.nan] * 3,
                      "net_income": [300.0] * 3})
    assert ca.adjust_eps(q)["eps"].tolist() == pytest.approx([10.0, 10.0, 10.0])


def test_adjust_eps_寬限區判不了當舊(monkeypatch):
    monkeypatch.setitem(ca.SPLITS, "9993", [{"date": "2026-09-02", "type": "ex_rights",
                                             "m": 3.0, "pf": None}])
    q = _q(["2026-06-30"], [30.0], [np.nan])           # 期限 8/14 已過、只有一季判不了
    assert ca.adjust_eps(q)["eps"].tolist() == pytest.approx([10.0])


def test_adjust_eps_types篩選(monkeypatch):
    monkeypatch.setitem(ca.SPLITS, "9995", [
        {"date": "2026-01-05", "type": "par_change", "m": 10, "pf": None},
        {"date": "2026-09-02", "type": "ex_rights", "m": 2.0, "pf": None}])
    q = pd.DataFrame({"ticker": "9995",
                      "period_end": pd.to_datetime(["2025-06-30", "2026-12-31"]),
                      "eps": [20.0, 1.0]})
    out = ca.adjust_eps(q, types=ca.EXCHANGE_LAG_TYPES)["eps"].tolist()
    assert out == pytest.approx([10.0, 1.0])       # 只 ÷2（配股）


def test_adjust_eps_upto篩選(monkeypatch):
    monkeypatch.setitem(ca.SPLITS, "9995", [
        {"date": "2026-01-05", "type": "par_change", "m": 10, "pf": None},
        {"date": "2026-09-02", "type": "ex_rights", "m": 2.0, "pf": None}])
    q = pd.DataFrame({"ticker": "9995",
                      "period_end": pd.to_datetime(["2025-06-30", "2026-12-31"]),
                      "eps": [20.0, 1.0]})
    out = ca.adjust_eps(q, upto=pd.Timestamp("2026-06-30"))["eps"].tolist()
    assert out == pytest.approx([2.0, 1.0])        # 只 ÷10（面額變更）
