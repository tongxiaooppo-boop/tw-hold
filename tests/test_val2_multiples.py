"""估值 2.0 自建倍數（upgrade_guide §4、§5-4、§10）。預期值由 Opus 定，實作者不得改。

合成資料（沿用 test_val2_eps_windows 的 make_q／make_monthly）：每季 EPS 0.96、歸母淨利 96（股數 100）、
歸母權益 1000 → 近 4 季／前瞻 EPS 3.84、每股淨值 10。股價 38.4 → PE 10、PB 3.84。
"""
import math

import numpy as np
import pandas as pd
import pytest

from reference import corporate_actions as ca
from screener import multiples_self as ms
from test_val2_eps_windows import make_monthly, make_q

T = pd.Timestamp
ASOF = T("2026-11-02")


def q_fixture(**over) -> pd.DataFrame:
    q = make_q("2026Q2", n=30, **over)
    q["equity_parent"] = 1000.0
    q["ticker"] = "9999"
    return q


def daily(price, start="2021-01-01", end="2026-10-30", ticker="9999.TW") -> pd.DataFrame:
    """price：常數或 f(date)->float。"""
    dates = pd.bdate_range(start, end)
    close = [price(d) if callable(price) else price for d in dates]
    return pd.DataFrame({"ticker": ticker, "date": dates, "close": close})


def history(price, q=None, per=None, events=None, monkeypatch=None):
    monkeypatch.setattr(ca, "SPLITS", events or {})
    monkeypatch.setattr(ca, "EVENTS_OK", True)
    closes = ms.monthly_closes(daily(price), ASOF)
    return ms.build_history("9999", q if q is not None else q_fixture(),
                            make_monthly("2026-09", first="2019-01"), closes, per)


def row(mh, month):
    return mh.loc[mh["month"] == month].iloc[0]


# ── 月底收盤 ──────────────────────────────────────────────

def test_完整月份判斷():
    assert ms.last_complete_month(T("2026-11-02")) == pd.Period("2026-10", "M")
    assert ms.last_complete_month(T("2026-10-31")) == pd.Period("2026-10", "M")
    assert ms.last_complete_month(T("2026-10-30")) == pd.Period("2026-09", "M")


def test_月底收盤_當月未結束不算_月底缺值保留():
    raw = pd.DataFrame({
        "ticker": ["9999.TW"] * 4 + ["8888.TWO"],
        "date": [T("2026-09-29"), T("2026-09-30"), T("2026-10-30"), T("2026-11-02"), T("2026-10-29")],
        "close": [10.0, np.nan, 11.0, 12.0, 5.0],
    })
    out = ms.monthly_closes(raw, ASOF)
    assert list(out.columns) == ["ticker", "month", "date", "close"]
    assert out[["ticker", "month"]].values.tolist() == [["8888", "2026-10"], ["9999", "2026-09"], ["9999", "2026-10"]]
    sep = out[(out.ticker == "9999") & (out.month == "2026-09")].iloc[0]
    assert sep["date"] == T("2026-09-30") and math.isnan(sep["close"])   # T-5：不往前找 9/29
    assert ms.monthly_closes(raw, T("2026-10-30"))["month"].max() == "2026-09"


# ── build_history ────────────────────────────────────────

def test_基本序列_欄位與數值(monkeypatch):
    mh = history(38.4, monkeypatch=monkeypatch)
    assert tuple(mh.columns) == ms.HIST_COLUMNS
    assert len(mh) == 70 and mh["month"].iloc[0] == "2021-01" and mh["month"].iloc[-1] == "2026-10"
    r = row(mh, "2026-10")
    assert r["eps_ttm"] == pytest.approx(3.84) and r["bvps"] == pytest.approx(10.0)
    assert (r["pe"], r["pb"]) == pytest.approx((10.0, 3.84))
    assert bool(r["valid_pe"]) and bool(r["valid_pb"]) and not bool(r["excluded"])
    assert mh["valid_pe"].all() and mh["valid_pb"].all()
    assert math.isnan(r["pe_exchange"])


