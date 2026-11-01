import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from screener import multiples

import numpy as np
import pandas as pd


def _monthly_data(values):
    values = list(values)
    return pd.DataFrame(
        {
            "date": [
                pd.Timestamp("2020-01-20") + pd.DateOffset(months=i)
                for i in range(len(values))
            ],
            "per": values,
            "pbr": values,
        }
    )


def _high_pe_data():
    rows = []
    for year in range(2020, 2025):
        dates = pd.date_range(f"{year}-01-02", periods=20, freq="B")
        for i, date in enumerate(dates):
            # 每年平均為 (20 + 44) / 2 = 32，不要求每天都超過 gate。
            rows.append(
                {"date": date, "per": 20.0 if i % 2 == 0 else 44.0, "pbr": 2.0}
            )
    return pd.DataFrame(rows)


def test_月底取該月最後有效值():
    per = pd.DataFrame(
        {
            "date": [
                "2023-02-28",
                "2023-01-31",
                pd.Timestamp("2023-01-30"),
                "2023-02-27",
                "2023-01-31",
                "2023-03-30",
                "2023-03-31",
                "2023-03-31",
            ],
            "per": [np.nan, 12, 10, 20, 15, 30, 40, 0],
            "pbr": [np.nan, 1.2, 1.0, 2.0, 1.5, 3.0, 4.0, 4.5],
        }
    )

    actual = multiples.month_end_values(per, "per")
    expected = pd.Series(
        [15.0, 20.0, 30.0],
        index=pd.DatetimeIndex(
            ["2023-01-31", "2023-02-27", "2023-03-30"], name="date"
        ),
        name="per",
    )
    pd.testing.assert_series_equal(actual, expected)

    # 同日最後一筆 per 無效，不能復活該日被覆蓋的有效 per。
    # pbr 則獨立判斷有效性。
    pbr = multiples.month_end_values(per, "pbr")
    assert pbr.index[-1] == pd.Timestamp("2023-03-31")
    assert pbr.iloc[-1] == 4.5


def test_無效值per小於等於0被排除():
    per = pd.DataFrame(
        {
            "date": [
                "2024-01-01",
                "2024-01-02",
                "2024-01-03",
                "2024-01-04",
                "2024-01-31",
                "2024-02-28",
                "2024-03-01",
            ],
            "per": [-2, 0, np.nan, 8, -1, 0, 6],
            "pbr": [1] * 7,
        }
    )
    actual = multiples.month_end_values(per, "per")
    assert actual.index.tolist() == [
        pd.Timestamp("2024-01-04"),
        pd.Timestamp("2024-03-01"),
    ]
    assert actual.tolist() == [8.0, 6.0]


def test_窗年數裁切():
    per = pd.DataFrame(
        {
            "date": [
                "2018-12-31",
                "2019-01-30",
                "2019-01-31",
                "2020-01-15",
                "2020-01-31",
                "2021-01-29",
                "2021-01-31",
            ],
            "per": [1, 2, 3, 7, 4, 5, 0],
        }
    )
    b = multiples.band(per, "per", years=2, min_months=3)
    assert b["ok"] is True
    assert b["n_months"] == 3
    assert b["window_start"] == "2019-01"
    assert b["window_end"] == "2021-01"
    np.testing.assert_allclose(list(b["raw"].values()), [3.4, 4.0, 4.6])

    all_history = multiples.band(per, "per", years=None, min_months=1)
    assert all_history["n_months"] == 4
    assert all_history["window_start"] == "2018-12"

    # asof 前最後有效日為 1/15，不能使用未來 1/31 的數值。
    historical = multiples.band(
        per, "per", years=1, min_months=2, asof="2020-01-30"
    )
    assert historical["n_months"] == 2
    assert historical["window_start"] == "2019-01"
    assert historical["window_end"] == "2020-01"
    np.testing.assert_allclose(
        list(historical["raw"].values()), [3.8, 5.0, 6.2]
    )

    # 日期窗口含起點。
    boundary = multiples.band(
        _monthly_data([10, 20]),
        "per",
        years=1,
        min_months=1,
        asof="2021-01-20",
    )
    assert boundary["n_months"] == 2


def test_有效月數不足_ok為False():
    b = multiples.band(_monthly_data([10, 20]), "per", None, 3)
    assert b["ok"] is False
    assert b["reason"] == "有效月數不足（2/3）"
    assert b["n_months"] == 2
    assert b["window_start"] == "2020-01"
    assert b["window_end"] == "2020-02"
    assert b["raw"] == {"p20": 12.0, "p50": 15.0, "p80": 18.0}
    assert b["capped"] == b["raw"]
    assert b["ratio"] == 1.5

    empty = multiples.band(_monthly_data([]), "per", None, 3, cap=30)
    assert empty["ok"] is False
    assert empty["reason"] == "有效月數不足（0/3）"
    assert empty["n_months"] == 0
    assert empty["window_start"] is None
    assert empty["window_end"] is None
    assert empty["raw"] == {"p20": None, "p50": None, "p80": None}
    assert empty["capped"] == empty["raw"]
    assert empty["ratio"] is None
    assert empty["truncated"] is False
    assert empty["cap"] == 30


