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


@pytest.fixture(autouse=True)
def _舊口徑為預設(monkeypatch):
    """本檔既有測試的預期值是舊口徑（近四季毛利率＋季節偏差、加業外中位數）；新口徑的測試自己指定 latest。"""
    monkeypatch.setattr(eps_nowcast, "TRIAL_BASIS", "ttm")


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
    assert result["eps_future"] is None
    assert result["future_status"] == "not_growth"
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


def test_遠季成長率為g12一半(monkeypatch):
    result = eps_nowcast.nowcast(_quarterly(), _monthly_with_twenty_percent_growth())
    assert result["params"]["g12"] == pytest.approx(0.20)
    assert result["params"]["g_far"] == pytest.approx(0.10)
    detail = eps_nowcast._estimate(eps_nowcast._normalize_q(_quarterly()),
        eps_nowcast._normalize_monthly(_monthly_with_twenty_percent_growth()),
        pd.Period("2026Q1"), result, basis="ttm")
    assert detail["rev"] == pytest.approx(110.0)
    assert detail["eps"] == pytest.approx(1.28)


def test_循環股遠季成長為0():
    result = eps_nowcast.nowcast(_quarterly(), _monthly_with_twenty_percent_growth(), g_far_zero=True)
    assert result["params"]["g12"] == pytest.approx(0.20)
    assert result["params"]["g_far"] == 0.0
    detail = eps_nowcast._estimate(eps_nowcast._normalize_q(_quarterly()),
        eps_nowcast._normalize_monthly(_monthly_with_twenty_percent_growth()),
        pd.Period("2026Q1"), result, basis="ttm")
    assert detail["rev"] == pytest.approx(100.0)
    assert detail["eps"] == pytest.approx(1.2)


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
    assert result["nc_quarters"][-1]["eps"] == pytest.approx(1.2)
    assert result["eps_nc"] == pytest.approx(3.0)
    _assert_unique_flags(result)


def test_股數推不出_ok為False():
    q = _quarterly()
    q["eps"] = 0.0

    result = eps_nowcast.nowcast(q, _monthly())

    assert result["ok"] is False
    assert result["reason"] == "股數推不出"
    assert result["params"]["shares"] is None
    assert result["eps_future"] is None
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
    assert result["eps_future"] is None
    assert result["future_quarters"] == []
    assert result["fallback"] is True
    assert eps_nowcast.FALLBACK_FLAG in result["flags"]
    assert any("去年同月營收缺漏" in flag for flag in result["flags"])
    assert all(row["kind"] == "actual" for row in result["nc_quarters"])
    _assert_unique_flags(result)


def test_季節偏差正負不一致為0(monkeypatch):
    monkeypatch.setattr(eps_nowcast, "TRIAL_BASIS", "ttm")      # 舊口徑
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


def test_k超過三季_退回nc且未來無資料():
    result = eps_nowcast.nowcast(_quarterly(), _monthly("2026-12-01"))

    assert result["k"] == 4
    assert result["fallback"] is True
    assert result["eps_nc"] == pytest.approx(4.8)
    assert result["eps_future"] is None
    assert eps_nowcast.FALLBACK_FLAG in result["flags"]


def test_g12缺值_遠季成長率用零():
    monthly = _monthly().drop(pd.Timestamp("2024-05-01"))

    result = eps_nowcast.nowcast(_quarterly(), monthly)

    assert result["params"]["g3"] == pytest.approx(0.0)
    assert result["params"]["g12"] is None
    assert result["params"]["g_far"] == 0.0
    assert result["eps_future"] is None


def test_g3缺值_k0仍可使用ttm():
    monthly = _monthly("2025-12-01").drop(pd.Timestamp("2024-10-01"))

    result = eps_nowcast.nowcast(_quarterly(), monthly)

    assert result["params"]["g3"] is None
    assert result["ok"] is True
    assert result["eps_nc"] == pytest.approx(4.8)
    assert result["eps_future"] is None
    assert result["fallback"] is False


def test_歸母淨利缺值使用合併淨利():
    q = _quarterly()
    q["ni_parent"] = np.nan

    result = eps_nowcast.nowcast(q, _monthly())

    assert result["ok"] is True
    assert result["params"]["m"] == pytest.approx(0.0)
    assert result["params"]["shares"] == pytest.approx(10.0)
    assert result["eps_future"] is None


def test_ttm最舊季eps缺值_滾動所需三季完整仍可成功():
    q = _quarterly()
    q.loc[q["period_end"] == pd.Timestamp("2025-03-31"), "eps"] = np.nan

    result = eps_nowcast.nowcast(q, _monthly())

    assert result["eps_ttm"] is None
    assert result["eps_nc"] == pytest.approx(4.8)
    assert result["eps_future"] is None
    assert result["fallback"] is False


