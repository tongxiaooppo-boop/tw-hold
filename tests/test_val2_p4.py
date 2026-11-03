"""估值 2.0 P4（docs/val2/P4_spec.md）。預期值由 Opus 定，實作者不得改。

合成卡沿用 test_val2_card：近 4 季 3.84（含 2026Q3 試算 1 季）、P20/P50/P80＝9.6/12/14.4、現價 38.4（10/30）、
前瞻季＝近 4 季（月營收到 2026-09）、RH(3.0, 3.1, 3.2) → 連續上修 2 個月、最後一次 +3.2%。
"""
import ast
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import val_view as vv                      # noqa: E402
from screener import eps_windows as ew     # noqa: E402
from screener import multiples_self as ms  # noqa: E402
from screener import val_card as vc        # noqa: E402
from test_val2_card import ASOF, CLS, MH, PX, Q, RH, T, card, _events  # noqa: E402,F401

LABEL = "9999 測試"


def A():
    return card(rh=RH(3.0, 3.1, 3.2))


def B():
    return card(mh=MH(valid_until="2021-12"))


# ── P4a：引擎補欄 ───────────────────────────────────────

def test_P4新欄_業外與前瞻短句():
    c = A()
    assert c["version"] == "card-v4-val2"
    assert len(c["nonop_hist"]) == 8 and c["nonop_hist"][-1]["q"] == "2026Q2"
    r = c["nonop_hist"][-1]
    assert r["nonop"] == pytest.approx(20.0) and r["pretax"] == pytest.approx(120.0)
    assert r["share"] == pytest.approx(20 / 120)
    assert c["nonop_median"] == pytest.approx(20.0)
    assert c["fwd_note"] == vc.FWD_NOTES["same"]
    assert c["revision"]["last_event"] == "normal"
    assert c["buy_range"]["where"] == "in" and c["buy_range"]["gap"] is None


def test_購買區間_現價高於上緣_給gap():
    b = card(px=PX(60.0))["buy_range"]
    assert b["where"] == "above" and b["gap"] == pytest.approx(60.0 / 46.08 - 1)


def test_前瞻短句_循環():
    c = card(cls=CLS("cyclical"))
    assert c["tier"] == "A" and c["fwd_note"] == vc.FWD_NOTES["cyclical"]


def test_前瞻短句_非循環但高檔_不說循環股():
    cls = CLS("normal")
    cls["state"] = ["歷史高獲利區"]
    cls["subtags"] = ["疑似循環"]
    c = card(cls=cls)
    assert c["tier"] == "A" and c["fwd_note"] == vc.FWD_NOTES["peak"]


def test_前瞻短句_非A層為None():
    c = B()
    assert c["tier"] == "B" and c["fwd_note"] is None


def test_沒有rev_hist_last_event為None():
    assert card()["revision"]["last_event"] is None


def test_業外中位數_共用函式():
    rows = [dict(pretax_income=p, op_income=0.0) for p in (1.0, 2.0, 3.0)]
    assert ew.nonop_median(rows) is None                       # 有效 <4
    rows.append(dict(pretax_income=10.0, op_income=0.0))
    rows.append(dict(pretax_income=np.nan, op_income=0.0))
    assert ew.nonop_median(rows) == pytest.approx(2.5)


def test_自建歷史位置():
    mh = MH()                                                   # 2026-10 那月 PE＝16（循環 8..16 的最高）
    p = ms.hist_position(mh, "pe", ASOF, 60)
    assert p == {"now": 16.0, "pct": 1.0, "n": 60, "month": "2026-10"}
    assert ms.hist_position(mh, "pe", ASOF, 12)["n"] == 12
    assert ms.hist_position(mh, "pb", ASOF, None)["n"] == 60
    assert ms.hist_position(MH(valid_until="2020-01"), "pe", ASOF, 60) is None


# ── P4a：格式化 ─────────────────────────────────────────

