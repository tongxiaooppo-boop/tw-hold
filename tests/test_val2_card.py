"""估值 2.0 估值卡引擎（upgrade_guide §5、§6、§10；P3）。預期值由 Opus 定，實作者不得改。

合成資料：每季營收 1000、毛利 300、營業利益 100、稅前 120、淨利／歸母 96、EPS 0.96（股數 100）、
歸母權益 1000（每股淨值 10）、股本 1000、總資產 2000、營業現金流 120。
asof＝2026-11-02、月營收到 2026-09 → 近 4 季＝2025Q4..2026Q2 實際＋2026Q3 試算（0.96），合計 3.84。
倍數序列 60 個月（2021-11～2026-10）PE 依序 8,10,12,14,16 循環 → P20/P50/P80＝9.6/12/14.4。
"""
import math

import numpy as np
import pandas as pd
import pytest

from reference import corporate_actions as ca
from screener import multiples_self as ms
from screener import val_card as vc
from test_val2_eps_windows import make_monthly, make_q

T = pd.Timestamp
ASOF = T("2026-11-02")
TTM = 3.84


@pytest.fixture(autouse=True)
def _events(monkeypatch):
    monkeypatch.setattr(ca, "SPLITS", {})
    monkeypatch.setattr(ca, "EVENTS_OK", True)


def Q(n=30, **over) -> pd.DataFrame:
    q = make_q("2026Q2", n=n, **over)
    for c, v in (("equity_parent", 1000.0), ("capital_stock", 1000.0), ("total_assets", 2000.0), ("ocf", 120.0)):
        q[c] = v
    q["ticker"] = "9999"
    return q


def REV(last="2026-09", **over) -> pd.DataFrame:
    s = make_monthly(last, first="2019-01", **over)
    return pd.DataFrame({"month": s.index.strftime("%Y-%m"), "revenue": s.values})


def PX(price=38.4) -> pd.DataFrame:
    return pd.DataFrame({"date": [T("2026-10-30")], "close": [price]})


def CLS(typ="normal", group="other", state=(), sub=(), **metrics) -> dict:
    return dict(ticker="9999", name="測試", industry="測試業", industry_group=group, type=typ,
                display_type=typ, state=list(state), subtags=list(sub), why=[], decided_at="2026-06-30",
                metrics=dict(metrics))


def MH(start="2021-11", end="2026-10", pe=(8, 10, 12, 14, 16), pe_fwd=None, pb=2.0,
       valid_until=None) -> pd.DataFrame:
    """pe／pe_fwd／pb：常數或循環序列；valid_until＝"YYYY-MM"（之後 valid_pe／valid_pe_fwd 為 False、值 NaN）。"""
    months = pd.period_range(start, end, freq="M")
    cyc = lambda v, i: v[i % len(v)] if isinstance(v, (tuple, list)) else v
    rows = []
    for i, m in enumerate(months):
        ok = valid_until is None or m <= pd.Period(valid_until, "M")
        pe_v = float(cyc(pe, i)) if ok else np.nan
        pf_v = float(cyc(pe_fwd if pe_fwd is not None else pe, i)) if ok else np.nan
        pb_v = float(cyc(pb, i)) if pb is not None else np.nan
        rows.append(dict(ticker="9999", month=str(m), date=m.end_time.normalize(), price_adj=38.4,
                         eps_ttm=TTM, eps_fwd=TTM, bvps=10.0, n_est_ttm=0, n_est_fwd=0,
                         pe=pe_v, pe_fwd=pf_v, pb=pb_v, valid_pe=ok, valid_pe_fwd=ok,
                         valid_pb=pb is not None, excluded=False, pe_exchange=np.nan))
    return pd.DataFrame(rows, columns=ms.HIST_COLUMNS)


def RH(*eps, window="2026Q1-2026Q4") -> pd.DataFrame:
    months = pd.period_range(end="2026-10", periods=len(eps), freq="M")
    return pd.DataFrame({"month": months.astype(str), "window": window, "eps_fwd": list(eps),
                         "n_est_q": 1, "event": "normal"})


