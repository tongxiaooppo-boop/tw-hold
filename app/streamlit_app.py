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


def _load(name: str) -> dict | None:
    p = DERIVED / name
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def _list_page(title: str, payload: dict | None, note: str) -> None:
    st.header(title)
    st.caption(note)
    if payload is None:
        st.info("清單尚未產出——`build_factors.py` / 每日 Action 跑過後這裡才有東西。")
        return
    meta = payload.get("_meta", {})
    if meta.get("trading_date"):
        st.caption(f"資料日期：{meta['trading_date']}　·　重算：{meta.get('rebuilt_at', '—')}")
    holdings = payload.get("holdings", [])
    if holdings:
        st.subheader("成分")
        st.dataframe(pd.DataFrame(holdings), width="stretch")
    changes = payload.get("changes", {})
    if changes:
        c1, c2 = st.columns(2)
        c1.subheader("新進"); c1.write(changes.get("added", []) or "—")
        c2.subheader("移除（= 出場訊號）"); c2.write(changes.get("removed", []) or "—")


def main() -> None:
    st.set_page_config(page_title="tw-hold", layout="wide")
    st.title("tw-hold")
    st.caption("長波段 / 價值 / 定存三清單 + 個股查詢。"
               "**候選 + 為什麼，不是建議。**"
               + ("　·　本地進階模式" if LOCAL_ADVANCED else "　·　雲端唯讀模式"))

    tabs = st.tabs(["價值", "定存", "長波段", "個股查詢"])
    with tabs[0]:
        _list_page("價值清單", _load("value_list.json"),
                   "F-Score ≥ 6 + Magic Formula 精神，季換股（3/6/9/12）。")
    with tabs[1]:
        _list_page("定存清單", _load("deposit_list.json"),
                   "殖利率 ≥ 5%（目標 5.5%）+ 七道硬門檻，季換股。"
                   "⚠️ U3 universe 修正前定存線是壞的（PRD §7、M0_HANDOFF §3）。")
    with tabs[2]:
        _list_page("長波段清單", _load("swing_list.json"),
                   "主動擇時、持有 2–12 週、每日重算、進場前寫死出場規則。")
    with tabs[3]:
        st.header("個股查詢")
        st.text_input("股票代號", placeholder="2330")
        if not LOCAL_ADVANCED:
            st.info("雲端唯讀模式：只服務前 500 大（bundle 內）。"
                    "即時補抓不在池內的個股是本地進階模式功能。")
        st.info("M4 實作。")


if __name__ == "__main__":
    main()
