"""估值卡「近 5 年 EPS」（使用者 2026-11-21）：每年 4/1 換成去年＋往前 4 年；只顯示不進價格。"""
import pandas as pd
import pytest

from screener import val_card as vc
from app import val_view as vv


def _q(start_year: int, end_year: int, eps: float = 1.0, drop: tuple = ()) -> pd.DataFrame:
    ends = pd.date_range(f"{start_year}-03-31", f"{end_year}-12-31", freq="QE")
    rows = [dict(period_end=d, eps=eps * (d.year - start_year + 1), revenue=100.0) for d in ends
            if (d.year, d.quarter) not in drop]
    return pd.DataFrame(rows)


@pytest.mark.parametrize("asof, last", [("2027-03-31", 2025), ("2027-04-01", 2026), ("2026-11-22", 2025),
                                        ("2026-01-05", 2024)])
def test_4月1日換年(asof, last):
    assert vc.eps_last_year(pd.Timestamp(asof)) == last


def test_五年合計與平均():
    r = vc.eps_years(_q(2019, 2026), pd.Timestamp("2026-11-22"))
    assert [y["year"] for y in r["years"]] == [2021, 2022, 2023, 2024, 2025]
    # 2021 是第 3 年 → 每季 3、全年 12；…2025 → 7×4＝28
    assert [y["eps"] for y in r["years"]] == [12.0, 16.0, 20.0, 24.0, 28.0]
    assert r["avg"] == pytest.approx(20.0) and r["n_used"] == 5 and (r["first"], r["last"]) == (2021, 2025)


def test_今年未滿四季不算():
    r = vc.eps_years(_q(2019, 2026, drop=((2026, 4),)), pd.Timestamp("2027-03-31"))
    assert r["last"] == 2025


def test_缺季那年留空_平均只算有值年度():
    r = vc.eps_years(_q(2019, 2025, drop=((2023, 2),)), pd.Timestamp("2026-11-22"))
    assert [y["eps"] for y in r["years"]][2] is None
    assert r["n_used"] == 4 and r["avg"] == pytest.approx((12 + 16 + 24 + 28) / 4)


def test_新股不滿五年():
    r = vc.eps_years(_q(2023, 2025), pd.Timestamp("2026-11-22"))
    assert [y["eps"] for y in r["years"]][:2] == [None, None] and r["n_used"] == 3


def test_沒有任何完整年度回None():
    assert vc.eps_years(_q(2026, 2026), pd.Timestamp("2026-11-22")) is None
    assert vc.eps_years(pd.DataFrame(), pd.Timestamp("2026-11-22")) is None


def _card(ey):
    return dict(ok=True, tier="D", eps=dict(ttm={}, fwd={}), growth=[], eps_years=ey, revision={})


def test_畫面_五年():
    v = vv.card_view(_card(vc.eps_years(_q(2019, 2026), pd.Timestamp("2026-11-22"))), "1234 測試", None)
    t = v.eps.years_table
    assert t.kind == "strip" and t.title == "近 5 年 EPS（元）"
    assert t.headers == ("21", "22", "23", "24", "25", "平均")
    assert t.rows == ((vv.fmt_eps(12.0), vv.fmt_eps(16.0), vv.fmt_eps(20.0), vv.fmt_eps(24.0),
                       vv.fmt_eps(28.0), vv.fmt_eps(20.0)),)
    assert all("平均 EPS" not in k[0] for k in v.eps.kv)   # 平均只出現在表的最後一格


def test_畫面_不滿五年標實際年數():
    v = vv.card_view(_card(vc.eps_years(_q(2023, 2025), pd.Timestamp("2026-11-22"))), "1234 測試", None)
    t = v.eps.years_table
    assert t.headers[-1] == "3 年平均" and t.rows[0][0] == vv.fmt_eps(None)


def test_舊卡沒有這欄不出錯():
    card = _card(None)
    del card["eps_years"]
    v = vv.card_view(card, "1234 測試", None)
    assert v.eps.years_table is None and all("平均 EPS" not in k[0] for k in v.eps.kv)


# ── 事件標註＋還原／實際切換（使用者 2026-11-21）──────────────────