def test_自建PE_純分割連續(monkeypatch):
    ev = {"9999": [{"date": "2024-06-17", "type": "split", "m": 4, "pf": 4}]}
    mh = history(lambda d: 153.6 if d < T("2024-06-17") else 38.4, events=ev, monkeypatch=monkeypatch)
    may, jun = row(mh, "2024-05"), row(mh, "2024-06")
    assert may["price_adj"] == pytest.approx(38.4)
    assert abs(jun["pe"] / may["pe"] - 1) < 0.05 and abs(jun["pb"] / may["pb"] - 1) < 0.05
    assert mh["pe"].to_numpy() == pytest.approx(np.full(len(mh), 10.0))


def test_自建PE_不含股利還原(monkeypatch):
    # 高殖利率股：沒有股數事件時 price_adj 就是原始收盤，自建 PE 與交易所 PER 一致
    px = lambda d: 38.4 + (d.month % 3) * 1.2
    monkeypatch.setattr(ca, "SPLITS", {})
    monkeypatch.setattr(ca, "EVENTS_OK", True)
    closes = ms.monthly_closes(daily(px), ASOF)
    per = pd.DataFrame({"ticker": "9999", "date": closes["date"], "per": closes["close"] / 3.84})
    per = pd.concat([per, pd.DataFrame({"ticker": ["9999"], "date": [T("2026-10-15")], "per": [99.0]})])
    mh = ms.build_history("9999", q_fixture(), make_monthly("2026-09", first="2019-01"), closes, per)
    assert mh["price_adj"].to_numpy() == pytest.approx(closes["close"].to_numpy())
    diff = (mh["pe"] / mh["pe_exchange"] - 1).abs().median()
    assert diff < 0.02
    assert row(mh, "2026-10")["pe_exchange"] == pytest.approx(closes["close"].iloc[-1] / 3.84)


def test_現金減資區間剔除(monkeypatch):
    ev = {"9999": [{"date": "2025-05-20", "type": "cap_reduction", "m": None, "pf": 0.8}]}
    mh = history(38.4, events=ev, monkeypatch=monkeypatch)
    for m in ("2025-05", "2025-06", "2025-07"):
        r = row(mh, m)
        assert bool(r["excluded"]) and not bool(r["valid_pe"]) and not bool(r["valid_pb"])
        assert math.isnan(r["pe"]) and math.isnan(r["pb"])
    for m in ("2025-04", "2025-08"):
        r = row(mh, m)
        assert not bool(r["excluded"]) and bool(r["valid_pe"])
    assert row(mh, "2025-06")["price_adj"] == pytest.approx(38.4)    # m=None 不乘


def test_有效月數_微利月無效(monkeypatch):
    q = q_fixture()
    q["eps"], q["ni_parent"] = 0.01, 1.0                            # 近 4 季 0.04 < EPS_MIN
    mh = history(0.3, q=q, monkeypatch=monkeypatch)                  # PE 7.5 也不算
    assert mh["eps_ttm"].to_numpy() == pytest.approx(np.full(len(mh), 0.04))
    assert not mh["valid_pe"].any() and mh["pe"].isna().all()
    assert mh["bvps"].isna().all() and not mh["valid_pb"].any()      # 股數推不出 → 無每股淨值


def test_PE超過上限無效(monkeypatch):
    mh = history(400.0, monkeypatch=monkeypatch)                     # PE 104 > 100
    assert not mh["valid_pe"].any() and mh["valid_pb"].all()


def test_每股淨值_股數推不出往前找(monkeypatch):
    # 2026Q2 EPS 缺 → 用 2026Q1 的股數 100；權益仍用 2026Q2 的 2000
    q = q_fixture(**{"2026Q2": dict(eps=np.nan)})
    q.loc[q["period_end"] == T("2026-06-30"), "equity_parent"] = 2000.0
    mh = history(38.4, q=q, monkeypatch=monkeypatch)
    assert row(mh, "2026-10")["bvps"] == pytest.approx(20.0)
    assert row(mh, "2026-07")["bvps"] == pytest.approx(10.0)         # 7 月底 Q2 尚未可見（8/14）