def test_格式化():
    assert vv.fmt_px(2034.2) == "2,034" and vv.fmt_px(36.864) == "36.9" and vv.fmt_px(None) == "—"
    assert vv.fmt_eps(98.734) == "98.73" and vv.fmt_eps(-1.2) == "-1.20"
    assert vv.fmt_mult(20.64, "pe") == "20.6 倍" and vv.fmt_mult(1.234, "pb") == "1.23 倍"
    assert vv.fmt_pct(0.0323) == "+3.2%" and vv.fmt_pct(0.165, False) == "16.5%"
    assert vv.fmt_yi(467_600_000_000) == "4,676 億" and vv.fmt_yi(640_000_000) == "6.4 億"
    assert vv.fmt_shares(25_928_000_000) == "259.3 億股"
    assert vv.fmt_range(36.864, 46.08) == "36.9～46.1"


def test_收錄範圍():
    assert vv.coverage_line({"count": 1098, "coverage_mktcap_k": 800}) == "估值涵蓋市值前 800 大"
    assert vv.coverage_line({"count": 1098, "coverage_mktcap_k": 50}) == "估值收錄 1098 檔"
    assert vv.coverage_line({"count": 1098}) == "估值收錄 1098 檔"
    assert vv.coverage_line(None) == ""


@pytest.mark.parametrize("rev, text", [
    (dict(last_pct=None, streak=2, direction="up", last_event="roll"), "窗口更換，本月不比較"),
    (dict(last_pct=None, streak=0, direction=None, last_event="report"), "改用財報，本月不比較"),
    (dict(last_pct=0.0323, streak=2, direction="up", last_event="normal"), "比上月 +3.2%，連續上修 2 個月"),
    (dict(last_pct=-0.05, streak=3, direction="down", last_event="normal"), "比上月 -5.0%，連續下修 3 個月"),
    (dict(last_pct=0.004, streak=0, direction=None, last_event="normal"), "比上月 +0.4%"),
    (dict(last_pct=None, streak=0, direction=None, last_event=None), "比上月持平"),
])
def test_上修文字(rev, text):
    assert vv.revision_text(rev) == text


# ── P4a：卡片 ──────────────────────────────────────────

def test_卡片_A層():
    v = vv.card_view(A(), LABEL, {"count": 1098, "coverage_mktcap_k": 800})
    p = v.price
    assert v.full and v.coverage == "估值涵蓋市值前 800 大"
    assert p.head_sub == "9999 測試｜normal" and p.price == "38.4" and p.price_sub == "現價（10/30）"
    assert p.tri == (("便宜價", "36.9"), ("合理價", "46.1"), ("昂貴價", "55.3")) and p.tri_note is None
    assert p.pos == ("合理區", "mid") and p.base_text == "基準：近 4 季 EPS 3.84 元"
    assert p.buy == ("36.9～46.1", "一般｜現價在區間內")
    assert p.fwd_tri is None and p.fwd_note == vc.FWD_NOTES["same"]
    assert v.eps.kv == (("近 4 季 EPS", "2025Q4～2026Q3，含 1 季試算", "3.84 元"),
                        ("前瞻 4 季 EPS", "新季營收未出（比上月 +3.2%，連續上修 2 個月）", "＝近 4 季"))
    assert v.eps.growth_table.rows == (("最新月（09 月）", "+0%", "—"),
                                       ("2026Q3（試算；營收已公布 3 個月）", "+0%", "-0%（基期低）"),
                                       ("近 4 季", "+0%", "+0%"))
    assert v.pins == {"近 4 季 EPS": "3.84", "基準": "3.84", "便宜價": "36.9", "合理價": "46.1",
                      "昂貴價": "55.3", "購買區間": "36.9～46.1"}


def test_卡片_現價高於上緣():
    p = vv.card_view(card(px=PX(60.0)), LABEL, None).price
    assert p.pos == ("昂貴區", "bad") and p.buy == ("36.9～46.1", "一般｜現價高於上緣 +30.2%")


