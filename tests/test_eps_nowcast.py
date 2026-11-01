# tests/test_eps_nowcast.py
# 假設：合成財報與月營收可獨立調整，不要求兩者歷史金額完全勾稽。
# 基準：季營收 100、毛利 30、費損 20、營業利益 10、業外 5；
# 稅率 20%、少數股權比 0、股數 10，故單季 EPS = 1.2。

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd
import pytest

from screener import eps_nowcast


def _quarterly():
    periods = pd.period_range("2021Q1", "2025Q4", freq="Q-DEC")
    return pd.DataFrame(
        {
            "period_end": periods.to_timestamp(how="end").normalize(),
            "revenue": 100.0,
            "gross_profit": 30.0,
            "op_income": 10.0,
            "pretax_income": 15.0,
            "net_income": 12.0,
            "ni_parent": 12.0,
            "eps": 1.2,
        }
    )


def _monthly(end="2026-02-01"):
    index = pd.date_range("2022-01-01", end, freq="MS")
    return pd.Series(100.0 / 3.0, index=index, dtype=float)


def _assert_unique_flags(result):
    assert len(result["flags"]) == len(set(result["flags"]))


def test_k0_月營收沒超過財報季_eps_nc等於ttm():
    result = eps_nowcast.nowcast(_quarterly(), _monthly("2025-11-01"))

    assert result["ok"] is True
    assert result["reason"] is None
    assert result["last_q"] == pd.Timestamp("2025-12-31")
    assert result["last_month"] == pd.Timestamp("2025-11-01")
    assert result["k"] == 0
    assert result["eps_ttm"] == pytest.approx(4.8)
    assert result["eps_nc"] == result["eps_ttm"]
    assert result["fallback"] is False
    assert [row["q"] for row in result["nc_quarters"]] == [
        "2025Q1", "2025Q2", "2025Q3", "2025Q4"
    ]
    assert all(row["kind"] == "actual" for row in result["nc_quarters"])
    _assert_unique_flags(result)


def test_k1_最新月在下一季中_補一季試算():
    result = eps_nowcast.nowcast(_quarterly(), _monthly())

    assert result["ok"] is True
    assert result["k"] == 1
    assert result["eps_nc"] == pytest.approx(4.8)
    assert [row["kind"] for row in result["nc_quarters"]] == [
        "actual", "actual", "actual", "est"
    ]
    estimated = result["nc_quarters"][-1]
    assert estimated["q"] == "2026Q1"
    assert estimated["rev"] == pytest.approx(100.0)
    assert estimated["gm"] == pytest.approx(0.30)
    assert estimated["op"] == pytest.approx(10.0)
    assert estimated["nonop"] == pytest.approx(5.0)
    assert estimated["eps"] == pytest.approx(1.2)
    assert result["eps_f4"] == pytest.approx(4.8)
    assert result["f4_far_quarters"] == 3
    assert all(row["kind"] == "est" for row in result["f4_quarters"])
    assert result["params"]["shares"] == pytest.approx(10.0)
    assert result["params"]["opex_ratio"] == pytest.approx(0.20)


def test_k2_最新月在下兩季_補兩季試算():
    result = eps_nowcast.nowcast(_quarterly(), _monthly("2026-05-01"))

    assert result["ok"] is True
    assert result["k"] == 2
    assert result["eps_nc"] == pytest.approx(4.8)
    assert [row["q"] for row in result["nc_quarters"]] == [
        "2025Q3", "2025Q4", "2026Q1", "2026Q2"
    ]
    assert [row["kind"] for row in result["nc_quarters"]] == [
        "actual", "actual", "est", "est"
    ]
    assert result["nc_quarters"][-1]["rev"] == pytest.approx(100.0)
    assert result["f4_far_quarters"] == 2


def test_g3用合計不用單月():
    monthly = _monthly()
    values = {
        "2024-12-01": 20.0,
        "2025-01-01": 20.0,
        "2025-02-01": 10.0,
        "2025-03-01": 40.0,
        "2025-12-01": 10.0,
        "2026-01-01": 30.0,
        "2026-02-01": 60.0,
    }
    for month, value in values.items():
        monthly.loc[pd.Timestamp(month)] = value

    result = eps_nowcast.nowcast(_quarterly(), monthly)

    # g3 = (10 + 30 + 60) / (20 + 20 + 10) - 1 = 1，而非 60/10 - 1。
    assert result["params"]["g3"] == pytest.approx(1.0)
    estimated = result["nc_quarters"][-1]
    # Q1 營收 = 30 + 60 + 40 * 2 = 170。
    assert estimated["rev"] == pytest.approx(170.0)
    # EPS = (170 * (0.3 - 0.2) + 5) * 0.8 / 10 = 1.76。
    assert estimated["eps"] == pytest.approx(1.76)
    assert result["eps_nc"] == pytest.approx(5.36)