def test_交易所PER缺值或零為NaN(monkeypatch):
    monkeypatch.setattr(ca, "SPLITS", {})
    monkeypatch.setattr(ca, "EVENTS_OK", True)
    closes = ms.monthly_closes(daily(38.4), ASOF)
    per = pd.DataFrame({"ticker": "9999", "date": closes["date"], "per": 0.0})
    mh = ms.build_history("9999", q_fixture(), make_monthly("2026-09", first="2019-01"), closes, per)
    assert mh["pe_exchange"].isna().all()


def test_事件表讀不到要報錯(monkeypatch):
    from reference import share_basis as sb
    monkeypatch.setattr(ca, "EVENTS_OK", False)
    closes = pd.DataFrame({"ticker": ["9999"], "month": ["2026-10"], "date": [T("2026-10-30")], "close": [38.4]})
    with pytest.raises(sb.EventsUnavailable):
        ms.build_history("9999", q_fixture(), make_monthly("2026-09", first="2019-01"), closes, None)


# ── 倍數窗 ───────────────────────────────────────────────

def mh_fixture() -> pd.DataFrame:
    months = pd.period_range("2021-01", "2026-10", freq="M")        # 70 個月，pe＝1..70
    n = len(months)
    return pd.DataFrame({
        "month": months.astype(str), "pe": np.arange(1, n + 1, dtype=float),
        "valid_pe": True, "eps_ttm": 1.0, "eps_fwd": 1.0,
        "pe_fwd": np.nan, "valid_pe_fwd": False, "pb": 2.0, "valid_pb": True,
    })


def test_倍數窗_估值日錨定與分位():
    s = ms.window_stats(mh_fixture(), "normal", "pe", ASOF, cap=30.0)
    assert (s["start"], s["end"], s["n_valid"], s["n_loss"]) == ("2021-11", "2026-10", 60, 0)
    assert s["raw_mults"] == pytest.approx((22.8, 40.5, 58.2))     # 11..70 的線性內插分位
    assert s["mults"] == pytest.approx((22.8, 30.0, 30.0)) and s["capped"] is True
    s2 = ms.window_stats(mh_fixture(), "normal", "pe", T("2026-10-15"), cap=None)
    assert (s2["start"], s2["end"], s2["n_valid"]) == ("2021-10", "2026-09", 60)
    assert s2["capped"] is False and s2["mults"] == s2["raw_mults"]


def test_倍數窗_缺月與虧損月():
    mh = mh_fixture()
    loss = mh["month"].isin(["2026-01", "2026-02", "2026-03"])
    mh.loc[loss, ["eps_ttm", "valid_pe"]] = [-1.0, False]
    mh = mh[mh["month"] != "2025-06"]                                 # 沒價格的月份不補列
    s = ms.window_stats(mh, "growth", "pe", ASOF, cap=50.0)
    assert (s["start"], s["end"], s["n_valid"], s["n_loss"]) == ("2023-11", "2026-10", 32, 3)


def test_倍數窗_PB全歷史與全無效():
    s = ms.window_stats(mh_fixture(), "pb", "pb", ASOF, cap=None)
    assert (s["start"], s["n_valid"]) == ("2021-01", 70) and s["mults"] == pytest.approx((2.0, 2.0, 2.0))
    e = ms.window_stats(mh_fixture(), "normal", "pe_fwd", ASOF, cap=30.0)
    assert e["n_valid"] == 0 and e["raw_mults"] == (None, None, None) and e["capped"] is False


def test_AB緩衝():
    assert ms.is_valid_tier_a(34, "normal", was_a=True)
    assert ms.is_valid_tier_a(33, "normal", was_a=True)
    assert not ms.is_valid_tier_a(32, "normal", was_a=True)
    assert not ms.is_valid_tier_a(35, "normal", was_a=False)
    assert ms.is_valid_tier_a(36, "normal", was_a=False)
    assert ms.is_valid_tier_a(36, "cyclical", was_a=False)
    assert ms.is_valid_tier_a(27, "growth", was_a=True) and not ms.is_valid_tier_a(26, "growth", was_a=True)
    assert ms.is_valid_tier_a(30, "growth", was_a=False) and not ms.is_valid_tier_a(29, "growth", was_a=False)
    assert ms.is_valid_tier_a(54, "pb", was_a=True) and not ms.is_valid_tier_a(59, "pb", was_a=False)
    with pytest.raises(KeyError):
        ms.is_valid_tier_a(40, "special", was_a=False)