def test_卡片_不在範圍():
    v = vv.card_view(card(cls=None), LABEL, None)
    assert not v.full and v.eps is None
    assert v.price.tri is None and v.price.tri_note == "不在估值範圍" and v.price.buy is None


def test_卡片_B層_三價位置一定有字():
    c = B()
    p = vv.card_view(c, LABEL, None).price
    assert p.tri is None and p.tri_note == f"{c['price_note']}，{vv.MORE_DETAIL}"
    assert p.fwd_label is None and p.buy is None
    assert p.extra and p.extra[0].startswith("現價本益比 10.0 倍")


# ── P4a：展開區 ────────────────────────────────────────

def _cells(tables):
    return [(t, r) for t in tables for r in t.rows]


def test_glossary_同名同源_每個圖釘對到卡片():
    """§9-3：卡片每個 pin 在展開區剛好標一次，數值字元相同、來源寫『＝卡片「標籤」』。"""
    c = A()
    v = vv.card_view(c, LABEL, None)
    tables = vv.detail_tables(c) + vv.explain_tables(c) + vv.trial_tables(c)
    pinned = [r for _, r in _cells(tables) if any(str(x).startswith(vv.PIN) for x in r)]
    for label, text in v.pins.items():
        hit = [r for r in pinned if any(str(x).startswith(f"＝卡片『{label}』") for x in r)]
        assert len(hit) == 1, label
        val = next(x for x in hit[0] if str(x).startswith(vv.PIN))
        assert val == f"{vv.PIN} {text}" or val.startswith(f"{vv.PIN} {text} "), (label, val)
    assert len(pinned) == len(v.pins)


def test_試算細節_順序與共用季():
    titles = [t.title or "" for t in vv.trial_tables(A())]
    assert titles[0].startswith("① 窗口表")
    shared = [t for t in titles if t.startswith("② 2026Q3 試算")]
    assert len(shared) == 1 and "（近 4 季、前瞻 4 季共用）" in shared[0]
    assert any(t.startswith("③ 三價推導") for t in titles) and any(t.startswith("④ 購買區間") for t in titles)
    assert any(t.startswith("⑥ 近 8 季業外（中位數") for t in titles)


def test_推導表列序():
    t = next(t for t in vv.trial_tables(A()) if (t.title or "").startswith("② 2026Q3"))
    steps = [r[0] for r in t.rows]
    assert steps == ["07 月營收", "08 月營收", "09 月營收", "＝ 季營收", "×（毛利率 − 營業費用率）",
                     "＝ 營業利益（試算）", "＋ 業外", "×（1−稅率）×（1−少數股權比）", "＝ 歸母淨利（試算）",
                     "÷ 股數", "＝ 試算 EPS"]
    assert t.kind == "derive" and t.headers == ("步驟", "數值", "來源／假設")
    assert len(t.rows) - 1 in t.hl


def test_展開區都是表格():
    c = A()
    for t in vv.detail_tables(c) + vv.explain_tables(c) + vv.trial_tables(c):
        assert t.kind in ("derive", "kv", "grid") and t.rows


def test_怎麼算_不含這檔數字():
    c = A()
    text = "\n".join("\n".join(r) for t in vv.explain_tables(c) for r in t.rows)
    for s in ("36.9", "46.1", "55.3", "3.84", "38.4"):
        assert s not in text, s


def test_定位細節_不放三價():
    c = A()
    text = "\n".join("\n".join(r) for t in vv.detail_tables(c) for r in t.rows)
    for s in ("36.9", "46.1", "55.3"):
        assert s not in text, s
    assert "有效月數" in text and "虧損月數" in text


def test_畫面不自己算():
    tree = ast.parse((ROOT / "app" / "val_view.py").read_text(encoding="utf-8"))
    banned_mod = {"streamlit", "pandas", "numpy"}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            assert not any(n.split(".")[0] in banned_mod for n in names), names
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"sum", "min", "max", "abs", "round"}, node.func.id
    allowed = {"fmt_yi", "fmt_shares"}
    for fn in [n for n in tree.body if isinstance(n, ast.FunctionDef)]:
        for node in ast.walk(fn):
            if isinstance(node, ast.BinOp) and not isinstance(node.op, ast.Add):
                ok = fn.name in allowed and isinstance(node.op, ast.Div)
                assert ok, f"{fn.name}: {type(node.op).__name__}"


