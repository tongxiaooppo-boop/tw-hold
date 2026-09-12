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
SHORT_DISCLAIMER = (
    "🔴🔴 **短線不是 tw-hold 的守備範圍**——這裡只把日線技術面條件逐條攤開，"
    "**零回測、零驗證**，雜訊極高。tw-hold 是長期持有工具；短線交易請用 tw-swing。"
    "融資融券變化 bundle 沒有 → 相關條件不出現。**不給訊號、不給買賣點。**"
)
# 「短線」分頁的清單來自 tw-swing 的分享級每日產出（結構化版）。這支 JSON 在
# Cloudflare Pages 上是公開路徑（`functions/_middleware.js` 白名單），免 PAT。
# 內容 = tw-swing `share-*.html` 的資料版，含它自己的分享級免責（`disclaimer`）。
_SWING_SHARE_URL = "https://tw-swing.pages.dev/share-latest.json"

#: 英文欄名 → 中文（明細表 / 複製給 AI 用）
LABELS = {
    "ticker": "代號", "name": "名稱", "industry": "產業", "close": "現價",
    "verdict": "verdict", "value_score": "價值分數", "safety_score": "存股安全分",
    "f_score": "F-Score", "roe": "ROE", "norm_pe": "normalized PE",
    "norm_ey": "normalized 盈餘殖利率", "fcf_yield": "FCF 殖利率", "ev_ebit": "EV/EBIT",
    "net_cash_to_mktcap": "淨現金/市值", "gross_margin": "毛利率",
    "cheap_threshold": "便宜門檻", "valuation_ceiling": "估值上緣", "upside_pct": "空間%",
    "cyclical_peak_flag": "循環高峰旗標", "eps_basis_suspect": "EPS 基準存疑",
    "industry_headwind": "產業逆風", "industry_ret_6m": "產業近6月中位報酬",
    "pe_p30": "PE P30", "pe_p70": "PE P70", "pe_market": "市場 PE",
    "buy_low": "買區下界", "buy_high": "買區上界", "buy_note": "買區備註",
    "reject_reason": "剔除原因", "cur_yield": "現價殖利率", "yield_floor": "殖利率門檻",
    "est_buy_price": "估值買價", "fill_rate": "近5年填息率", "ret3y_incl": "近3年含息報酬",
    "avg_yield_3y": "近3年均殖利率", "avg_yield_5y": "近5年均殖利率",
    "yield_pctile_5y": "殖利率5年分位", "div_years": "連續配息年", "last_cash_dividend": "近一次現金股利",
    "ann_vol": "年化週波動", "payout_ratio_ttm": "配息率TTM", "cyclical_penalty": "景氣循環懲罰",
    "debt_ratio": "負債比",
    # 長波段候選池（狀態型，沒有 verdict）——沒登記的話「複製給 AI」會吐英文欄名，
    # 而且比率欄不會換算成 %（0.92 其實是 +92%，AI 讀不出來，2026-09-11 修）。
    "eps_yoy_q": "季 EPS YoY", "revenue_yoy": "月營收 YoY", "revenue_accel": "月營收 YoY 加速",
    "inst_net20": "法人 20 日淨買超（股）", "trend_cnt": "Minervini 趨勢模板（滿分 8）",
    "dist_50ma": "距 50MA", "dist_52w_high": "距 52 週高", "dist_200ma": "距 200MA",
    "risk_stop": "停損參考位", "risk_pct_at_close": "現價到停損位的風險",
    "max_buy": "可買上限", "conditions": "進場條件狀態", "invalidation": "失效條件現況",
    "support": "支持", "oppose": "反對",
}
PCT_FIELDS = {"roe", "fcf_yield", "norm_ey", "gross_margin", "upside_pct", "cur_yield",
              "yield_floor", "fill_rate", "ret3y_incl", "avg_yield_3y", "avg_yield_5y",
              "yield_pctile_5y", "net_cash_to_mktcap", "payout_ratio_ttm", "debt_ratio",
              "industry_ret_6m",
              "eps_yoy_q", "revenue_yoy", "dist_50ma", "dist_52w_high", "dist_200ma",
              "risk_pct_at_close"}