# ── 上修判斷 ─────────────────────────────────────────────

W1, W2 = "2026Q1-2026Q4", "2026Q2-2027Q1"


def rev(*rows) -> pd.DataFrame:
    """rows＝(window, eps_fwd, event)。"""
    months = pd.period_range("2026-01", periods=len(rows), freq="M").astype(str)
    return pd.DataFrame([dict(month=m, window=w, eps_fwd=e, event=ev) for m, (w, e, ev) in zip(months, rows)])


def test_上修事件分類():
    a = {"window": W1, "actual_qs": ("2026Q1", "2026Q2")}
    assert ms.revision_event(None, a) == "roll"
    assert ms.revision_event(a, {"window": W2, "actual_qs": ("2026Q2",)}) == "roll"
    assert ms.revision_event(a, {"window": W1, "actual_qs": ("2026Q1", "2026Q2", "2026Q3")}) == "report"
    assert ms.revision_event(a, dict(a)) == "normal"
    assert ms.revision_event(a, {"window": None, "actual_qs": ()}) == "roll"


def test_上修_連續兩次():
    r = ms.revision_streak(rev((W1, 10.0, "roll"), (W1, 10.3, "normal"), (W1, 10.6, "normal")))
    assert r["streak"] == 2 and r["direction"] == "up"
    assert r["last_pct"] == pytest.approx(10.6 / 10.3 - 1)


def test_上修_換季月不比較():
    r = ms.revision_streak(rev((W1, 10.0, "roll"), (W1, 10.3, "normal"), (W1, 10.6, "normal"),
                               (W2, 8.0, "roll")))
    assert r["streak"] == 2 and r["direction"] == "up" and r["last_pct"] is None
    r2 = ms.revision_streak(rev((W1, 10.0, "roll"), (W1, 10.3, "normal"), (W1, 12.0, "report"),
                                (W1, 12.5, "normal")))
    assert r2["streak"] == 2 and r2["direction"] == "up"


def test_上修_同窗口未達2趴():
    r = ms.revision_streak(rev((W1, 10.0, "roll"), (W1, 10.15, "normal")))
    assert r["streak"] == 0 and r["direction"] is None and r["last_pct"] == pytest.approx(0.015)
    r2 = ms.revision_streak(rev((W1, 10.0, "roll"), (W1, 10.25, "normal")))
    assert r2["streak"] == 1 and r2["direction"] == "up"


def test_上修_反向與持平():
    r = ms.revision_streak(rev((W1, 10.0, "roll"), (W1, 10.3, "normal"), (W1, 10.6, "normal"),
                               (W1, 10.0, "normal")))
    assert r["streak"] == 1 and r["direction"] == "down"
    r2 = ms.revision_streak(rev((W1, 10.0, "roll"), (W1, 10.3, "normal"), (W1, 10.35, "normal")))
    assert r2["streak"] == 0 and r2["direction"] is None
    r3 = ms.revision_streak(rev((W1, 10.0, "roll"), (W1, np.nan, "normal")))
    assert r3 == {"last_pct": None, "streak": 0, "direction": None}
    assert ms.revision_streak(rev((W1, 10.0, "roll"))) == {"last_pct": None, "streak": 0, "direction": None}


def test_每股淨值_歸母淨利缺改用合併淨利(monkeypatch):
    """P3（Opus 2026-11-02）：保險、部分營建歸母淨利整欄缺 → 股數用 net_income ÷ eps。"""
    q = q_fixture()
    q["ni_parent"] = q["net_income"]
    r = row(history(38.4, q=q, monkeypatch=monkeypatch), "2026-10")
    assert r["bvps"] == pytest.approx(10.0) and bool(r["valid_pb"])
