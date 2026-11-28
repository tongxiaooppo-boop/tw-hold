"""回測報告分頁（2026-11-28 使用者要求）：上面放研究報告，下面放 app 其他分頁的回測報告。

- 研究報告：`app/reports/*.md` 靜態檔，`REPORTS` 決定順序。
- 其他回測報告：直接讀 `streamlit_app.BACKTEST_NOTES` 的 "backtest" 欄（原頁面照舊顯示，這裡不複製文字）。
- 每份報告都放展開區，點開才看得到全部（之後還會加報告）。
"""
from __future__ import annotations

import json
import re
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
    ("個股波段回測（20 多條規則對 0050）", "swing_stock_v6.md",
     "v6。細寫 S5、三條件 S2／S3、L1＋MA60：淨值圖、逐年、拿掉最好一年、敏感度、2025 起重新 100 萬；其他規則只列結果。2026-11-28"),
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
    "swing_stock_v6.md": (
        "warn", "沒有可用的", "0 條", "穩定贏 0050 的策略",
        "四條都過了及格線其中一項，但拿掉最好一年後全部輸 0050。S5 最平均、回撤淺，2025 起重新跑卻只賺 11%。",
        [("+16.0% / -28%", "S5 年化／回撤"), ("+12.5% vs +14.1%", "S5 拿掉 2021"),
         ("+172.6% vs +96.7%", "2025 起 S3／0050")]),
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
    if num not in "①②③④⑤⑥⑦⑧⑨":
        num = ""
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


#: md 裡的圖表標記 `<!-- chart:key -->`，資料在同名 `<stem>_charts.json`
_CHART_RE = re.compile(r"^<!-- chart:(\w+) -->$", re.M)
#: 淨值圖配色：0050 灰虛線，其他依序輪替（跟 stockcharts 同一組色）
_LINE_COLORS = ["#4A86C5", "#C9863A", "#C2669A", "#8C79C9", "#5E9488"]


def read_charts(fname: str) -> dict:
    p = REPORT_DIR / (Path(fname).stem + "_charts.json")
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def split_report(md: str) -> list[tuple[str, str]]:
    """把 md 依圖表標記切段：[("md", 文字), ("chart", key), ...]。"""
    out, pos = [], 0
    for m in _CHART_RE.finditer(md):
        if md[pos:m.start()].strip():
            out.append(("md", md[pos:m.start()]))
        out.append(("chart", m.group(1)))
        pos = m.end()
    if md[pos:].strip():
        out.append(("md", md[pos:]))
    return out


def nav_figure(spec: dict):
    """淨值折線圖（萬元）。spec＝{title, log, names: {欄: 顯示名}, data: {d: [日期], 欄: [值]}}。"""
    import plotly.graph_objects as go
    from app.stockcharts import _LAYOUT
    d = spec["data"]
    fig = go.Figure()
    i = 0
    for k, name in spec["names"].items():
        if k not in d:
            continue
        base = k == "0050"
        fig.add_trace(go.Scatter(
            x=d["d"], y=d[k], name=name, mode="lines",
            line=dict(color="#7D8A96" if base else _LINE_COLORS[i % len(_LINE_COLORS)],
                      width=2.2 if base else 1.6, dash="dash" if base else "solid"),
            hovertemplate="%{y:,.0f} 萬"))
        i += 0 if base else 1
    fig.update_layout(**_LAYOUT, title=dict(text=spec.get("title", ""), font=dict(size=14)),
                      hovermode="x unified", height=420)
    if spec.get("log"):
        fig.update_yaxes(type="log", tickvals=[50, 100, 200, 400, 800, 1600],
                         ticktext=[f"{v}萬" for v in (50, 100, 200, 400, 800, 1600)])
    else:
        fig.update_yaxes(ticksuffix="萬")
    return fig


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
                    charts = read_charts(fname)
                    for kind, val in split_report(read_report(fname)):
                        if kind == "md":
                            st.markdown(val)
                        elif val in charts:
                            st.plotly_chart(nav_figure(charts[val]), use_container_width=True,
                                            config={"scrollZoom": False, "displayModeBar": False,
                                                    "doubleClick": False})
        bts = app_backtests(notes)
        if bts:
            st.markdown("#### 各分頁的回測報告")
            st.caption("跟各分頁頁尾「回測報告」展開區是同一份內容。")
            for label, md in bts:
                with st.expander(f"📊 {label}"):
                    st.markdown(md)