def test_缺季不跨季拼接ttm():
    q = _quarterly()
    q = q.loc[q["period_end"] != pd.Timestamp("2025-06-30")]

    result = eps_nowcast.nowcast(q, _monthly())

    assert result["ok"] is False
    assert result["eps_ttm"] is None
    assert result["eps_nc"] is None
    assert result["eps_future"] is None
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


def test_最新一季口徑_遠季維持最近一季營收且用最新一季毛利率(monkeypatch):
    monkeypatch.setattr(eps_nowcast, "TRIAL_BASIS", "latest")
    q = _quarterly()
    q.loc[q.index[-1], ["gross_profit", "op_income"]] = [50.0, 30.0]   # 最新一季毛利率 50%、費用率 20%
    q["pretax_income"] = q["op_income"] + 5.0
    q["net_income"] = q["pretax_income"] * 0.8
    q["ni_parent"] = q["net_income"]
    q["eps"] = q["ni_parent"] / 10.0

    result = eps_nowcast.nowcast(q, _monthly_with_twenty_percent_growth())

    assert result["params"]["gm_last"] == pytest.approx(0.5)
    assert result["params"]["opex_last"] == pytest.approx(0.2)
    copies = [row for row in result["nc_quarters"] if row["kind"] == "copy"]
    assert len(copies) == 1
    for row in copies:
        assert row["gm"] == pytest.approx(0.5)              # 不加季節偏差
        assert row["opex_ratio"] == pytest.approx(0.2)
        assert row["rev"] == pytest.approx(q.iloc[-1]["revenue"])   # 遠季＝最近一季營收，不乘 g_far
    for row in copies:
        assert row["nonop"] == 0.0                          # 試算季排除業外（與展開表一致）
        # EPS = (rev × (0.5 − 0.2) + 0) × (1 − t) × (1 − m) ÷ 股數
        p = result["params"]
        expected = row["rev"] * 0.3 * (1 - p["t"]) * (1 - p["m"]) / p["shares"]
        assert row["eps"] == pytest.approx(expected)


def test_窗口_k等於0時三季實際加一季copy(monkeypatch):
    monkeypatch.setattr(eps_nowcast, "TRIAL_BASIS", "latest")
    r = eps_nowcast.nowcast(_quarterly(), _monthly("2025-12-01"))
    assert r["basis"] == "latest"
    assert [x["kind"] for x in r["nc_quarters"]] == ["actual"] * 3 + ["copy"]
    assert [x["q"] for x in r["nc_quarters"]] == ["2025Q2", "2025Q3", "2025Q4", "2026Q1"]
    assert r["eps_nc"] == pytest.approx(4.4)  # 3×1.2＋100×(0.3−0.2)×0.8÷10


def test_窗口_k等於1時兩季實際一季est一季copy(monkeypatch):
    monkeypatch.setattr(eps_nowcast, "TRIAL_BASIS", "latest")
    r = eps_nowcast.nowcast(_quarterly(), _monthly())
    assert [x["kind"] for x in r["nc_quarters"]] == ["actual", "actual", "est", "copy"]
    assert [x["q"] for x in r["nc_quarters"]] == ["2025Q3", "2025Q4", "2026Q1", "2026Q2"]
    assert r["eps_nc"] == pytest.approx(4.0)  # 2×1.2＋2×0.8


@pytest.mark.parametrize("end,k", [("2026-05-01", 2), ("2026-08-01", 3)])
def test_latest窗口_k等於2及3(monkeypatch, end, k):
    monkeypatch.setattr(eps_nowcast, "TRIAL_BASIS", "latest")
    r = eps_nowcast.nowcast(_quarterly(), _monthly(end))
    assert [x["kind"] for x in r["nc_quarters"]] == ["actual"] * (3-k) + ["est"] * k + ["copy"]
    assert r["eps_nc"] == pytest.approx((3-k)*1.2 + (k+1)*0.8)


def test_copy季營收等於最近一個est季營收(monkeypatch):
    monkeypatch.setattr(eps_nowcast, "TRIAL_BASIS", "latest")
    monthly = _monthly("2026-05-01")
    monthly.loc["2026-04-01"] = 50
    monthly.loc["2026-05-01"] = 60
    r = eps_nowcast.nowcast(_quarterly(), monthly)
    # g3＝(100/3＋50＋60)÷100−1，Q2＝50＋60＋(100/3)×(43/30)。
    expected = 110 + (100/3) * (43/30)
    assert r["nc_quarters"][-2]["rev"] == pytest.approx(expected)
    assert r["nc_quarters"][-1]["rev"] == pytest.approx(expected)
    assert r["nc_quarters"][-1]["rev_src"] == "flat"