# 卡片臉上（明細以外）不重複顯示的欄位——這些已在卡片臉上以其他形式出現。
FACE_SKIP = {
    "value": {"ticker", "name", "verdict", "upside_pct", "value_score", "f_score",
              "roe", "close", "cheap_threshold", "industry", "reject_reason",
              "buy_low", "buy_high", "buy_note", "cyclical_peak_flag", "eps_basis_suspect",
              "industry_headwind", "industry_ret_6m"},
    "deposit": {"ticker", "name", "verdict", "cur_yield", "yield_floor", "est_buy_price",
                "close", "div_years", "ret3y_incl", "fill_rate", "safety_score",
                "industry", "reject_reason", "buy_low", "buy_high", "buy_note",
                "industry_headwind", "industry_ret_6m"},
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


#: 策略邏輯 + 回測結果——2026-09-12 使用者要求搬進頁尾、預設收合（不是每次都要看，
#: 但要能點開查）。內容是靜態文字（回測數字不會隨每日重算變動），三線各自一份。
#: 為什麼打不過 0050——大盤集中在少數贏家，不是選股邏輯的問題（2026-09-12 量化）。
#: 只掛在拿 0050 當對照組的兩條線（價值／長波段）；定存對照的是 0056，組成不同，不適用。
_WHY_0050 = (
    "**為什麼打不過 0050**：2016-01→2026-09 還原（含息）累積報酬，台積電 2330 "
    "**+2,160%**、聯發科 2454 **+2,783%**、台達電 2308 **+1,432%**，都遠超過 0050 本身"
    "的 **+887%**。台積電長期在 0050 權重約 35–45%，粗算貢獻就接近 0050 全部漲幅的 "
    "8–9 成——這段期間 0050 的報酬幾乎是這三檔半導體/科技巨頭撐出來的，分散在 100+ 檔"
    "的規則型選股數學上贏不了重壓少數贏家的市值加權指數。不是策略設計的缺陷，是這段"
    "期間大盤本身的結構性特徵。完整筆記：`docs/reports/why_0050_hard_to_beat_20260912.md`。"
)

BACKTEST_NOTES = {
    "value": {
        "logic": ("F-Score ≥ 6 + Magic Formula 精神（歸一化本益比／盈餘殖利率排序），"
                 "月看、季換（3/31、5/15、8/14、11/14），前 15、單一產業 ≤ 40%。"
                 "verdict 只由便宜門檻驅動（PRD §6.3），不做總分排名式的推薦。"),
        "backtest": (
            "**實驗 B'（2026-09-12，port 版，季換股回溯，2016-03→2026-06，41 期）**\n\n"
            "| | 含息年化 | 最大回撤 |\n"
            "| :-- | --: | --: |\n"
            "| N=10 | +23.13% | −30.9% |\n"
            "| N=20 | +25.75% | −26.8% |\n"
            "| 對照組（不排序、過門檻就全買，N=∞） | **+28.86%** | **−20.5%** |\n"
            "| 0050 同期（含息） | +24.16% | −17.6% |\n\n"
            "**年化接近或小勝大盤，但回撤明顯更深；對照組反而年化最高、回撤最淺**——"
            "排名機制（Magic Formula 精神那套 rank）本身在這段期間沒有幫上忙，是硬門檻"
            "（F-Score≥6 等）在做事。\n\n"
            "沿用原始實驗 B（2026-09-07）的方法論，改用 tw-hold 自己的 `factors/`／`reference/`／"
            "`screener/` 重新接線（原始 `research/backtest_rebalance.py` 依賴的 `twswing.value` "
            "套件已被刪除，import 會炸——2026-09-12 完成 port，見 HANDOFF §1.6、完整報告 "
            "`docs/reports/backtest_value_20260912.md`）。跟舊數字的差異主要來自 2026-09-08 "
            "之後修正的因子計算（equity_parent 抓錯表、EPS 分割還原等），不是重跑本身引入的誤差。\n\n"
            "🔴 生存者偏差：universe 是 bundle `universe.parquet` 的 `in_universe`（609 檔，"
            "市值前500∪成交值前500），拿去回溯 2016 等於已知誰活到今天，"
            "**結論當上界看待，真實會更差**。\n\n" + _WHY_0050),
    },
    "deposit": {
        "logic": ("殖利率 ≥ 5%（目標 5.5%）+ 硬門檻（含填息率 ≥ 60%、近 3 年含息報酬 ≥ 0），"
                 "季換股，前 15、單一產業 ≤ 40%。買價 = 近 3 年均現金股利 ÷ 殖利率門檻（PRD §7.3）。"),
        "backtest": (
            "**實驗 B（2026-09-07，季換股回溯，2016 起）**：N=10 含息年化 **+10.80%**、"
            "最大回撤 **−25.2%**；同期 0056 含息 **+16.36%**、回撤 **−17.2%**——**報酬跟回撤都輸對照 ETF**。\n\n"
            "🔴 這組數字**目前重跑不出來**（同上，依賴的套件已搬走，待 port）；而且定存線的 "
            "`cut5y`（近 5 年減配判定）門檻 2026-09-08 之後放寬過（通過檔數 55→~92），這組 "
            "2026-09-07 的數字沒反映放寬後的候選池，**已經過時**，重跑後可能改變。\n\n"
            "🔴 生存者偏差：universe 是回測當時的前 ~500 大，**結論當上界看待，真實會更差**。"),
    },
    "swing": {
        "logic": ("候選池六條件全過才進池：CANSLIM 基本面（季 EPS YoY>25%、近3年TTM EPS成長、"
                 "ROE>15%、毛利率未連兩季惡化、F-Score≥6）∩ 月營收 YoY>0 且加速 ∩ 法人20日"
                 "淨買超>0 ∩ Minervini 趨勢模板 8/8。停損參考位 = max(50MA, 近20週前低, "
                 "現價−2×ATR14)。失效條件（任一觸發）：收盤跌破50MA、趨勢模板<5/8、"
                 "月營收 YoY 連2個月轉負、季 EPS YoY 轉負。"),
        "backtest": (
            "**實驗 E（2026-09-12，事件驅動回測，2016-01→2026-09，550 週）**：\n\n"
            "| 口徑 | 年化 | 最大回撤 | 勝率 |\n"
            "| :-- | --: | --: | --: |\n"
            "| 次日開盤（PRD 字面規格：固定停損） | +13.4% | −37.1% | 25% |\n"
            "| 限價買得到（固定停損） | +12.0% | −37.1% | 23% |\n"
            "| 次日開盤 + 移動 ATR 停損（非本頁現行規格，對照組） | +19.4% | −31.2% | 42% |\n"
            "| 0050 同期（含息還原） | +24.0% | −33.8% | — |\n\n"
            "**現行規格（固定停損）是主要弱點，不是候選池選股本身的問題**：73% 出場都是停損，"
            "而且停損位進場當下算一次、之後不隨獲利上移——正常拉回就把部位洗出去，吃不到"
            "後面的行情，報酬跟回撤雙輸大盤。移動停損版本（借用 tw-swing 機制，**目前沒有"
            "收進候選池邏輯，只是測試對照組**）拿回大部分報酬、回撤還低於大盤，但那是額外"
            "測試結果，不是這頁現在算給你看的東西。\n\n"
            "🔴 生存者偏差：universe 是今天 bundle 的 610 檔（市值/成交值前段班），"
            "**結論當上界看待，真實會更差**。完整報告：`docs/reports/backtest_longswing_20260912.md`。"
            "\n\n" + _WHY_0050),
    },
}


def _strategy_backtest_expander(kind: str) -> None:
    info = BACKTEST_NOTES.get(kind)
    if not info:
        return
    with st.expander("📖 策略邏輯 + 回測結果（點開看）"):
        st.markdown("**策略怎麼做的**")
        st.markdown(info["logic"])
        st.markdown("**回測結果**")
        st.markdown(info["backtest"])


def _fmt(field: str, v) -> str:
    if v is None or v == "":
        return "—"
    if isinstance(v, bool):
        return "是" if v else "否"
    if isinstance(v, (int, float)):
        if field in PCT_FIELDS:
            return f"{v * 100:.1f}%"
        return f"{v:,}" if isinstance(v, int) else f"{v:,.2f}"
    return str(v)


def _fmt_removed(removed: list) -> list[str]:
    return [f"{r['ticker']}（{r.get('reason', '')}）" if isinstance(r, dict) else str(r)
            for r in removed]


def _bullets(items: list, empty: str = "—") -> str:
    """list → markdown 條列（取代醜的 st.write(list) JSON 樹）。"""
    items = [x for x in (items or []) if x not in (None, "")]
    return "\n".join(f"- {x}" for x in items) if items else empty


# ── 主動式 ETF 認養旗標（context flag；見 build_active_etf_flags.py）──────────
# 規模前五大主動式 ETF（統一/復華/群益官網每日揭露 PCF）前後兩日持股差分——
# 只是把「近一日主動式 ETF 對這檔加碼／調節」攤在卡片上，**不 gate 任何進出場**。
# 非官方三大法人／投信買賣超。來源過期或抓不到 → 整組隱藏（helper 回空字串）。
_ACTIVE_SRC = "規模前五大主動式 ETF・第三方投信 PCF"
_ACTIVE_LABEL = {
    "consensus_buy": "🏦 主動ETF 認養", "buy": "🏦 主動ETF 加碼",
    "consensus_sell": "🏦 主動ETF 調節", "sell": "🏦 主動ETF 調節",
}


def _active_flags() -> dict:
    """回整份 flags dict；schema 壞或 anchor 落後 > 4 天 → 回 {}（呼叫端一律當「沒有」）。"""
    d = _load("active_etf_flags.json") or {}
    m = d.get("_meta") or {}
    if not m.get("schema_ok"):
        return {}
    ad = m.get("anchor_date")
    try:
        if ad and (pd.Timestamp(_taipei_today()) - pd.Timestamp(ad)).days > 4:
            return {}
    except Exception:
        pass
    return d


def _span_label(n) -> str:
    """旗標實際涵蓋幾個交易日。某檔基金漏抓一天時它的差分就是跨日的——文案照實講，
    不要一律寫「近一日」（2026-09-11 修；判定見 build_active_etf_flags._span_days）。"""
    return f"近 {int(n)} 個交易日" if isinstance(n, int) and n > 1 else "近一日"


def _active_of(ticker, flags: dict) -> dict | None:
    return (flags.get("flags") or {}).get(str(ticker or "").split(".")[0]) if flags else None


def _active_chip(f: dict | None) -> str:
    if not f or f.get("kind") in (None, "neutral"):
        return ""
    label = _ACTIVE_LABEL.get(f["kind"], "🏦 主動ETF")
    cons = f.get("consensus")
    tail = f" ×{abs(cons)}" if isinstance(cons, int) and abs(cons) >= 2 else ""
    return f'<span class="thc-flag">{_esc(label + tail)}</span>'


def _active_evidence(f: dict | None) -> tuple[str, str]:
    """回 (支持句, 反對句)——只會有一個非空；都空＝這檔沒被主動式 ETF 動。"""
    if not f or f.get("kind") in (None, "neutral"):
        return "", ""
    ns = f.get("net_shares")
    lots = f"{ns / 1000:+,.0f} 張" if isinstance(ns, (int, float)) else "—"
    ic = f.get("issuer_count")
    who = f"{ic} 檔主動 ETF" if isinstance(ic, int) else "主動 ETF"
    cons = f.get("consensus") or 0
    strong = "、共識強" if f.get("consensus_strong") and abs(cons) >= 2 else ""
    same = f"（{abs(cons)} 檔同向{strong}）" if abs(cons) >= 2 else ""
    win = _span_label(f.get("span_days"))
    if f["kind"] in ("consensus_buy", "buy"):
        return f"主動式 ETF：{who}{win}淨買超 {lots}{same}", ""
    return "", f"主動式 ETF 調節：{who}{win}淨賣超 {lots.lstrip('+')}{same}"


def _active_legend(flags: dict) -> str:
    m = flags.get("_meta") or {}
    if not m:
        return ""
    stale = m.get("stale_etfs")
    stale_txt = f"，{stale}/{m.get('total_etfs', '?')} 檔尚未更新" if stale else ""
    # 有基金漏抓一天 → 它的差分跨 > 1 個交易日，這裡要講清楚是哪幾檔（stale_etfs
    # 抓不到這種：它有兩份快照、只是不相鄰）。
    multi = m.get("multi_day_etfs") or []
    multi_txt = (f"，其中 {'／'.join(multi)} 因為中間漏抓，差分跨 "
                 f"{m.get('max_span_days', 2)} 個交易日" if multi else "")
    return (f"🏦 主動式 ETF 認養＝近一次揭露變化中「規模前五大主動式 ETF」對該股的加碼／調節"
            f"（{_ACTIVE_SRC}，真實股數差，資料日 {m.get('anchor_date', '—')}"
            f"{stale_txt}{multi_txt}）。"
            f"**非官方三大法人／投信買賣超，不是機構認養背書**；賣出也可能是基金"
            f"應付大額贖回而被迫調節，不一定代表看壞後市。")


_PCF_INDEX = REPO / "data" / "pcf" / "_index.json"
_REBUILD_RUNS_URL = ("https://github.com/tongxiaooppo-boop/tw-hold"
                     "/actions/workflows/rebuild.yml")


def _load_pcf_index() -> dict | None:
    try:
        return json.loads(_PCF_INDEX.read_text(encoding="utf-8")) if _PCF_INDEX.exists() else None
    except Exception:  # noqa: BLE001
        return None


def _ago_human(iso: str | None) -> str:
    """ISO 時戳 → 「3 小時前」；壞掉就原樣回。"""
    if not iso:
        return "—"
    from datetime import datetime, timezone
    try:
        t = datetime.fromisoformat(str(iso))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        sec = (datetime.now(timezone.utc) - t).total_seconds()
    except Exception:  # noqa: BLE001
        return str(iso)
    if sec < 90:
        return "剛剛"
    if sec < 3600:
        return f"{int(sec // 60)} 分鐘前"
    if sec < 86400:
        return f"{int(sec // 3600)} 小時前"
    return f"{int(sec // 86400)} 天前"


# ── 版型 B：判斷卡（使用者裁決 2026-09-08；配色「北歐靜謐」方案 C，2026-09-11）──
# 卡片依「判斷類別」暈染色（好／警示／中性），不是漲跌色；漲跌色只留給真的漲跌
# （目前只有個股 K 線，見 stockcharts.py 的 --thc-up/--thc-down 對應色）。
# 這裡的變數是唯一色源——要微調配色只改這個 :root 區塊，其餘規則一律吃 var()。
_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;700&family=JetBrains+Mono:wght@500;600;700&family=Noto+Serif+TC:wght@600&display=swap');
:root{
  --thc-bg:#EEF1F4;
  --thc-surface:#FFFFFF; --thc-surface2:#F5F7F9; --thc-line:#E4E8EC;
  --thc-ink:#2B333B; --thc-soft:#5E6B76; --thc-faint:#8A97A3;
  --thc-accent:#5C7A72;
  /* 判斷類卡片暈染——good=通過/推薦、warn=存疑/風險、neutral=一般 */
  --thc-good:#5C7A72; --thc-good-bg:#DEE9E6;
  --thc-warn:#8A6A5F; --thc-warn-bg:#F1E3DF;
  --thc-neutral:#5E7686; --thc-neutral-bg:#DEE7EC;
  --thc-flag:#8A6A5F;
  --thc-bad:#B5453B;
  /* 漲跌色（台股慣例，紅漲綠跌）——只給真正的價格漲跌用，不要拿來標判斷結果 */
  --thc-up:#C4574A; --thc-down:#4A7D74;
  /* 同一個紅、給需要半透明的地方（雷達徽章）——別再寫死 rgba(196,87,74,…) */
  --thc-up-rgb:196,87,74;
  --thc-sans:"Manrope",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  --thc-mono:"JetBrains Mono",ui-monospace,Menlo,monospace;
}
.stApp{background:var(--thc-bg);}
/* Streamlit 的 Material 圖示是「靠 ligature 把文字變成圖」的 <span>，字體被蓋掉就會
   顯示成 keyboard_arrow_right 這種原始文字。預設 testid 是 stIconMaterial，但
   DynamicIcon 允許呼叫端覆寫（stAlertDynamicIcon / stToastDynamicIcon /
   stFileChipIcon*）——都含 "Icon"，用包含式比對一次蓋掉（2026-09-11）。
   app 自己的 <span> 沒有 data-testid，不受影響。 */
.stApp, .stApp p, .stApp li, .stApp label,
.stApp span:not([data-testid*="Icon"]){font-family:var(--thc-sans);}
/* 分頁選單（st.radio）前面原生的圓圈勾選標——藏掉，只留文字，雷達徽章疊在文字後面就好。
   結構是 <label data-testid="stRadioOption"><input type=radio hidden><div><div>[圓圈][文字]</div></div></label>；
   圓圈那個 div 沒有 testid，用「跟 stMarkdownContainer 同一排的第一個 div」抓它，不用猜 class 名稱。 */
div[data-testid="stRadioGroup"] [data-testid="stRadioOption"]
  div:has(> [data-testid="stMarkdownContainer"]) > div:first-child{display:none;}
.thc-grid{display:grid;gap:.7rem;grid-template-columns:1fr;align-items:stretch;margin-top:.3rem;}
.thc-grid > .thc-card{height:100%;}
@media (min-width:900px){.thc-grid{grid-template-columns:1fr 1fr;}}
.thc-card{display:flex;background:var(--thc-surface);border:1px solid var(--thc-line);
  border-radius:10px;overflow:hidden;}
.thc-card .thc-stripe{width:4px;flex-shrink:0;background:var(--thc-neutral);}
.thc-card.thc-good .thc-stripe{background:var(--thc-good);}
.thc-card.thc-warn .thc-stripe{background:var(--thc-warn);}
.thc-body{flex:1;min-width:0;padding:.8rem 1rem .85rem;}
.thc-head{display:flex;align-items:baseline;gap:.5rem;flex-wrap:wrap;}
.thc-tk{font-family:var(--thc-mono);font-weight:600;font-size:1.18rem;color:var(--thc-ink);}
.thc-tk a{color:inherit;text-decoration:none;border-bottom:1px dashed var(--thc-faint);}
.thc-tk a:hover{color:var(--thc-accent);border-bottom-color:var(--thc-accent);}
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
.thc-bar{margin:.6rem 0 .25rem;height:7px;border-radius:99px;background:var(--thc-line);position:relative;}
.thc-bar .z{position:absolute;top:0;bottom:0;left:0;background:rgba(92,122,114,.28);
  border:1px solid rgba(92,122,114,.5);border-radius:99px;}
.thc-bar .n{position:absolute;top:-4px;width:3px;height:15px;background:var(--thc-ink);
  border-radius:2px;box-shadow:0 0 0 1.5px var(--thc-bg);}
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
.sw-cols li b{font-family:var(--thc-mono);font-variant-numeric:tabular-nums;color:var(--thc-ink);}
@media (min-width:560px){.sw-cols{grid-template-columns:1fr 1fr;}}
.thc-details table{width:100%;border-collapse:collapse;margin-top:.45rem;}
.thc-details td{padding:.22rem .1rem;border-bottom:.5px solid var(--thc-line);}
.thc-details td:first-child{color:var(--thc-faint);white-space:nowrap;padding-right:.9rem;}
.thc-details td:last-child{font-family:var(--thc-mono);text-align:right;
  font-variant-numeric:tabular-nums;color:var(--thc-ink);}
/* 多軌體檢：檢核清單。桌面＝四欄類表格（不動）；手機＝堆疊，狀態永遠靠右可見 */
.thc-cl{border:1px solid var(--thc-line);border-radius:8px;overflow:hidden;margin:.15rem 0 .1rem;}
.thc-cl-row{display:grid;grid-template-columns:minmax(0,1.5fr) minmax(0,2fr) minmax(0,.9fr) minmax(0,.85fr);
  gap:.2rem .7rem;padding:.5rem .85rem;border-top:1px solid var(--thc-line);
  font-size:.88rem;align-items:baseline;}
.thc-cl-row:first-child{border-top:none;}
.thc-cl-hd{font-family:var(--thc-mono);font-size:.7rem;text-transform:uppercase;letter-spacing:.07em;
  color:var(--thc-faint);font-weight:600;background:var(--thc-surface2);}
.thc-cl-item{color:var(--thc-ink);}
.thc-cl-gate{color:var(--thc-soft);}
.thc-cl-cur{font-family:var(--thc-mono);font-variant-numeric:tabular-nums;color:var(--thc-ink);}
.thc-cl-st{font-weight:600;white-space:nowrap;}
.thc-cl-st.good{color:var(--thc-good);}
.thc-cl-st.bad{color:var(--thc-bad);}
.thc-cl-st.warn{color:var(--thc-warn);}
.thc-cl-st.na{color:var(--thc-faint);}
@media (max-width:640px){
  .thc-cl-hd{display:none;}
  .thc-cl-row{grid-template-columns:1fr auto;column-gap:.6rem;row-gap:.15rem;padding:.6rem .8rem;}
  .thc-cl-item{grid-column:1;grid-row:1;font-weight:600;}
  .thc-cl-st{grid-column:2;grid-row:1;text-align:right;}
  .thc-cl-cur{grid-column:1/-1;font-size:.82rem;color:var(--thc-soft);}
  .thc-cl-gate{grid-column:1/-1;font-size:.78rem;color:var(--thc-faint);}
  .thc-cl-cur::before{content:"現值　";color:var(--thc-faint);}
  .thc-cl-gate::before{content:"門檻　";color:var(--thc-faint);}
}
/* 主動式 ETF 每日動向——沿用卡片語言，一檔一框 */
.ae-stack{display:flex;flex-direction:column;gap:.7rem;margin:.4rem 0 .2rem;}
.ae-stack .thc-card{height:auto;}
.ae-stack .sw-cols a{color:var(--thc-accent);text-decoration:none;}
.ae-stack .sw-cols a:hover{text-decoration:underline;}
.ae-stack .sw-cols li.flat{list-style:none;margin-left:-1.05rem;color:var(--thc-faint);}
/* 頁尾「回到頂部」——樣式對齊隔壁的 st.button（切換分頁那顆） */
a.thc-toplink{display:block;text-align:center;padding:.55rem .8rem;border-radius:.5rem;
  border:1px solid var(--thc-line);color:var(--thc-soft)!important;
  text-decoration:none!important;font-size:.9rem;line-height:1.6;}
a.thc-toplink:hover{border-color:var(--thc-soft);color:var(--thc-ink)!important;}
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


def _nav_badge_css(nav: str) -> str:
    """目前分頁文字後面疊一個小雷達徽章（同心圈＋掃描扇形＋中心點）。

    - 用 `nth-of-type` 對到選中的那個 `stRadioOption`（react-aria 把 7 個選項渲染成
      radiogroup 底下 7 個相鄰 `<label>`，順序由 `NAV` 保證），不用去猜 BaseWeb 內部
      的 checked 狀態怎麼反映在 DOM 上。
    - 掃描扇形照 NAV 在「8 方位環」（含未來第 8 個美股焦點）上的順位轉：
      價值=正上方(0°)，之後每項順時針 +45°。
    - 🔴 圓圈的半徑一定要寫死 `circle 23px`：不寫的話 radial-gradient 預設是
      farthest-corner（23√2 = 32.5px），百分比停點會算到盒子外——外圈整圈被
      `border-radius:50%` 裁掉、內圈只剩 0.5px（2026-09-11 修）。
    - 紅色沿用漲跌色 `--thc-up`（使用者要「紅漲」直覺），半透明吃 `--thc-up-rgb`，
      不另外寫死色碼。
    """
    i = NAV.index(nav) if nav in NAV else 0
    sel = (f'div[data-testid="stRadioGroup"] [data-testid="stRadioOption"]'
           f':nth-of-type({i + 1})')
    ring = "rgba(var(--thc-up-rgb),.38)"
    return f"""<style>
{sel} {{ position: relative; z-index: 0; overflow: visible; }}
{sel}::before {{
  content: ""; position: absolute; left: 50%; top: 50%; z-index: -1; pointer-events: none;
  width: 46px; height: 46px; transform: translate(-50%, -50%); border-radius: 50%;
  background:
    radial-gradient(circle 23px at center, var(--thc-up) 0 2px, transparent 2px),
    conic-gradient(from {i * 45 - 22.5}deg,
      rgba(var(--thc-up-rgb),.30) 0deg 45deg, transparent 45deg 360deg),
    radial-gradient(circle 23px at center,
      transparent 0 11.5px, {ring} 11.5px 12.5px,
      transparent 12.5px 19px, {ring} 19px 20px, transparent 20px);
}}
</style>"""


def _inject_css(nav: str = "") -> None:
    """一次注入：主題 CSS + 目前分頁的雷達徽章。

    徽章的規則依「選中哪一頁」而變，但**併在同一次 `st.markdown`**——分開注入會多出
    一個 `stMarkdown` 元素，`stVerticalBlock` 的 flex gap 照算，分頁列下面就多一格
    空白（2026-09-11 修）。`nav` 在建 radio *之前* 從 session_state 取得。
    """
    st.markdown(_CSS + (_nav_badge_css(nav) if nav else ""), unsafe_allow_html=True)


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


def _tk_link(ticker) -> str:
    """代號 → 指向個股查詢的連結（`?code=` 由 _route() 接手）。"""
    t = _esc(ticker)
    return f'<span class="thc-tk"><a href="?code={t}" target="_self">{t}</a></span>'


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
    if r.get("industry_headwind"):
        rr = r.get("industry_ret_6m")
        rt = f"（近6月中位 {rr*100:.0f}%）" if isinstance(rr, (int, float)) else ""
        flags += f'<span class="thc-flag">⚠ 產業逆風{rt}</span>'

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
        f'<div class="thc-head">{_tk_link(r.get("ticker"))}'
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


def _swing_b_html(c: dict, flag: dict | None = None) -> str:
    """長波段候選卡——同 B 視覺語言，但沒有 verdict / 買價（狀態型）。
    支持/反對 + 條件表 + 失效條件全進卡片；只有「複製給 AI」在外面。
    `flag`：主動式 ETF 認養旗標（context，非 gate）。"""
    def _ul(items, empty):
        items = [x for x in (items or []) if x not in (None, "")]
        lis = "".join(f"<li>{_esc(x)}</li>" for x in items) or f"<li>{_esc(empty)}</li>"
        return f"<ul>{lis}</ul>"

    sup_x, opp_x = _active_evidence(flag)
    support = list(c.get("support") or []) + ([sup_x] if sup_x else [])
    oppose = list(c.get("oppose") or []) + ([opp_x] if opp_x else [])
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
        f'<div class="thc-head">{_tk_link(c.get("ticker"))}'
        f'<span class="thc-cn">{_esc(c.get("name",""))}</span>{_active_chip(flag)}'
        + (f'<span class="sw-risk">{risk:+.0%} 風險</span>' if risk is not None else "")
        + f'</div><div class="thc-ctx">{ctx}</div>'
        f'<div class="sw-cols">'
        f'<div><div class="sw-h sup">支持</div>{_ul(support, "（未發現額外支持證據）")}</div>'
        f'<div><div class="sw-h">反對</div>{_ul(oppose, "（未發現反對證據——代表檢查不足）")}</div>'
        f'</div>'
        f'<details class="thc-details"><summary>條件成立狀態 + 失效條件</summary>'
        f'<div class="sw-h" style="margin-top:.5rem">進場條件（全部成立才進候選池）</div>'
        f'{_cond_table_html(c.get("conditions", []))}'
        f'<div class="sw-h" style="margin-top:.6rem">失效條件（目前狀態；v3.1 不追蹤持倉）</div>'
        f'{_cond_table_html(c.get("invalidation", []))}'
        f'<div class="thc-barcap" style="margin-top:.5rem">{_esc(dist)}</div>'
        f'</details>'
        f'</div></div>')


