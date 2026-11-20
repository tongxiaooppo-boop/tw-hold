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


def _m(start, vals):
    return pd.DataFrame({"month": [str(p) for p in pd.period_range(start, periods=len(vals), freq="M")],
                         "revenue": vals})


def _base():
    return _m("2024-11", [100.0] * 12 + [110.0] * 12)


def test_rev_yoy_基本():
    y3, y12, last = vr.rev_yoy(_base())
    assert abs(y3 - 0.10) < 1e-9 and abs(y12 - 0.10) < 1e-9 and last == "2026-10"


def test_rev_yoy_只夠15月():
    y3, y12, last = vr.rev_yoy(_m("2025-08", [100.0] * 3 + [120.0] * 12))
    assert abs(y3 - 0.20) < 1e-9 and y12 is None and last == "2026-10"


def test_rev_yoy_缺去年同月():
    m = _base()
    m = m[m["month"] != "2025-09"]
    assert vr.rev_yoy(m) == (None, None, "2026-10")


def test_rev_yoy_分母非正():
    assert vr.rev_yoy(_m("2024-11", [0.0] * 12 + [110.0] * 12)) == (None, None, "2026-10")


def test_rev_yoy_空表():
    assert vr.rev_yoy(pd.DataFrame()) == (None, None, None)


def test_rev_flag_衰退():
    assert vr.rev_flag("一般", -0.2, 0.01) == "近三月營收比去年少 20%，過去獲利可能撐不住"


def test_rev_flag_衰退不到1pct():
    assert vr.rev_flag("循環", -0.003, None) == "近三月營收比去年少不到 1%，過去獲利可能撐不住"


def test_rev_flag_降溫():
    assert vr.rev_flag("高成長", 0.51, 0.73) == "營收仍在增加，但成長放慢（近12月年增 73% → 近三月 51%），合理價要再確認"


def test_rev_flag_降溫只限高成長():
    assert vr.rev_flag("一般", 0.51, 0.73) == ""


def test_rev_flag_降溫未達門檻():
    assert vr.rev_flag("高成長", 0.60, 0.73) == ""


def test_rev_flag_無資料():
    assert vr.rev_flag("高成長", None, 0.5) == ""


# ---- 月營收欄位（2026-11-20）----
def _mrev(n=24, end="2026-10", over=None, scale=1e9, as_ts=False):
    months = pd.period_range(end=end, periods=n, freq="M")
    vals = {p: 100 * scale for p in months}
    for k, v in (over or {}).items():
        vals[pd.Period(k, "M")] = v
    idx = [p.to_timestamp() if as_ts else str(p) for p in months]
    return pd.DataFrame({"month": idx, "revenue": [vals[p] for p in months]})


def test_rev_month_info_單月年增():
    d = vr.rev_month_info(_mrev(over={"2026-10": 125e9}), "2026-10")
    assert abs(d["rev_m_yoy"] - 0.25) < 1e-9 and d["rev_low_base"] is False


def test_rev_month_info_低基期():
    d = vr.rev_month_info(_mrev(over={"2025-10": 5e7, "2026-10": 1e8}), "2026-10")
    assert d["rev_low_base"] is True


def test_rev_month_info_Timestamp與字串同結果():
    o = {"2026-10": 125e9}
    assert (vr.rev_month_info(_mrev(over=o), "2026-10")
            == vr.rev_month_info(_mrev(over=o, as_ts=True), "2026-10"))


def test_rev_month_info_month_None():
    assert vr.rev_month_info(_mrev(), None) == {
        "rev_m_yoy": None, "rev_streak": 0, "rev_record": False, "rev_low_base": False}


def test_rev_progress():
    rows = [{"rev_month": m} for m in ["2026-10", "2026-10", "2026-09", None]]
    assert vr.rev_progress(rows, "2026-11-20") == {"month": "2026-10", "published": 2, "total": 4}


_FULL = {"rev_month": "2026-10", "rev_m_yoy": 0.25, "rev3m_yoy": 0.18, "rev_record": True,
         "rev_streak": 7, "rev_low_base": False}


def test_rev_text_完整():
    assert vr.rev_text(_FULL) == "10月 +25%｜近3月 +18%・創新高・連 7 月成長"


def test_rev_text_低基期與短連續():
    r = {"rev_month": "2026-10", "rev_m_yoy": None, "rev3m_yoy": None, "rev_record": False,
         "rev_streak": 2, "rev_low_base": True}
    assert vr.rev_text(r) == "10月 低基期"


def test_rev_text_接近零():
    assert "±0%" in vr.rev_text({**_FULL, "rev_m_yoy": 0.004})
    assert "-1%" in vr.rev_text({**_FULL, "rev_m_yoy": -0.006})


def test_rev_month_info_去年同月缺():
    m = _mrev(n=24)
    m = m[m["month"] != "2025-10"]
    d = vr.rev_month_info(m, "2026-10")
    assert d["rev_m_yoy"] is None and d["rev_low_base"] is False
    assert vr.rev_text({"rev_month": "2026-10", **d}).startswith("10月 —")


def test_rev_month_info_去年同月為零():
    d = vr.rev_month_info(_mrev(over={"2025-10": 0}), "2026-10")
    assert d["rev_m_yoy"] is None and d["rev_low_base"] is False


def test_rev_month_info_歷史太短不稱創新高():
    assert vr.rev_month_info(_mrev(n=20, over={"2026-10": 200e9}), "2026-10")["rev_record"] is False
    assert vr.rev_month_info(_mrev(n=40, over={"2026-10": 200e9}), "2026-10")["rev_record"] is True


def test_rev_month_info_目標月缺():
    m = _mrev(n=24, end="2026-09")
    d = vr.rev_month_info(m, "2026-10")
    assert d["rev_m_yoy"] is None and d["rev_streak"] == 0 and d["rev_record"] is False