def test_逐季代數一致(monkeypatch):
    monkeypatch.setattr(eps_nowcast, "TRIAL_BASIS", "latest")
    q = _quarterly()
    q["ni_parent"] = 10.8
    q["eps"] = 1.08
    r = eps_nowcast.nowcast(q, _monthly("2026-05-01"))
    p = r["params"]
    for x in r["nc_quarters"]:
        if x["kind"] == "actual":
            continue
        assert x["rev"] == pytest.approx(100)
        assert x["gp"] == pytest.approx(30)
        assert x["opex"] == pytest.approx(20)
        assert x["op"] == pytest.approx(10)
        assert x["nonop"] == 0
        assert x["conv"] == pytest.approx(0.72)
        assert x["net"] == pytest.approx(7.2)
        assert x["shares"] == pytest.approx(10)
        assert x["eps"] == pytest.approx(0.72)
        assert x["rev"] * x["gm"] - x["opex"] == pytest.approx(x["op"])
        assert (x["op"] + x["nonop"]) * x["conv"] / x["shares"] == pytest.approx(x["eps"])
        assert x["conv"] == pytest.approx((1-p["t"])*(1-p["m"]))


@pytest.mark.parametrize("end", ["2025-12-01", "2026-02-01", "2026-05-01", "2026-08-01"])
def test_前瞻四季等於各季eps加總(monkeypatch, end):
    monkeypatch.setattr(eps_nowcast, "TRIAL_BASIS", "latest")
    r = eps_nowcast.nowcast(_quarterly(), _monthly(end))
    assert r["eps_nc"] == pytest.approx(sum(x["eps"] for x in r["nc_quarters"]))


@pytest.mark.parametrize("column", ["gross_profit", "op_income"])
def test_latest口徑最新一季毛利率缺值不退回ttm(monkeypatch, column):
    monkeypatch.setattr(eps_nowcast, "TRIAL_BASIS", "latest")
    q = _quarterly()
    q.loc[q.index[-1], column] = np.nan
    r = eps_nowcast.nowcast(q, _monthly())
    assert r["fallback"] is True
    assert r["eps_nc"] == pytest.approx(4.8)
    assert "最新一季毛利率／費用率缺值" in r["flags"]
    assert all(x["kind"] == "actual" for x in r["nc_quarters"])


@pytest.mark.parametrize("column,values,metric,expected,flag", [
    ("revenue", [100, 100, 100, 130], "rev_qoq", 0.30, True),
    ("revenue", [100, 100, 100, 70], "rev_qoq", -0.30, True),
    ("revenue", [100, 100, 100, 129.99], "rev_qoq", 0.2999, False),
    ("gross_profit", [30, 30, 30, 35], "gm_pp", 0.05, True),
    ("gross_profit", [30, 30, 30, 25], "gm_pp", -0.05, True),
    ("gross_profit", [30, 30, 30, 34.99], "gm_pp", 0.0499, False),
    ("eps", [1, 2, 3, 4.01], "eps_x", 2.005, True),
    ("eps", [1, 2, 3, 4], "eps_x", 2, False),
    ("eps", [-1, 0, 1, 10], "eps_x", None, False),
    ("eps", [0.01, 0.02, 0, 10], "eps_x", None, False),
    ("eps", [1, 2, 0, 3.01], "eps_x", 3.01/1.5, True),
])
def test_高變動旗標_各條件(monkeypatch, column, values, metric, expected, flag):
    monkeypatch.setattr(eps_nowcast, "TRIAL_BASIS", "latest")
    q = _quarterly()
    q.loc[q.index[-4:], column] = values
    if column == "revenue":
        q["gross_profit"] = q["revenue"] * 0.3  # 固定毛利率，單獨檢驗營收條件。
    r = eps_nowcast.nowcast(q, _monthly())
    v = r["variability"]
    assert v["flag"] is flag
    assert bool(v["reasons"]) is flag
    assert v["metrics"][metric] == (pytest.approx(expected) if expected is not None else None)