def _monthly_with_twenty_percent_growth():
    monthly = _monthly("2025-12-01")
    monthly.loc["2025-01-01":"2025-12-01"] = 40.0
    return monthly


def test_遠季成長率為g12一半():
    result = eps_nowcast.nowcast(
        _quarterly(), _monthly_with_twenty_percent_growth()
    )

    assert result["params"]["g12"] == pytest.approx(0.20)
    assert result["params"]["g_far"] == pytest.approx(0.10)
    assert result["f4_far_quarters"] == 4
    assert len(result["f4_quarters"]) == 4
    for row in result["f4_quarters"]:
        assert row["rev"] == pytest.approx(110.0)
        # EPS = (110 * 0.1 + 5) * 0.8 / 10 = 1.28。
        assert row["eps"] == pytest.approx(1.28)
    assert result["eps_f4"] == pytest.approx(5.12)


def test_循環股遠季成長為0():
    result = eps_nowcast.nowcast(
        _quarterly(),
        _monthly_with_twenty_percent_growth(),
        g_far_zero=True,
    )

    assert result["params"]["g12"] == pytest.approx(0.20)
    assert result["params"]["g_far"] == 0.0
    assert result["f4_far_quarters"] == 4
    assert result["eps_f4"] == pytest.approx(4.8)
    assert all(
        row["rev"] == pytest.approx(100.0) for row in result["f4_quarters"]
    )


def test_稅率超界改用20且加旗標():
    q = _quarterly()
    q["net_income"] = 6.0
    q["ni_parent"] = 6.0
    q["eps"] = 0.6

    result = eps_nowcast.nowcast(q, _monthly())

    # 原始稅率 = 1 - 6/15 = 60%；股數仍為 6/0.6 = 10。
    assert result["ok"] is True
    assert result["params"]["t"] == pytest.approx(0.20)
    assert result["params"]["shares"] == pytest.approx(10.0)
    assert "稅率超界，改用 20%" in result["flags"]
    assert result["f4_quarters"][0]["eps"] == pytest.approx(1.2)
    assert result["eps_nc"] == pytest.approx(3.0)
    _assert_unique_flags(result)


def test_股數推不出_ok為False():
    q = _quarterly()
    q["eps"] = 0.0

    result = eps_nowcast.nowcast(q, _monthly())

    assert result["ok"] is False
    assert result["reason"] == "股數推不出"
    assert result["params"]["shares"] is None
    assert result["eps_f4"] is None
    assert result["fallback"] is True
    assert result["eps_nc"] == 0.0
    assert eps_nowcast.FALLBACK_FLAG in result["flags"]


def test_去年同月缺_退回ttm並加旗標():
    monthly = _monthly("2026-01-01").drop(pd.Timestamp("2025-02-01"))

    result = eps_nowcast.nowcast(_quarterly(), monthly)

    # g3 的 Nov/Dec/Jan 仍完整；失敗的是 Q1 待補月份的去年二月。
    assert result["params"]["g3"] == pytest.approx(0.0)
    assert result["ok"] is True
    assert result["reason"] is None
    assert result["eps_nc"] == pytest.approx(4.8)
    assert result["eps_f4"] is None
    assert result["f4_quarters"] == []
    assert result["fallback"] is True
    assert eps_nowcast.FALLBACK_FLAG in result["flags"]
    assert any("去年同月營收缺漏" in flag for flag in result["flags"])
    assert all(row["kind"] == "actual" for row in result["nc_quarters"])
    assert result["f4_far_quarters"] == 3
    _assert_unique_flags(result)