def _copy_item(x) -> str:
    """條件表那種 `{"項": ..., "狀態": ...}` → 一行人話。"""
    if isinstance(x, dict):
        return "　".join(f"{kk} {vv}" for kk, vv in x.items() if vv not in (None, ""))
    return str(x)


def _copy_for_ai(title: str, meta: dict, rows: list[dict]) -> str:
    """清單 → 貼給 AI 的純文字。

    ⚠️ 這份是餵給別的 AI 讀的，兩件事不能省（2026-09-11 修）：
      - 比率欄一律照 `PCT_FIELDS` 換算成 %——長波段的 `0.27` 其實是 +27%，
        原樣吐出去 AI 分不出是 27% 還是 0.27%。
      - list / dict（條件表、支持/反對）要展開成條列，不能吐 Python repr。
    候選池的 `c_*` 布林跟「進場條件狀態」完全重複（全過才進池）→ 不重覆印。
    """
    lines = [f"# {title}（tw-hold，資料日期 {meta.get('trading_date', '—')}）",
             "※ 候選 + 判斷依據，非投資建議。", ""]
    for r in rows:
        head = f"- {r.get('ticker')} {r.get('name', '')}".rstrip()
        if r.get("verdict"):
            head += f"｜{r['verdict']}"
        lines.append(head)
        for k, v in r.items():
            if k in ("ticker", "name", "verdict") or k.startswith("c_"):
                continue
            if isinstance(v, (list, tuple)):
                items = [_copy_item(x) for x in v if x not in (None, "")]
                if items:
                    lines.append(f"    {LABELS.get(k, k)}:")
                    lines.extend(f"      - {it}" for it in items)
                continue
            if isinstance(v, dict):
                lines.append(f"    {LABELS.get(k, k)}: {_copy_item(v)}")
                continue
            if v in (None, ""):
                continue
            lines.append(f"    {LABELS.get(k, k)}: {_fmt(k, v)}")
    return "\n".join(lines)


