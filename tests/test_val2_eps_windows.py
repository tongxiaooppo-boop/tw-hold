"""估值 2.0 EPS 窗口（upgrade_guide §3、§10）。預期值由 Opus 定，實作者不得改。

合成資料：每季營收 1000、毛利 300、營業利益 100、稅前 120、淨利 96、歸母 96、EPS 0.96（股數 100）。
→ 試算季（營收 1000）：毛利率 0.30、費用率 0.20、營業利益 100、業外中位數 20、稅前 120、
  稅率 0.20、少數股權 0 → 歸母 96 → EPS 0.96。
"""
import math

import pandas as pd
import pytest

from screener import eps_windows as ew


def make_q(last: str, n: int = 12, drop: tuple[str, ...] = (), **over) -> pd.DataFrame:
    """n 季連續財報，末季＝last；over＝{"2026Q2": {"eps": 0}} 覆寫個別季。"""
    end = pd.Period(last, "Q")
    rows = []
    for i in range(n - 1, -1, -1):
        p = end - i
        if str(p) in drop:
            continue
        r = dict(period_end=p.end_time.normalize(), revenue=1000.0, gross_profit=300.0, op_income=100.0,
                 pretax_income=120.0, net_income=96.0, ni_parent=96.0, eps=0.96)
        r.update(over.get(str(p), {}))
        rows.append(r)
    return pd.DataFrame(rows)


def make_monthly(last: str, first: str = "2022-01", value: float = 1000.0 / 3, **over) -> pd.Series:
    idx = pd.period_range(first, last, freq="M")
    s = pd.Series(value, index=idx.to_timestamp())
    for k, v in over.items():
        s[pd.Timestamp(k + "-01")] = v
    return s


def qs(w: ew.EpsWindow) -> list[tuple[str, str]]:
    return [(r.q, r.kind) for r in w.quarters]


def test_近4季_營收到齊算入試算季():
    w = ew.ttm_window(make_q("2026Q2"), make_monthly("2026-09"), pd.Timestamp("2026-10-15"))
    assert w.ok and w.status == "ok" and w.n_est == 1
    assert qs(w) == [("2025Q4", "actual"), ("2026Q1", "actual"), ("2026Q2", "actual"), ("2026Q3", "est")]
    est = w.quarters[-1]
    assert est.months_known == 3 and est.fill_method is None and est.params_from == "2026Q2"
    assert math.isclose(est.eps, 0.96, rel_tol=1e-9)
    assert math.isclose(w.eps, 0.96 * 4, rel_tol=1e-9)
    d = w.details[-1]
    assert (d.gm_last, d.opex_last, d.nonop, d.tax, d.minority, d.shares) == pytest.approx(
        (0.30, 0.20, 20.0, 0.20, 0.0, 100.0))


def test_近4季_營收未齊不算入():
    w = ew.ttm_window(make_q("2026Q2"), make_monthly("2026-08"), pd.Timestamp("2026-10-15"))
    assert w.ok and w.n_est == 0
    assert qs(w)[-1] == ("2026Q2", "actual") and len(w.quarters) == 4


def test_前瞻_新季0個月等於近4季():
    q, m, asof = make_q("2026Q2"), make_monthly("2026-09"), pd.Timestamp("2026-10-20")
    t = ew.ttm_window(q, m, asof)
    f = ew.fwd_window(q, m, asof, base=t)
    assert f.quarters == t.quarters and f.status == t.status and f.n_est == t.n_est


def test_前瞻_年報期兩個試算季():
    q, m, asof = make_q("2025Q3"), make_monthly("2026-01"), pd.Timestamp("2026-02-15")
    t = ew.ttm_window(q, m, asof)
    assert qs(t) == [("2025Q1", "actual"), ("2025Q2", "actual"), ("2025Q3", "actual"), ("2025Q4", "est")]
    f = ew.fwd_window(q, m, asof, base=t)
    assert qs(f) == [("2025Q2", "actual"), ("2025Q3", "actual"), ("2025Q4", "est"), ("2026Q1", "est")]
    assert f.n_est == 2


def test_缺月補值_Q1只有1月用3個月():
    q, m, asof = make_q("2025Q3"), make_monthly("2026-01"), pd.Timestamp("2026-02-15")
    f = ew.fwd_window(q, m, asof)
    last = f.quarters[-1]
    assert last.q == "2026Q1" and last.months_known == 1 and last.fill_method == "q1_3m"


def test_共用試算季同一物件():
    w = ew.windows(make_q("2025Q3"), make_monthly("2026-01"), pd.Timestamp("2026-02-15"))
    t4 = [d for d in w["ttm"].details if d.q == "2025Q4"][0]
    f4 = [d for d in w["fwd"].details if d.q == "2025Q4"][0]
    assert t4 is f4


