"""tw-hold — 三清單 + 個股查詢。

只渲染 `data/derived/*.json`（雲端運算量趨近 0，PRD §8）。無絕對路徑、雲端可佈署。
個股即時補抓 = 本地進階模式（偵測 FINMIND_TOKEN）。

跑：
    streamlit run app/streamlit_app.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

REPO = Path(__file__).resolve().parents[1]
DERIVED = REPO / "data" / "derived"
# Streamlit Cloud 只把 app/ 放進 sys.path——把 repo 根也加進去，factors / fetch_bundle
# / screener 這些頂層模組才 import 得到。
for _p in (str(REPO), str(REPO / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

LOCAL_ADVANCED = bool(os.environ.get("FINMIND_TOKEN")) or (REPO / ".env").exists()

DISCLAIMER = (
    "**這不是投資建議。** tw-hold 是決策支援工具：給候選標的 + 判斷依據（支持／反對／"
    "風險量化），**買賣由你決定**。所有數字可能有誤、可能過期、有生存者偏差；"
    "verdict／買價是規則算出來的，不是預測。真金下單前自己再查一次。"
)
SWING_DISCLAIMER = (
    "🔴 **長波段候選池沒有回測支撐**——這是風控算術，不是驗證過的買點。只回答"
    "「這個進場點承擔多少風險」，**不回答「會不會賺」**。不給 verdict、不給買價、"
    "不排名次。"
)

#: 英文欄名 → 中文（明細表 / 複製給 AI 用）
LABELS = {
    "ticker": "代號", "name": "名稱", "industry": "產業", "close": "現價",
    "verdict": "verdict", "value_score": "價值分數", "safety_score": "存股安全分",
    "f_score": "F-Score", "roe": "ROE", "norm_pe": "normalized PE",
    "norm_ey": "normalized 盈餘殖利率", "fcf_yield": "FCF 殖利率", "ev_ebit": "EV/EBIT",
    "net_cash_to_mktcap": "淨現金/市值", "gross_margin": "毛利率",
    "cheap_threshold": "便宜門檻", "valuation_ceiling": "估值上緣", "upside_pct": "空間%",
    "cyclical_peak_flag": "循環高峰旗標", "eps_basis_suspect": "EPS 基準存疑",
    "pe_p30": "PE P30", "pe_p70": "PE P70", "pe_market": "市場 PE",
    "buy_low": "買區下界", "buy_high": "買區上界", "buy_note": "買區備註",
    "reject_reason": "剔除原因", "cur_yield": "現價殖利率", "yield_floor": "殖利率門檻",
    "est_buy_price": "估值買價", "fill_rate": "近5年填息率", "ret3y_incl": "近3年含息報酬",
    "avg_yield_3y": "近3年均殖利率", "avg_yield_5y": "近5年均殖利率",
    "yield_pctile_5y": "殖利率5年分位", "div_years": "連續配息年", "last_cash_dividend": "近一次現金股利",
    "ann_vol": "年化週波動", "payout_ratio_ttm": "配息率TTM", "cyclical_penalty": "景氣循環懲罰",
    "debt_ratio": "負債比",
}
PCT_FIELDS = {"roe", "fcf_yield", "norm_ey", "gross_margin", "upside_pct", "cur_yield",
              "yield_floor", "fill_rate", "ret3y_incl", "avg_yield_3y", "avg_yield_5y",
              "yield_pctile_5y", "net_cash_to_mktcap", "payout_ratio_ttm", "debt_ratio"}

# 卡片臉上顯示的欄位（其餘收進明細）
FACE = {
    "value": ["close", "cheap_threshold", "upside_pct", "value_score"],
    "deposit": ["close", "cur_yield", "est_buy_price", "fill_rate"],
}
SORT_KEYS = {
    "value": {"價值分數": "value_score", "空間%": "upside_pct", "現價": "close"},
    "deposit": {"存股安全分": "safety_score", "現價殖利率": "cur_yield", "現價": "close"},
}


def _load(name: str) -> dict | None:
    p = DERIVED / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _disclaimer(extra: str | None = None) -> None:
    st.warning(DISCLAIMER + (("\n\n" + extra) if extra else ""))


def _fmt(field: str, v) -> str:
    if v is None or v == "":
        return "—"
    if isinstance(v, bool):
        return "是" if v else "否"
    if isinstance(v, (int, float)):
        return f"{v * 100:.1f}%" if field in PCT_FIELDS else f"{v:,.2f}"
    return str(v)


def _fmt_removed(removed: list) -> list[str]:
    return [f"{r['ticker']}（{r.get('reason', '')}）" if isinstance(r, dict) else str(r)
            for r in removed]


def _bullets(items: list, empty: str = "—") -> str:
    """list → markdown 條列（取代醜的 st.write(list) JSON 樹）。"""
    items = [x for x in (items or []) if x not in (None, "")]
    return "\n".join(f"- {x}" for x in items) if items else empty


def _verdict_icon(v: str) -> str:
    if not v:
        return ""
    if v.startswith("推薦"):
        return "🟢"
    if v.startswith("觀望"):
        return "🟡"
    return "⚪"


def _copy_for_ai(title: str, meta: dict, rows: list[dict]) -> str:
    lines = [f"# {title}（tw-hold，資料日期 {meta.get('trading_date', '—')}）",
             "※ 候選 + 判斷依據，非投資建議。", ""]
    for r in rows:
        head = f"- {r.get('ticker')} {r.get('name', '')}｜{r.get('verdict', '')}"
        lines.append(head)
        for k, v in r.items():
            if k in ("ticker", "name", "verdict") or v in (None, ""):
                continue
            lines.append(f"    {LABELS.get(k, k)}: {_fmt(k, v)}")
    return "\n".join(lines)


def _detail_table(r: dict, skip: set[str]) -> pd.DataFrame:
    return pd.DataFrame(
        [(LABELS.get(k, k), _fmt(k, v)) for k, v in r.items()
         if k not in skip and not isinstance(v, (list, dict))],
        columns=["項目", "值"])


def _card_list(kind: str, title: str, payload: dict | None, note: str) -> None:
    _disclaimer()
    st.header(title)
    st.caption(note)
    if payload is None:
        st.info("清單尚未產出。")
        _disclaimer()
        return

    meta = payload.get("_meta", {})
    bits = [f"資料日期 {meta.get('trading_date', '—')}"]
    if meta.get("period"):
        bits.append(f"本期換股日 {meta['period']}"
                    + ("（成分凍結）" if meta.get("frozen") else "（本次重算）"))
    bits.append(f"重算 {meta.get('rebuilt_at', '—')}")
    st.caption("　·　".join(bits))
    if meta.get("warning"):
        st.warning(meta["warning"])
    if meta.get("g2_note"):
        st.caption("🔒 " + meta["g2_note"])

    holdings = payload.get("holdings", [])
    verdicts = sorted({h.get("verdict", "") for h in holdings})
    c1, c2 = st.columns([2, 1])
    pick = c1.multiselect("篩選 verdict", verdicts, default=verdicts)
    sort_label = c2.selectbox("排序", list(SORT_KEYS[kind]))
    sk = SORT_KEYS[kind][sort_label]
    rows = [h for h in holdings if h.get("verdict", "") in pick]
    rows.sort(key=lambda h: (h.get(sk) is None, -(h.get(sk) or 0)))

    st.subheader(f"本季成分（{len(rows)}/{len(holdings)} 檔）")
    for r in rows:
        with st.container(border=True):
            head = st.columns([3, 2, 2, 2, 2])
            flags = ("　⚠循環高位" if r.get("cyclical_peak_flag") else "") + \
                    ("　⚠EPS存疑" if r.get("eps_basis_suspect") else "")
            head[0].markdown(f"### {r.get('ticker')} {r.get('name', '')}\n"
                             f"{_verdict_icon(r.get('verdict', ''))} {r.get('verdict', '')}{flags}")
            for col, field in zip(head[1:], FACE[kind]):
                col.metric(LABELS.get(field, field), _fmt(field, r.get(field)))
            bl, bh, bn = r.get("buy_low"), r.get("buy_high"), r.get("buy_note")
            if bl and bh:
                st.markdown(f"**買入區間**：{bl:,.2f} – {bh:,.2f}")
            elif bn:
                st.markdown(f"**買入區間**：{bn}")
            with st.expander("明細"):
                st.dataframe(_detail_table(r, {"ticker", "name"}),
                             hide_index=True, width="stretch")

    changes = payload.get("changes", {})
    if changes.get("added") or changes.get("removed"):
        st.subheader("本季換股（正式變動）")
        if changes.get("turnover_pct") is not None:
            st.caption(f"換手率 {changes['turnover_pct']:.0%}")
        cc = st.columns(2)
        cc[0].markdown("**新進**\n\n" + _bullets(changes.get("added")))
        cc[1].markdown("**移除（= 出場訊號）**\n\n" + _bullets(_fmt_removed(changes.get("removed", []))))

    cand = payload.get("candidates", {})
    if cand.get("likely_in") or cand.get("likely_out"):
        st.subheader("候補變動（若今天重選；提示，非正式換股）")
        cc = st.columns(2)
        cc[0].markdown("**擠進前 15**\n\n" + _bullets(cand.get("likely_in")))
        cc[1].markdown("**掉出前 15**\n\n" + _bullets(_fmt_removed(cand.get("likely_out", []))))

    with st.expander("複製給 AI"):
        st.code(_copy_for_ai(title, meta, rows), language="markdown")

    _disclaimer()


def _swing_page(payload: dict | None) -> None:
    _disclaimer(SWING_DISCLAIMER)
    st.header("長波段候選池")
    st.caption("CANSLIM（歐尼爾）+ Minervini 趨勢模板，全部寫成「條件成立狀態」。"
               "每週重算。**候選池，不是推薦清單。**")
    if payload is None or not payload.get("candidates_pool"):
        st.info((payload or {}).get("_meta", {}).get("pool_note", "候選池尚未產出。"))
        _disclaimer(SWING_DISCLAIMER)
        return

    meta = payload.get("_meta", {})
    st.caption(f"資料日期 {meta.get('trading_date', '—')}　·　{meta.get('pool_note', '')}"
               f"　·　重算 {meta.get('rebuilt_at', '—')}")

    chg = payload.get("changes", {})
    if chg.get("added") or chg.get("removed"):
        cc = st.columns(2)
        cc[0].markdown("**本週新增候選**\n\n" + _bullets(chg.get("added")))
        cc[1].markdown("**本週退出候選（條件不再成立）**\n\n" + _bullets(chg.get("removed")))

    for c in payload["candidates_pool"]:
        with st.container(border=True):
            top = st.columns([3, 2, 2, 2])
            top[0].markdown(f"### {c['ticker']}　{c.get('name', '')}\n{c.get('industry', '')}")
            top[1].metric("現價", _fmt("close", c.get("close")))
            top[2].metric("停損參考位", _fmt("close", c.get("risk_stop")),
                          f"{(c.get('risk_pct_at_close') or 0):+.0%} 風險")
            top[3].metric("可買上限", _fmt("close", c.get("max_buy")))
            s1, s2 = st.columns(2)
            s1.markdown("**支持**\n\n" + _bullets(c.get("support"), "（未發現額外支持證據）"))
            s2.markdown("**反對**\n\n" + _bullets(c.get("oppose")))
            with st.expander("條件成立狀態 + 失效條件檢查表"):
                st.markdown("**進場條件（全部成立才進候選池）**")
                st.dataframe(pd.DataFrame(c.get("conditions", [])), hide_index=True, width="stretch")
                st.markdown("**失效條件（目前狀態；v3.1 不追蹤持倉）**")
                st.dataframe(pd.DataFrame(c.get("invalidation", [])), hide_index=True, width="stretch")
                st.caption(f"距 50MA {(c.get('dist_50ma') or 0):+.0%}　·　"
                           f"距 52 週高 {(c.get('dist_52w_high') or 0):+.0%}　·　"
                           f"距 200MA {(c.get('dist_200ma') or 0):+.0%}")

    with st.expander("複製給 AI"):
        st.code(_copy_for_ai("長波段候選池", meta, payload["candidates_pool"]),
                language="markdown")
    _disclaimer(SWING_DISCLAIMER)


@st.cache_resource(show_spinner="第一次載入：從 tw-swing Release 拉 bundle…")
def _ensure_bundle():
    from bundle_data import ensure_assets
    return ensure_assets()


@st.cache_data(ttl=3600, show_spinner=False)
def _stock_data(code: str) -> dict:
    import bundle_data as bd
    from factors.factors import quarterly_factors
    px, per, fin, div = (bd.prices(code), bd.per_history(code),
                         bd.financials(code), bd.dividends(code))
    qf = quarterly_factors(fin) if not fin.empty else fin
    return {"px": px, "per": per, "fin": fin, "div": div, "qf": qf}


def _stock_page() -> None:
    import charts as ch
    _disclaimer()
    st.header("個股查詢")
    st.caption("攤開數據讓人／AI 判斷，**不打分、不給買賣建議**（PRD §4.1）。"
               "雲端只服務 bundle 內的股票（前 ~500 大 + 定存宇宙）。")
    code = st.text_input("股票代號", placeholder="2330").strip()
    if not code:
        _disclaimer()
        return

    got = _ensure_bundle()
    if not any(got.values()):
        st.error("拉不到 bundle——雲端需要 `TWSWING_BUNDLE_PAT`（st.secrets），本地需要 `.env`。")
        _disclaimer()
        return

    d = _stock_data(code)
    if d["px"].empty and d["fin"].empty:
        st.warning(f"{code} 不在 bundle 內。"
                   + ("本地進階模式可即時補抓（尚未實作）。" if LOCAL_ADVANCED
                      else "雲端唯讀模式只服務 bundle 內的股票。"))
        _disclaimer()
        return

    name = code
    if not d["px"].empty:
        st.plotly_chart(ch.kline(d["px"], name), width='stretch')
        if not d["per"].empty:
            st.plotly_chart(ch.pe_river(d["px"], d["per"], name), width='stretch')

    if not d["qf"].empty:
        c1, c2 = st.columns(2)
        c1.plotly_chart(ch.quarterly_eps(d["qf"], name), width='stretch')
        c2.plotly_chart(ch.margins(d["qf"], name), width='stretch')
        st.plotly_chart(ch.cashflow(d["qf"], name), width='stretch')

    if not d["div"].empty:
        st.plotly_chart(ch.dividends_chart(d["div"], name), width='stretch')

    st.info("📊 月營收走勢圖：bundle 目前只有單月快照，歷史圖待 revenue 歷史併入 bundle。")

    if not d["qf"].empty:
        st.subheader("Piotroski F-Score 9 分項")
        st.caption("**只打勾、不加總、不當買賣依據。** 加總分數在價值清單裡當品質門檻，"
                   "這裡是診斷用。")
        st.dataframe(ch.fscore_table(d["qf"]), hide_index=True, width="stretch")

    with st.expander("原始季度數據"):
        st.dataframe(d["qf"] if not d["qf"].empty else d["fin"], width="stretch")

    _disclaimer()


def main() -> None:
    st.set_page_config(page_title="tw-hold", layout="wide")
    st.title("tw-hold")
    st.caption("長波段 / 價值 / 定存三清單 + 個股查詢。**候選 + 為什麼，不是建議。**"
               + ("　·　本地進階模式" if LOCAL_ADVANCED else "　·　雲端唯讀模式"))

    tabs = st.tabs(["價值", "定存", "長波段", "個股查詢"])
    with tabs[0]:
        _card_list("value", "價值清單", _load("value_list.json"),
                   "F-Score ≥ 6 + Magic Formula 精神。月看、季換（3/31、5/15、8/14、11/14），"
                   "前 15、單一產業 ≤ 40%。verdict 只由便宜門檻驅動（§6.3）。")
    with tabs[1]:
        _card_list("deposit", "定存清單", _load("deposit_list.json"),
                   "殖利率 ≥ 5%（目標 5.5%）+ 硬門檻（含填息率 ≥ 60%、近 3 年含息報酬 ≥ 0），"
                   "季換股，前 15、單一產業 ≤ 40%。買價 = 近 3 年均現金股利 ÷ 殖利率門檻（§7.3）。")
    with tabs[2]:
        _swing_page(_load("swing_list.json"))
    with tabs[3]:
        _stock_page()


if __name__ == "__main__":
    main()
