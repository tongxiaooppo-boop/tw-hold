"""估值卡片組裝層（screener/val_card.py）與失效偵測（screener/detect.py）的路由與守門測試。
合成資料：每季營收 100、毛利率 30%、費損 20%、業外 5、稅 20%、10 股 → 單季 EPS = (10+5)*0.8/10 = 1.2。"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from screener import detect as dt  # noqa: E402
from screener import val_card as vc  # noqa: E402

QE = pd.date_range("2022-03-31", periods=16, freq="QE")


def _qf(n=16, eps=1.2):
    return pd.DataFrame({
        "period_end": QE[:n], "revenue": 100.0, "gross_profit": 30.0, "op_income": 10.0,
        "pretax_income": 15.0, "net_income": 12.0, "ni_parent": 12.0, "eps": eps,
        "capital_stock": 100.0, "equity_parent": 50.0})


def _rev(last="2026-01"):
    months = pd.period_range("2021-01", last, freq="M")
    return pd.DataFrame({"month": [str(m) for m in months], "revenue": 33.0})


def _per(n_years=6, per=15.0):
    d = pd.bdate_range(end="2026-01-30", periods=260 * n_years)
    return pd.DataFrame({"date": d, "per": per, "pbr": 2.0})


def _px():
    d = pd.bdate_range(end="2026-01-30", periods=30)
    return pd.DataFrame({"date": d, "close": 20.0})


def _cls(typ="normal", state=(), sub=()):
    return {"type": typ, "display_type": "一般", "state": list(state), "subtags": list(sub),
            "why": [], "metrics": {}, "decided_at": "2025-12-31"}


def test_無分類_ok為False():
    assert vc.build_card(_qf(), _rev(), _px(), _per(), None)["ok"] is False


def test_一般股_給PE三價與12個月價():
    c = vc.build_card(_qf(), _rev(), _px(), _per(), _cls())
    assert c["ok"] and c["method"] == "PE" and c["prices"] is not None
    assert abs(c["prices"]["fair"] - 15.0 * c["prices"]["base"]) < 1e-6    # 倍數固定 15
    assert c["forward"] is not None and c["forward"]["rolling"]["base"] > 0
    assert c["position"] == "cheap"          # 現價 20 < 便宜價 15×~4.8


def test_特殊與資料不足_補位三價_低可信度_不給前瞻():
    for t in ("special", "insufficient"):
        c = vc.build_card(_qf(), _rev(), _px(), _per(), _cls(t))
        p = c["prices"]
        assert p and p["source"] == "補位" and p["mults"] == list(vc.FALLBACK_MULTS[t])
        assert abs(p["fair"] - 4.8 * vc.FALLBACK_MULTS[t][1]) < 1e-6        # 近四季 EPS 4.8
        assert c["forward"] is None and c["confidence"]["level"] == "低"


def test_賠錢不給三價_任何類型():
    for t in ("normal", "growth", "cyclical", "financial", "special", "insufficient"):
        c = vc.build_card(_qf(eps=-0.5), _rev(), _px(), _per(), _cls(t, sub=["資產重"] if t == "cyclical" else ()))
        assert c["prices"] is None and "賠錢" in c["no_price"], t


def test_獲利狀態只降級不擋價():
    c = vc.build_card(_qf(), _rev(), _px(), _per(), _cls(state=["獲利不穩"]))
    assert c["prices"] is not None and c["prices"]["source"] == "歷史"
    assert any("獲利不穩" in d for d in c["confidence"]["degrades"])


def test_高獲利區加疑似循環_改用較低EPS_仍給價_不給前瞻():
    eps = [0.5] * 12 + [1.2] * 4                 # 近四季 4.8、3 年平均 (6+4.8)/3=... 近 12 季合計 ÷ 3
    q = _qf(eps=0.0)
    q["eps"] = eps
    c = vc.build_card(q, _rev(), _px(), _per(), _cls(state=["歷史高獲利區"], sub=["疑似循環"]))
    p = c["prices"]
    avg3 = sum(eps[-12:]) / 3
    assert p and p["source"] == "歷史" and p["base_name"] == "近四季與 3 年平均較低者"
    assert abs(p["base"] - min(sum(eps[-4:]), avg3)) < 1e-9 and p["base"] < 4.8
    assert c["forward"] is None and any("高獲利區" in d for d in c["confidence"]["degrades"])


def test_倍數P20超過上限_改補位():
    c = vc.build_card(_qf(), _rev(), _px(), _per(per=40.0), _cls())
    assert c["prices"]["source"] == "補位" and c["prices"]["mults"] == list(vc.FALLBACK_MULTS["normal"])
    assert any("上限" in n for n in c["notes"]) and c["forward"] is None


def test_歷史月數不足_高成長補位用高成長倍數():
    c = vc.build_card(_qf(), _rev(), _px(), _per(n_years=2), _cls("growth"))
    assert c["prices"]["source"] == "補位" and c["prices"]["mults"] == list(vc.FALLBACK_MULTS["growth"])


def test_試算閘門擋下_改用近四季實際EPS_仍給價_可信度低():
    q = _qf()
    q["pretax_income"] = q["op_income"] + np.where(np.arange(len(q)) % 2 == 0, 40.0, -30.0)   # 業外占比高且不穩
    c = vc.build_card(q, _rev(), _px(), _per(), _cls())
    p = c["prices"]
    assert p and p["source"] == "歷史" and p["base_name"] == "過去 4 季 EPS"
    assert c["forward"] is None and c["confidence"]["level"] == "低"


def test_循環資產輕_走PE歷史_資產重走PB():
    c = vc.build_card(_qf(), _rev(), _px(), _per(), _cls("cyclical", sub=["資產輕"]))
    assert c["method"] == "PE" and c["prices"]["source"] == "歷史" and c["forward"] is None
    c = vc.build_card(_qf(), _rev(), _px(), _per(), _cls("cyclical", sub=["資產重"]))
    assert c["method"] == "PB" and c["prices"] is not None and c["forward"] is None


def test_財報不足4季_不給價():
    c = vc.build_card(_qf(3), _rev(), _px(), _per(), _cls())
    assert c["ok"] and c["prices"] is None


# ── detect ──
def test_股數差15以上_降級不擋():
    q = _qf()
    q["capital_stock"] = 100.0 * 3
    assert dt.shares_check(q).level == "degrade"


def test_業外占比高且不穩_擋住():
    q = _qf()
    q["pretax_income"] = q["op_income"] + np.where(np.arange(len(q)) % 2 == 0, 40.0, -30.0)
    assert dt.nonop_gate(q).level == "block"


def test_可信度彙總():
    ok = dt.Check("a", "ok", None, "")
    d1 = dt.Check("b", "degrade", None, "x")
    d2 = dt.Check("c", "degrade", None, "y")
    b = dt.Check("d", "block", None, "z")
    assert dt.confidence([ok])["level"] == "高"
    assert dt.confidence([ok, d1])["level"] == "中"
    assert dt.confidence([d1, d2])["level"] == "低"
    assert dt.confidence([d1, b])["level"] == "不給價"
    sv = dt.Check("e", "severe", None, "w")
    assert dt.confidence([sv])["level"] == "低" and dt.confidence([sv])["degrades"] == ["w"]


def test_PB窗內有大型股數事件_改補位_小事件降級():
    big = [(pd.Timestamp("2025-06-01"), 2.98)]
    c = vc.build_card(_qf(), _rev(), _px(), _per(), _cls("cyclical", sub=["資產重"]), share_events=big)
    assert c["prices"]["source"] == "補位" and c["confidence"]["level"] == "低"
    assert any("股數調整" in n for n in c["notes"])
    small = [(pd.Timestamp("2025-06-01"), 1.05)]
    c = vc.build_card(_qf(), _rev(), _px(), _per(), _cls("cyclical", sub=["資產重"]), share_events=small)
    assert c["prices"]["source"] == "歷史" and any("股數調整" in d for d in c["confidence"]["degrades"])


def test_剛好10pct事件_補位且未知分類與未給事件資料():
    c = vc.build_card(_qf(), _rev(), _px(), _per(), _cls("cyclical", sub=["資產重"]),
                      share_events=[(pd.Timestamp("2025-06-01"), 0.9)])
    assert c["prices"]["source"] == "補位"
    c = vc.build_card(_qf(), _rev(), _px(), _per(), _cls("cyclical", sub=["資產重"]), share_events=None)
    assert c["prices"]["source"] == "歷史" and any("事件資料" in d for d in c["confidence"]["degrades"])
    assert vc.build_card(_qf(), _rev(), _px(), _per(), _cls("weird"))["prices"] is None


def test_金融股_無歷史PB_補位金融倍數():
    c = vc.build_card(_qf(), _rev(), _px(), _per(n_years=2), _cls("financial"))
    assert c["prices"]["source"] == "補位" and c["prices"]["mults"] == list(vc.FALLBACK_MULTS["financial"])


def test_財報落後3季以上_不給12個月價():
    c = vc.build_card(_qf(), _rev("2026-12"), _px(), _per(), _cls())
    assert c["forward"] is None


def test_購買參考價_空間達10pct才給():
    c = vc.build_card(_qf(), _rev(), _px(), _per(), _cls())          # 現價 20，前瞻價遠高於 22
    f = c["forward"]
    assert f["ref_ok"] and abs(f["ref_price"] - f["rolling"]["base"] / 1.10) < 1e-9
    hi = _px(); hi["close"] = 500.0                                   # 現價遠高於前瞻價 → 空間不足
    f2 = vc.build_card(_qf(), _rev(), hi, _per(), _cls())["forward"]
    assert f2["ref_ok"] is False and f2["margin"] is None and f2["ref_price"] is None


def test_財報落後剛好3季_不給前瞻股價但三價仍給():
    c = vc.build_card(_qf(), _rev("2026-09"), _px(), _per(), _cls())     # 最後財報 2025Q4，月營收到 2026-09 → k=3
    assert c["prices"] is not None and c["forward"] is None


def test_分類基準落後最新財報_降級提示():
    cl = _cls(); cl["decided_at"] = "2025-06-30"                         # 財報最新 2025-12-31
    c = vc.build_card(_qf(), _rev(), _px(), _per(), cl)
    assert any("分類基準" in d for d in c["confidence"]["degrades"])


def test_怎麼算規則列_含回測狀態且不含舊術語():
    import importlib, sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
    sa = importlib.import_module("streamlit_app")
    for method, typ in (("PE", "normal"), ("PE", "growth"), ("PB", "financial")):
        rows = dict(sa._card_explain_rows({"method": method, "type": typ}))
        assert "回測" in rows["回測狀態"] and "沒有" in rows["回測狀態"]
        assert all("P20" not in v and "**" not in v for v in rows.values())     # 表格內不渲染 markdown，不能留粗體符號


def test_最新季EPS缺值_用本益比反推_財報賠錢仍不給():
    q = _qf()
    q.loc[q.index[-2:], "eps"] = np.nan                       # 金融股常見：最新兩季 EPS 空白
    c = vc.build_card(q, _rev(), _px(), _per(per=15.0), _cls("financial"))
    assert c["prices"] is not None and any("反推" in d for d in c["confidence"]["degrades"])
    blank = _per(); blank["per"] = np.nan                    # 交易所本益比也空白 → 無從判斷（PE 路線需要 EPS）
    assert vc.build_card(q, _rev(), _px(), blank, _cls("normal"))["prices"] is None


def test_金融股EPS缺值且本益比空白_PB仍給價():
    q = _qf()
    q.loc[q.index[-2:], "eps"] = np.nan
    blank = _per(); blank["per"] = np.nan
    c = vc.build_card(q, _rev(), _px(), blank, _cls("financial"))
    assert c["prices"] is not None and c["method"] == "PB" and not c.get("no_price")


def test_反推EPS_最新一天PER空白_不用舊值():
    q = _qf()
    q.loc[q.index[-2:], "eps"] = np.nan
    per = _per(per=15.0)
    per.loc[per.index[-5:], "per"] = np.nan                  # 最近幾天 PER 空白（賠錢），更早有值
    assert vc.build_card(q, _rev(), _px(), per, _cls("normal"))["prices"] is None


def test_獲利狀態降級_不放行前瞻股價與對照價():
    c = vc.build_card(_qf(), _rev(), _px(), _per(), _cls(state=["轉機"]))
    assert c["prices"] is not None and c["forward"] is None and c["compare"] is None


def test_前瞻EPS非正_改近四季_可信度低():
    q = _qf(); q["op_income"] = [10.0] * 12 + [-30.0] * 4      # 近期營業虧損 → NC 非正，但 TTM 以 eps 欄為準仍正
    c = vc.build_card(q, _rev(), _px(), _per(), _cls())
    if c["prices"] and c["prices"]["base_name"] == "過去 4 季 EPS" and (c["eps"] or {}).get("eps_nc", 1) <= 0:
        assert c["confidence"]["level"] == "低"


def test_高變動降可信度不改價格(monkeypatch):
    baseline = vc.build_card(_qf(), _rev(), _px(), _per(), _cls())
    original = vc.en.nowcast

    def with_variability(*args, **kwargs):
        result = original(*args, **kwargs)
        result["variability"] = {"flag": True, "reasons": ["營收季增減達 30%"], "metrics": {"rev_qoq": 0.3}}
        return result

    monkeypatch.setattr(vc.en, "nowcast", with_variability)
    warned = vc.build_card(_qf(), _rev(), _px(), _per(), _cls())
    assert any("營收季增減達 30%" in d for d in warned["confidence"]["degrades"])
    assert warned["confidence"]["level"] == "低"                       # 備註說可信度低，欄位就要真的是低
    for key in ("prices", "forward", "compare"):
        assert warned[key] == baseline[key]


def test_試算單季EPS超過歷史最高2倍_加短備註不改價格(monkeypatch):
    baseline = vc.build_card(_qf(), _rev(), _px(), _per(), _cls())
    original = vc.en.nowcast

    def with_spike(*args, **kwargs):
        result = original(*args, **kwargs)
        result["nc_quarters"] = list(result.get("nc_quarters") or []) + [{"kind": "est", "eps": 1e6}]
        return result

    monkeypatch.setattr(vc.en, "nowcast", with_spike)
    warned = vc.build_card(_qf(), _rev(), _px(), _per(), _cls())
    assert any("2 倍" in n and "未必全轉成獲利" in n for n in warned["notes"])
    assert not any("2 倍" in n for n in baseline["notes"])
    for key in ("prices", "forward", "compare", "confidence"):
        assert warned[key] == baseline[key]


def test_股價_滾動與已公布兩組並列():
    c = vc.build_card(_qf(), _rev(), _px(), _per(), _cls())
    f = c["forward"]
    # 兩季實際 1.2，加兩季 99×0.1×0.8÷10。
    assert abs(f["rolling"]["eps"] - 3.984) < 1e-9
    assert abs(f["reported"]["eps"] - 4.8) < 1e-9
    assert abs(f["gap"] - (3.984 / 4.8 - 1)) < 1e-9
    for key, eps in (("rolling", 3.984), ("reported", 4.8)):
        for price in ("lo", "base", "hi"):
            assert abs(f[key][price] - eps * 15) < 1e-9


def _test_gap_big(monkeypatch):
    original = vc.en.nowcast
    def changed(*args, **kwargs):
        r = original(*args, **kwargs)
        r["eps_nc"] = 8.0
        return r
    monkeypatch.setattr(vc.en, "nowcast", changed)
    f = vc.build_card(_qf(), _rev(), _px(), _per(), _cls())["forward"]
    assert f["gap_big"] and f["rolling"] and f["reported"]
    assert f["ref_price"] is None and f["margin"] is None and not f["ref_ok"]


def test_股價_前瞻退回時三價用過去4季且不給估值價對照(monkeypatch):
    original = vc.en.nowcast
    def fallback(*args, **kwargs):
        r = original(*args, **kwargs)
        r["eps_nc"] = r["eps_ttm"]
        r["flags"].append(vc.en.FALLBACK_FLAG)
        return r
    monkeypatch.setattr(vc.en, "nowcast", fallback)
    c = vc.build_card(_qf(), _rev(), _px(), _per(), _cls())
    assert c["forward"] is None                                      # 前瞻退回：三價本身就是過去 4 季 EPS，不重複給對照價
    assert c["prices"]["base_name"] == "過去 4 季 EPS" and c["prices"]["base"] == 4.8


def test_購買參考價依滾動估值價():
    f = vc.build_card(_qf(), _rev(), _px(), _per(), _cls())["forward"]
    assert abs(f["ref_price"] - 3.984 * 15 / 1.10) < 1e-9

globals()["test_股價_差距超過30%不給參考價與空間"] = _test_gap_big


def test_口徑差異大_不判位置且對照警示同門檻(monkeypatch):
    original = vc.en.nowcast
    def big(*args, **kwargs):
        r = original(*args, **kwargs)
        r["eps_nc"] = 8.0
        return r
    monkeypatch.setattr(vc.en, "nowcast", big)
    c = vc.build_card(_qf(), _rev(), _px(), _per(), _cls())
    assert c["forward"]["gap_big"] and c["position"] == "na"
    assert c["compare"]["warn"] == (abs(c["compare"]["diff"]) > 0.30)
    assert vc.DIFF_WARN == 0.30


def test_口徑差異小_保留位置判斷():
    c = vc.build_card(_qf(), _rev(), _px(), _per(), _cls())
    assert not c["forward"]["gap_big"] and c["position"] in ("cheap", "fair", "dear")


def test_前瞻不可用_降級並說明原因():
    q = _qf()
    q.loc[q.index[-1], "gross_profit"] = np.nan          # 最新一季毛利缺值 → 前瞻試算失敗
    c = vc.build_card(q, _rev(), _px(), _per(), _cls())
    if not (c["eps"] or {}).get("ok"):
        assert any("前瞻 4 季無法試算" in d for d in c["confidence"]["degrades"])
        assert c["confidence"]["level"] != "高"


def test_財報落後3季_三價改用過去4季且不給對照價(monkeypatch):
    original = vc.en.nowcast
    def late(*args, **kwargs):
        r = original(*args, **kwargs)
        r["k"] = 3
        return r
    monkeypatch.setattr(vc.en, "nowcast", late)
    c = vc.build_card(_qf(), _rev(), _px(), _per(), _cls())
    assert c["forward"] is None and c["prices"]["base_name"] == "過去 4 季 EPS"
    assert any("財報已落後 3 季以上" in d for d in c["confidence"]["degrades"])