def test_財報延遲():
    q, m, asof = make_q("2025Q3"), make_monthly("2026-03"), pd.Timestamp("2026-04-15")
    t = ew.ttm_window(q, m, asof)
    assert t.status == "report_late" and t.n_est == 0
    assert qs(t) == [("2024Q4", "actual"), ("2025Q1", "actual"), ("2025Q2", "actual"), ("2025Q3", "actual")]
    f = ew.fwd_window(q, m, asof, base=t)
    assert f.status == "report_late" and f.quarters == t.quarters


def test_斷季窗口不可用():
    q = make_q("2026Q2", drop=("2025Q4",))
    r = ew.reported_window(q, pd.Timestamp("2026-10-15"))
    assert not r.ok and r.status == "no_data"
    t = ew.ttm_window(q, make_monthly("2026-08"), pd.Timestamp("2026-10-15"))
    assert not t.ok


def test_缺月補值_累計年增():
    q = make_q("2026Q3")
    m = make_monthly("2026-10", **{"2025-10": 100.0, "2025-11": 100.0, "2025-12": 100.0, "2026-10": 120.0})
    f = ew.fwd_window(q, m, pd.Timestamp("2026-11-12"), live=True)
    assert f.quarters[-1].q == "2026Q4" and f.quarters[-1].fill_method == "yoy_q"
    months = f.details[-1].months
    assert months[0] == ("2026-10", 120.0, "actual")
    assert months[1][0] == "2026-11" and math.isclose(months[1][1], 120.0) and months[1][2] == "yoy_q"
    assert math.isclose(f.details[-1].revenue, 360.0)


def test_應公布未公布不試算():
    # 2026Q3：7、9 月有，8 月已過 9/10 仍缺 → 前瞻不可試算
    m = make_monthly("2026-09").drop(pd.Timestamp("2026-08-01"))
    q, asof = make_q("2026Q2"), pd.Timestamp("2026-10-15")
    t = ew.ttm_window(q, m, asof)
    assert t.n_est == 0 and qs(t)[-1] == ("2026Q2", "actual")
    f = ew.fwd_window(q, m, asof, base=t)
    assert not f.ok and f.status == "not_estimable"


def test_抵銷比過小不試算():
    over = {}
    for i, p in enumerate(pd.period_range("2024Q3", "2026Q2", freq="Q")):
        x = 10.0 if i % 2 else -9.0          # 末季（2026Q2）為 +10
        over[str(p)] = dict(pretax_income=x, net_income=x * 0.8, ni_parent=x * 0.8, eps=x * 0.8 / 100)
    q, m, asof = make_q("2026Q2", **over), make_monthly("2026-09"), pd.Timestamp("2026-10-15")
    t = ew.ttm_window(q, m, asof)
    assert t.ok and t.n_est == 0 and t.reason
    f = ew.fwd_window(q, m, asof, base=t)
    assert f.status == "not_estimable"


def test_股數推不出不試算():
    q = make_q("2026Q2", **{"2026Q2": dict(eps=0.0)})
    m, asof = make_monthly("2026-09"), pd.Timestamp("2026-10-15")
    t = ew.ttm_window(q, m, asof)
    assert t.n_est == 0
    assert ew.fwd_window(q, m, asof, base=t).status == "not_estimable"


def test_稅只課在賺錢的季():
    # 最新季營業利益 −200 → 試算稅前 = −200 + 20 < 0 → 稅率 0
    q = make_q("2026Q2", **{"2026Q2": dict(op_income=-200.0)})
    t = ew.ttm_window(q, make_monthly("2026-09"), pd.Timestamp("2026-10-15"))
    d = t.details[-1]
    assert d.tax == 0.0 and d.op < 0


def test_金融股不試算():
    q, m, asof = make_q("2026Q2"), make_monthly("2026-09"), pd.Timestamp("2026-10-15")
    t = ew.ttm_window(q, m, asof, financial=True)
    assert t.n_est == 0 and t.quarters == ew.reported_window(q, asof).quarters


def test_live_未到期財報也算已公布():
    # asof=8/1：2026Q2 法定期限 8/14 未到；live=False 不可見、live=True 有資料就可見
    q, m, asof = make_q("2026Q2"), make_monthly("2026-06"), pd.Timestamp("2026-08-01")
    assert ew.reported_window(q, asof).quarters[-1].q == "2026Q1"
    assert ew.reported_window(q, asof, live=True).quarters[-1].q == "2026Q2"


def test_重複季取最後一筆且不排序也可():
    q = make_q("2026Q2")
    dup = q.iloc[[-1]]
    q2 = pd.concat([dup.assign(eps=0.1), q.iloc[::-1], dup.assign(eps=1.5)])   # 輸入順序的最後一筆＝1.5
    r = ew.reported_window(q2, pd.Timestamp("2026-10-15"))
    assert r.ok and [x.q for x in r.quarters] == ["2025Q3", "2025Q4", "2026Q1", "2026Q2"]
    assert math.isclose(r.quarters[-1].eps, 1.5)