def _card_list(kind: str, title: str, payload: dict | None) -> None:
    st.header(title)
    if payload is None:
        st.info("清單尚未產出。")
        _strategy_backtest_expander(kind)
        _disclaimer()
        return

    meta = payload.get("_meta", {})
    bits = [f"資料日期 {meta.get('trading_date', '—')}"]
    if meta.get("period"):
        bits.append(f"本期換股日 {meta['period']}"
                    + ("（成分凍結）" if meta.get("frozen") else "（本次重算）"))
    bits.append(f"重算 {meta.get('rebuilt_at', '—')}")
    st.caption("　·　".join(bits))
    _disclaimer()
    if meta.get("warning"):
        st.warning(meta["warning"])

    holdings = payload.get("holdings", [])
    # 定存的 verdict 內嵌數字（「觀望（殖利率 4.4% < 門檻 5.0%）」）→ 每檔自成一組。
    # 篩選按**類別**（推薦 / 觀望 / 資料不足 / 不推薦），不按完整字串。
    cats = [c for c in ("推薦", "觀望", "資料不足", "不推薦")
            if any(_verdict_cat(h.get("verdict", "")) == c for h in holdings)]
    c1, c2 = st.columns([2, 1])
    pick = c1.pills("篩選 verdict（點掉不想看的）", cats, selection_mode="multi",
                    default=cats, key=f"_pick_{kind}") or cats
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

    st.divider()
    if meta.get("g2_note"):
        st.caption("🔒 " + meta["g2_note"])
    _strategy_backtest_expander(kind)
    _disclaimer()


_SWING_STOP_STATUS = {"candidate": "候選中", "dropped_from_pool": "已出候選池（停損未觸發）",
                      "stopped_out": "已跌破移動停損"}


def _swing_exit_table() -> None:
    """出場觀察表（2026-09-12 使用者要求）——**不是持倉追蹤**，不需要你輸入買在哪天/哪個價。
    系統用「第一次通過候選池六條件那天」當進場代理，逐日追蹤移動停損（進場後最高價 −
    2×進場當天 ATR14，比照 tw-swing H2-trailatr2）。候選池把它移除後這裡**不會馬上停止**，
    繼續看價格走勢直到真的跌破停損才算出場——回答「被移除之後接下來怎麼走」。"""
    data = _load("swing_stops.json")
    if not data or not data.get("tracked"):
        return
    rows = []
    for tk, r in data["tracked"].items():
        last = r.get("last_close")
        stop = r.get("trail_stop")
        dist = (last / stop - 1.0) if last and stop else None
        rows.append({
            "代號": tk, "狀態": _SWING_STOP_STATUS.get(r["status"], r["status"]),
            "入池日": r.get("first_seen"), "進場價": r.get("entry_price"),
            "現價": last, "目前停損價": stop,
            "距停損%": f"{dist:+.1%}" if dist is not None else "—",
            "出池日": r.get("dropped_date") or "—",
            "出場日": r.get("exit_date") or "—", "出場價": r.get("exit_price") or "—",
        })
    order = {"候選中": 0, "已出候選池（停損未觸發）": 1, "已跌破移動停損": 2}
    rows.sort(key=lambda r: (order.get(r["狀態"], 9), r["入池日"] or ""), reverse=False)
    with st.expander(f"📉 出場觀察表（移動停損，非官方持倉，{len(rows)} 檔｜點開看）"):
        st.caption(
            "**不是持倉追蹤**——系統用「第一次通過候選池六條件那天」當進場代理，之後逐日"
            "追蹤移動停損（進場後最高價 − 2×進場當天 ATR14，只漲不跌，比照 tw-swing "
            "`H2-trailatr2`）。從候選池被移除**不會馬上讓這裡停止**，會繼續看價格走勢直到"
            "真的跌破停損才算出場，方便回顧「被移除之後接下來怎麼走」。**只是觀察參考，"
            "不是買賣建議、不保證你當初真的買在進場價。**")
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        meta = data.get("_meta", {})
        st.caption(f"最後更新：{meta.get('asof', '—')}　·　移動停損倍數 {meta.get('trail_atr_mult', '—')}×ATR14")


def _swing_page(payload: dict | None) -> None:
    st.header("長波段候選池")
    if payload is None or not payload.get("candidates_pool"):
        st.info((payload or {}).get("_meta", {}).get("pool_note", "候選池尚未產出。"))
        _swing_exit_table()
        _strategy_backtest_expander("swing")
        _disclaimer(SWING_DISCLAIMER)
        return

    meta = payload.get("_meta", {})
    st.caption(f"資料日期 {meta.get('trading_date', '—')}　·　{meta.get('pool_note', '')}"
               f"　·　重算 {meta.get('rebuilt_at', '—')}")
    _disclaimer()

    flags = _active_flags()
    if flags:
        st.caption(_active_legend(flags))

    chg = payload.get("changes", {})
    if chg.get("added") or chg.get("removed"):
        cc = st.columns(2)
        cc[0].markdown("**新增候選（vs 上次重算）**\n\n" + _bullets(chg.get("added")))
        cc[1].markdown("**退出候選（條件不再成立）**\n\n" + _bullets(chg.get("removed")))

    st.markdown(
        '<div class="thc-grid">'
        + "".join(_swing_b_html(c, _active_of(c.get("ticker"), flags))
                  for c in payload["candidates_pool"]) + "</div>",
        unsafe_allow_html=True)

    with st.expander("複製給 AI"):
        st.code(_copy_for_ai("長波段候選池", meta, payload["candidates_pool"]),
                language="markdown")
    st.divider()
    _swing_exit_table()
    _strategy_backtest_expander("swing")
    _disclaimer(SWING_DISCLAIMER)