def card(q=None, rev=None, px=None, cls="default", mh=None, rh=None, ind=None):
    return vc.build_card(Q() if q is None else q, REV() if rev is None else rev, PX() if px is None else px,
                         CLS() if cls == "default" else cls, MH() if mh is None else mh, rh, ind, ASOF)


FIELDS = {"ok", "tier", "route", "reason", "price", "px_date", "ticker", "type", "display_type", "state", "subtags",
          "why", "class_asof", "eps", "growth", "prices", "position", "fwd_prices", "buy_range", "revision",
          "b_tier", "c_tier", "roe", "eps_3y_avg", "price_note", "quality", "status", "notes", "version",
          "nonop_hist", "nonop_median", "fwd_note"}  # P4 新增


# ── 回傳結構 ─────────────────────────────────────────────

def test_回傳欄位齊全():
    c = card()
    assert set(c) == FIELDS
    assert set(c["eps"]) == {"reported", "ttm", "fwd", "est_disabled"}
    assert set(c["status"]) == {"data", "share_basis", "comparability", "estimate"}
    assert c["version"] == vc.CARD_VERSION and c["ticker"] == "9999" and c["px_date"] == "2026/10/30"


def test_不在母體為D():
    c = vc.build_card(Q(), REV(), PX(), None, MH(), None, None, ASOF)
    assert c["ok"] is False and c["tier"] == "D" and "分類母體" in c["reason"]
    assert set(c) == FIELDS


def test_財報不足4季為D():
    c = card(q=Q(n=3))
    assert c["ok"] is True and c["tier"] == "D" and c["reason"] == "財報不足 4 季"


@pytest.mark.parametrize("typ", ["special", "insufficient"])
def test_特殊與資料不足為D(typ):
    c = card(cls=CLS(typ))
    assert c["tier"] == "D" and c["reason"] == vc.D_REASONS[typ] and c["prices"] is None


# ── A-PE ────────────────────────────────────────────────

def test_A_PE_三價與購買區間():
    c = card()
    assert (c["tier"], c["route"]) == ("A", "PE")
    p = c["prices"]
    assert (p["cheap"], p["fair"], p["dear"]) == pytest.approx((36.864, 46.08, 55.296))
    assert p["mults"] == pytest.approx((9.6, 12.0, 14.4)) and p["raw_mults"] == pytest.approx((9.6, 12.0, 14.4))
    assert p["base"] == pytest.approx(TTM) and p["base_name"] == vc.BASE_TTM and p["metric"] == "pe"
    assert (p["n_valid"], p["n_loss"], p["window"], p["cap"], p["capped"]) == (60, 0, "2021-11～2026-10", 30.0, False)
    assert c["position"] == "fair"
    assert c["buy_range"] == pytest.approx({"low": 36.864, "high": 46.08, "state": "normal", "note": None})
    assert c["eps"]["ttm"]["n_est"] == 1 and c["eps"]["ttm"]["eps"] == pytest.approx(TTM)
    assert c["eps"]["est_disabled"] is None
    assert c["b_tier"] is None and c["c_tier"] is None and c["roe"] is None and c["eps_3y_avg"] is None


def test_前瞻_新季營收未出不給前瞻三價():
    c = card()
    assert c["fwd_prices"] is None and vc.NOTE_FWD_SAME in c["notes"]


def test_購買區間_連續兩次上修切前瞻():
    c = card(rev=REV("2026-10"), mh=MH(pe_fwd=(10, 12, 14, 16, 18)), rh=RH(3.0, 3.1, 3.2))
    f = c["fwd_prices"]
    assert f["base_name"] == vc.BASE_FWD and f["metric"] == "pe_fwd"
    assert (f["cheap"], f["fair"], f["dear"]) == pytest.approx((3.84 * 11.6, 53.76, 3.84 * 16.4))
    assert c["revision"]["streak"] == 2 and c["revision"]["direction"] == "up"
    b = c["buy_range"]
    assert b["state"] == "fwd_up" and b["low"] == pytest.approx(36.864) and b["high"] == pytest.approx(53.76)
    assert b["note"] == vc.BUY_NOTE_FWD


