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

# 卡片臉上（明細以外）不重複顯示的欄位——這些已在卡片臉上以其他形式出現。
FACE_SKIP = {
    "value": {"ticker", "name", "verdict", "upside_pct", "value_score", "f_score",
              "roe", "close", "cheap_threshold", "industry", "reject_reason",
              "buy_low", "buy_high", "buy_note", "cyclical_peak_flag", "eps_basis_suspect"},
    "deposit": {"ticker", "name", "verdict", "cur_yield", "yield_floor", "est_buy_price",
                "close", "div_years", "ret3y_incl", "fill_rate", "safety_score",
                "industry", "reject_reason", "buy_low", "buy_high", "buy_note"},
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


# ── 版型 B：判斷卡（使用者裁決 2026-09-08）──────────────────────────────
_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@500;600&family=Noto+Serif+TC:wght@600&display=swap');
:root{
  --thc-surface:#1e211a; --thc-surface2:#262a20; --thc-line:#333a2d;
  --thc-ink:#e9ece6; --thc-soft:#a3ada2; --thc-faint:#7c8677;
  --thc-accent:#5fb89e;
  --thc-good:#68b784; --thc-good-bg:#1e2c22;
  --thc-warn:#d69f57; --thc-warn-bg:#2e2717;
  --thc-neutral:#9aa39a; --thc-neutral-bg:#262b24;
  --thc-flag:#d5894f;
  --thc-mono:"IBM Plex Mono",ui-monospace,Menlo,monospace;
}
.thc-grid{display:grid;gap:.7rem;grid-template-columns:1fr;align-items:start;margin-top:.3rem;}
@media (min-width:900px){.thc-grid{grid-template-columns:1fr 1fr;}}
.thc-card{display:flex;background:var(--thc-surface);border:1px solid var(--thc-line);
  border-radius:10px;overflow:hidden;}
.thc-card .thc-stripe{width:4px;flex-shrink:0;background:var(--thc-neutral);}
.thc-card.thc-good .thc-stripe{background:var(--thc-good);}
.thc-card.thc-warn .thc-stripe{background:var(--thc-warn);}
.thc-body{flex:1;min-width:0;padding:.8rem 1rem .85rem;}
.thc-head{display:flex;align-items:baseline;gap:.5rem;flex-wrap:wrap;}
.thc-tk{font-family:var(--thc-mono);font-weight:600;font-size:1.18rem;color:var(--thc-ink);}
.thc-cn{font-family:"Noto Serif TC",serif;font-weight:600;font-size:1.03rem;}
.thc-pill{display:inline-flex;align-items:center;gap:.34rem;font-size:.78rem;font-weight:600;
  padding:.14rem .55rem;border-radius:99px;white-space:nowrap;}
.thc-pill::before{content:"";width:.48rem;height:.48rem;border-radius:99px;background:currentColor;}
.thc-pill.thc-good{color:var(--thc-good);background:var(--thc-good-bg);}
.thc-pill.thc-warn{color:var(--thc-warn);background:var(--thc-warn-bg);}
.thc-pill.thc-neutral{color:var(--thc-neutral);background:var(--thc-neutral-bg);}
.thc-flag{font-size:.72rem;color:var(--thc-faint);font-weight:500;white-space:nowrap;}
.thc-ctx{font-size:.85rem;color:var(--thc-soft);margin-top:.2rem;}
.thc-hero{display:flex;align-items:flex-end;gap:.5rem;margin:.55rem 0 .1rem;}
.thc-big{font-family:var(--thc-mono);font-weight:600;font-size:1.9rem;line-height:1;
  font-variant-numeric:tabular-nums;color:var(--thc-ink);}
.thc-big.up{color:var(--thc-good);}
.thc-cap{font-size:.78rem;color:var(--thc-faint);padding-bottom:.18rem;}
.thc-bar{margin:.6rem 0 .25rem;height:7px;border-radius:99px;background:#2c332a;position:relative;}
.thc-bar .z{position:absolute;top:0;bottom:0;left:0;background:rgba(104,183,132,.30);
  border:1px solid rgba(104,183,132,.5);border-radius:99px;}
.thc-bar .n{position:absolute;top:-4px;width:3px;height:15px;background:#e9ece6;
  border-radius:2px;box-shadow:0 0 0 1.5px #131511;}
.thc-barcap{font-size:.72rem;color:var(--thc-soft);font-family:var(--thc-mono);
  display:flex;justify-content:space-between;gap:.5rem;}
.thc-note{font-size:.8rem;color:var(--thc-soft);margin:.5rem 0 .1rem;}
.thc-chips{display:flex;flex-wrap:wrap;gap:.38rem;margin:.7rem 0 .1rem;}
.thc-chip{font-size:.77rem;background:var(--thc-surface2);border:1px solid var(--thc-line);
  border-radius:6px;padding:.2rem .5rem;white-space:nowrap;color:var(--thc-soft);}
.thc-chip b{font-family:var(--thc-mono);font-weight:600;font-variant-numeric:tabular-nums;color:var(--thc-ink);}
.thc-details{margin-top:.55rem;font-size:.85rem;}
.thc-details summary{cursor:pointer;color:var(--thc-soft);font-size:.83rem;list-style:none;font-weight:500;}
.thc-details summary::-webkit-details-marker{display:none;}
.thc-details summary::before{content:"▸ ";color:var(--thc-accent);}
.thc-details[open] summary::before{content:"▾ ";}
/* 長波段：支持/反對兩欄 */
.sw-risk{margin-left:auto;font-family:var(--thc-mono);font-size:.8rem;color:var(--thc-warn);white-space:nowrap;}
.sw-cols{display:grid;gap:.6rem 1.4rem;margin-top:.6rem;}
.sw-h{font-family:var(--thc-mono);font-size:.72rem;text-transform:uppercase;letter-spacing:.08em;
  color:var(--thc-faint);font-weight:600;margin-bottom:.15rem;}
.sw-h.sup{color:var(--thc-good);}
.sw-cols ul{margin:0;padding-left:1.05rem;font-size:.84rem;color:var(--thc-soft);}
.sw-cols li{margin:.16rem 0;}
@media (min-width:560px){.sw-cols{grid-template-columns:1fr 1fr;}}
.thc-details table{width:100%;border-collapse:collapse;margin-top:.45rem;}
.thc-details td{padding:.22rem .1rem;border-bottom:1px solid var(--thc-line);}
.thc-details td:first-child{color:var(--thc-faint);white-space:nowrap;padding-right:.9rem;}
.thc-details td:last-child{font-family:var(--thc-mono);text-align:right;
  font-variant-numeric:tabular-nums;color:var(--thc-ink);}
/* Streamlit 元件微調——深底下的線 / 字提亮 */
[data-testid="stExpander"] details{border-color:var(--thc-line)!important;}
.stCaption,[data-testid="stCaptionContainer"]{color:var(--thc-soft)!important;}
/* 手機：把並排欄位改直向堆疊（個股查詢圖表擠壓 + 卡片篩選列 + 支持/反對） */
@media (max-width:640px){
  [data-testid="stHorizontalBlock"]{flex-wrap:wrap!important;}
  [data-testid="stHorizontalBlock"] > [data-testid="stColumn"],
  [data-testid="stHorizontalBlock"] > [data-testid="column"]{
    flex:1 1 100%!important;min-width:100%!important;width:100%!important;}
  .thc-big{font-size:1.65rem;}
  .thc-tk{font-size:1.1rem;}
}
</style>
"""


def _inject_css() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def _sev(verdict: str) -> str:
    if verdict.startswith("推薦"):
        return "good"
    if verdict.startswith("觀望"):
        return "warn"
    return "neutral"          # 資料不足 / 不推薦 / 其他


def _verdict_cat(verdict: str) -> str:
    """完整 verdict → 類別（篩選用）。"""
    for c in ("推薦", "觀望", "資料不足", "不推薦"):
        if verdict.startswith(c):
            return c
    return verdict.split("（")[0] or "其他"


def _paren(verdict: str) -> str:
    """把「觀望（現價殖利率 4.4% < 門檻 5.0%）」取出括號裡那句。沒有括號 → 空字串。"""
    if "（" in verdict and verdict.endswith("）"):
        return verdict[verdict.index("（") + 1:-1]
    return ""


def _esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _ctx_line(r: dict, kind: str) -> str:
    """卡片頭下的一句話依據。優先用 verdict 括號內容，否則自己組。"""
    p = _paren(r.get("verdict", ""))
    ind = r.get("industry") or ""
    if p:
        return _esc(f"{ind}　·　{p}" if ind else p)
    if kind == "value":
        ct, cl = r.get("cheap_threshold"), r.get("close")
        if ct is not None and cl is not None:
            rel = "之下（有安全邊際）" if cl <= ct else "之上（無安全邊際）"
            return _esc(f"{ind}　·　現價 {cl:,.2f} 在便宜門檻 {ct:,.2f} {rel}")
    else:
        cy, yf = r.get("cur_yield"), r.get("yield_floor")
        if cy is not None and yf is not None:
            rel = "≥" if cy >= yf else "<"
            return _esc(f"{ind}　·　現價殖利率 {cy*100:.1f}% {rel} 門檻 {yf*100:.1f}%")
    return _esc(ind)


def _buy_block(r: dict, kind: str) -> str:
    """買入區間視覺：有數字買區 → 長條；只有 buy_note → 一句話；都沒有 → 空。"""
    bl, bh, bn = r.get("buy_low"), r.get("buy_high"), r.get("buy_note")
    if bl and bh:
        return (f'<div class="thc-note"><b>買入區間</b>　{bl:,.2f} – {bh:,.2f}</div>')
    cl = r.get("close")
    ref = r.get("est_buy_price") if kind == "deposit" else r.get("cheap_threshold")
    label = "估值買價" if kind == "deposit" else "便宜門檻"
    out = ""
    if cl is not None and ref is not None and ref > 0:
        top = max(cl, ref) * 1.12
        zw = min(100.0, ref / top * 100)
        nx = min(100.0, cl / top * 100)
        out += (f'<div class="thc-bar"><span class="z" style="width:{zw:.0f}%"></span>'
                f'<span class="n" style="left:{nx:.0f}%"></span></div>'
                f'<div class="thc-barcap"><span>{label} {ref:,.2f}</span>'
                f'<span>現價 {cl:,.2f}</span></div>')
    if bn:
        out += f'<div class="thc-note">{_esc(bn)}</div>'
    return out


def _chips(r: dict, kind: str) -> str:
    if kind == "value":
        pairs = [("價值分數", _fmt("value_score", r.get("value_score"))),
                 ("F-Score", _fmt("f_score", r.get("f_score"))),
                 ("ROE", _fmt("roe", r.get("roe")))]
    else:
        pairs = [("估值買價", _fmt("est_buy_price", r.get("est_buy_price"))),
                 ("連配", (f"{int(r['div_years'])} 年" if r.get("div_years") else "—")),
                 ("3年含息", _fmt("ret3y_incl", r.get("ret3y_incl")))]
        if r.get("fill_rate") is not None:
            pairs.append(("填息率", _fmt("fill_rate", r.get("fill_rate"))))
    return "".join(f'<span class="thc-chip"><b>{_esc(v)}</b> {k}</span>' for k, v in pairs)


def _detail_html(r: dict, kind: str) -> str:
    rows = "".join(
        f"<tr><td>{_esc(LABELS.get(k, k))}</td><td>{_esc(_fmt(k, v))}</td></tr>"
        for k, v in r.items()
        if k not in FACE_SKIP[kind] and v not in (None, "")
        and not isinstance(v, (list, dict)))
    return f"<details class='thc-details'><summary>明細</summary><table>{rows}</table></details>"


def _card_b_html(r: dict, kind: str) -> str:
    v = r.get("verdict", "")
    sev = _sev(v)
    pill = "推薦" if sev == "good" else ("觀望" if sev == "warn" else (
        "資料不足" if v.startswith("資料不足") else (v.split("（")[0] or "—")))
    flags = ""
    if r.get("cyclical_peak_flag"):
        flags += '<span class="thc-flag">⚠ 循環高位</span>'
    if r.get("eps_basis_suspect"):
        flags += '<span class="thc-flag">⚠ EPS 存疑</span>'

    if kind == "value":
        up = r.get("upside_pct")
        if sev == "good" and up is not None:
            big, cap, is_up = f"+{up*100:.0f}%", "到估值上緣的空間", up > 0
        else:
            # 無安全邊際 / 資料不足時，「空間%」會誤導——臉上放便宜門檻，現價當註腳
            ct, cl = r.get("cheap_threshold"), r.get("close")
            big = f"{ct:,.2f}" if ct is not None else "—"
            cap = f"便宜門檻（現價 {cl:,.2f}）" if cl is not None else "便宜門檻"
            is_up = False
    else:
        cy = r.get("cur_yield")
        big = f"{cy*100:.1f}%" if cy is not None else "—"
        cap = "現價殖利率"
        is_up = cy is not None and cy >= (r.get("yield_floor") or 0.05)

    html = (
        f'<div class="thc-card thc-{sev}"><div class="thc-stripe"></div><div class="thc-body">'
        f'<div class="thc-head"><span class="thc-tk">{_esc(r.get("ticker"))}</span>'
        f'<span class="thc-cn">{_esc(r.get("name",""))}</span>'
        f'<span class="thc-pill thc-{sev}">{_esc(pill)}</span>{flags}</div>'
        f'<div class="thc-ctx">{_ctx_line(r, kind)}</div>'
        f'<div class="thc-hero"><span class="thc-big{" up" if is_up else ""}">{_esc(big)}</span>'
        f'<span class="thc-cap">{cap}</span></div>'
        f'{_buy_block(r, kind)}'
        f'<div class="thc-chips">{_chips(r, kind)}</div>'
        f'{_detail_html(r, kind)}'
        f'</div></div>')
    return html


def _cond_table_html(rows: list[dict]) -> str:
    if not rows:
        return ""
    body = "".join(
        "<tr>" + "".join(f"<td>{_esc(v)}</td>" for v in row.values()) + "</tr>"
        for row in rows)
    return f"<table>{body}</table>"


def _swing_b_html(c: dict) -> str:
    """長波段候選卡——同 B 視覺語言，但沒有 verdict / 買價（狀態型）。
    支持/反對 + 條件表 + 失效條件全進卡片；只有「複製給 AI」在外面。"""
    def _ul(items, empty):
        items = [x for x in (items or []) if x not in (None, "")]
        lis = "".join(f"<li>{_esc(x)}</li>" for x in items) or f"<li>{_esc(empty)}</li>"
        return f"<ul>{lis}</ul>"

    risk = c.get("risk_pct_at_close")
    ctx = "　·　".join(x for x in [
        _esc(c.get("industry") or ""),
        f"現價 {c['close']:,.2f}" if c.get("close") is not None else "",
        f"可買上限 {c['max_buy']:,.2f}" if c.get("max_buy") is not None else "",
        f"停損 {c['risk_stop']:,.2f}" if c.get("risk_stop") is not None else "",
    ] if x)
    dist = "　·　".join([
        f"距 50MA {(c.get('dist_50ma') or 0):+.0%}",
        f"距 52 週高 {(c.get('dist_52w_high') or 0):+.0%}",
        f"距 200MA {(c.get('dist_200ma') or 0):+.0%}"])
    return (
        f'<div class="thc-card thc-neutral"><div class="thc-stripe"></div><div class="thc-body">'
        f'<div class="thc-head"><span class="thc-tk">{_esc(c.get("ticker"))}</span>'
        f'<span class="thc-cn">{_esc(c.get("name",""))}</span>'
        + (f'<span class="sw-risk">{risk:+.0%} 風險</span>' if risk is not None else "")
        + f'</div><div class="thc-ctx">{ctx}</div>'
        f'<div class="sw-cols">'
        f'<div><div class="sw-h sup">支持</div>{_ul(c.get("support"), "（未發現額外支持證據）")}</div>'
        f'<div><div class="sw-h">反對</div>{_ul(c.get("oppose"), "（未發現反對證據——代表檢查不足）")}</div>'
        f'</div>'
        f'<details class="thc-details"><summary>條件成立狀態 + 失效條件</summary>'
        f'<div class="sw-h" style="margin-top:.5rem">進場條件（全部成立才進候選池）</div>'
        f'{_cond_table_html(c.get("conditions", []))}'
        f'<div class="sw-h" style="margin-top:.6rem">失效條件（目前狀態；v3.1 不追蹤持倉）</div>'
        f'{_cond_table_html(c.get("invalidation", []))}'
        f'<div class="thc-barcap" style="margin-top:.5rem">{_esc(dist)}</div>'
        f'</details>'
        f'</div></div>')


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
    # 定存的 verdict 內嵌數字（「觀望（殖利率 4.4% < 門檻 5.0%）」）→ 每檔自成一組。
    # 篩選按**類別**（推薦 / 觀望 / 資料不足 / 不推薦），不按完整字串。
    cats = [c for c in ("推薦", "觀望", "資料不足", "不推薦")
            if any(_verdict_cat(h.get("verdict", "")) == c for h in holdings)]
    c1, c2 = st.columns([2, 1])
    pick = c1.multiselect("篩選 verdict", cats, default=cats)
    sort_label = c2.selectbox("排序", list(SORT_KEYS[kind]))
    sk = SORT_KEYS[kind][sort_label]
    rows = [h for h in holdings if _verdict_cat(h.get("verdict", "")) in pick]
    rows.sort(key=lambda h: (h.get(sk) is None, -(h.get(sk) or 0)))

    st.subheader(f"本季成分（{len(rows)}/{len(holdings)} 檔）")
    st.markdown(
        '<div class="thc-grid">' + "".join(_card_b_html(r, kind) for r in rows) + "</div>",
        unsafe_allow_html=True)

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

    st.markdown(
        '<div class="thc-grid">'
        + "".join(_swing_b_html(c) for c in payload["candidates_pool"]) + "</div>",
        unsafe_allow_html=True)

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
    import stockcharts as ch
    _disclaimer()
    st.header("個股查詢")
    st.caption("攤開數據讓人／AI 判斷，**不打分、不給買賣建議**（PRD §4.1）。"
               "雲端只服務 bundle 內的股票（前 ~500 大 + 定存宇宙）。")
    st.markdown("**股票代號**")
    with st.form("stock_query", border=False):
        fc1, fc2 = st.columns([5, 1])
        _in = fc1.text_input("代號", placeholder="2330", label_visibility="collapsed")
        _go = fc2.form_submit_button("查詢", use_container_width=True)
    if _go and _in.strip():
        st.session_state["_stock_code"] = _in.strip()
    code = st.session_state.get("_stock_code", "")
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

    def _chart(fn, *args, target=st):
        """單張圖爆掉不要整頁掛——就地顯示錯誤、繼續下一張。"""
        try:
            target.plotly_chart(fn(*args), use_container_width=True)
        except Exception as e:  # noqa: BLE001
            target.warning(f"「{getattr(fn, '__name__', '圖')}」畫不出來：{type(e).__name__}: {e}")

    if not d["px"].empty:
        end = pd.Timestamp(pd.to_datetime(d["px"]["date"]).max())
        rng = st.segmented_control("顯示區間", ["3月", "今年至資料日期", "1年", "2年", "全部"],
                                   default="1年", key="_px_range") or "1年"
        if rng == "今年至資料日期":
            start = pd.Timestamp(end.year, 1, 1)
        elif rng == "全部":
            start = None
        else:
            start = end - pd.Timedelta(days={"3月": 92, "1年": 365, "2年": 730}[rng])
        short = rng in ("3月", "今年至資料日期", "1年")
        ma = ch._MA_SHORT if short else ch._MA_LONG
        _chart(ch.kline, d["px"], name, start, ma)
        if not d["per"].empty:
            _chart(ch.pe_river, d["px"], d["per"], name, start)

    if not d["qf"].empty:
        c1, c2 = st.columns(2)
        _chart(ch.quarterly_eps, d["qf"], name, target=c1)
        _chart(ch.margins, d["qf"], name, target=c2)
        _chart(ch.cashflow, d["qf"], name)

    if not d["div"].empty:
        _chart(ch.dividends_chart, d["div"], name)

    st.info("📊 月營收走勢圖：bundle 目前只有單月快照，歷史圖待 revenue 歷史併入 bundle。")

    if not d["qf"].empty:
        st.subheader("Piotroski F-Score 9 分項")
        st.caption("**只打勾、不加總、不當買賣依據。** 加總分數在價值清單裡當品質門檻，"
                   "這裡是診斷用。")
        st.dataframe(ch.fscore_table(d["qf"]), hide_index=True, use_container_width=True)

    with st.expander("原始季度數據"):
        st.dataframe(d["qf"] if not d["qf"].empty else d["fin"], use_container_width=True)

    _disclaimer()


def main() -> None:
    st.set_page_config(page_title="tw-hold", layout="wide")
    _inject_css()
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
