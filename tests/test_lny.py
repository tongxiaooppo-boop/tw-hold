from screener import lny


def test_window_2026():
    s, e = lny.lunar_new_year_window(2026)
    assert (str(s.date()), str(e.date())) == ("2026-02-13", "2026-02-22")


def test_months_2025_跨兩月():
    assert lny.months_touching_lny(2025) == ["2025-01", "2025-02"]


def test_months_2026_只二月():
    assert lny.months_touching_lny(2026) == ["2026-02"]


def test_month_touches():
    assert lny.month_touches_lny("2025-01") is True
    assert lny.month_touches_lny("2026-01") is False
    assert lny.month_touches_lny("2026-03") is False
    assert lny.month_touches_lny("2099-02") is False