def test_購買區間_前瞻合理較低不切():
    c = card(rev=REV("2026-10"), mh=MH(pe_fwd=(6, 8, 10, 12, 14)), rh=RH(3.0, 3.1, 3.2))
    assert c["fwd_prices"]["fair"] == pytest.approx(38.4)
    assert c["buy_range"]["state"] == "normal" and c["buy_range"]["high"] == pytest.approx(46.08)


def test_購買區間_現價高於上緣():
    c = card(px=PX(50.0))
    assert c["position"] == "fair" and c["buy_range"]["note"] == vc.BUY_NOTE_ABOVE


def test_倍數P20高於上限_不給三價():
    c = card(mh=MH(pe=(55, 60, 65, 70, 75)))
    p = c["prices"]
    assert c["tier"] == "A" and p["cap"] == 50.0           # 5 年每年獲利且年均 PE >30 → 上限 50
    assert p["raw_mults"] == pytest.approx((59.0, 65.0, 71.0)) and p["capped"] is True
    assert p["cheap"] is None and p["fair"] is None and p["dear"] is None
    assert c["position"] == "na" and c["buy_range"] is None and vc.NOTE_CAP_FLAT in c["notes"]


def test_高本益比例外_上限50不截斷():
    p = card(mh=MH(pe=(32, 34, 36, 38, 40)))["prices"]
    assert p["cap"] == 50.0 and p["capped"] is False and p["fair"] == pytest.approx(3.84 * 36)


def test_AB緩衝_卡片():
    assert card(mh=MH(start="2019-01", pe=10, valid_until="2024-08"))["tier"] == "A"     # 本月 34、之前 A
    c = card(mh=MH(start="2019-01", pe=10, valid_until="2024-06"))                     # 本月 32
    assert c["tier"] == "B" and c["prices"] is None


def test_沒有倍數序列為B():
    c = vc.build_card(Q(), REV(), PX(), CLS(), None, None, None, ASOF)
    assert c["tier"] == "B" and c["b_tier"]["pe_now"] == pytest.approx(10.0)


def test_循環_較低獲利情境():
    hi = {"eps": 2.0, "ni_parent": 200.0, "net_income": 200.0, "pretax_income": 250.0}
    q = Q(**{p: hi for p in ("2025Q3", "2025Q4", "2026Q1", "2026Q2")})
    c = card(q=q, rev=REV("2026-06"), cls=CLS("cyclical", sub=["資產輕"]))
    p = c["prices"]
    assert c["tier"] == "A" and p["base_name"] == vc.BASE_LOW
    assert p["base"] == pytest.approx(15.68 / 3)                # min(近 4 季 8.0, 3 年平均 5.2267)
    assert c["eps_3y_avg"] == pytest.approx(15.68 / 3)      # 使用者 11/2：只列 3 年平均
    assert c["fwd_prices"] is None


def test_高獲利區加循環跡象_較低獲利情境():
    hi = {"eps": 2.0, "ni_parent": 200.0, "net_income": 200.0, "pretax_income": 250.0}
    q = Q(**{p: hi for p in ("2025Q3", "2025Q4", "2026Q1", "2026Q2")})
    c = card(q=q, rev=REV("2026-06"), cls=CLS("normal", state=["歷史高獲利區"], sub=["疑似循環"]))
    assert c["prices"]["base_name"] == vc.BASE_LOW and c["eps_3y_avg"] == pytest.approx(15.68 / 3)


# ── A-PB ────────────────────────────────────────────────

PB72 = dict(start="2020-11", pe=10, pb=(1.0, 1.5, 2.5, 3.0))


def test_購買區間_PB無前瞻_金融ROE():
    c = card(px=PX(15.0), cls=CLS("financial", group="financial"), mh=MH(**PB72))
    assert (c["tier"], c["route"]) == ("A", "PB")
    p = c["prices"]
    assert (p["cheap"], p["fair"], p["dear"]) == pytest.approx((10.0, 20.0, 30.0))
    assert p["base"] == pytest.approx(10.0) and p["base_name"] == vc.BASE_BVPS and p["metric"] == "pb"
    assert p["n_valid"] == 72 and p["window"] == "2020-11～2026-10" and p["cap"] is None
    assert c["fwd_prices"] is None and c["position"] == "fair"
    assert c["buy_range"] == pytest.approx({"low": 10.0, "high": 20.0, "state": "normal", "note": None})
    assert c["roe"] == pytest.approx(0.384)
    assert c["eps"]["ttm"]["n_est"] == 0                       # 金融不試算


