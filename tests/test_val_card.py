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
    assert c["forward"] is not None and c["forward"]["base"] > 0
    assert c["position"] == "cheap"          # 現價 20 < 便宜價 15×~4.8


def test_特殊與資料不足_不給價():
    for t in ("special", "insufficient"):
        c = vc.build_card(_qf(), _rev(), _px(), _per(), _cls(t))
        assert c["prices"] is None and c["no_price"]


def test_虧損狀態_不給PE價但仍列前瞻EPS():
    c = vc.build_card(_qf(), _rev(), _px(), _per(), _cls(state=["虧損"]))
    assert c["prices"] is None and "虧損" in c["no_price"] and c["eps"]["ok"]


def test_高獲利區加疑似循環_高峰閘門不給價():
    c = vc.build_card(_qf(), _rev(), _px(), _per(), _cls(state=["歷史高獲利區"], sub=["疑似循環"]))
    assert c["prices"] is None and "高獲利區" in c["no_price"]


def test_倍數P20超過上限_不給價():
    c = vc.build_card(_qf(), _rev(), _px(), _per(per=40.0), _cls())
    assert c["prices"] is None and "上限" in c["no_price"]


def test_循環資產輕_不給價_資產重走PB():
    assert vc.build_card(_qf(), _rev(), _px(), _per(), _cls("cyclical", sub=["資產輕"]))["prices"] is None
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


def test_PB窗內有大型股數事件_擋住_小事件降級():
    big = [(pd.Timestamp("2025-06-01"), 2.98)]
    c = vc.build_card(_qf(), _rev(), _px(), _per(), _cls("cyclical", sub=["資產重"]), share_events=big)
    assert c["prices"] is None and "股數調整" in "".join(c["confidence"]["blocks"])
    small = [(pd.Timestamp("2025-06-01"), 1.05)]
    c = vc.build_card(_qf(), _rev(), _px(), _per(), _cls("cyclical", sub=["資產重"]), share_events=small)
    assert c["prices"] is not None and any("股數調整" in d for d in c["confidence"]["degrades"])


def test_剛好10pct事件_擋住且未知分類與未給事件資料():
    c = vc.build_card(_qf(), _rev(), _px(), _per(), _cls("cyclical", sub=["資產重"]),
                      share_events=[(pd.Timestamp("2025-06-01"), 0.9)])
    assert c["prices"] is None
    c = vc.build_card(_qf(), _rev(), _px(), _per(), _cls("cyclical", sub=["資產重"]), share_events=None)
    assert c["prices"] is not None and any("事件資料" in d for d in c["confidence"]["degrades"])
    assert vc.build_card(_qf(), _rev(), _px(), _per(), _cls("weird"))["prices"] is None


def test_財報落後3季以上_不給12個月價():
    c = vc.build_card(_qf(), _rev("2026-12"), _px(), _per(), _cls())
    assert c["forward"] is None


def test_購買參考價_空間達10pct才給():
    c = vc.build_card(_qf(), _rev(), _px(), _per(), _cls())          # 現價 20，前瞻價遠高於 22
    f = c["forward"]
    assert f["ref_ok"] and abs(f["ref_price"] - f["base"] / 1.10) < 1e-9
    hi = _px(); hi["close"] = 500.0                                   # 現價遠高於前瞻價 → 空間不足
    f2 = vc.build_card(_qf(), _rev(), hi, _per(), _cls())["forward"]
    assert f2["ref_ok"] is False and f2["margin"] < 0.10
