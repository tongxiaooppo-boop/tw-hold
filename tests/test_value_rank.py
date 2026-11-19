import numpy as np
import pandas as pd

from screener import value_rank as vr


def _q(eps=None, rev=None):
    n = len(eps if eps is not None else rev)
    return pd.DataFrame({
        "period_end": pd.date_range("2018-03-31", periods=n, freq="QE"),
        "eps": eps if eps is not None else [1.0] * n,
        "revenue": rev if rev is not None else [100.0] * n,
    })


def test_eps_ratio_基本():
    assert vr.eps_ratio(_q(eps=[1.0] * 12 + [3.0] * 4)) == 3.0


def test_eps_ratio_不足16季():
    assert vr.eps_ratio(_q(eps=[1.0] * 15)) is None


def test_eps_ratio_前三年平均非正():
    assert vr.eps_ratio(_q(eps=[0.0] * 12 + [3.0] * 4)) is None


def test_revenue_growth_基本():
    assert vr.revenue_growth(_q(rev=[100.0] * 4 + [150.0] * 4)) == 0.5


def test_revenue_growth_有缺():
    assert vr.revenue_growth(_q(rev=[100.0] * 7 + [np.nan])) is None


def test_category_高成長優先():
    assert vr.category("growth", 5.0, 0.5)[0] == "高成長"


def test_category_循環分類不進高成長():
    assert vr.category("cyclical", None, 0.9)[0] == "循環"


def test_category_eps暴增營收沒跟():
    g, why = vr.category("normal", 3.0, 0.1)
    assert g == "循環" and "3.0 倍" in why


def test_category_一般():
    assert vr.category("normal", 1.2, 0.1) == ("一般", "")


def _row(t, price, fair, group="一般"):
    return {"ticker": t, "group": group, "price": price, "fair": fair}


def test_rank_只留合理價以下且排序():
    rows = [_row("a", 50, 100), _row("b", 110, 100), _row("c", 80, 100)]
    got = vr.rank(rows)["一般"]
    assert [r["ticker"] for r in got] == ["a", "c"]
    assert [round(r["gap"], 2) for r in got] == [-0.5, -0.2]


def test_rank_取前20與從缺():
    rows = [_row(f"t{i:02d}", 50 + i, 100) for i in range(25)]
    got = vr.rank(rows)
    assert len(got["一般"]) == 20 and got["循環"] == [] and got["高成長"] == []


def test_rank_缺價跳過():
    rows = [_row("a", 50, None), _row("b", float("nan"), 100), _row("c", 50, 100)]
    assert [r["ticker"] for r in vr.rank(rows)["一般"]] == ["c"]
