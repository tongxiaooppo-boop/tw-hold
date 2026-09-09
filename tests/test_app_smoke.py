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
    # 改成 session_state 導覽後只渲染選中分頁——逐頁切過去確認標題都在。
    at = _run()
    assert "價值清單" in " ".join(h.value for h in at.header)
    for label, want in [("定存", "定存清單"), ("長波段", "長波段候選池")]:
        at.radio(key="_nav").set_value(label).run()
        assert want in " ".join(h.value for h in at.header)


def test_多軌體檢分頁_不輸入代號不炸():
    at = _run()
    at.radio(key="_nav").set_value("多軌體檢").run()
    assert not at.exception
    assert "多軌體檢" in " ".join(h.value for h in at.subheader)


def test_多軌體檢_帶代號_四個分頁都渲染不炸():
    at = AppTest.from_file(REPO_APP, default_timeout=60)
    at.session_state["_nav"] = "多軌體檢"
    at.session_state["_stock_code"] = "2330"
    at.run()
    assert not at.exception
    # 三軌至少要有一張檢核表（dataframe）或明確的 info，不能整頁掛
    assert at.dataframe or any("因子表" in i.value or "資料" in i.value for i in at.info)


def test_兩頁共用代號且可頁內切換():
    at = AppTest.from_file(REPO_APP, default_timeout=30)
    at.session_state["_stock_code"] = "2330"
    at.session_state["_nav"] = "個股查詢"
    at.run()
    assert not at.exception
    # 個股查詢頁應有「→ 多軌體檢」的跳轉鈕；按下去切到多軌體檢，代號不變
    at.button(key="_peer_多軌體檢").click().run()
    assert at.session_state["_nav"] == "多軌體檢"
    assert at.session_state["_stock_code"] == "2330"
    assert "多軌體檢" in " ".join(h.value for h in at.subheader)


def test_代號連結指向個股查詢():
    at = _run()
    md = " ".join(m.value for m in at.markdown)
    assert 'href="?code=' in md and 'target="_self"' in md


def test_query_param_code_切到個股查詢():
    at = AppTest.from_file(REPO_APP, default_timeout=30)
    at.query_params["code"] = "2330"
    at.run()
    assert not at.exception
    assert at.session_state["_nav"] == "個股查詢"
    assert at.session_state["_stock_code"] == "2330"
    assert "code" not in at.query_params  # 用完就清，不然被鎖在該分頁


def test_卡片HTML有進到頁面():
    at = _run()
    md = " ".join(m.value for m in at.markdown)
    # 版型 B 的 class 應該出現在 st.markdown 注入的 HTML 裡
    assert "thc-card" in md and "thc-hero" in md


def test_card_b_html_單張():
    import sys
    sys.path.insert(0, "app")
    import streamlit_app as app
    row = {"ticker": "9911", "name": "櫻花", "close": 81.7, "verdict": "推薦",
           "safety_score": 0.585, "cur_yield": 0.0554, "yield_floor": 0.05,
           "est_buy_price": 85.41, "div_years": 12.0, "ret3y_incl": 0.15,
           "fill_rate": None, "buy_note": "支撐位（82.8）已在買點之上 → 等回檔",
           "industry": "其他", "buy_low": None, "buy_high": None}
    out = app._card_b_html(row, "deposit")
    assert "9911" in out and "櫻花" in out and "5.5%" in out
    assert "thc-good" in out and "估值買價" in out


def test_verdict_cat_定存內嵌數字歸類():
    import sys
    sys.path.insert(0, "app")
    import streamlit_app as app
    assert app._verdict_cat("觀望（現價殖利率 4.4% < 門檻 5.0%）") == "觀望"
    assert app._verdict_cat("推薦") == "推薦"
    assert app._verdict_cat("資料不足（EPS 基準存疑）") == "資料不足"