@pytest.mark.parametrize("e, label", [
    (dict(type="ex_both", m=1.07), ("配股", "+7%")), (dict(type="ex_rights", m=1.034), ("配股", "+3.4%")),
    (dict(type="cap_reduction", m=0.8), ("減資", "−20%")), (dict(type="par_change", m=4), ("分割", "1拆4")),
    (dict(type="split", m=7), ("分割", "1拆7")), (dict(type="cap_reduction", m=None, pf=0.99), ("現金減資", "不還原")),
    (dict(type="ex_both", m=None), None)])
def test_事件短標(e, label):
    assert vc.event_label(dict(e, date="2024-08-01")) == label


def _with_raw(q, factor=1.1):
    q = q.copy()
    q["eps_raw"] = q["eps"] * factor
    return q


def test_事件落在年度與之後(monkeypatch):
    monkeypatch.setitem(vc.ca.SPLITS, "9999", [
        dict(date="2022-08-01", type="ex_both", m=1.05), dict(date="2022-09-01", type="cap_reduction", m=0.9),
        dict(date="2026-08-04", type="ex_both", m=1.07), dict(date="2027-01-01", type="ex_both", m=1.1),
        dict(date="2015-01-01", type="ex_both", m=1.2)])
    r = vc.eps_years(_q(2019, 2026), pd.Timestamp("2026-11-22"), "9999")
    assert [y["event"] for y in r["years"]] == [None, "配股\n+5%\n減資\n−10%", None, None, None]
    assert r["after"] == "26/08 配股+7%"   # asof 之後的 2027 事件不列、窗口前的 2015 不列


def test_實際值與平均():
    r = vc.eps_years(_with_raw(_q(2019, 2026)), pd.Timestamp("2026-11-22"))
    assert [y["eps_raw"] for y in r["years"]] == pytest.approx([13.2, 17.6, 22.0, 26.4, 30.8])
    assert r["avg_raw"] == pytest.approx(22.0)
    assert vc.eps_years(_q(2019, 2026), pd.Timestamp("2026-11-22"))["avg_raw"] is None   # 沒 eps_raw 欄


def test_畫面_切換兩張表與註記(monkeypatch):
    monkeypatch.setitem(vc.ca.SPLITS, "9999", [dict(date="2024-08-01", type="ex_both", m=1.1),
                                               dict(date="2026-08-04", type="ex_both", m=1.07)])
    v = vv.card_view(_card(vc.eps_years(_with_raw(_q(2019, 2026)), pd.Timestamp("2026-11-22"), "9999")),
                     "9999 測試", None)
    adj, raw = v.eps.years_table, v.eps.years_table_raw
    assert adj.headers == raw.headers and adj.rows[1] == raw.rows[1] == ("", "", "", "配股\n+10%", "", "")
    assert raw.rows[0][-1] == vv.fmt_eps(22.0) and adj.rows[0][-1] == vv.fmt_eps(20.0)
    assert v.eps.years_note == "舊年度已按現在股數換算（只換算配股、減資、分割）；之後：26/08 配股+7%，已計入"
    assert v.eps.years_note_raw == "當年公布值（同財經網站），配股前後不能直接比；之後：26/08 配股+7%"


def test_現金減資標不還原且在之後清單(monkeypatch):
    monkeypatch.setitem(vc.ca.SPLITS, "9999", [dict(date="2023-10-01", type="cap_reduction", m=None, pf=0.9),
                                               dict(date="2026-09-01", type="cap_reduction", m=None, pf=0.9)])
    r = vc.eps_years(_q(2019, 2026), pd.Timestamp("2026-11-22"), "9999")
    assert r["years"][2]["event"] == "現金減資\n不還原" and r["after"] == "26/09 現金減資（不還原）"


def test_沒有事件就沒有第二列與註記():
    v = vv.card_view(_card(vc.eps_years(_with_raw(_q(2019, 2026)), pd.Timestamp("2026-11-22"), "0000")),
                     "0000 測試", None)
    assert len(v.eps.years_table.rows) == 1 and v.eps.years_note is None


def test_沒有原始值不給實際表():
    v = vv.card_view(_card(vc.eps_years(_q(2019, 2026), pd.Timestamp("2026-11-22"))), "1234 測試", None)
    assert v.eps.years_table_raw is None


def test_val_inputs保留原始EPS():
    import inspect
    from app import val_inputs
    src = inspect.getsource(val_inputs.quarterly)
    assert 'q["eps_raw"] = q["eps"]' in src and src.index("eps_raw") < src.index("adjust_eps(q)")
