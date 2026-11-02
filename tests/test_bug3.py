import sys

import numpy as np
import pandas as pd
import pytest

from factors.factors import _normalized_eps
from reference import loader
from screener import candidate_pool as cp
from screener import classify as cl
from screener.screen import screen_value


ASOF = pd.Timestamp("2026-02-01")


def _fund(base=1.0, eps=1.5, gm=(32.0, 31.0, 30.0)):
    q = pd.DataFrame({
        "ticker": ["2330"] * 5,
        "period_end": pd.date_range("2024-12-31", periods=5, freq="QE"),
        "disclosure_date": pd.Timestamp("2026-01-01"),
        "eps": [base, 1.0, 1.0, 1.0, eps],
        "ttm_eps": 5.0, "roe": 0.2, "f_score": 8,
        "gross_margin": [30.0, 30.0, gm[2], gm[1], gm[0]],
    })
    return cp.canslim_fundamental(q, ASOF).loc["2330"]


def test_eps_yoy_negative_base_not_pass():
    r = _fund(-2, -4)
    assert not r["c_eps_yoy"] and pd.isna(r["eps_yoy_q"])


def test_eps_yoy_zero_base_not_pass():
    r = _fund(0, 1)
    assert not r["c_eps_yoy"] and pd.isna(r["eps_yoy_q"])


def test_eps_yoy_positive_base_unchanged():
    r = _fund()
    assert r["eps_yoy_q"] == pytest.approx(0.5) and r["c_eps_yoy"]


def test_gm_partial_nan_fails():
    assert not _fund(gm=(30, np.nan, 28))["c_gm_not_deteriorating"]


def test_gm_all_nan_passes():
    assert _fund(gm=(np.nan,) * 3)["c_gm_not_deteriorating"]


def test_gm_full_unchanged():
    assert not _fund(gm=(30, 31, 32))["c_gm_not_deteriorating"]
    assert _fund(gm=(32, 31, 30))["c_gm_not_deteriorating"]


def _chips():
    return pd.DataFrame({"ticker": "2330", "date": pd.date_range("2026-01-01", periods=20),
                         "foreign_net": 100.0, "trust_net": 100.0})


def test_inst_nan_in_window_is_nan():
    c = _chips()
    c.loc[10, "foreign_net"] = np.nan
    assert pd.isna(cp.institutional_net20(c, ASOF).loc["2330"])


def test_inst_full_window_unchanged():
    assert cp.institutional_net20(_chips(), ASOF).loc["2330"] == 4000


def test_crossing_no_stock_data():
    dates = pd.date_range("2025-01-01", periods=3, freq="MS")
    r = cl.crossing_test(pd.Series(np.nan, index=dates), pd.Series(-0.1, index=dates))
    assert r == {"n": 0, "k": 0, "passed": False, "executed": False, "no_data": True}


def test_crossing_no_shrink_unchanged():
    dates = pd.date_range("2025-01-01", periods=3, freq="MS")
    r = cl.crossing_test(pd.Series(np.nan, index=dates), pd.Series(0.1, index=dates))
    assert r == {"n": 0, "k": 0, "passed": True, "executed": False, "no_data": False}


def test_cagr5_required_from_24q():
    # 指定可讀區段沒有建構 helper，依任務書允許的替代方式檢查常數。
    assert 22 < cl.GROWTH_CAGR5_REQ_Q
    assert 24 == cl.GROWTH_CAGR5_REQ_Q
    assert cl.GROWTH_MIN_LISTED_Q == 20


def _norm(years, values, period="2025-03-31"):
    q = pd.DataFrame({"ticker": ["2330"], "period_end": [pd.Timestamp(period)]})
    ann = pd.DataFrame({"ticker": "2330", "_year": years, "annual_eps": values})
    return _normalized_eps(q, ann).iloc[0]


def test_normalized_eps_calendar_years():
    assert pd.isna(_norm([2010, 2011, 2012, 2024], [1, 2, 3, 10]))


def test_normalized_eps_three_of_five():
    assert _norm([2020, 2022, 2024], [3, 6, 9]) == pytest.approx(6.0)
    # 最近一年缺年度資料仍須延伸查表，2019 已不在五年窗內。
    assert _norm([2019, 2020, 2022, 2023], [100, 3, 6, 9]) == pytest.approx(6.0)


def test_dividend_all_nan_is_nan(monkeypatch):
    from reference import corporate_actions

    d = pd.DataFrame({"ticker": ["2330"] * 3, "year": [2023, 2023, 2024],
                      "cash_earnings": [np.nan, np.nan, 2.0], "cash_surplus": np.nan,
                      "stock_earnings": np.nan, "pay_date": pd.NaT,
                      "announce_date": pd.NaT, "ex_date": pd.NaT})
    monkeypatch.setattr(loader, "_read", lambda name: d.copy())
    monkeypatch.setattr(corporate_actions, "adjust_dividends", lambda frame, cols: frame)
    out = loader.load_dividends().set_index("year")
    assert pd.isna(out.loc[2023, "cash_dividend"])
    assert out.loc[2024, "cash_dividend"] == 2.0


def _screen_windows(periods, margins):
    q = pd.DataFrame({"ticker": "2330", "period_end": pd.to_datetime(periods),
                      "disclosure_date": pd.Timestamp("2026-01-01"),
                      "rev_yoy": -0.1, "gross_margin": margins})
    captured = {}

    class WindowsReady(Exception):
        pass

    def trace(frame, event, arg):
        if frame.f_code is screen_value.__code__ and event == "line" and "gm_old" in frame.f_locals:
            captured.update({k: frame.f_locals[k].copy() for k in ("weak_rev", "gm_old")})
            raise WindowsReady
        return trace

    # 在視窗算完時擷取中間結果，避免依賴無關的下游篩選欄位。
    previous = sys.gettrace()
    try:
        sys.settrace(trace)
        with pytest.raises(WindowsReady):
            screen_value(q, asof=ASOF)
    finally:
        sys.settrace(previous)
    return captured


def test_screen_weak_rev_calendar_gap():
    r = _screen_windows(["2025-03-31", "2025-06-30", "2025-12-31"], [30, 30, 30])
    assert not r["weak_rev"].loc["2330"]


def test_screen_gm_old_20_calendar_quarters():
    r = _screen_windows(["2020-09-30", "2020-12-31", "2025-06-30", "2025-12-31"],
                        [11, 22, 33, 44])
    assert r["gm_old"].loc["2330"] == 22
