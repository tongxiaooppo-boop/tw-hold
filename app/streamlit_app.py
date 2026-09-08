"""tw-hold — 三清單 + 個股查詢。

M0.2 骨架：只渲染 `data/derived/*.json`（雲端運算量趨近 0，PRD §8）。
無絕對路徑、雲端可佈署。個股即時補抓 = 本地進階模式（偵測 FINMIND_TOKEN）。

跑：
    streamlit run app/streamlit_app.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st

REPO = Path(__file__).resolve().parents[1]
DERIVED = REPO / "data" / "derived"

#: 本地進階模式：有 FinMind token 才開個股即時補抓（雲端不放 token → 停用）。
LOCAL_ADVANCED = bool(os.environ.get("FINMIND_TOKEN")) or (REPO / ".env").exists()

#: 每個分頁頂部 + 底部都要出現（使用者要求 2026-09-08）。
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


def _load(name: str) -> dict | None:
    p = DERIVED / name
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def _disclaimer(extra: str | None = None) -> None:
    st.warning(DISCLAIMER + (("\n\n" + extra) if extra else ""))


def _fmt_removed(removed: list) -> list[str]:
    out = []
    for r in removed:
        out.append(f"{r['ticker']}（{r.get('reason', '')}）" if isinstance(r, dict) else str(r))
    return out


def _list_page(title: str, payload: dict | None, note: str) -> None:
    _disclaimer()
    st.header(title)
    st.caption(note)
    if payload is None:
        st.info("清單尚未產出——`build_lists.py` / 每日 Action 跑過後這裡才有東西。")
        _disclaimer()
        return
    meta = payload.get("_meta", {})
    bits = []
    if meta.get("trading_date"):
        bits.append(f"資料日期 {meta['trading_date']}")
    if meta.get("period"):
        bits.append(f"本期換股日 {meta['period']}"
                    + ("（成分凍結，只刷新價格/verdict）" if meta.get("frozen")
                       else "（本次重算成分）"))
    bits.append(f"重算 {meta.get('rebuilt_at', '—')}")
    st.caption("　·　".join(bits))
    if meta.get("warning"):
        st.warning(meta["warning"])
    if meta.get("g2_note"):
        st.caption("🔒 " + meta["g2_note"])

    holdings = payload.get("holdings", [])
    if holdings:
        st.subheader(f"本季成分（{len(holdings)} 檔）")
        st.dataframe(pd.DataFrame(holdings), width="stretch")

    changes = payload.get("changes", {})
    if changes.get("added") or changes.get("removed"):
        st.subheader("本季換股（正式變動）")
        if changes.get("turnover_pct") is not None:
            st.caption(f"換手率 {changes['turnover_pct']:.0%}")
        c1, c2 = st.columns(2)
        c1.markdown("**新進**"); c1.write(changes.get("added", []) or "—")
        c2.markdown("**移除（= 出場訊號）**")
        c2.write(_fmt_removed(changes.get("removed", [])) or "—")

    cand = payload.get("candidates", {})
    if cand.get("likely_in") or cand.get("likely_out"):
        st.subheader("候補變動（若今天重選；提示，非正式換股）")
        c1, c2 = st.columns(2)
        c1.markdown("**分數擠進前 15**"); c1.write(cand.get("likely_in", []) or "—")
        c2.markdown("**本季成分掉出前 15**")
        c2.write(_fmt_removed(cand.get("likely_out", [])) or "—")

    _disclaimer()


def _swing_page(payload: dict | None) -> None:
    _disclaimer(SWING_DISCLAIMER)
    st.header("長波段候選池")
    st.caption("CANSLIM（歐尼爾）+ Minervini 趨勢模板，全部寫成「條件成立狀態」。"
               "每週重算。**候選池，不是推薦清單。**")
    if payload is None or not payload.get("candidates_pool"):
        st.info(payload["_meta"].get("pool_note", "候選池尚未產出。")
                if payload else "候選池尚未產出。")
        _disclaimer(SWING_DISCLAIMER)
        return

    meta = payload.get("_meta", {})
    st.caption(f"資料日期 {meta.get('trading_date', '—')}　·　{meta.get('pool_note', '')}"
               f"　·　重算 {meta.get('rebuilt_at', '—')}")

    ch = payload.get("changes", {})
    if ch.get("added") or ch.get("removed"):
        c1, c2 = st.columns(2)
        c1.markdown("**本週新增候選**"); c1.write(ch.get("added", []) or "—")
        c2.markdown("**本週退出候選（條件不再成立）**"); c2.write(ch.get("removed", []) or "—")

    for c in payload["candidates_pool"]:
        with st.container(border=True):
            top = st.columns([1, 1, 1, 1])
            top[0].markdown(f"### {c['ticker']}")
            top[1].metric("現價", c.get("close"))
            top[2].metric("停損參考位", c.get("risk_stop"),
                          f"{(c.get('risk_pct_at_close') or 0):+.0%} 風險")
            top[3].metric("可買上限", c.get("max_buy"))
            s1, s2 = st.columns(2)
            s1.markdown("**支持**")
            s1.write(c.get("support") or ["（未發現額外支持證據）"])
            s2.markdown("**反對**")
            s2.write(c.get("oppose") or ["—"])
            with st.expander("條件成立狀態 + 失效條件檢查表"):
                st.markdown("**進場條件（全部成立才進候選池）**")
                st.dataframe(pd.DataFrame(c.get("conditions", [])), hide_index=True,
                             width="stretch")
                st.markdown("**失效條件（目前狀態；v3.1 不追蹤持倉）**")
                st.dataframe(pd.DataFrame(c.get("invalidation", [])), hide_index=True,
                             width="stretch")
                st.caption(f"距 50MA {(c.get('dist_50ma') or 0):+.0%}　·　"
                           f"距 52 週高 {(c.get('dist_52w_high') or 0):+.0%}　·　"
                           f"距 200MA {(c.get('dist_200ma') or 0):+.0%}")

    _disclaimer(SWING_DISCLAIMER)


def main() -> None:
    st.set_page_config(page_title="tw-hold", layout="wide")
    st.title("tw-hold")
    st.caption("長波段 / 價值 / 定存三清單 + 個股查詢。"
               "**候選 + 為什麼，不是建議。**"
               + ("　·　本地進階模式" if LOCAL_ADVANCED else "　·　雲端唯讀模式"))

    tabs = st.tabs(["價值", "定存", "長波段", "個股查詢"])
    with tabs[0]:
        _list_page("價值清單", _load("value_list.json"),
                   "F-Score ≥ 6 + Magic Formula 精神。月看、季換（3/31、5/15、8/14、11/14），"
                   "前 15、單一產業 ≤ 40%。verdict 只由便宜門檻驅動（§6.3）。")
    with tabs[1]:
        _list_page("定存清單", _load("deposit_list.json"),
                   "殖利率 ≥ 5%（目標 5.5%）+ 硬門檻（含填息率 ≥ 60%、近 3 年含息報酬 ≥ 0），"
                   "季換股，前 15、單一產業 ≤ 40%。買價 = 近 3 年均現金股利 ÷ 殖利率門檻（§7.3）。")
    with tabs[2]:
        _swing_page(_load("swing_list.json"))
    with tabs[3]:
        _disclaimer()
        st.header("個股查詢")
        st.text_input("股票代號", placeholder="2330")
        if not LOCAL_ADVANCED:
            st.info("雲端唯讀模式：只服務前 500 大（bundle 內）。"
                    "即時補抓不在池內的個股是本地進階模式功能。")
        st.info("M4 實作。")
        _disclaimer()


if __name__ == "__main__":
    main()