def test_季節偏差正負不一致為0():
    q = _quarterly()
    for date, profit in (
        ("2023-03-31", 40.0),
        ("2024-03-31", 20.0),
        ("2025-03-31", 40.0),
    ):
        q.loc[q["period_end"] == pd.Timestamp(date), "gross_profit"] = profit
    q["op_income"] = q["gross_profit"] - 20.0
    q["pretax_income"] = q["op_income"] + 5.0
    q["net_income"] = q["pretax_income"] * 0.8
    q["ni_parent"] = q["net_income"]
    q["eps"] = q["ni_parent"] / 10.0

    result = eps_nowcast.nowcast(q, _monthly())

    # 三個 Q1 偏差依序為 +0.075、-0.075、+0.075，故季節偏差為零。
    # 最新 TTM 毛利率 = (40 + 30 + 30 + 30) / 400 = 0.325。
    assert result["params"]["gm_ttm"] == pytest.approx(0.325)
    estimated = result["nc_quarters"][-1]
    assert estimated["gm"] == pytest.approx(0.325)
    assert estimated["op"] == pytest.approx(12.5)
    assert estimated["eps"] == pytest.approx(1.4)
    assert result["eps_nc"] == pytest.approx(5.0)


def test_k超過三季_只退回nc而f4仍可成功():
    result = eps_nowcast.nowcast(_quarterly(), _monthly("2026-12-01"))

    assert result["k"] == 4
    assert result["fallback"] is True
    assert result["eps_nc"] == pytest.approx(4.8)
    assert result["eps_f4"] == pytest.approx(4.8)
    assert result["f4_far_quarters"] == 0
    assert eps_nowcast.FALLBACK_FLAG in result["flags"]


def test_g12缺值_遠季成長率用零():
    monthly = _monthly().drop(pd.Timestamp("2024-05-01"))

    result = eps_nowcast.nowcast(_quarterly(), monthly)

    assert result["params"]["g3"] == pytest.approx(0.0)
    assert result["params"]["g12"] is None
    assert result["params"]["g_far"] == 0.0
    assert result["eps_f4"] == pytest.approx(4.8)


def test_g3缺值_k0仍可使用ttm():
    monthly = _monthly("2025-12-01").drop(pd.Timestamp("2024-10-01"))

    result = eps_nowcast.nowcast(_quarterly(), monthly)

    assert result["params"]["g3"] is None
    assert result["ok"] is True
    assert result["eps_nc"] == pytest.approx(4.8)
    assert result["eps_f4"] is None
    assert result["fallback"] is False


def test_歸母淨利缺值使用合併淨利():
    q = _quarterly()
    q["ni_parent"] = np.nan

    result = eps_nowcast.nowcast(q, _monthly())

    assert result["ok"] is True
    assert result["params"]["m"] == pytest.approx(0.0)
    assert result["params"]["shares"] == pytest.approx(10.0)
    assert result["eps_f4"] == pytest.approx(4.8)


def test_ttm最舊季eps缺值_滾動所需三季完整仍可成功():
    q = _quarterly()
    q.loc[q["period_end"] == pd.Timestamp("2025-03-31"), "eps"] = np.nan

    result = eps_nowcast.nowcast(q, _monthly())

    assert result["eps_ttm"] is None
    assert result["eps_nc"] == pytest.approx(4.8)
    assert result["eps_f4"] == pytest.approx(4.8)
    assert result["fallback"] is False


def test_缺季不跨季拼接ttm():
    q = _quarterly()
    q = q.loc[q["period_end"] != pd.Timestamp("2025-06-30")]

    result = eps_nowcast.nowcast(q, _monthly())

    assert result["ok"] is False
    assert result["eps_ttm"] is None
    assert result["eps_nc"] is None
    assert result["eps_f4"] is None
    assert result["fallback"] is True


def test_不修改輸入():
    q = _quarterly()
    monthly = _monthly()
    q_before = q.copy(deep=True)
    monthly_before = monthly.copy(deep=True)

    eps_nowcast.nowcast(q, monthly)

    pd.testing.assert_frame_equal(q, q_before)
    pd.testing.assert_series_equal(monthly, monthly_before)


def test_q不是dataframe才拋typeerror():
    with pytest.raises(TypeError):
        eps_nowcast.nowcast([], _monthly())


@pytest.mark.parametrize(
    "q, monthly",
    [
        (pd.DataFrame(), pd.Series(dtype=float)),
        (_quarterly().drop(columns="revenue"), _monthly()),
        (_quarterly(), None),
        (_quarterly(), pd.Series([1.0], index=["不是日期"])),
    ],
)
def test_其他無效輸入不拋例外(q, monthly):
    result = eps_nowcast.nowcast(q, monthly)

    assert result["ok"] is False
    assert isinstance(result["reason"], str)
    assert set(result["params"]) == set(eps_nowcast.PARAM_NAMES)
    _assert_unique_flags(result)
