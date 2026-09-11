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


def test_主動式ETF分頁_渲染不炸():
    at = _run()
    at.radio(key="_nav").set_value("主動式 ETF").run()
    assert not at.exception
    assert "主動式 ETF 每日動向" in " ".join(h.value for h in at.header)
    # 五檔基金代號都要出現（有訊號或「等隔天」都算）
    blob = " ".join(m.value for m in at.markdown)
    for code in ("00981A", "00403A", "00991A", "00982A", "00992A"):
        assert code in blob


def test_多軌體檢_帶代號_四個分頁都渲染不炸():
    at = AppTest.from_file(REPO_APP, default_timeout=60)
    at.session_state["_nav"] = "多軌體檢"
    at.session_state["_stock_code"] = "2330"
    at.run()
    assert not at.exception
    # 至少要渲染出一張檢核清單（thc-cl HTML）或明確的 info，不能整頁掛
    assert any("thc-cl-row" in m.value for m in at.markdown) or \
        any("因子表" in i.value or "資料" in i.value for i in at.info)


def test_兩頁共用代號且可頁內切換():
    at = AppTest.from_file(REPO_APP, default_timeout=30)
    at.session_state["_stock_code"] = "2330"
    at.session_state["_nav"] = "個股查詢"
    at.run()
    assert not at.exception
    # 頁尾「切到另一頁」是真的 st.button，按下去＝表頭 radio 切分頁、代號不變
    at.button(key="_ft_goto").click().run()
    assert at.session_state["_nav"] == "多軌體檢"
    assert at.session_state["_stock_code"] == "2330"
    assert "多軌體檢" in " ".join(h.value for h in at.subheader)


def test_切頁保留代號():
    at = AppTest.from_file(REPO_APP, default_timeout=30)
    at.session_state["_nav"] = "個股查詢"
    at.session_state["_stock_code"] = "2454"
    at.run()
    assert at.session_state["_code_mirror"] == "2454"         # 非 widget 鏡像有寫入
    # 模擬 Streamlit 切頁把 widget key 清掉，只剩鏡像
    at.session_state["_stock_code"] = ""
    at.query_params["goto"] = "多軌體檢"
    at.run()
    assert at.session_state["_stock_code"] == "2454"          # 從鏡像補回


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


def test_短線分頁_切過去不炸():
    # 來源網路可達與否都要「不丟例外」：拉不到 → st.error，拉得到 → 卡片。
    at = AppTest.from_file(REPO_APP, default_timeout=40)
    at.session_state["_nav"] = "短線"
    at.run()
    assert not at.exception
    assert "短線清單（tw-swing）" in " ".join(h.value for h in at.header)
    txt = " ".join([m.value for m in at.markdown]
                   + [e.value for e in at.error] + [i.value for i in at.info])
    assert ("thc-card" in txt) or ("拉不到" in txt) or ("無訊號" in txt)


def test_short_b_html_單張():
    import sys
    sys.path.insert(0, "app")
    import streamlit_app as app
    c = {"ticker": "6672.TW", "name": "騰輝電子-KY", "pool_label": "一號池 · 核心",
         "signal": "領先股回檔進場", "signal_date": "2026-09-07", "entry": 299.5,
         "stop": 250.29, "risk_pct": 0.164, "position_pct": 0.03, "rs_rank": 0.966,
         "vol_ratio": 3.07, "note": "回測 MA50 帶量彈"}
    out = app._short_b_html(c)
    assert "6672.TW" in out and "?code=6672" in out       # 連結去掉 .TW 後綴
    assert "騰輝電子-KY" in out and "領先股回檔進場" in out
    assert "thc-card" in out