def test_營建PB有效為A():
    c = card(px=PX(15.0), cls=CLS("special", special_triggers=["construction"]), mh=MH(**PB72))
    assert (c["tier"], c["route"]) == ("A", "PB") and c["roe"] is None


def test_PB有效月不足為D():
    c = card(cls=CLS("financial", group="financial"), mh=MH(start="2022-01", pe=10, pb=2.0))   # 58 個月
    assert c["tier"] == "D" and c["route"] == "PB" and c["reason"] == vc.PB_NO_HIST


def test_循環資產重走PB():
    c = card(px=PX(15.0), cls=CLS("cyclical", sub=["資產重"]), mh=MH(**PB72))
    assert c["route"] == "PB" and c["tier"] == "A"


# ── B／C ────────────────────────────────────────────────

LOSS = {"op_income": -50.0, "pretax_income": -50.0, "net_income": -50.0, "ni_parent": -50.0, "eps": -0.5}


def test_虧損優先C():
    q = Q(**{str(p): LOSS for p in pd.period_range("2019Q1", "2026Q2", freq="Q")})
    c = card(q=q, px=PX(20.0), mh=MH(start="2020-11", pe=10, pb=(1.0, 1.5, 2.5, 3.0)))
    assert c["tier"] == "C" and c["prices"] is None and c["buy_range"] is None
    assert c["c_tier"] == pytest.approx({"pb_now": 2.0, "pb_pct": 0.5, "n_valid": 72, "text": vc.C_TEXT})


def test_B層產業樣本不足():
    peers = {"測試業": {"median_pe": 15.0, "n": 5, "values": [8.0, 9.0, 15.0, 20.0, 25.0]}}
    c = card(mh=MH(valid_until="2023-06"), ind=peers)          # 有效 20 個月 → B
    assert c["tier"] == "B" and c["prices"] is None and c["buy_range"] is None
    assert c["b_tier"] == pytest.approx({"pe_now": 10.0, "industry_pct": None, "eps_needed": None,
                                         "n_peers": 5, "median_pe": None})


def test_B層_產業百分位與反推EPS():
    peers = {"測試業": {"median_pe": 12.0, "n": 10, "values": [6.0, 7, 8, 9, 11, 12, 13, 14, 15, 16]}}
    b = card(mh=MH(valid_until="2023-06"), ind=peers)["b_tier"]
    assert b == pytest.approx({"pe_now": 10.0, "industry_pct": 0.4, "eps_needed": 3.2,
                               "n_peers": 10, "median_pe": 12.0})


# ── 可信度帶來的停用 ─────────────────────────────────────

def test_試算停用_近4季退回已公布():
    # 方案 B（11/2）：業外閘門改提示，改用營收劇變觸發停用
    c = card(rev=REV("2026-09", **{"2026-07": 1000.0, "2026-08": 1000.0, "2026-09": 1000.0}))
    assert c["status"]["estimate"]["level"] == "stop"
    assert "營收" in c["eps"]["est_disabled"]
    t = c["eps"]["ttm"]
    assert t["n_est"] == 0 and t["eps"] == pytest.approx(TTM)
    assert [r["q"] for r in t["quarters"]] == ["2025Q3", "2025Q4", "2026Q1", "2026Q2"]
    assert c["eps"]["fwd"] is None and c["fwd_prices"] is None and c["tier"] == "A"


def test_股數事件表讀不到為D(monkeypatch):
    monkeypatch.setattr(ca, "EVENTS_OK", False)
    c = card()
    assert c["tier"] == "D" and "股數事件表" in c["reason"]
    assert c["status"]["share_basis"]["level"] == "stop"


def test_現金減資區間為D(monkeypatch):
    monkeypatch.setattr(ca, "SPLITS", {"9999": [{"date": "2026-09-15", "type": "cap_reduction", "m": None}]})
    c = card()
    assert c["tier"] == "D" and "現金減資" in c["reason"] and c["prices"] is None


