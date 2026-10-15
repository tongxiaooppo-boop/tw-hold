"""已知股票分割 / 面額變更的每股數字還原（reference.corporate_actions）。"""
from __future__ import annotations

import pandas as pd

from reference.corporate_actions import IGNORE_JUMPS, SPLITS, adjust_per_share, adjust_prices


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
        assert tk.isdigit()
        for e in events:
            assert pd.Timestamp(e["date"]) and e["factor"] > 0 and e["factor"] != 1
    assert not (set(SPLITS) & set(IGNORE_JUMPS))     # 同一檔不能又修又忽略


def test_偵測器對已登記或已忽略的跳空不再報():
    from build_factors import detect_unhandled_splits
    for line in detect_unhandled_splits():
        tk = line.split()[0]
        assert tk not in SPLITS and tk not in IGNORE_JUMPS


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