# ── P4a：河流圖 ────────────────────────────────────────

def _px_daily(price=38.4):
    d = pd.bdate_range("2024-01-01", "2026-10-30")
    return pd.DataFrame({"date": d, "close": price})


def test_river_用原始價():
    """原始收盤不還原：價格序列＝原始收盤（無股數事件）；EPS 階梯＝當時可見的已公布 4 季（3.84），不因還原下偏。"""
    c = A()
    fr = __import__("screener.river", fromlist=["river_frame"]).river_frame(Q(), _px_daily(), MH(), c, "9999", ASOF)
    f = fr["frame"]
    assert fr["ok"] and fr["metric"] == "pe"
    assert (f["price"] == 38.4).all()
    assert f.loc[f["date"] == T("2025-06-30"), "base"].iloc[0] == pytest.approx(3.84)
    assert fr["note"] == "估值卡三價用近 4 季 EPS，河道用已公布 4 季 EPS，兩者可能不同"   # 合成卡含 1 季試算


def test_river_倍數同估值卡():
    from screener.river import river_frame
    c = A()
    fr = river_frame(Q(), _px_daily(), MH(), c, "9999", ASOF)
    assert fr["mults"] == tuple(c["prices"]["mults"])
    row = fr["frame"].iloc[-1]
    assert row["p50"] == pytest.approx(row["base"] * c["prices"]["mults"][1])
    assert fr["legend"] == "已公布 4 季 EPS × 歷史 20%／50%／80% 本益比"


def test_river_沒有倍數不畫河道():
    from screener.river import river_frame
    c = B()
    fr = river_frame(Q(), _px_daily(), MH(valid_until="2021-12"), c, "9999", ASOF)
    assert fr["mults"] is None and fr["frame"]["p50"].isna().all() and fr["reason"] == c["price_note"]


# ── P4a：體檢 ──────────────────────────────────────────

def test_checklist_pe分位_自建():
    import checklist as cl
    per = pd.DataFrame({"date": pd.date_range("2021-01-01", periods=60, freq="ME"), "per": 5.0, "pbr": 9.0})
    rows = cl.swing_checks({"px": pd.DataFrame(), "per": per, "mh": MH(), "asof": ASOF})
    pe = next(r for r in rows if r["項目"] == "本益比歷史位置（自建）")
    pb = next(r for r in rows if r["項目"] == "股價淨值比歷史位置（自建）")
    assert pe["現值"] == "本益比 16.0 倍（分位 100%）" and pe["門檻"] == "近 5 年分位 ≤ 40%"
    assert pb["現值"] == "股價淨值比 2.00 倍（分位 100%）" and pb["門檻"] == "全歷史分位 ≤ 40%"
    assert not any(r["項目"].startswith(("PE 位於", "PB 位於")) for r in rows)


def test_試算停用顯示白話原因():
    """11/3：卡片放短句、展開區「為什麼沒試算」放白話說明；公式層與後段檢查都適用。"""
    from test_val2_card import REV
    q = Q()
    q.loc[q.index[-1], "gross_profit"] = np.nan
    c = card(q=q, rev=REV("2026-09"))
    assert vv.stop_plain(c) == vv.STOP_PLAIN["毛利或"]
    rows = dict(vv.detail_tables(c)[0].rows)
    assert rows["為什麼沒試算"] == vv.STOP_PLAIN["毛利或"][1]
    jump = card(rev=REV("2026-09", **{"2026-07": 1000.0, "2026-08": 1000.0, "2026-09": 1000.0}))
    assert vv.stop_plain(jump) == vv.STOP_PLAIN["營收劇變"]
    assert vv.stop_plain(card()) is None