def test_最新季EPS缺_不用淨利反推():
    c = card(q=Q(**{"2026Q2": {"eps": np.nan}}))
    t = c["eps"]["ttm"]
    assert t["status"] == "report_late" and t["quarters"][-1]["q"] == "2026Q1" and t["n_est"] == 0
    assert any(i["name"] == "財報延遲" for i in c["status"]["data"]["items"])


def test_面額未收集為未檢查():
    s = card()["status"]["share_basis"]
    assert s["level"] == "unchecked" and any(i["name"] == "面額與特別股" for i in s["items"])


# ── 年增率列、品質 ───────────────────────────────────────

def test_年增率列():
    rows = card(rev=REV("2026-10", **{"2026-10": 400.0}))["growth"]
    assert [r["key"] for r in rows] == ["month", "last_q", "ttm", "fwd"]
    m, last, ttm, fwd = rows
    assert m["period"] == "2026-10" and m["eps"] is None
    assert m["rev"]["label"] == "pct" and m["rev"]["value"] == pytest.approx(0.2)
    assert (last["period"], last["kind"], last["months_known"]) == ("2026Q3", "est", 3)
    assert last["rev"]["value"] == pytest.approx(0.0) and last["eps"]["value"] == pytest.approx(0.0)
    assert ttm["period"] == "2025Q4～2026Q3" and ttm["eps"]["value"] == pytest.approx(0.0)
    assert fwd["rev"] is None and fwd["eps"]["value"] == pytest.approx(4.00 / 3.84 - 1)


def test_年增率_新季未出不列前瞻():
    assert [r["key"] for r in card()["growth"]] == ["month", "last_q", "ttm"]


def test_品質_現金流與應計():
    assert card()["quality"] == pytest.approx({"cfo_ni": 1.25, "accrual": -0.048})


# ── P3 驗收後補（Opus，2026-11-02 乾跑發現）──────────────────

def test_金融業分類資料不足仍走PB():
    c = card(px=PX(15.0), cls=CLS("insufficient", group="financial"), mh=MH(**PB72))
    assert (c["tier"], c["route"]) == ("A", "PB") and c["roe"] == pytest.approx(0.384)


def test_歸母淨利缺_用合併淨利推股數():
    q = Q()
    q["ni_parent"] = q["net_income"]
    assert vc.bvps_live(q) == pytest.approx(10.0)


def test_微利為C():
    thin = {"eps": 0.004, "ni_parent": 0.4, "net_income": 0.4}
    q = Q(**{str(p): thin for p in pd.period_range("2019Q1", "2026Q2", freq="Q")})
    c = card(q=q, rev=REV("2026-06"))
    assert c["tier"] == "C" and c["c_tier"]["text"] == vc.C_TEXT_THIN and c["b_tier"] is None


def test_沒有三價時三價位置放短句():
    """使用者 11/2：沒有三價的地方務必放簡單說明，詳細點開看。"""
    assert card()["price_note"] is None
    assert vc.build_card(Q(), REV(), PX(), None, MH(), None, None, ASOF)["price_note"] == vc.PRICE_NOTES["universe"]
    assert card(cls=CLS("special"))["price_note"] == vc.PRICE_NOTES["special"]
    assert card(cls=CLS("insufficient"))["price_note"] == vc.PRICE_NOTES["few"]
    assert card(mh=MH(valid_until="2023-06"))["price_note"] == vc.PRICE_NOTES["b_only"]
    assert card(mh=MH(pe=(55, 60, 65, 70, 75)))["price_note"] == vc.PRICE_NOTES["cap"]
    q = Q(**{str(p): LOSS for p in pd.period_range("2019Q1", "2026Q2", freq="Q")})
    assert card(q=q, px=PX(20.0))["price_note"] == vc.PRICE_NOTES["loss"]
    assert card(cls=CLS("financial", group="financial"), mh=MH(start="2022-01", pe=10, pb=2.0))["price_note"] == vc.PRICE_NOTES["pb_hist"]
    assert all(len(v) <= 15 for v in vc.PRICE_NOTES.values())      # 短句：卡片一行放得下
