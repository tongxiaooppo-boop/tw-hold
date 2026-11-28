"""回測報告分頁（2026-11-28 使用者要求）：上面放研究報告，下面放 app 其他分頁的回測報告。

- 研究報告：`app/reports/*.md` 靜態檔，`REPORTS` 決定順序。
- 其他回測報告：直接讀 `streamlit_app.BACKTEST_NOTES` 的 "backtest" 欄（原頁面照舊顯示，這裡不複製文字）。
- 每份報告都放展開區，點開才看得到全部（之後還會加報告）。
"""
from __future__ import annotations

from html import escape as _esc
from pathlib import Path

REPORT_DIR = Path(__file__).resolve().parent / "reports"

#: (標題, 檔名, 一行說明)；順序即顯示順序
REPORTS: list[tuple[str, str, str]] = [
    ("市值型 ETF 加碼①：找策略（每段大跌一份預算）", "etf_addon_1_search.md",
     "0050，59 個方案比「什麼時候加碼比較不傷」，挑出三個候選；含逐段明細、指標與均線統計。2026-11-28"),
    ("市值型 ETF 加碼②：每年年初一筆錢的帳戶回測", "etf_addon_2_account.md",
     "0050，三個候選＋年初全買，投入 10/20/30/40%；另計 -20%＋國安基金；含每一筆買進。2026-11-28"),
    ("市值型 ETF 加碼③：投入比例怎麼分", "etf_addon_3_weights.md",
     "0050，8 組比例 × 三策略與 59 方案重測；每級觸發幾年；隨機日期測試分批時機有沒有加分。2026-11-28"),
]

#: 頁首「目前建議」：(狀態燈號 sev, 燈號文字, 一句話, [(數字, 說明)])；None＝不顯示
VERDICT: tuple[str, str, str, list[tuple[str, str]]] | None = (
    "warn", "待你拍板",
    "0050 加碼四級比例建議從 10/20/30/40 改成 0/20/30/50（保守可用 0/0/50/50）。減傷靠比例，不靠訊號挑時機。",
    [("-47.2% → -45.2%", "最大回撤（2006 起）"), ("-0.15 個百分點", "年化代價"), ("17/20 年", "第 1 級觸發")],
)

#: 每份研究報告的重點卡（key＝檔名）：(燈號 sev, 燈號文字, 大數字, 大數字說明, 一句結論, [(數字, 說明)])
#: 數字照抄報告本文，改報告時一起改（test_回測報告分頁 會檢查每份報告都有卡）。
CARDS: dict[str, tuple[str, str, str, str, str, list[tuple[str, str]]]] = {
    "etf_addon_1_search.md": (
        "neutral", "找候選", "+13.0%", "你的做法・佔預算一年報酬",
        "贏你的方案主要贏在 2020、2025 兩次急殺；拿掉之後差距很小。最穩的是「跌幅＋確認」。",
        [("+20.3%", "月線乖離"), ("+4.1% / +4.6%", "去急殺：你／月線"), ("-2.3%", "跌幅＋確認 最差一段")]),
    "etf_addon_2_account.md": (
        "neutral", "帳戶回測", "+15.9%", "S1 你的做法・年化（2006 起）",
        "三個策略年化都比年初全買少 0.3～2 個百分點，換到的是大跌年少虧。S1 報酬最好。",
        [("+16.2%", "年初全買"), ("-36.8% / -43.2%", "2008：S1／全買"), ("+16.3%", "S1 加國安基金")]),
    "etf_addon_3_weights.md": (
        "good", "建議", "0/20/30/50", "四級比例（待拍板）",
        "前兩級幾乎年年觸發，等於沒擇時。隨機日期測試：時機能多賺、不能少虧，少虧要靠後重比例。",
        [("100%", "年化勝過隨機日"), ("27～67%", "回撤勝過隨機日"), ("17/20 年", "第 1 級觸發")]),
}


def _chips(items: list[tuple[str, str]]) -> str:
    return "".join(f'<span class="thc-chip">{_esc(c)} <b>{_esc(v)}</b></span>' for v, c in items)


def verdict_html(v=VERDICT) -> str:
    if not v:
        return ""
    sev, pill, text, items = v
    return (f'<div class="thc-card thc-{sev} rp-verdict"><div class="thc-stripe"></div><div class="thc-body">'
            f'<div class="thc-head"><span class="rp-eyebrow">目前建議</span>'
            f'<span class="thc-pill thc-{sev}">{_esc(pill)}</span></div>'
            f'<div class="rp-line">{_esc(text)}</div><div class="thc-chips">{_chips(items)}</div></div></div>')


def card_html(title: str, fname: str) -> str:
    c = CARDS.get(fname)
    if not c:
        return ""
    sev, pill, big, cap, line, items = c
    short = title.split("：", 1)[-1]
    num = title.split("：", 1)[0][-1] if "：" in title else ""
    return (f'<div class="thc-card thc-{sev} rp-card"><div class="thc-stripe"></div><div class="thc-body">'
            f'<div class="thc-head"><span class="rp-no">{_esc(num)}</span><span class="thc-cn">{_esc(short)}</span>'
            f'<span class="thc-pill thc-{sev}">{_esc(pill)}</span></div>'
            f'<div class="thc-hero"><span class="thc-big">{_esc(big)}</span><span class="thc-cap">{_esc(cap)}</span></div>'
            f'<div class="rp-line">{_esc(line)}</div><div class="thc-chips">{_chips(items)}</div></div></div>')

#: BACKTEST_NOTES 的 key → 顯示名稱（順序即顯示順序）；沒有 "backtest" 欄的自動略過
APP_BACKTESTS: list[tuple[str, str]] = [
    ("short", "短線"),
    ("swing", "長波段"),
    ("value", "價值"),
    ("deposit", "定存"),
]


def read_report(fname: str) -> str:
    p = REPORT_DIR / fname
    return p.read_text(encoding="utf-8") if p.exists() else f"（找不到報告檔 `{fname}`）"


def app_backtests(notes: dict) -> list[tuple[str, str]]:
    """回傳 [(顯示名稱, markdown)]，只收有回測內容的分頁。"""
    return [(label, notes[k]["backtest"]) for k, label in APP_BACKTESTS
            if k in notes and notes[k].get("backtest")]


def render(st, notes: dict) -> None:
    with st.container(key="report_page"):
        st.subheader("回測報告")
        st.caption("每份報告點開看全部。數字是研究當時的結果，不會每天重算。")
        if VERDICT:
            st.markdown(verdict_html(), unsafe_allow_html=True)
        st.markdown("#### 研究報告")
        for title, fname, desc in REPORTS:
            st.markdown(card_html(title, fname), unsafe_allow_html=True)
            with st.expander(f"看全文：{title}"):
                st.caption(desc)
                with st.container(key=f"rp_md_{fname.split('.')[0]}"):
                    st.markdown(read_report(fname))
        bts = app_backtests(notes)
        if bts:
            st.markdown("#### 各分頁的回測報告")
            st.caption("跟各分頁頁尾「回測報告」展開區是同一份內容。")
            for label, md in bts:
                with st.expander(f"📊 {label}"):
                    st.markdown(md)