def test_cap截斷_truncated為True且capped不超過cap():
    per = _monthly_data(range(1, 11))
    b = multiples.band(per, "per", None, 10, cap=5.0)
    assert b["ok"] is True
    assert b["cap"] == 5.0
    assert b["truncated"] is True
    assert all(value <= 5.0 for value in b["capped"].values())
    np.testing.assert_allclose(
        list(b["capped"].values()), [2.8, 5.0, 5.0]
    )
    np.testing.assert_allclose(
        list(b["raw"].values()), [2.8, 5.5, 8.2]
    )
    assert np.isclose(b["ratio"], 8.2 / 2.8)

    at_limit = multiples.band(
        per, "per", None, 10, cap=b["raw"]["p80"]
    )
    assert at_limit["truncated"] is False


def test_p20_p50_p80_對線性序列():
    b = multiples.band(_monthly_data(range(1, 11)), "per", None, 10)
    # 線性插值位置為 (n - 1) * q：1.8、4.5、7.2。
    np.testing.assert_allclose(
        list(b["raw"].values()), [2.8, 5.5, 8.2]
    )
    assert b["capped"] == b["raw"]
    assert b["cap"] is None
    assert b["truncated"] is False
    assert b["reason"] is None

    constant = multiples.band(_monthly_data([7, 7, 7]), "pbr", None, 3)
    assert constant["raw"] == {"p20": 7.0, "p50": 7.0, "p80": 7.0}
    assert constant["ratio"] == 1.0


def test_prices_base非正回None():
    per = _monthly_data(range(1, 11))
    b = multiples.band(per, "per", None, 10, cap=5.0)
    for base in (None, 0, -1, np.nan):
        assert multiples.prices(base, b) is None

    insufficient = multiples.band(per, "per", None, 11)
    assert multiples.prices(2.0, insufficient) is None

    p = multiples.prices(2.0, b)
    assert set(p) == {
        "cheap", "fair", "dear", "cheap_raw", "fair_raw", "dear_raw"
    }
    np.testing.assert_allclose(
        [p["cheap"], p["fair"], p["dear"]],
        [5.6, 10.0, 10.0],
    )
    np.testing.assert_allclose(
        [p["cheap_raw"], p["fair_raw"], p["dear_raw"]],
        [5.6, 11.0, 16.4],
    )


def test_high_pe_exception_五年都高且獲利為True():
    per = _high_pe_data()
    eps = {year: 2.0 for year in range(2020, 2025)}
    assert multiples.high_pe_exception(per, eps) is True

    too_few = per.loc[per["date"].dt.year != 2020]
    assert multiples.high_pe_exception(too_few, eps) is False

    nineteen_days = per.drop(per.index[0])
    assert multiples.high_pe_exception(nineteen_days, eps) is False

    at_gate = per.copy()
    at_gate.loc[at_gate["date"].dt.year == 2022, "per"] = 30.0
    assert multiples.high_pe_exception(at_gate, eps) is False


def test_high_pe_exception_有一年虧損為False():
    per = _high_pe_data()
    eps = {year: 2.0 for year in range(2020, 2025)}
    eps[2022] = -0.5
    assert multiples.high_pe_exception(per, eps) is False

    eps[2022] = 0.0
    assert multiples.high_pe_exception(per, eps) is False

    del eps[2022]
    assert multiples.high_pe_exception(per, eps) is False


def test_classify_position三種與na():
    b = multiples.band(_monthly_data([10, 20, 30]), "per", None, 3)
    p = multiples.prices(1.0, b)
    assert p["cheap"] == 14.0
    assert p["fair"] == 20.0
    assert p["dear"] == 26.0

    assert multiples.classify_position(13.0, p) == "cheap"
    for price in (14.0, 17.0, 20.0, 23.0, 26.0):
        assert multiples.classify_position(price, p) == "fair"
    assert multiples.classify_position(27.0, p) == "dear"
    assert multiples.classify_position(None, p) == "na"
    assert multiples.classify_position(20.0, None) == "na"
    assert multiples.classify_position(np.nan, p) == "na"

    for key in ("cheap", "fair", "dear"):
        incomplete = dict(p)
        incomplete[key] = None
        assert multiples.classify_position(20.0, incomplete) == "na"