@st.cache_data(ttl=1800, show_spinner="拉 tw-swing 每日清單…")
def _fetch_swing_share() -> dict | None:
    """抓 tw-swing 分享級每日清單（結構化版）。拉不到就回 None——這一頁沒有
    這份資料就是空的，不該讓整個 app 掛掉，也不該無聲顯示舊的。"""
    import json as _json
    import urllib.request
    try:
        req = urllib.request.Request(_SWING_SHARE_URL, headers={"User-Agent": "tw-hold"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return _json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001  網路 / JSON / 逾時都退化成「沒有清單」
        return None


def _taipei_today() -> str:
    from datetime import datetime, timedelta, timezone
    return f"{datetime.now(timezone.utc) + timedelta(hours=8):%Y-%m-%d}"


def _short_b_html(c: dict, flag: dict | None = None) -> str:
    """單檔短線候選卡——沿用 B 視覺語言，狀態型：沒有 verdict / 買價 / 排名。
    每一格都是 tw-swing `share-*.html` 上看得到的資料；`flag` 是主動式 ETF 認養旗標。"""
    def _n(v, fmt):
        return fmt.format(v) if isinstance(v, (int, float)) else "—"

    code = str(c.get("ticker") or "").split(".")[0]      # 6538.TWO → 6538（個股查詢用）
    ctxbits = "　·　".join(x for x in [
        _esc(c.get("pool_label") or ""),
        f"進場 {_n(c.get('entry'), '{:,.2f}')}",
        f"停損 {_n(c.get('stop'), '{:,.2f}')}",
        f"風險 {_n(c.get('risk_pct'), '{:.1%}')}",
        f"部位 {_n(c.get('position_pct'), '{:.1%}')}",
    ] if x and not x.endswith("—"))
    meta2 = "　·　".join([
        f"RS {_n(c.get('rs_rank'), '{:.0%}')}",
        f"量比 {_n(c.get('vol_ratio'), '{:.1f}')}",
        f"觸發日 {_esc(c.get('signal_date') or '—')}",
    ])
    return (
        f'<div class="thc-card thc-neutral"><div class="thc-stripe"></div><div class="thc-body">'
        f'<div class="thc-head">'
        f'<span class="thc-tk"><a href="?code={_esc(code)}" target="_self">{_esc(c.get("ticker"))}</a></span>'
        f'<span class="thc-cn">{_esc(c.get("name",""))}</span>'
        f'<span class="thc-flag">{_esc(c.get("signal") or "")}</span>{_active_chip(flag)}</div>'
        f'<div class="thc-ctx">{ctxbits}</div>'
        f'<div class="thc-note">{_esc(c.get("note") or "")}</div>'
        f'<div class="thc-barcap" style="margin-top:.45rem">{_esc(meta2)}</div>'
        f'</div></div>')


def _shortterm_page() -> None:
    st.header("短線清單（tw-swing）")

    data = _fetch_swing_share()
    if data is None:
        st.error("拉不到 tw-swing 每日清單（網路或來源暫時無法存取）。"
                 "可直接看 https://tw-swing.pages.dev/share-latest")
        _disclaimer(SHORT_DISCLAIMER)
        return

    asof = data.get("asof", "—")
    gen = data.get("generated_at", "—")
    wd = data.get("weekday", "")
    # 「整群計算時間」放在最顯眼的地方；當天沒產出時明講，不靜默拿舊的當新的。
    st.caption(f"**清單產生日 {asof}（{wd}）**　·　產生時刻 {gen}（台北）　·　來源 tw-swing")
    _disclaimer()
    today = _taipei_today()
    if asof != "—" and asof < today:
        lag = (pd.Timestamp(today) - pd.Timestamp(asof)).days
        msg = (f"⚠️ 這份是 **{asof}** 產生的清單，距今 {lag} 天。"
               "若今天是交易日、盤後仍停在這個日期，代表 tw-swing 今日尚無新產出——"
               "**別把這份當今天的清單看**。")
        (st.warning if lag >= 4 else st.info)(msg)

    for p in data.get("pools", []):
        if p.get("warn_html"):
            st.warning(p["warn_html"])

    cands = data.get("candidates", [])
    if data.get("empty") or not cands:
        st.info(f"tw-swing 在 {asof} 收盤後跑完，**當日無訊號**。")
        st.caption("這份清單由 **tw-swing** 每個交易日盤後產出，tw-hold 只是原樣轉呈。"
                   "進場價／停損只在**訊號隔日開盤**可執行，過了就失效。")
        for d in data.get("disclaimer", []):
            st.caption("· " + d)
        _disclaimer(SHORT_DISCLAIMER)
        return

    flags = _active_flags()
    if flags:
        st.caption(_active_legend(flags))
    st.subheader(f"當日候選（{len(cands)} 檔）")
    st.markdown('<div class="thc-grid">'
                + "".join(_short_b_html(c, _active_of(c.get("ticker"), flags)) for c in cands)
                + "</div>", unsafe_allow_html=True)

    with st.expander("複製給 AI"):
        lines = [f"# 短線清單 tw-swing（產生日 {asof}，非投資建議、隔日開盤前有效）", ""]
        for c in cands:
            lines.append(
                f"- {c.get('ticker')} {c.get('name','')}｜{c.get('signal','')}"
                f"｜進場 {c.get('entry')}｜停損 {c.get('stop')}｜觸發日 {c.get('signal_date')}"
                f"｜{c.get('note','')}")
        st.code("\n".join(lines), language="markdown")

    st.divider()
    st.caption("這份清單由 **tw-swing** 每個交易日盤後產出，tw-hold 只是原樣轉呈。"
               "進場價／停損只在**訊號隔日開盤**可執行，過了就失效。")
    for d in data.get("disclaimer", []):
        st.caption("· " + d)
    _disclaimer(SHORT_DISCLAIMER)


@st.cache_resource(show_spinner="第一次載入：從 tw-swing Release 拉 bundle…")
def _ensure_bundle():
    """回 `{檔名: 有沒有}`。下載中途斷線 / GitHub API 抽風 → 不要讓整頁吐 traceback，
    退化成「一個都沒有」，呼叫端已經有寫好的提示（2026-09-11 修）。"""
    from bundle_data import ensure_assets
    try:
        return ensure_assets()
    except Exception as e:  # noqa: BLE001
        st.session_state["_bundle_err"] = f"{type(e).__name__}: {e}"
        return {}


@st.cache_data(ttl=3600, show_spinner=False)
def _stock_data(code: str) -> dict:
    """個股頁 / 多軌體檢共用的資料包。

    每一張表各自接住例外（某個 parquet 壞了 / schema 變了 → 那張表退化成空的），
    不要讓整頁吐 traceback——這支在多軌體檢是在 `_safe_checks` 之外呼叫的，
    一張表炸掉會連累四軌全滅（2026-09-11 修）。
    """
    import bundle_data as bd
    from factors.factors import quarterly_factors
    errs: list[str] = []

    def _g(fn, *a):
        try:
            return fn(*a)
        except Exception as e:  # noqa: BLE001
            errs.append(f"{getattr(fn, '__name__', fn)}: {type(e).__name__}: {e}")
            return pd.DataFrame()

    px, per, fin = _g(bd.prices, code), _g(bd.per_history, code), _g(bd.financials, code)
    div, rev, chp = _g(bd.dividends, code), _g(bd.revenue, code), _g(bd.chips, code)
    qf = _g(quarterly_factors, fin) if not fin.empty else fin
    return {"px": px, "per": per, "fin": fin, "div": div, "qf": qf, "rev": rev,
            "chips": chp, "_errs": errs}


def _qf_display(df: pd.DataFrame):
    """原始季度表：金額欄改「千元 + 千分號」，其餘欄不動。回傳 Styler。"""
    if df is None or df.empty:
        return df
    d = df.copy()
    money = [c for c in d.columns
             if pd.api.types.is_numeric_dtype(d[c]) and d[c].abs().max() >= 1e5]
    for c in money:
        d[c] = d[c] / 1000
    d = d.rename(columns={c: f"{c}(千元)" for c in money})
    money_k = [f"{c}(千元)" for c in money]
    return d.style.format(subset=money_k, formatter="{:,.0f}", na_rep="—")


def _chart(fn, *args, target=None) -> None:
    """單張圖爆掉不要整頁掛——就地顯示錯誤、繼續下一張。手機關掉拖曳縮放。"""
    tgt = target if target is not None else st
    try:
        tgt.plotly_chart(fn(*args), use_container_width=True, config={
            "scrollZoom": False, "displayModeBar": False, "doubleClick": False,
        })
    except Exception as e:  # noqa: BLE001
        tgt.warning(f"「{getattr(fn, '__name__', '圖')}」畫不出來：{type(e).__name__}: {e}")


def _stock_input(form_key: str, submit_label: str) -> str:
    """個股查詢 / 多軌體檢共用同一支代號。

    ⚠️ 兩頁的輸入框都用 widget key `_stock_code`。Streamlit 在「切頁 → 原本那個
    widget 沒再 render」時會把它的 key 從 session_state 清掉 → 切過去就變空白。
    對策：另存一個**非 widget** 的鏡像 key `_code_mirror`（永不被清），widget 建立前
    先拿它把 `_stock_code` 補回來。"""
    if not st.session_state.get("_stock_code") and st.session_state.get("_code_mirror"):
        st.session_state["_stock_code"] = st.session_state["_code_mirror"]
    with st.form(form_key, border=False):
        c1, c2 = st.columns([5, 1])
        c1.text_input("代號", key="_stock_code", placeholder="2330",
                      label_visibility="collapsed")
        c2.form_submit_button(submit_label, use_container_width=True)
    code = st.session_state.get("_stock_code", "").strip()
    if code:
        st.session_state["_code_mirror"] = code
    return code


def _page_footer(other_nav: str, other_label: str) -> None:
    """個股查詢 / 多軌體檢 共用的頁尾。
    - 回到頂部：`<a href="#top">`（唯一在 Streamlit 可靠的捲動方式，連頁首 anchor='top'）。
    - 切到另一頁：真的 `st.button` —— 功能就等於表頭那顆 radio（`_nav_goto` 由 main()
      在建 radio *前* 寫入 `_nav`，避開「widget 建立後不能改 key」）。"""
    st.divider()
    c1, c2 = st.columns(2)
    c1.markdown('<a href="#top" class="thc-toplink">⬆ 回到頂部</a>', unsafe_allow_html=True)
    if c2.button(other_label, key="_ft_goto", use_container_width=True):
        st.session_state["_nav_goto"] = other_nav
        st.rerun()


def _stock_page() -> None:
    import stockcharts as ch
    st.header("個股查詢", anchor="top")
    _disclaimer()
    st.markdown("**股票代號**")
    code = _stock_input("stock_query", "查詢")
    if not code:
        _disclaimer()
        return

    got = _ensure_bundle()
    if not any(got.values()):
        st.error("拉不到 bundle——雲端需要 `TWSWING_BUNDLE_PAT`（st.secrets），本地需要 `.env`。"
                 + (f"（{st.session_state['_bundle_err']}）"
                    if st.session_state.get("_bundle_err") else ""))
        _disclaimer()
        return

    d = _stock_data(code)
    for _e in d.get("_errs") or []:      # 某張表讀壞了 → 就地講清楚，不靜默當成「沒這檔」
        st.warning(f"這一份資料讀不出來，相關圖表／檢核會缺：{_e}")
    if d["px"].empty and d["fin"].empty:
        st.warning(f"{code} 不在 bundle 內。"
                   + ("本地進階模式可即時補抓（尚未實作）。" if LOCAL_ADVANCED
                      else "雲端唯讀模式只服務 bundle 內的股票。"))
        _disclaimer()
        return

    name = code

    _aflags = _active_flags()
    _aef = _active_of(code, _aflags)
    if _aef and _aef.get("kind") not in (None, "neutral"):
        _sx, _ox = _active_evidence(_aef)
        st.markdown(f'<div class="thc-chips">{_active_chip(_aef)}</div>', unsafe_allow_html=True)
        st.caption((_sx or _ox) + "　—　" + _active_legend(_aflags))

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
        c3, c4 = st.columns(2)
        _chart(ch.roe_trend, d["qf"], name, target=c3)
        _chart(ch.balance_health, d["qf"], name, target=c4)
        _chart(ch.cashflow, d["qf"], name)

    if not d["div"].empty:
        _chart(ch.dividends_chart, d["div"], name)

    xstart = start if (not d["px"].empty and start is not None) else None

    if not d["per"].empty:
        _chart(ch.yield_trend, d["per"], name, xstart)

    rev = d.get("rev")
    if rev is not None and len(rev) >= 13:
        _chart(ch.monthly_revenue, rev, name, xstart)
    elif rev is not None and not rev.empty:
        st.info(f"📊 月營收：目前只有 {len(rev)} 個月，滿 13 個月才畫 YoY 圖"
                "（等 revenue 歷史隨下次 bundle 發佈進來）。")
    else:
        st.info("📊 月營收走勢圖：這檔在 bundle 沒有月營收資料。")

    chp = d.get("chips")
    if chp is not None and not chp.empty:
        _chart(ch.institutional_net, chp, name, xstart)

    if not d["qf"].empty:
        st.subheader("Piotroski F-Score 9 分項")
        st.caption("**只打勾、不加總、不當買賣依據。** 加總分數在價值清單裡當品質門檻，"
                   "這裡是診斷用。")
        st.dataframe(ch.fscore_table(d["qf"]), hide_index=True, use_container_width=True)

    with st.expander("原始季度數據"):
        st.caption("金額欄位以**千元**顯示、加千分號；eps／比率／年季欄維持原值。")
        _raw = d["qf"] if not d["qf"].empty else d["fin"]
        st.dataframe(_qf_display(_raw), use_container_width=True)

    st.divider()
    st.caption("攤開數據讓人／AI 判斷，**不打分、不給買賣建議**（PRD §4.1）。"
               "雲端只服務 bundle 內的股票（約 1000-1980 檔，視資料表而定——不是只有候選池"
               "篩選用的前 500 大，帶哪一檔的代號都可以查）。")
    _disclaimer()
    _page_footer("多軌體檢", f"🔬 多軌體檢 {code} →")


_DERIVED_RELEASE = ("https://github.com/tongxiaooppo-boop/tw-hold"
                    "/releases/download/derived-latest")


@st.cache_resource(show_spinner="載入因子表…")
def _ensure_derived_factors() -> None:
    """factors_{value,deposit}.parquet 不進版控（每天一顆 blob）→ 執行期從 tw-hold
    的 derived-latest release 拉（公開 repo，免 PAT）。本地已有 build 產物就沿用。

    ⚠️ 先下載到 `.part` 再 `replace()`——直接寫目的檔的話，連線中途斷掉會留下半截
    parquet，而「存在且非空」就被當成有了、永遠不重抓，`@st.cache_resource` 又讓它
    整個 session 卡死（2026-09-11 修）。
    """
    import urllib.request
    DERIVED.mkdir(parents=True, exist_ok=True)
    for n in ("factors_value.parquet", "factors_deposit.parquet"):
        p = DERIVED / n
        if p.exists() and p.stat().st_size > 0:
            continue
        tmp = p.with_suffix(p.suffix + ".part")
        try:
            urllib.request.urlretrieve(f"{_DERIVED_RELEASE}/{n}", tmp)
            tmp.replace(p)
        except Exception:  # noqa: BLE001  拉不到就退化成「不在因子表」，不炸
            tmp.unlink(missing_ok=True)


@st.cache_data(ttl=3600, show_spinner=False)
def _factor_row(track: str, code: str) -> dict | None:
    """`factors_{value,deposit}.parquet` 裡該檔那一列（清單頁同一份因子）。

    讀壞了（檔案毀損 / schema 變了）→ 回 None（＝「不在因子表」），不要讓多軌體檢
    整頁掛掉——這支是在 `_safe_checks` 之外呼叫的。壞檔直接刪掉讓下次重抓。
    """
    _ensure_derived_factors()
    p = DERIVED / f"factors_{track}.parquet"
    if not p.exists():
        return None
    try:
        df = pd.read_parquet(p)
    except Exception:  # noqa: BLE001
        p.unlink(missing_ok=True)
        return None
    c = str(code).strip().split(".")[0]
    hit = df[df["ticker"].astype(str).str.split(".").str[0] == c]
    return hit.iloc[0].to_dict() if not hit.empty else None


def _safe_checks(fn, *args, **kwargs) -> list[dict]:
    """跑某一軌的檢核；任何例外 → 就地紅字、回空列，不讓整個「多軌體檢」頁掛掉
    （這頁只是把判準攤開，單軌算不出來不該連累其他三軌）。"""
    try:
        return fn(*args, **kwargs)
    except Exception as e:  # noqa: BLE001
        st.error(f"這一軌算不出來：{type(e).__name__}: {e}")
        return []


def _render_checks(rows: list[dict], note: str, missing: str | None = None,
                   disclaimer: str | None = None) -> None:
    st.caption(note)
    if missing:
        st.info(missing)
        return
    if not rows:
        st.info("這檔缺足夠資料算這一軌。")
        return

    import checklist as cl

    s = cl.summarize(rows)
    if s["缺口"]:
        st.markdown("🔴 **未達的門檻**：" + " · ".join(s["缺口"]))
    else:
        st.markdown("🟢 **沒有門檻被擋下**（不代表完美，只代表這些條件都成立）")
    if s["待確認"]:
        st.caption("⚪ 資料不足、未判定：" + " · ".join(s["待確認"]))
    if s["風險命中"]:
        st.markdown("⚠️ **風險命中**：" + " · ".join(s["風險命中"]))

    def _st_cls(v: str) -> str:
        v = str(v)
        return ("good" if v.startswith("✅") else "bad" if v.startswith("❌")
                else "warn" if v.startswith("⚠️") else "na")

    df = pd.DataFrame(rows)
    for grp in df["組"].drop_duplicates():
        sub = df[df["組"] == grp]
        st.markdown(f"**{grp}**")
        html = ['<div class="thc-cl">',
                '<div class="thc-cl-row thc-cl-hd"><span>項目</span><span>門檻</span>'
                '<span>現值</span><span>狀態</span></div>']
        for _, r in sub.iterrows():
            html.append(
                '<div class="thc-cl-row">'
                f'<span class="thc-cl-item">{_esc(r["項目"])}</span>'
                f'<span class="thc-cl-gate">{_esc(r["門檻"])}</span>'
                f'<span class="thc-cl-cur">{_esc(r["現值"])}</span>'
                f'<span class="thc-cl-st {_st_cls(r["狀態"])}">{_esc(r["狀態"])}</span>'
                '</div>')
        html.append('</div>')
        st.markdown("".join(html), unsafe_allow_html=True)
    if disclaimer:
        st.caption(disclaimer)


def _checklist_page() -> None:
    """多軌體檢：同一檔、四套判準逐條攤開。不加總、不給 verdict／買價／排名。"""
    import checklist as cl

    st.subheader("多軌體檢", anchor="top")
    code = _stock_input("cl_query", "體檢")
    if not code:
        _disclaimer()
        return

    got = _ensure_bundle()
    if not any(got.values()):
        st.error("拉不到 bundle——雲端需要 `TWSWING_BUNDLE_PAT`（st.secrets），本地需要 `.env`。"
                 + (f"（{st.session_state['_bundle_err']}）"
                    if st.session_state.get("_bundle_err") else ""))
        _disclaimer()
        return

    fv, fd = _factor_row("value", code), _factor_row("deposit", code)
    d = _stock_data(code)
    for _e in d.get("_errs") or []:      # 某張表讀壞了 → 就地講清楚，不靜默當成「沒這檔」
        st.warning(f"這一份資料讀不出來，相關圖表／檢核會缺：{_e}")
    px_fin_empty = d["px"].empty and d["fin"].empty
    if px_fin_empty and fv is None and fd is None:
        st.warning(f"{code} 不在資料範圍——bundle 與因子表（約 1000 檔上市普通股）都查無。"
                   "超出範圍的股票**不另外抓單股資料**（PRD §M4 雲端唯讀）。")
        _disclaimer()
        return

    import stockcharts as ch

    name = (fv or fd or {}).get("name") or ""
    nm = name or code
    st.markdown(f"### {code}{' ' + name if name and name != code else ''}")

    # 主動式 ETF 認養：來源正常 → 傳 flag dict（沒動作就傳 {}，檢核表顯示「無」）；
    # 來源過期／抓不到 → 傳 None，檢核表整列不出現。
    _aflags = _active_flags()
    _aef = (_active_of(code, _aflags) or {}) if _aflags else None
    if _aflags:
        st.caption(_active_legend(_aflags))

    qf, px, per, div, rev, chp = (d["qf"], d["px"], d["per"], d["div"], d["rev"], d["chips"])
    end = pd.to_datetime(px["date"]).max() if not px.empty else None

    def _ago(days):
        return end - pd.Timedelta(days=days) if end is not None else None

    t0, t1, t2, t3 = st.tabs(["⚡ 短線", "🟠 波段", "🔵 價值", "🟢 定存"])
    with t0:
        # 短線是日尺度 → 圖只看近 3 個月
        _render_checks(_safe_checks(cl.short_checks, d, active_etf=_aef),
                       "純日線技術面條件逐條攤開。融資融券變化 bundle 沒有 → 不出現。",
                       missing=("這檔在 bundle 沒有價量資料，無法體檢短線軌。"
                                if px.empty else None),
                       disclaimer=SHORT_DISCLAIMER)
        st.caption("——對應圖表（短線尺度：近 3 個月）——")
        if not px.empty:
            _chart(ch.kline, px, nm, _ago(95), ch._MA_SHORT)
        if chp is not None and not chp.empty:
            _chart(ch.institutional_net, chp, nm, _ago(95))
    with t1:
        # 波段是週~數月尺度 → 圖只看近 1 年價量、近 2 年月營收、近 1 季籌碼
        _render_checks(_safe_checks(cl.swing_checks, d, active_etf=_aef),
                       "門檻取自主畫面「長波段候選池」（CANSLIM + Minervini）。趨勢模板只做 7 條，"
                       "不含相對強弱 RS（需全市場橫斷面）。",
                       missing=("這檔在 bundle 沒有價量／財報資料，無法體檢波段軌。"
                                if px_fin_empty else None),
                       disclaimer=SWING_DISCLAIMER)
        st.caption("——對應圖表（波段尺度：近 1 年）——")
        if not px.empty:
            _chart(ch.kline, px, nm, _ago(365), ch._MA_SHORT)
        if rev is not None and len(rev) >= 13:
            _chart(ch.monthly_revenue, rev, nm, _ago(730))
        if chp is not None and not chp.empty:
            _chart(ch.institutional_net, chp, nm, _ago(120))
    with t2:
        # 價值是年度尺度 → 逐季圖看近 6 年、PE 河流看近 5 年
        _render_checks(_safe_checks(cl.value_checks, fv),
                       "F-Score + Magic Formula 精神；門檻與價值清單同一份因子。",
                       None if fv is not None else "這檔不在價值因子表（約 1000 檔），無法體檢價值軌。")
        st.caption("——對應圖表（價值尺度：近 5～6 年）——")
        if not qf.empty:
            c1, c2 = st.columns(2)
            _chart(ch.roe_trend, qf, nm, 24, target=c1)
            _chart(ch.margins, qf, nm, target=c2)
        if not px.empty and not per.empty:
            _chart(ch.pe_river, px, per, nm, _ago(1825))
    with t3:
        # 定存看長期：股利連續性 10+ 年、殖利率 5 年分位、負債結構近 6 年
        _render_checks(_safe_checks(cl.deposit_checks, fd),
                       "殖利率硬底線 5% + 填息率 / 含息報酬 / 配息穩定；門檻與定存清單一致。",
                       None if fd is not None else "這檔不在定存因子表（約 1000 檔），無法體檢定存軌。")
        st.caption("——對應圖表（定存尺度：股利近 12 年、殖利率近 5 年）——")
        if not div.empty:
            _chart(ch.dividends_chart, div, nm)
        if not per.empty:
            _chart(ch.yield_trend, per, nm, _ago(1825))
        if not qf.empty:
            _chart(ch.balance_health, qf, nm, 24)
    st.caption("完整圖表（K 線可選區間、季 EPS、現金流、F-Score…）在「個股查詢」頁。")
    st.divider()
    st.caption("同一檔股票，分別用「短線 / 波段 / 價值 / 定存」四套判準逐條攤開。"
               "**只打勾、不加總、不給 verdict／買價／排名**——成立幾條、缺哪條，自己衡量。"
               "短線軌零回測、只是把技術面條件列出來（tw-hold 是長期工具，短線用 tw-swing）。")
    _disclaimer()
    _page_footer("個股查詢", f"📈 看 {code} 的完整圖表 →")


def _fmt_aum_navps(fmd: dict) -> str:
    """基金規模（總 AUM）+ 淨值（每受益權單位）前後對照 + 當日折溢價——PCF 快照
    本來就有 fund_nav/fund_units，折溢價額外抓 TWSE 收盤價（fund_close，見
    pcf_fetchers.fetch_twse_closes）算出來；跟三方站官網數字對過是準的。"""
    aum_t, aum_p = fmd.get("aum"), fmd.get("aum_prev")
    nps_t, nps_p = fmd.get("navps"), fmd.get("navps_prev")
    parts = []
    if isinstance(aum_t, (int, float)) and isinstance(aum_p, (int, float)) and aum_p:
        pct = (aum_t - aum_p) / aum_p * 100
        parts.append(f"規模 {aum_t / 1e8:,.0f}億（{pct:+.2f}%）")
    if isinstance(nps_t, (int, float)) and isinstance(nps_p, (int, float)) and nps_p:
        pct = (nps_t - nps_p) / nps_p * 100
        parts.append(f"淨值 {nps_t:,.2f}（{pct:+.2f}%）")
    prem = fmd.get("premium_pct")
    if isinstance(prem, (int, float)):
        parts.append(f"折溢價 {prem:+.2f}%")
    elif fmd.get("premium_skipped"):
        # 市價與淨值不同一天 → 不給跨日的折溢價（2026-09-11 修，見 fetch_twse_closes）
        cd = fmd.get("close_date")
        why = (f"收盤價是 {cd} 的，跟 PCF 基準日 {fmd.get('date') or '—'} 不同天"
               if cd else "這份快照沒記收盤價是哪天的，下次重抓才有")
        parts.append(f"折溢價 —（{why}）")
    return "　·　".join(parts)


def _ae_card(code: str, issuer: str, name: str, sev: str, pill: str, ctx: str, *,
             buys: list | None = None, sells: list | None = None,
             names: dict | None = None, note: str | None = None,
             meta_line: str = "") -> str:
    """主動式 ETF 單檔卡片——沿用版型 B 的 thc-card / sw-cols 語言（同長波段那張）。"""
    names = names or {}

    def _li(tks: list | None) -> str:
        if not tks:
            return '<li class="flat">—</li>'
        return "".join(
            f'<li><a href="?code={_esc(t)}" target="_self">{_esc(t)}</a>'
            f'　{_esc(names.get(t, ""))}</li>' for t in tks)

    parts = [
        '<div class="thc-head">',
        f'<span class="thc-tk">{_esc(code)}</span>',
        f'<span class="thc-cn">{_esc(issuer)}{("・" + _esc(name)) if name else ""}</span>',
        f'<span class="thc-pill thc-{sev}">{_esc(pill)}</span>',
        '</div>',
        f'<div class="thc-ctx">{_esc(ctx)}</div>',
    ]
    if note:
        parts.append(f'<div class="thc-note">{_esc(note)}</div>')
    if buys is not None or sells is not None:
        parts.append(
            '<div class="sw-cols">'
            f'<div><div class="sw-h sup">加碼 / 新進</div><ul>{_li(buys)}</ul></div>'
            f'<div><div class="sw-h">調節 / 出清</div><ul>{_li(sells)}</ul></div>'
            '</div>')
    if meta_line:
        parts.append(f'<div class="thc-barcap" style="margin-top:.5rem">{_esc(meta_line)}</div>')
    return (f'<div class="thc-card thc-{sev}"><div class="thc-stripe"></div>'
            f'<div class="thc-body">{"".join(parts)}</div></div>')


def _active_summary(fl: dict) -> str:
    """五檔加總：整體加碼 vs 整體調節（跨五檔彙總，不是單一基金視角）。

    方向沿用 `build_active_etf_flags.py` 的 `kind` 判斷（consensus 優先，
    否則看淨股數方向）——**不是多數決**。同一檔如果有買有賣（分歧），
    不會被藏起來：買賣家數直接標在項目旁，例如「3買2賣，淨額計」。
    """
    buys = [(tk, f) for tk, f in fl.items() if f.get("kind") in ("consensus_buy", "buy")]
    sells = [(tk, f) for tk, f in fl.items() if f.get("kind") in ("consensus_sell", "sell")]
    buys.sort(key=lambda kv: (-(kv[1].get("consensus") or 0),
                              -abs(kv[1].get("net_amount") or kv[1].get("net_shares") or 0)))
    sells.sort(key=lambda kv: ((kv[1].get("consensus") or 0),
                               -abs(kv[1].get("net_amount") or kv[1].get("net_shares") or 0)))

    def _row(tk: str, f: dict) -> str:
        b, s = f.get("buyers") or [], f.get("sellers") or []
        ns = f.get("net_shares")
        lots = f"{ns / 1000:+,.0f} 張" if isinstance(ns, (int, float)) else "—"
        mix = (f'　<span class="thc-flag">（{len(b)}買{len(s)}賣，淨額計）</span>'
               if b and s else "")
        sp = f.get("span_days")
        if isinstance(sp, int) and sp > 1:      # 漏抓一天 → 這一列不是「近一日」
            mix += f'　<span class="thc-flag">（跨 {sp} 個交易日）</span>'
        return (f'<li><a href="?code={_esc(tk)}" target="_self">{_esc(tk)}</a>'
                f'　{_esc(f.get("name") or "")}　<b>{_esc(lots)}</b>{mix}</li>')

    buy_html = "".join(_row(tk, f) for tk, f in buys) or '<li class="flat">—</li>'
    sell_html = "".join(_row(tk, f) for tk, f in sells) or '<li class="flat">—</li>'
    return (
        '<div class="thc-card thc-neutral"><div class="thc-stripe"></div><div class="thc-body">'
        '<div class="thc-head"><span class="thc-cn">五檔加總</span></div>'
        f'<div class="thc-ctx">整體加碼 {len(buys)} 檔　·　整體調節 {len(sells)} 檔'
        '（有買有賣的檔位以淨額判斷方向，比數不隱藏）</div>'
        '<div class="sw-cols">'
        f'<div><div class="sw-h sup">整體加碼 / 新進</div><ul>{buy_html}</ul></div>'
        f'<div><div class="sw-h">整體調節 / 出清</div><ul>{sell_html}</ul></div>'
        '</div></div></div>')


def _active_etf_page() -> None:
    """主動式 ETF 每日動向——那五檔前後兩個交易日的 PCF 差分，日期對齊股票日線。
    純渲染 data/pcf/_index.json + data/derived/active_etf_flags.json，零抓取。
    兼作「爬五家投信官網有沒有正常」的體檢面板。"""
    st.header("主動式 ETF 每日動向", anchor="top")

    idx = _load_pcf_index()
    flags = _load("active_etf_flags.json") or {}
    meta = flags.get("_meta") or {}
    fm_all = meta.get("funds") or {}
    idx_funds = (idx or {}).get("funds") or {}

    if not fm_all and not idx_funds:
        st.error("還沒有 PCF 快照／旗標產出——CI 第一次 rebuild 應該還沒跑完。")
        st.markdown(f"[看 rebuild 執行紀錄 →]({_REBUILD_RUNS_URL})")
        _disclaimer()
        return

    anchor = meta.get("anchor_date") or "—"
    synced, total = meta.get("synced_etfs"), meta.get("total_etfs") or 5
    idx_upd = (idx or {}).get("updated_at")
    st.markdown(
        f"**資料日 {anchor}**　·　{synced if synced is not None else '—'} / {total} 檔算得出差分"
        f"　·　快照最後更新 {_ago_human(idx_upd)}")
    _disclaimer()
    if meta.get("schema_ok") is False:
        st.error("`schema_ok = False`——旗標已在各分頁 / 卡片整組隱藏，直到管線恢復。")
    _idx_date = (idx_upd or "")[:10]
    try:
        if _idx_date and (pd.Timestamp(_taipei_today()) - pd.Timestamp(_idx_date)).days > 3:
            st.warning(f"⚠️ 快照最後更新 {_idx_date}，距今超過 3 天。中間若有交易日，代表 CI 沒跑、"
                       f"或五家投信官網把 CI 的 IP 擋掉了——看 [rebuild 執行紀錄]({_REBUILD_RUNS_URL}) "
                       "的「PCF 快照」步驟有沒有 `::warning::`。")
    except Exception:  # noqa: BLE001
        pass

    fl = flags.get("flags") or {}
    if fl:
        st.markdown(_active_summary(fl), unsafe_allow_html=True)
        st.caption("以下逐檔看是哪些基金在買賣：")

    def _moved_by(code: str):
        buys = sorted(tk for tk, f in fl.items() if code in (f.get("buyers") or []))
        sells = sorted(tk for tk, f in fl.items() if code in (f.get("sellers") or []))
        nm = {tk: (fl[tk].get("name") or "") for tk in (*buys, *sells)}
        return buys, sells, nm

    order = ([r["code"] for r in (idx or {}).get("nav_rank") or []]
             or list(idx_funds) or list(fm_all))
    missing = set((idx or {}).get("missing") or [])

    cards: list[str] = []
    for code in order:
        fi = idx_funds.get(code) or {}
        fmd = fm_all.get(code) or {}
        issuer = fi.get("issuer") or fmd.get("issuer") or ""
        name = fi.get("name") or ""
        snaps_n = len(list((REPO / "data" / "pcf" / code).glob("*.parquet")))
        fetched = _ago_human(fi.get("fetched_at"))

        if code in missing or (not fi and not fmd):
            cards.append(_ae_card(
                code, issuer, name, "neutral", "🔴 沒抓到",
                "這次 CI 完全沒抓到這一檔。",
                note="通常是被反爬擋、或投信官網改版——看 CI log 的 `::warning::`。",
                meta_line=f"最後抓取 {fetched}"))
            continue

        if not fmd.get("synced"):
            tail = ("（群益 buyback API 沒有日期參數，只能等隔天累積第二份）"
                    if issuer == "群益" else "")
            cards.append(_ae_card(
                code, issuer, name, "warn", "🟡 等隔天",
                f"最新 PCF 日 {fi.get('latest_date') or fmd.get('date') or '—'}",
                note=f"目前只有 {snaps_n} 份 PCF 快照——要連續兩個交易日才算得出差分{tail}。",
                meta_line=f"抓取 {fetched}　·　持股 {fi.get('holdings_n', '—')} 檔"))
            continue

        date = fmd.get("date") or fi.get("latest_date") or "—"
        buys, sells, nm = _moved_by(code)
        aum_line = _fmt_aum_navps(fmd)
        meta_line = (f"抓取 {fetched}　·　持股 {fi.get('holdings_n', '—')} 檔"
                     f"　·　磁碟留存 {snaps_n} 份快照")
        cards.append(_ae_card(
            code, issuer, name, "good", "🟢 差分已算",
            f"{fmd.get('prev_date', '?')} → {date}　·　濾掉零星微調後共動 "
            f"{fmd.get('moved_n', 0)} 檔" + (f"　·　{aum_line}" if aum_line else ""),
            buys=buys, sells=sells, names=nm, meta_line=meta_line))

    st.markdown(f'<div class="ae-stack">{"".join(cards)}</div>', unsafe_allow_html=True)

    st.divider()
    st.caption(
        "規模前五大主動式 ETF，發行投信官網每日揭露的 PCF（申購買回清單），前後兩個交易日"
        "真實股數差＝這五檔當日的加碼／調節（門檻濾掉權重當量 <0.03pp 的雜訊）。"
        "賣出也可能是基金應付大額贖回被迫調節，不一定是看壞這檔股票。"
        f"日期對齊股票日線的交易日。**{_ACTIVE_SRC}；非官方三大法人／投信買賣超，永不 gate。**")
    _msp = meta.get("max_span_days") or 1
    _multi = meta.get("multi_day_etfs") or []
    st.caption(
        ("目前顯示**近 1 交易日**的變化（資料日 vs 前一交易日）。"
         if _msp <= 1 else
         f"多數基金顯示**近 1 交易日**的變化；**{'／'.join(_multi)} 中間漏抓，"
         f"它的差分跨 {_msp} 個交易日**（每張卡片標了自己的 `前一份 → 資料日`）。")
        + "近 5 日變化要等每檔基金的快照歷史累積足夠再開。")
    st.caption("代號可點進「個股查詢」看該股日線；旗標同時掛在「多軌體檢／長波段／短線」分頁上。"
               f"　·　🔧 爬取失敗會在 CI 顯示 `::warning::`：[rebuild 執行紀錄 →]({_REBUILD_RUNS_URL})")
    _disclaimer()


APP_NAME = "股市雷達"          # repo 仍叫 tw-hold；網頁表頭用這個（非投顧語氣，2026-09-11 改名）
NAV = ["價值", "定存", "長波段", "短線", "個股查詢", "多軌體檢", "主動式 ETF"]


def _route() -> None:
    """卡片上的代號連結 `?code=XXXX` → 預填個股查詢 + 切分頁。
    處理完就把 query param 清掉，否則每次 rerun 都被鎖在個股查詢分頁。"""
    code = (st.query_params.get("code") or "").strip()
    if code:
        st.session_state["_stock_code"] = code
        st.session_state["_nav"] = "個股查詢"
        del st.query_params["code"]


def main() -> None:
    st.set_page_config(page_title=APP_NAME, page_icon="📡", layout="wide")
    _route()
    goto = st.session_state.pop("_nav_goto", None)   # 頁內「切到另一頁」——在建 radio 前寫入
    if goto in NAV:
        st.session_state["_nav"] = goto
    # radio 還沒建，但 key 綁 session_state——使用者點過的那一頁在 rerun 一開始就已經
    # 寫回去了，所以這裡就能知道等一下會選中哪一頁，徽章 CSS 才併得進同一次注入。
    _inject_css(st.session_state.get("_nav") or NAV[0])
    st.title(f"📡 {APP_NAME}")
    st.caption("價值 / 定存 / 長波段三清單 + 短線（tw-swing 轉呈）+ 個股查詢。**候選 + 為什麼，不是建議。**"
               + ("　·　本地進階模式" if LOCAL_ADVANCED else "　·　雲端唯讀模式"))

    nav = st.radio("分頁", NAV, horizontal=True, key="_nav",
                   label_visibility="collapsed")

    if nav == "價值":
        _card_list("value", "價值清單", _load("value_list.json"))
    elif nav == "定存":
        _card_list("deposit", "定存清單", _load("deposit_list.json"))
    elif nav == "長波段":
        _swing_page(_load("swing_list.json"))
    elif nav == "短線":
        _shortterm_page()
    elif nav == "個股查詢":
        _stock_page()
    elif nav == "多軌體檢":
        _checklist_page()
    else:
        _active_etf_page()


if __name__ == "__main__":
    main()