def test_active_chip_與_evidence():
    import sys
    sys.path.insert(0, "app")
    import streamlit_app as app
    buy = {"kind": "consensus_buy", "net_shares": 1803000, "issuer_count": 2,
           "consensus": 3, "consensus_strong": True}
    assert "認養" in app._active_chip(buy) and "×3" in app._active_chip(buy)
    sup, opp = app._active_evidence(buy)
    assert "淨買超" in sup and "+1,803 張" in sup and opp == ""
    sell = {"kind": "sell", "net_shares": -500000, "issuer_count": 1, "consensus": 0}
    s2, o2 = app._active_evidence(sell)
    assert s2 == "" and "淨賣超" in o2 and "500 張" in o2
    assert app._active_chip(None) == "" and app._active_chip({"kind": "neutral"}) == ""


def test_active_flags_過期回空():
    import sys
    sys.path.insert(0, "app")
    import streamlit_app as app
    # _active_flags 讀 data/derived/active_etf_flags.json；schema 壞 → {}
    d = app._load("active_etf_flags.json")
    assert d is not None                       # rebuild 產物在 repo 裡
    # 不論其新舊，函式不能炸、回傳 dict
    assert isinstance(app._active_flags(), dict)


def test_verdict_cat_定存內嵌數字歸類():
    import sys
    sys.path.insert(0, "app")
    import streamlit_app as app
    assert app._verdict_cat("觀望（現價殖利率 4.4% < 門檻 5.0%）") == "觀望"
    assert app._verdict_cat("推薦") == "推薦"
    assert app._verdict_cat("資料不足（EPS 基準存疑）") == "資料不足"


def test_旗標文案跟著實際跨幾個交易日走():
    """2026-09-11 迴歸：某檔基金漏抓一天時它的差分跨 2 個交易日，文案不能寫死
    「近一日」（旗標的 span_days 由 build_active_etf_flags 算）。"""
    import sys
    sys.path.insert(0, "app")
    import streamlit_app as app
    one = {"kind": "buy", "net_shares": 30000, "issuer_count": 1, "consensus": 0,
           "span_days": 1}
    two = {**one, "span_days": 2}
    assert "近一日淨買超" in app._active_evidence(one)[0]
    assert "近 2 個交易日淨買超" in app._active_evidence(two)[0]
    # 舊格式（沒有 span_days）→ 退回「近一日」，不炸
    assert "近一日" in app._active_evidence({k: v for k, v in one.items()
                                            if k != "span_days"})[0]


def test_複製給AI_比率換算成百分比且不吐python_repr():
    """這份是要貼給別的 AI 讀的：0.27 必須寫成 +27%（不然 AI 分不出 27% / 0.27%），
    條件表 / 支持反對要展開成條列，不能是 Python repr（2026-09-11 修）。"""
    import sys
    sys.path.insert(0, "app")
    import streamlit_app as app
    rows = [{"ticker": "1560", "name": "中砂", "c_eps_yoy": True,
             "revenue_yoy": 0.2656, "dist_50ma": 0.0575, "close": 733.0,
             "conditions": [{"項": "ROE > 15%", "狀態": "成立"}],
             "support": ["季 EPS YoY +92%"], "oppose": []}]
    out = app._copy_for_ai("長波段候選池", {"trading_date": "2026-09-10"}, rows)
    assert "月營收 YoY: 26.6%" in out and "距 50MA: 5.8%" in out
    assert "{'" not in out and "[{" not in out        # 沒有 Python repr
    assert "      - 項 ROE > 15%　狀態 成立" in out
    assert "c_eps_yoy" not in out                     # 跟條件表重複 → 不印
    assert out.splitlines()[3] == "- 1560 中砂"        # 沒 verdict 就不留空的「｜」


def test_複製給AI_有verdict時保留():
    import sys
    sys.path.insert(0, "app")
    import streamlit_app as app
    out = app._copy_for_ai("價值清單", {"trading_date": "2026-09-10"},
                           [{"ticker": "2330", "name": "台積電", "verdict": "觀望（無安全邊際）",
                             "roe": 0.3}])
    assert "- 2330 台積電｜觀望（無安全邊際）" in out and "ROE: 30.0%" in out
