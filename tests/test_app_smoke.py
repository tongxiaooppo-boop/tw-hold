"""版型 B + 深色主題改版後的煙霧測試——app 從真的 data/derived/*.json 渲染不炸。

個股查詢分頁不輸入代號就 return，不會打 bundle 網路。
"""

from __future__ import annotations

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")
AppTest = st_testing.AppTest

REPO_APP = "app/streamlit_app.py"


def _run():
    at = AppTest.from_file(REPO_APP, default_timeout=30)
    at.run()
    return at


def test_app_不丟例外():
    at = _run()
    assert not at.exception


def test_三清單分頁都有標題():
    at = _run()
    heads = " ".join(h.value for h in at.header)
    assert "價值清單" in heads and "定存清單" in heads and "長波段候選池" in heads


def test_卡片HTML有進到頁面():
    at = _run()
    md = " ".join(m.value for m in at.markdown)
    # 版型 B 的 class 應該出現在 st.markdown 注入的 HTML 裡
    assert "thc-card" in md and "thc-hero" in md


def test_render_card_b_單張_不炸():
    import sys
    sys.path.insert(0, "app")
    import streamlit_app as app
    row = {"ticker": "9911", "name": "櫻花", "close": 81.7, "verdict": "推薦",
           "safety_score": 0.585, "cur_yield": 0.0554, "yield_floor": 0.05,
           "est_buy_price": 85.41, "div_years": 12.0, "ret3y_incl": 0.15,
           "fill_rate": None, "buy_note": "支撐位（82.8）已在買點之上 → 等回檔",
           "industry": "其他", "buy_low": None, "buy_high": None}
    html_parts = []
    app.st.markdown = lambda h, **k: html_parts.append(h)   # 攔截
    app._render_card_b(row, "deposit")
    out = html_parts[-1]
    assert "9911" in out and "櫻花" in out and "5.5%" in out
    assert "thc-good" in out and "估值買價" in out
