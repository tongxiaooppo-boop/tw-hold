"""鎖住引擎、估值資料與畫面共用欄位。"""
import ast
import importlib
import sys
from pathlib import Path

import pytest

from test_val_card import _qf, _rev, _px, _per, _cls
from screener import val_card as vc

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sa = importlib.import_module("streamlit_app")


class Display:
    def __init__(self):
        self.text = []
    def markdown(self, value, **kwargs):
        self.text.append(value)
    def caption(self, value, **kwargs):
        self.text.append(value)


@pytest.mark.parametrize("end", ["2025-12", "2026-01", "2026-04"])
def test_卡片與展開區EPS同源(monkeypatch, end):
    q = _qf()
    q.loc[q.index[-1], ["ni_parent", "net_income", "eps"]] = [13.2, 13.2, 1.32]
    q.loc[q.index[-1], "op_income"] = q.loc[q.index[-5], "op_income"] * 1.2      # 營業利益年增（未來 4 季成長條件）
    rev = _rev(end)
    rev.loc[rev.index[-12:], "revenue"] = 39.6
    c = vc.build_card(q, rev, _px(), _per(), _cls())
    nc = c["eps"]
    assert nc["future_status"] == "ok"
    eps_keys = ("eps_ttm", "eps_nc", "eps_future")
    for key, detail in zip(eps_keys, ("ttm_quarters", "nc_quarters", "future_quarters")):
        assert nc[key] == pytest.approx(sum(x["eps"] for x in nc[detail]), abs=1e-9, rel=0)
    # 用記錄 formatter 鎖卡片原始數值，避免四捨五入遮蔽差異。
    seen = []
    def fmt(value, *args):
        seen.append(value)
        return str(value)
    monkeypatch.setattr(sa, "_fmt_x", fmt)
    lines = sa._card_eps_lines(nc)
    assert seen == [nc["eps_future"], nc["eps_ttm"], nc["eps_nc"]]
    assert len(lines) == 3
    display, tables = Display(), []
    monkeypatch.setattr(sa, "st", display)
    monkeypatch.setattr(sa, "_vtable", lambda headers, rows, *args: tables.append((headers, rows)))
    sa._eps_quarter_tables(nc)
    for key in ("eps_nc", "eps_future"):
        assert any(str(nc[key]) in t for t in display.text)
    quarter_tables = [rows for headers, rows in tables if headers == ["季", "類別", "EPS"]]
    assert [sum(float(row[2]) for row in rows) for rows in quarter_tables] == pytest.approx(
        [nc["eps_nc"], nc["eps_future"]], abs=1e-9, rel=0)


@pytest.mark.parametrize("end", ["2025-12", "2026-01", "2026-04"])
def test_股價同源(end):
    c = vc.build_card(_qf(), _rev(end), _px(), _per(), _cls())
    f = c["forward"]
    text = sa._card_lines(c)
    for key in ("rolling", "reported"):
        value = f[key]
        assert value["base"] == pytest.approx(value["eps"] * 15, abs=1e-9, rel=0)
        assert f"{value['base']:,.1f}" in text
    assert f["ref_price"] == pytest.approx(f["rolling"]["base"] / 1.10, abs=1e-9, rel=0)
    assert f"{f['ref_price']:,.1f}" in text


def test_畫面不含舊名詞():
    root = Path(__file__).resolve().parents[1]
    for file in ("app/streamlit_app.py", "screener/val_card.py", "screener/detect.py", "screener/eps_nowcast.py"):
        tree = ast.parse((root / file).read_text(encoding="utf-8"))
        # 已知暫留（HANDOFF A19）：① 買進區間停用中（valuation.BUY_RANGE_PAUSED），_buy_lines 與「沒有成長價」不會顯示；
        # ② 月營收分頁 _rev_view_value 仍用舊 valuation.estimate，換新引擎是第二階段。兩者處理完要移除這個排除。
        skip = {id(n) for f in ast.walk(tree) if isinstance(f, ast.FunctionDef) and f.name in ("_buy_lines", "_rev_view_value")
                for n in ast.walk(f)}
        for node in ast.walk(tree):
            if id(node) in skip or (isinstance(node, ast.Constant) and node.value == "沒有成長價"):
                continue
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                # 文件字串與註解不會顯示；只檢查可執行字串。
                if any(isinstance(parent, ast.Expr) and parent.value is node for parent in ast.walk(tree)):
                    continue
                if '<style>' in node.value:
                    continue
                assert not any(word in node.value for word in ("F4", "前瞻股價", "已公布 TTM", "年化試算", "今年預估", "成長價", "12 個月基準價", "EPS_NC", "滾動獲利估值價", "已公布獲利估值價", "近四季實際")), (file, node.lineno, node.value)


def test_畫面不自己算推導():
    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / "app/streamlit_app.py").read_text(encoding="utf-8"))
    names = {"_card_eps_lines", "_card_lines", "_card_block", "_eps_quarter_tables", "_valuation_block"}
    for func in tree.body:
        if not isinstance(func, ast.FunctionDef) or func.name not in names:
            continue
        for node in ast.walk(func):
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
                pytest.fail(f"{func.name}:{node.lineno} 畫面自行相乘")


def test_現價倍數與歷史中位倍數同源():
    c = vc.build_card(_qf(), _rev(), _px(), _per(), _cls())
    f = c["forward"]
    assert f["implied_pe"] == pytest.approx(c["price"] / f["rolling"]["eps"], abs=1e-9, rel=0)
    assert f["mult_p50"] == pytest.approx(f["rolling"]["base"] / f["rolling"]["eps"], abs=1e-9, rel=0)   # 與合理價同一個倍數
    assert "口徑不完全相同" in sa._card_explain(c)


def test_倍數行讀引擎欄位且與三價一致():
    c = vc.build_card(_qf(), _rev(), _px(), _per(), _cls())
    line = sa._mult_line(c)
    cp = c["band"]["capped"]
    for key in ("p20", "p50", "p80"):
        assert f"{cp[key]:.1f}" in line
    assert c["prices"]["fair"] == pytest.approx(c["prices"]["base"] * cp["p50"], abs=1e-9, rel=0)
    assert c["band"]["years"] in (None, 3, 5) and ("全部歷史" in line or f"近 {c['band']['years']} 年" in line)
    assert "P20" not in line and "P50" not in line