def test_畫面不自己算推導():
    import ast
    source = (Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    func = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_eps_quarter_tables")
    # 允許股數換算億股；任何乘法或其餘除法都會讓本測試失敗。
    for n in ast.walk(func):
        if isinstance(n, ast.BinOp):
            assert not isinstance(n.op, ast.Mult)
            if isinstance(n.op, ast.Div):
                assert isinstance(n.left, ast.Name) and n.left.id == "shares"
                assert isinstance(n.right, ast.Constant) and n.right.value == 1e8


def _growth_case(monkeypatch, end="2026-02-01", multiple=1.2):
    monkeypatch.setattr(eps_nowcast, "TRIAL_BASIS", "latest")
    q = _quarterly()
    q.loc[q.index[-1], ["ni_parent", "net_income", "eps"]] = [13.2, 13.2, 1.32]
    q.loc[q.index[-1], "op_income"] = q.loc[q.index[-5], "op_income"] * 1.2      # 營業利益年增（未來 4 季成長條件）
    m = _monthly(end)
    cutoff = m.index[-1] - pd.DateOffset(months=11)
    m.loc[cutoff:] *= multiple
    return q, m


@pytest.mark.parametrize("end", ["2025-12-01", "2026-02-01"])
def test_未來四季_前兩季與前瞻最後兩季完全相同(monkeypatch, end):
    q, m = _growth_case(monkeypatch, end)
    r = eps_nowcast.nowcast(q, m)
    assert r["future_status"] == "ok"
    assert r["future_quarters"][:2] == r["nc_quarters"][2:4]
    assert all(a is b for a, b in zip(r["future_quarters"], r["nc_quarters"][2:4]))


@pytest.mark.parametrize("j", [1, 2])
def test_未來四季_成長預測季營收等於copy季乘成長因子(monkeypatch, j):
    q, m = _growth_case(monkeypatch)
    r = eps_nowcast.nowcast(q, m)
    # g=0.2；Q1=40+40+40×1.2=128，copy 沿用。
    x = r["future_quarters"][j+1]
    assert x["rev"] == pytest.approx(128 * 1.1 ** (j/4))
    assert x["kind"] == x["rev_src"] == "grow"


def test_未來四季_逐季代數一致(monkeypatch):
    q, m = _growth_case(monkeypatch)
    r = eps_nowcast.nowcast(q, m)
    for x in r["future_quarters"]:
        assert x["rev"] * x["gm"] - x["opex"] == pytest.approx(x["op"])
        assert (x["op"] + x["nonop"]) * x["conv"] / x["shares"] == pytest.approx(x["eps"])
    assert r["eps_future"] == pytest.approx(sum(x["eps"] for x in r["future_quarters"]))


def test_未來四季_營收衰退不給預測(monkeypatch):
    q, m = _growth_case(monkeypatch, multiple=0.8)
    r = eps_nowcast.nowcast(q, m)
    assert (r["eps_future"], r["future_quarters"], r["future_status"]) == (None, [], "not_growth")


@pytest.mark.parametrize("ni", [12, 11])
def test_未來四季_最新季淨利年增非正不給預測(monkeypatch, ni):
    q, m = _growth_case(monkeypatch)
    q.loc[q.index[-1], "ni_parent"] = ni
    r = eps_nowcast.nowcast(q, m)
    assert (r["eps_future"], r["future_quarters"], r["future_status"]) == (None, [], "not_growth")


def test_未來四季_去年同季虧損視為不成立(monkeypatch):
    q, m = _growth_case(monkeypatch)
    q.loc[q.index[-5], "ni_parent"] = -1
    r = eps_nowcast.nowcast(q, m)
    assert (r["eps_future"], r["future_quarters"], r["future_status"]) == (None, [], "not_growth")


def test_未來四季_乘數封頂130(monkeypatch):
    q, m = _growth_case(monkeypatch, multiple=10)
    r = eps_nowcast.nowcast(q, m)
    for j, x in enumerate(r["future_quarters"][2:], 1):
        assert x["rev"] == pytest.approx(4000 * 1.69 ** (j/4))
        assert x["rev"] <= 4000 * 1.30 * (1 + 1e-12)


def test_未來四季_前瞻fallback時no_data(monkeypatch):
    q, m = _growth_case(monkeypatch, end="2026-12-01")
    r = eps_nowcast.nowcast(q, m)
    assert eps_nowcast.FALLBACK_FLAG in r["flags"]
    assert (r["eps_future"], r["future_quarters"], r["future_status"]) == (None, [], "no_data")


def test_eps_f4欄位已移除():
    r = eps_nowcast.nowcast(_quarterly(), _monthly())
    assert not {"eps_f4", "f4_quarters", "f4_far_quarters"} & r.keys()


def test_未來四季_營業利益未年增不給預測(monkeypatch):
    q, m = _growth_case(monkeypatch)
    q.loc[q.index[-1], "op_income"] = q.loc[q.index[-5], "op_income"]       # 淨利年增但營業利益持平（靠業外）
    r = eps_nowcast.nowcast(q, m)
    assert r["future_status"] == "not_growth" and r["eps_future"] is None and r["future_quarters"] == []
