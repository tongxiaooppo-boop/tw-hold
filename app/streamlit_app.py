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
import time
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
    "**這不是投資建議。** 只給候選標的與判斷依據，**買賣由你決定**；數字可能有誤或過期，"
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
    "peer_metric_median": "同業ROE中位數", "peer_rank": "產業內排名", "peer_n": "產業檔數",
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
              "industry_ret_6m", "peer_metric_median",
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
                 "季換（3/31、5/15、8/14、11/14），前 15、單一產業 ≤ 40%。"
                 "verdict 只由便宜門檻驅動（PRD §6.3），不做總分排名式的推薦。"),
        "glossary": (
            "- **F-Score（Piotroski F-Score）**：9 項財務體質指標各自二元判斷（有沒有賺錢、"
            "現金流是不是正的、槓桿有沒有降低……）加總成 0–9 分，分數愈高代表財務體質愈"
            "穩健，**跟股票便宜不便宜沒有直接關係**，這裡拿來當品質門檻（≥6 才入池）。\n"
            "- **Magic Formula（Joel Greenblatt「神奇公式」）**：把「便宜」（盈餘殖利率）"
            "和「好」（資本報酬率）各自排名，兩個名次加起來再排一次，兼顧品質與價格——"
            "這裡只借用這個排序精神做參考排序，不是完整重現原始公式的持股週期／再平衡規則。"
        ),
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
            "**結論當上界看待，真實會更差**。\n\n"
            "**2026-09-22 資金天花板跨方法論驗證（情境 B）**：套用跟短線/長波段同一套"
            "「本金獨立、資金不足放棄、賣出即回籠」模型，但改成本金 **200 萬**、**維持"
            "季度整批換股**（不像短線拆成逐日搶資金）——每次換股日上一期全部賣出、"
            "資金 100% 回籠，依市值由大到小只買前 N 檔。逐年報酬（策略當年報酬，"
            "括號內是年末帳戶價值萬元，本金 200 萬）：\n\n"
            "| 年 | N=5 | N=10 | 0050 |\n"
            "| :-- | --: | --: | --: |\n"
            "| 2016 | +14.0%（228.1） | +19.3%（238.6） | +22.1%（228.6） |\n"
            "| 2017 | +7.9%（246.0） | +9.5%（261.3） | +18.0%（270.0） |\n"
            "| 2018 | −2.4%（240.1） | +5.5%（275.6） | −5.5%（256.7） |\n"
            "| 2019 | +2.5%（246.1） | +15.4%（318.1） | +36.1%（342.7） |\n"
            "| 2020 | +20.4%（296.3） | +20.0%（381.6） | +30.2%（449.5） |\n"
            "| 2021 | +32.7%（393.4） | +23.9%（472.7） | +19.9%（548.0） |\n"
            "| 2022 | −24.9%（295.5） | −21.2%（372.3） | −21.7%（431.7） |\n"
            "| 2023 | +17.0%（345.7） | +20.0%（446.8） | +26.9%（550.5） |\n"
            "| 2024 | +31.6%（454.8） | +22.0%（544.9） | +49.3%（818.3） |\n"
            "| 2025 | +30.4%（592.9） | +33.2%（725.6） | +38.1%（1,119.9） |\n"
            "| 2026 | +81.8%（1,078.1） | +84.5%（1,338.4） | +60.9%（1,839.5） |\n"
            "| **全期年化** | **+17.86%** | **+20.38%** | — |\n"
            "| **最大回撤** | −34.0% | −25.6% | — |\n"
            "| **MAR** | 0.52 | 0.80 | — |\n\n"
            "兩者全期年化都輸同期 0050（終值 1,839.5 萬），N=5 輸得更多；但逐年看"
            "有幾年（2018、2022）策略還小贏或跟平 0050，不是每年都輸。\n\n"
            "⚠️ **這不是「排名機制沒用」的新證據**（那個結論已經在上面 2026-09-12 版本"
            "得出）——**是「把分散策略硬改集中」的效果**：價值線原本設計是「過硬門檻的"
            "候選全部等權買進」（每期中位數 217 檔，追求分散），這裡被迫只買市值最大的"
            "前 5 或 10 檔，數字差異主要來自「集中在最大型股」，不是「資金不夠買」"
            "（候選數 217 遠多於 N，真正的限制是 N 本身）。完整數字："
            "`tw-hold/docs/reports/backtest_scenario_b_2026-09-22.md`〈價值因子指數〉一節、"
            "整合版 `docs/reports/backtest_four_ledgers_2026-09-22.html`。\n\n"
            "---\n\n"
            "**每年歸零重跑**：上面是連續複利（某年賺多了會放大隔年本金）。這裡"
            "改成每年 1/1 都重新從 200 萬本金開始，不延續前一年資金水位或未平倉"
            "部位，換股節奏不變（3/6/9/12 月）：\n\n"
            "| 年 | N=5 | N=10 | 0050 |\n"
            "| :-- | --: | --: | --: |\n"
            "| 2016 | +13.0%（226.0） | +18.4%（236.9） | +22.1% |\n"
            "| 2017 | +8.0%（216.1） | +7.9%（215.8） | +18.0% |\n"
            "| 2018 | −6.4%（187.3） | −0.1%（199.9） | −5.5% |\n"
            "| 2019 | −2.0%（196.0） | +5.8%（211.6） | +36.1% |\n"
            "| 2020 | +69.1%（338.2） | +73.1%（346.2） | +30.2% |\n"
            "| 2021 | +12.6%（225.1） | +9.0%（218.0） | +19.9% |\n"
            "| 2022 | −23.0%（154.0） | −22.4%（155.2） | −21.7% |\n"
            "| 2023 | +10.8%（221.6） | +16.8%（233.6） | +26.9% |\n"
            "| 2024 | +21.3%（242.6） | +13.9%（227.8） | +49.3% |\n"
            "| 2025 | +43.5%（287.1） | +38.6%（277.3） | +38.1% |\n"
            "| 2026 | +39.6%（279.2） | +42.3%（284.6） | +60.9% |\n"
            "| **贏 0050 的年數** | **2/11** | **2/11** | — |\n\n"
            "**拆開複利路徑依賴後，價值線逐年贏 0050 的次數只有 2/11**（2020、2025）"
            "——連續複利版的全期年化之所以還算跟得上，主要是靠 2026 那一期用複利"
            "累積的本金放大效果，不是逐年都有穩定的相對優勢。已知限制同短線的每年"
            "歸零重跑（年底未平倉部位用收盤價未實現標記後直接捨棄，不帶到隔年；"
            "2026 只有 1 期換股，樣本比其他年份少）。完整表格："
            "`tw-hold/docs/reports/backtest_scenario_b_yearly_reset_2026-09-22.md`"
            "〈價值因子指數〉一節。\n\n" + _WHY_0050),
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
        "logic": ("候選池六條件全過才進池：CANSLIM 兩條（季 EPS YoY>25%、近3年TTM EPS成長）"
                 "∩ 另外疊加的品質門檻——非 CANSLIM 本身（ROE>15%、毛利率未連兩季惡化、"
                 "F-Score≥6）∩ 月營收 YoY>0 且加速 ∩ 法人20日淨買超>0 ∩ Minervini 趨勢模板"
                 " 8/8。停損參考位 = max(50MA, 近20週前低, 現價−2×ATR14)。失效條件（任一"
                 "觸發）：收盤跌破50MA、趨勢模板<5/8、月營收 YoY 連2個月轉負、季 EPS YoY 轉負。"
                 "**不含大盤方向（CANSLIM 的「M」）當硬性 gate**——2026-09-14 測過拿「只在"
                 "多頭週新進場」當硬性門檻，回測結果變差；改測「排除空頭週（多頭+震盪皆可）」"
                 "才是有效的市況篩選，加上移動 ATR 停損是目前驗證過最好的組合，"
                 "詳見下方名詞解釋與回測結果。"),
        "glossary": (
            "**CANSLIM（William O'Neil 成長股篩選法）逐字母核實——沒做的就明講，不要以為"
            "掛了這個名字就等於七條都做了：**\n\n"
            "| 字母 | 原始定義 | 這裡做了嗎 |\n"
            "| :-- | :-- | :-- |\n"
            "| **C** 當季盈餘 | 季 EPS 年增 ≥18–20% | ✅ 做了（門檻設 25%，比原始更嚴） |\n"
            "| **A** 年度盈餘成長 | 近 3 年每年都要成長 | 🟡 變形——只檢查「現在 TTM EPS "
            "> 3 年前 TTM EPS」，不是逐年都要達標 |\n"
            "| **N** 新產品/新高 | 新產品、新管理層、股價創新高 | ❌ 沒做——bundle 沒有"
            "新聞/產品資料；技術面「離52週高點」是 Minervini 模板自己的條件，不是為 N 做的 |\n"
            "| **S** 籌碼供需 | 流通股數少、庫藏股、爆量上漲 | ❌ 沒做——沒有股數變化/"
            "庫藏股資料源 |\n"
            "| **L** 領導股 | 產業內相對強度排名最前 | 🟡 變形——借用 Minervini 的 RS "
            "百分位（對比0050），概念相通但不是 CANSLIM 自己算的 |\n"
            "| **I** 法人認養 | 法人持股家數增加、優質基金買進 | 🟡 變形——用「法人20日"
            "淨買超金額」當代理，不是「持股家數變化」 |\n"
            "| **M** 大盤方向 | 整體市場要處於確認的多頭 | 🟡 **變形，2026-09-14 拍板**——"
            "「只在多頭週新進場」測過會讓表現變差（年化 +13.2%→+7.0%、回撤 −37.1%→"
            "−43.2%），太硬；改成「排除空頭週（多頭+震盪皆可）」才是有效門檻，已收進"
            "候選池新進場邏輯（見下方回測結果），跟原始 CANSLIM「確認多頭」的定義不同，"
            "是比較軟的擇時 |\n\n"
            "**另外三條門檻（ROE>15%、毛利率未連兩季惡化、F-Score≥6）根本不是 CANSLIM**，"
            "是另外借用 Piotroski F-Score 精神加的品質篩選，混在同一句「CANSLIM 基本面」"
            "裡容易誤會成原始定義的一部分，這裡拆開講清楚。\n\n"
            "**Minervini 趨勢模板（Mark Minervini「動能大師」的 Stage 2 判定）**：8 條"
            "均線排列＋相對高低點的條件（例如股價站上 MA50/150/200、MA200 向上、離 52 週"
            "低點夠遠……），用來篩「目前處於健康上升趨勢」的股票，**純技術面過濾，不保證"
            "會繼續漲**——這裡做了 8 條裡的 8 條，checklist 頁的「波段」分頁因為算力/資料"
            "限制只做 7 條，會跟這裡數字對不上。"
        ),
        "backtest": (
            "**實驗 E（2026-09-14 跑，2026-09-23 修正年化，事件驅動回測，550 週，"
            "universe 609 檔，市況進場 × 移動停損組合矩陣，共 10 種口徑）**\n\n"
            "🔴 **2026-09-23 查證：候選池 2016-01～2019-02 結構性恆空，原本的年化被"
            "拖低了近10個百分點，甚至翻案了「打不打得過0050」的結論**——候選池六條件"
            "之一「近3年TTM EPS要成長」需要12季前財報，但季度財報只從2015-Q1開始，"
            "第一個候選池非空的週落在2019-02-15。原本算年化是拿整個2016-2026"
            "（10.65年）當分母，把這近3年的0%死區也算進去；下表「年化」欄已經改成"
            "排除死區、只從2019-01-01起算的正確版本（回撤/勝率不受死區影響，維持"
            "原樣）。**修正前現行規格顯示+21.9%輸給0050同期+24.0%，修正後其實是"
            "+31.0%小贏0050修正後的+29.7%**——結論從「打不過大盤」翻案成「小贏"
            "大盤」。完整說明見 `docs/reports/backtest_longswing_20260923.md`"
            "（`_20260914.md`/`_20260912.md` 兩份舊報告的年化已經過時，不要再引用）。\n\n"
            "⚠️ **命名澄清（2026-09-23）**：下表「次日開盤」才是本 repo 其他報告"
            "（`backtest_scenario_b.py`／`backtest_top17_buyable.py`，也就是短線/"
            "價值分頁引用的「資金天花板」「每年歸零」那套）定義的**買得到口徑**"
            "——之前 tw-swing 測過「限價三日」（訊號收盤掛限價、3日內沒成交放棄）"
            "當買得到的候選，實測後被打槍，確定買得到原則就是次日開盤。這支腳本"
            "早期把「限價於訊號收盤」誤標成「買得到口徑」，是這支腳本自己的舊命名"
            "跟其他報告不一致，已經改名，不要把「限價於訊號收盤」那列當成買得到"
            "版本看。\n\n"
            "| 口徑 | 年化（2019起，正確） | 最大回撤 | 勝率 |\n"
            "| :-- | --: | --: | --: |\n"
            "| **次日開盤（＝本repo買得到口徑，PRD字面規格：不限市況、固定停損）** | +18.7% | −37.1% | 25% |\n"
            "| 限價於訊號收盤（更保守的進場假設，非買得到口徑，固定停損） | +16.7% | −37.1% | 23% |\n"
            "| 次日開盤 + 移動 ATR 停損（不限市況） | +27.1% | −31.2% | 42% |\n"
            "| 只留多頭週（M gate）+ 固定停損 | +9.9% | −43.2% | 28% |\n"
            "| 只留多頭週（M gate）+ 移動 ATR 停損 | +10.0% | −31.6% | 41% |\n"
            "| 排除空頭週 + 固定停損 | +20.4% | −36.9% | 28% |\n"
            "| **✅ 排除空頭週 + 移動 ATR 停損（現行規格＝買得到口徑）** | **+31.0%** | **−29.4%** | 43% |\n"
            "| 排除空頭週 + 市況緊縮停損（空頭/震盪收緊到1.5×ATR，買得到口徑） | +37.2% | −39.5% | 41% |\n"
            "| 限價於訊號收盤 + 排除空頭週 + 移動ATR停損（額外穩健性測試，非買得到） | +27.2% | −39.8% | 43% |\n"
            "| 限價於訊號收盤 + 排除空頭週 + 市況緊縮停損（額外穩健性測試，非買得到） | +27.1% | −43.9% | 41% |\n"
            "| 0050 同期（含息還原，2019起） | +29.7% | −33.8% | — |\n\n"
            "**額外穩健性測試（2026-09-23 使用者追加）**：把現行規格／市況緊縮停損"
            "換成更保守的「限價於訊號收盤」進場（跳空開高的訊號直接放棄）試一次——"
            "兩者年化都掉到 +27%左右、輸給 0050 修正後的 +29.7%，回撤也都變差"
            "（−29.4%→−39.8%、−39.5%→−43.9%）。這符合直覺：長波段候選池訊號本來就"
            "偏動能股，好標的容易跳空開高，保守進場會系統性放棄最強勢的那些訊號。"
            "**但這不是「買得到口徑打不過0050」的證據**——本repo的買得到口徑定義"
            "是次日開盤，不是這裡測的限價假設，現行規格用買得到口徑本身是小贏的"
            "（見上面 +31.0%）。這兩格只是告訴你：如果你的下單習慣比較保守（怕"
            "追高不敢用市價/次日開盤），數字會差多少。\n\n"
            "**「排除空頭週 + 移動 ATR 停損」是核心矩陣裡的最佳解，已收進候選池的進出場邏輯"
            "（2026-09-14 拍板）**：年化跟回撤同時贏過「不限市況+移動停損」，證實市況篩選"
            "要軟（排除空頭週，多頭+震盪皆可進場）不能硬（只留多頭週）——震盪週的候選池"
            "本身就有濾掉弱股的效果，硬性只留多頭週反而把有效訊號也一起擋掉。\n\n"
            "**「市況緊縮停損」測過但沒有採用**：多頭維持 2×ATR、空頭/震盪收緊到 1.5×ATR，"
            "年化確實更高（+37.2%），但最大回撤反而惡化到 −39.5%（比不緊縮的 −29.4% 更深）"
            "——收緊倍數讓部位在震盪期更容易被正常拉回洗出去，減少了本來能撐過去、後續"
            "反彈的部位，年化靠少數幾筆大賺的交易撐起來，回撤卻變差。這條線的核心關切"
            "是「不求賺多少，但不要賠很大」，這個變體用回撤換年化的方向不對，所以只留"
            "在下方表格當紀錄，沒有收進候選池邏輯。\n\n"
            "現行規格（固定停損、不限市況）原本的主要弱點是停損位進場當下算一次、之後"
            "不隨獲利上移，正常拉回就把部位洗出去，吃不到後面的行情——這是為什麼移動停損"
            "普遍比固定停損好；市況篩選則是額外多贏一段，兩者疊加才是現在這格。\n\n"
            "**分市況（0050 代理，`reference.regime`，只算2019起、累積報酬不是年化）**：\n\n"
            "| 口徑 | 多頭（967天） | 震盪（553天） | 空頭（341天） |\n"
            "| :-- | --: | --: | --: |\n"
            "| 次日開盤（不限市況、固定停損） | +518.5% | +36.2% | −55.8% |\n"
            "| 移動 ATR 停損（不限市況） | +235.8% | +196.4% | −36.8% |\n"
            "| 只留多頭週（M gate）+ 固定停損 | +503.2% | −24.2% | −55.0% |\n"
            "| **✅ 排除空頭週 + 移動 ATR 停損（現行規格）** | +226.9% | **+199.3%** | "
            "**−19.2%** | \n"
            "| 排除空頭週 + 市況緊縮停損 | +233.1% | +254.5% | −4.4% |\n\n"
            "獲利幾乎全部來自多頭（候選池本來就偏動能/趨勢股，正常）；現行規格在震盪期"
            "維持移動停損的優勢（+199.3%），同時因為排除空頭週新進場，空頭期虧損"
            "（−19.2%）比不篩市況的版本（−36.8%）更淺——這是市況篩選真正貢獻的地方，"
            "不是「少曝險=安全」這種直覺，是空頭週的候選池訊號品質本身就比較差，篩掉"
            "有實質作用。\n\n"
            "完整結果：`docs/reports/backtest_longswing_20260923.md`。\n\n"
            "🔴 生存者偏差：universe 是今天 bundle 的 609 檔（市值/成交值前段班），"
            "**結論當上界看待，真實會更差**。\n\n"
            "✅ **市況進場門檻 + 移動停損都已經是產品邏輯，不只是回測數字**：候選池"
            "`build_candidate_pool()`（2026-09-14）大盤空頭週整批回空、不顯示新候選；"
            "下方「📉 出場觀察表」（`screener/swing_stops.py`，2026-09-12 上線）用"
            "「第一次通過候選池六條件那天」當進場代理（**不需要你輸入實際買入日期/"
            "價格**），逐日追蹤移動停損（進場後最高價 − 2×進場當天 ATR14，倍數固定"
            "2.0×，跟這次驗證最好的組合一致，沒有採用「市況緊縮到1.5×」那個變體——"
            "見上方為什麼沒採用）。**跟回測不是同一份程式碼**：這裡是「候選池狀態機 + "
            "進場代理」逐日累積出來的觀察表，回測是全歷史模擬重算——邏輯一致但實作"
            "分開，兩邊要各自維護。頁面上方 `risk_stop` 欄仍是 §5.3「進場當下算一次」"
            "的參考位，移動停損是下方觀察表額外算的另一個數字，兩者不是同一件事、"
            "刻意並存。"
            "\n\n"
            "🔴 **2026-09-23 查證：2016-01～2019-02 這段候選池恆空，是資料地基問題**——"
            "CANSLIM 六條件之一「近 3 年 TTM EPS 要成長」的算法要拿 12 季前的財報"
            "比較，但季度財報資料只從 2015-Q1 開始，往回推第一次算得出來要到 "
            "2019-Q1 附近，實測第一個候選池非空的週是 **2019-02-15**。下面表格"
            "**只列 2019 起、真正有資料可以評估的年份**——2016-2018 不是策略評估過"
            "那三年剛好沒找到標的，是資料根本不足以判定，列出來會誤導，直接不放。"
            "「全期年化/最大回撤/MAR」這幾個統計數字用的是 NAV 曲線從第一筆真實交易"
            "才開始算，本來就沒被這段死區拖累，不需要重算。\n\n"
            "**2026-09-22 資金天花板跨方法論驗證（情境 B，跟短線/價值同一套模型）**："
            "套上「本金獨立 200 萬、資金不足放棄、市值前 N、次日開盤進場、賣出即回籠」"
            "的約束（跟上面 2026-09-14 那份「純事件驅動、不設本金上限」的回測是不同"
            "程式碼、不同模型）。N=5 與 N=10 數字幾乎相同，逐年報酬（策略當年報酬，"
            "括號內是年末帳戶價值萬元，本金 200 萬，取 N=5）：\n\n"
            "| 年 | 策略 | 0050 |\n"
            "| :-- | --: | --: |\n"
            "| 2019 | −1.5%（196.9） | +36.1%（252.3） |\n"
            "| 2020 | +2.7%（202.2） | +30.2%（330.9） |\n"
            "| 2021 | +157.7%（521.1） | +19.9%（403.4） |\n"
            "| 2022 | −3.8%（501.4） | −21.7%（317.8） |\n"
            "| 2023 | +80.9%（907.1） | +26.9%（405.3） |\n"
            "| 2024 | +65.5%（1,501.3） | +49.3%（602.4） |\n"
            "| 2025 | +45.4%（2,183.2） | +38.1%（824.5） |\n"
            "| 2026 | +5.8%（2,309.8） | +60.9%（1,354.2） |\n"
            "| **全期年化** | **+38.49%（N=5）／+38.80%（N=10）** | — |\n"
            "| **最大回撤** | −27.4% | — |\n"
            "| **MAR** | 1.41／1.42 | — |\n\n"
            "獲利集中在 2021/2023/2024/2025 幾個多頭年份，2019-2020 小賠、2022 空頭"
            "小賠、2026 明顯放緩——**跟連續複利版 2026-09-14 那份「純事件驅動、不設"
            "本金上限」的回測方向一致**（移動停損 + 市況篩選確實有效），資金天花板版"
            "數字更高是因為多頭年份用複利部位重壓放大了效果，**兩份用不同方法論互相"
            "佐證同一個結論，不是互相矛盾**。完整數字："
            "`tw-hold/docs/reports/backtest_scenario_b_2026-09-22.md`〈長波段候選池〉一節、"
            "整合版 `docs/reports/backtest_four_ledgers_2026-09-22.html`（這兩份原始報告"
            "仍然列出 2016-2018，已補上同一則資料地基說明，只是沒有刪列——app 這裡"
            "直接省略更乾淨）。\n\n"
            "---\n\n"
            "**每年歸零重跑**：上面是連續複利。這裡改成每年 1/1 都重新從 200 萬本金"
            "開始，不延續前一年資金水位或未平倉部位（同樣只列 2019 起）：\n\n"
            "| 年 | N=5 | N=10 | 0050 |\n"
            "| :-- | --: | --: | --: |\n"
            "| 2019 | −1.5%（196.9） | −0.1%（199.8） | +36.1% |\n"
            "| 2020 | +2.9%（205.9） | +3.0%（206.1） | +30.2% |\n"
            "| 2021 | +186.1%（572.3） | +186.6%（573.3） | +19.9% |\n"
            "| 2022 | −5.0%（190.1） | −6.9%（186.2） | −21.7% |\n"
            "| 2023 | +80.9%（361.9） | +80.9%（361.9） | +26.9% |\n"
            "| 2024 | +70.5%（341.0） | +73.7%（347.5） | +49.3% |\n"
            "| 2025 | +51.0%（302.0） | +51.0%（302.0） | +38.1% |\n"
            "| 2026 | +5.8%（211.6） | +6.1%（212.2） | +60.9% |\n"
            "| **贏 0050 的年數** | **5/8** | **5/8** | — |\n\n"
            "**拆開複利路徑依賴後長波段逐年贏 0050 五次**（2021-2025 連續五年），"
            "比價值線（2/11，見上方）更穩定——2021 那年 +186% 是單一年份的爆發，"
            "不是連續複利下由前幾年小賺墊高本金堆出來的假象。已知限制同短線的每年"
            "歸零重跑。完整表格："
            "`tw-hold/docs/reports/backtest_scenario_b_yearly_reset_2026-09-22.md`"
            "〈長波段候選池〉一節。\n\n" + _WHY_0050),
    },
    "short": {
        # 2026-09-22 補：之前這裡只講表格欄位，規則本身怎麼做完全沒寫（丟給
        # tw-swing 自己的文件）——使用者要求把策略說明實際寫進 tw-hold，不要
        # 只是一句「看 tw-swing 文件」。逐規則 111 條全掃排行榜還是只在 tw-swing
        # 自家 BENCH.md（那個量體不適合搬過來），但 capital_watch 這三條實際在
        # 跑的規則本身的邏輯，寫在這裡。
        "logic": (
            "**現行 `capital_watch` 組合，三條規則各自獨立、進出場邏輯都不同：**\n\n"
            "**H2-trailatr2 · 三日兩缺口（缺口續勢）**——進場：今天、昨天各出現一個"
            "向上跳空缺口（連續兩個缺口）且收盤站上 MA20（過濾下跌途中的反彈跳空）。"
            "初始停損＝第二個缺口那根 K 棒最低價 − 0.5×ATR14；**出場換成移動停損**——"
            "進場後最高價 − 2×進場日 ATR14，獲利達 1R 後停損上移到成本（保本），最長"
            "持有 60 天。「H2」本身進場條件沒變，這是**只換出場**的變體（tw-swing"
            " PRD 規定不能改既有規則的 entry，要測新出場一律用另開變體的方式）。\n\n"
            "**Y4 · 上升軌道突破 + 月營收年增加速 + 估值未過熱（CANSLIM 精神）**——"
            "進場：A3 突破上升軌道線 + 月營收年增率轉正 + 營收年增**正在加速**（比"
            "只要求轉正更嚴）+ PE 百分位 < 75（估值還沒過熱）四個條件疊加。出場**跟 "
            "H2-trailatr2 用同一套機制**（2×ATR 移動停損 + 1R 保本、60 天到期）——"
            "Y4 這條規則本身的定義裡就內建了移動停損，不是額外疊加的變體。\n\n"
            "**W6 · 月營收創年高 + 估值便宜（GARP：Growth At a Reasonable Price）**——"
            "進場：最新月營收創近 12 個月新高 + PE 百分位 < 40（相對自身歷史便宜）"
            "兩個背景條件成立時，等**當天 MA5 上穿 MA20**才真正觸發。**出場是三條"
            "裡最簡單的一條**——固定停損（進場當根最低價 − 0.5×ATR14），沒有移動"
            "停損、沒有保本機制、也沒有基本面轉弱就出場的邏輯，純粹撐到觸發停損或"
            "自然出場。這是它在 tw-swing 自家逐規則框架裡「死在最大回撤」的主要"
            "原因——好的進場訊號配笨出場，抱不住波動。\n\n"
            "三條規則的訊號、進場價、停損位都是 tw-swing 每日盤後產生、tw-hold 原樣"
            "轉呈，不在這裡重算。"),
        "glossary": ("`pool_label`＝命中哪組規則、`進場`／`停損`＝進場價與停損參考位、"
                 "`風險%`／`部位%`＝那個停損位換算出的部位風險與建議部位大小、`RS`＝相對強度"
                 "百分位、`量比`＝成交量對均量的倍數、`觸發日`＝訊號出現的那天。"
                 "規則本身完整的逐規則排行榜（111 條全掃）記在 tw-swing 自己的文件裡"
                 "（`docs/BENCH.md`、https://tw-swing.pages.dev/bench），這裡不重複收錄。"),
        "backtest": (
            "**⚠️ 現行掛牌的是出場變體，不是規則庫排行榜上的原始版**：tw-swing 模擬單"
            "真正在跑的是 `H2-trailatr2`（H2「三日兩缺口」的進場條件不變，出場換成"
            "**2×ATR 移動停損 + 保本**）跟 `Y4`（CANSLIM 本尊，不是任何出場變體）跟 "
            "`W6`（原始版，沒有變體）——三條合稱 `capital_watch` 組合（2026-09-22 "
            "起，取代舊制風險%配置）。**bench.html 排行榜上獨立列出的「H2」「Y4-plow20」"
            "是同一家族裡回測表現最好的版本，不是實際部署版本**，兩者不要混為一談。\n\n"
            "---\n\n"
            "**tw-hold 資金天花板跨方法論驗證（情境 B，2026-09-22）**：跟長波段/價值線"
            "同一套模型——每條規則各自獨立本金 100 萬、資金不足放棄、同日多檔訊號依"
            "市值取前 N（N=5/N=10）、次日開盤進場、賣出即回籠。這套模型現在也是 "
            "tw-swing `paper_capital.py` 真正在跑的模擬單口徑，跟 tw-swing 自家 "
            "bench.html 那套「逐筆超額報酬 vs 同期0050」的規則篩選框架是**不同層次的"
            "問題**（篩選框架決定「這條規則有沒有 edge」，資金天花板決定「用真實資金"
            "上限去交易，年化/回撤長什麼樣」），兩邊數字不能直接對照。\n\n"
            "| 規則 | 出場邏輯 | N=5 年化 | N=10 年化 | 最大回撤 | MAR |\n"
            "| :-- | :-- | --: | --: | --: | --: |\n"
            "| H2-trailatr2 | 2×ATR 移動停損＋保本 | +6.58% | +6.70% | −80.5%～−81.0% | 0.08 |\n"
            "| Y4 | 2×ATR 移動停損＋保本（規則本身內建，同機制） | +12.99% | +12.99% | −63.6% | 0.20 |\n"
            "| W6 | 固定停損＋到期（三條裡唯一沒有移動停損的） | +8.21% | +8.21% | −72.1% | 0.11 |\n\n"
            "逐年報酬（策略當年報酬，括號內是年末帳戶價值萬元，本金 100 萬，取 N=5、"
            "N=10 數字幾乎相同）：\n\n"
            "| 年 | H2-trailatr2 | Y4 | W6 | 0050 |\n"
            "| :-- | --: | --: | --: | --: |\n"
            "| 2016 | −0.9%（99.1） | +92.8%（192.8） | +23.5%（123.5） | +22.1%（121.2） |\n"
            "| 2017 | −25.0%（74.3） | +24.3%（239.6） | +19.3%（147.4） | +18.0%（143.2） |\n"
            "| 2018 | −10.7%（66.3） | +79.9%（431.1） | −41.4%（86.3） | −5.5%（136.2） |\n"
            "| 2019 | +46.2%（96.9） | −19.9%（345.1） | −13.5%（74.7） | +36.1%（181.8） |\n"
            "| 2020 | +28.1%（124.2） | −15.0%（293.5） | −32.2%（50.6） | +30.2%（238.4） |\n"
            "| 2021 | +27.3%（158.1） | +39.4%（409.0） | +69.7%（85.9） | +19.9%（290.7） |\n"
            "| 2022 | +22.8%（194.2） | −20.3%（326.0） | −17.7%（70.7） | −21.7%（229.0） |\n"
            "| 2023 | +0.6%（195.3） | +9.5%（357.2） | +40.4%（99.2） | +26.9%（292.0） |\n"
            "| 2024 | −63.1%（72.1） | +25.2%（447.0） | +99.7%（198.2） | +49.3%（434.1） |\n"
            "| 2025 | +9.1%（78.7） | −45.6%（243.4） | +53.9%（305.0） | +38.1%（594.1） |\n"
            "| 2026 | +148.7%（195.7） | +48.1%（360.3） | −25.8%（226.4） | +60.9%（975.7） |\n\n"
            "三條都遠遠輸同期 0050（同組 100 萬本金對照組 2026 終值約 976～938 萬，"
            "三條規則自己終值只有 196～360 萬）——**這套模型下的回撤比 bench.html 顯示"
            "的樂觀很多**（尤其 H2-trailatr2 深達 −80%），原因是「各自獨立 100 萬、"
            "訊號來就全押現金」放大了波動，不代表規則本身沒有 edge，是資金約束 + "
            "滿倉部署的效果，跟 tw-swing 自己實際用的風險%配置（每筆只押一部分本金）"
            "不是同一件事。\n\n"
            "**W6 為什麼在這套模型下還留著**：W6 在 tw-swing 自家逐規則框架"
            "（bench.html）判「四道門檻不過」（死在 MAR、最大回撤），**規則層本身沒有"
            "翻案**；但在這套資金天花板 / 跨方法論驗證下，年化跟回撤跟另外兩條在同一"
            "數量級，沒有明顯更差——這是它被納入 `capital_watch` 的依據，是「配置決定"
            "在這套模型下站得住」，不是「規則層通過了」。\n\n"
            "---\n\n"
            "**每年歸零重跑（拆開複利路徑依賴，看逐年獨立表現）**：上面的年化數字是"
            "「連續複利」——某一年賺多了會放大隔年的本金，一兩個爆賺年可以撐起"
            "整段期間的年化。這裡改成**每年 1/1 都重新從 100 萬本金開始**，不延續"
            "前一年的資金水位，用來看「規則本身逐年獨不獨立地穩」（N=5/N=10 數字"
            "幾乎相同，只列 N=5）：\n\n"
            "| 年 | H2-trailatr2 | Y4 | W6 | 0050 |\n"
            "| :-- | --: | --: | --: | --: |\n"
            "| 2016 | −0.9% | +92.8% | +23.5% | +22.1% |\n"
            "| 2017 | −25.0% | +24.3% | +19.3% | +18.0% |\n"
            "| 2018 | −10.7% | +79.9% | −41.4% | −5.5% |\n"
            "| 2019 | +46.2% | −19.9% | −13.5% | +36.1% |\n"
            "| 2020 | +41.3% | −13.7% | −26.7% | +30.2% |\n"
            "| 2021 | +27.8% | +48.0% | +60.7% | +19.9% |\n"
            "| 2022 | +25.7% | −20.3% | −16.8% | −21.7% |\n"
            "| 2023 | +0.6% | +9.5% | +1.8% | +26.9% |\n"
            "| 2024 | −62.2% | +25.2% | +98.1% | +49.3% |\n"
            "| 2025 | +15.3% | −45.6% | +60.2% | +38.1% |\n"
            "| 2026 | +124.5% | +28.5% | +82.4% | +60.9% |\n"
            "| **贏 0050 的年數** | **5/11** | **5/11** | **7/11** | — |\n\n"
            "**逐年勝率跟連續複利版的排名不一樣**——W6 逐年贏 0050 的次數最多"
            "（7/11），H2-trailatr2／Y4 都是打平（5/11），但三條各自都有單年重摔"
            "的情況（H2-trailatr2 2024 −62.2%、Y4 2025 −45.6%、W6 2018 −41.4%），"
            "**沒有一條是「每年都穩」的**。連續複利版年化數字比較好看的規則，不代表"
            "逐年品質比較穩，是少數幾個爆賺年用複利放大了整段期間的年化——這正是"
            "「歸零重跑」這個角度存在的理由。已知限制：年底還沒出場的部位用當天"
            "收盤價做未實現標記後直接捨棄，不算出場也不會帶到隔年，某些年末數字"
            "含未實現損益。完整表格（含 N=10、成交筆數）："
            "`tw-hold/docs/reports/backtest_scenario_b_yearly_reset_2026-09-22.md`"
            "〈附加：H2-trailatr2 / Y4〉、〈W6〉兩節。\n\n"
            "**月報酬熱力圖／權益曲線**：這裡的資金天花板模型是 tw-hold 這邊另外"
            "驗證用的，不是 tw-swing 自己畫圖表的那套。tw-swing 官方 tearsheet"
            "（權益曲線、回撤水下圖、**月報酬熱力圖**、滾動夏普）用的是它自己"
            "風險%配置的 `portfolio_sim`，現在對應到 `capital_watch` 組合的版本在 "
            "`tw-swing/docs/reports/tearsheet_20260923-bba58b2-capital_watch.html`"
            "（2026-09-23 重新產生，CAGR +18.73%、最大回撤 −30.7%、Sharpe 1.08）——"
            "**這是另一套模型**（風險%配置，不是資金天花板）——bench.html 逐規則"
            "篩選／tw-hold 資金天花板（連續複利+每年歸零兩個角度）／tw-swing 風險%"
            "配置 tearsheet，三套方法論各自回答不同問題，數字不能互相替代或加總。\n\n"
            "完整數字：`tw-hold/docs/reports/backtest_scenario_b_2026-09-22.md`"
            "〈附加：H2-trailatr2 / Y4〉、〈W6〉兩節，整合版 "
            "`docs/reports/backtest_four_ledgers_2026-09-22.html`。生存者偏差同上（609 "
            "檔 universe，結論當上界看待）。"),
    },
}


def _strategy_backtest_expander(kind: str) -> None:
    """策略規格說明跟回測結果拆成兩個獨立展開區——合在一起內容太長，兩者關心的
    問題也不同（規格是「這條線怎麼運作」，回測是「跑起來的結果」），2026-09-14
    使用者要求拆開。沒有回測數字的軌（例如短線）就只有前一個展開區。"""
    info = BACKTEST_NOTES.get(kind)
    if not info:
        return
    has_bt = "backtest" in info
    spec_title = "📖 策略邏輯（點開看）" if has_bt else "📖 策略規格說明（點開看）"
    with st.expander(spec_title):
        st.markdown("**策略怎麼做的**" if has_bt else "**表格欄位是什麼意思**")
        st.markdown(info["logic"])
        if "glossary" in info:
            st.markdown("**名詞是什麼意思**")
            st.markdown(info["glossary"])
    if has_bt:
        with st.expander("📊 回測報告（點開看）"):
            st.markdown(info["backtest"])


def _fmt(field: str, v) -> str:
    if v is None or v == "":
        return "—"
    if isinstance(v, bool):
        return "是" if v else "否"
    if isinstance(v, (int, float)):
        if field in ("peer_rank", "peer_n"):          # 名次/檔數：整數，不要顯示 .00
            return f"{int(v)}"
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
    notes = set((f.get("exit_notes") or {}).values())
    if "出清" in notes:
        tail += "・已出清"
    elif "僅剩1張" in notes:
        tail += "・僅剩1張"
    return f'<span class="thc-flag">{_esc(label + tail)}</span>'


def _exit_note_text(exit_notes: dict) -> str:
    """{基金代號: "出清"/"僅剩1張"} → 附在賣出證據句後面的括號註記。"""
    if not exit_notes:
        return ""
    parts = [f"{code} {note}" for code, note in sorted(exit_notes.items())]
    return "（" + "、".join(parts) + "）"


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
    exit_txt = _exit_note_text(f.get("exit_notes") or {})
    return "", f"主動式 ETF 調節：{who}{win}淨賣超 {lots.lstrip('+')}{same}{exit_txt}"


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
.thc-header-badge{display:flex;justify-content:flex-end;align-items:center;
  height:100%;padding-top:1.1rem;}
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
/* 主動式 ETF 卡片內的持股明細——用 .thc-details 展開，表格本身限高可捲動
   （先看前段、往下拉看其餘全部），表頭黏在捲動區頂端方便對欄。 */
.ae-hold-wrap{max-height:340px;overflow-y:auto;margin-top:.35rem;border:1px solid var(--thc-line);border-radius:6px;}
.ae-hold-table{width:100%;border-collapse:collapse;font-size:.8rem;}
.ae-hold-table thead th{position:sticky;top:0;background:var(--thc-surface2);text-align:left;
  padding:.32rem .5rem;border-bottom:1px solid var(--thc-line);color:var(--thc-faint);
  font-weight:600;font-size:.72rem;}
.ae-hold-table td{padding:.28rem .5rem;border-bottom:.5px solid var(--thc-line);color:var(--thc-soft);}
.ae-hold-table tr:last-child td{border-bottom:none;}
.ae-hold-table td.num,.ae-hold-table th.num{text-align:right;font-family:var(--thc-mono);
  font-variant-numeric:tabular-nums;color:var(--thc-ink);}
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
/* 總經導航——市場多空卡（方案 A：雙欄卡片，MA60/MA200 兩列並陳）。
   跟 reference.regime 的判斷語意色共用同一組 token，但這裡是獨立判斷（見
   reference/market_status.py 檔頭），不要混成同一件事。 */
.mc-grid{display:grid;gap:.7rem;grid-template-columns:1fr;margin-top:.3rem;}
@media (min-width:720px){.mc-grid{grid-template-columns:1fr 1fr;}}
.mc-card{display:flex;background:var(--thc-surface);border:1px solid var(--thc-line);
  border-radius:10px;overflow:hidden;}
.mc-card .stripe{width:4px;flex-shrink:0;background:var(--thc-neutral);}
.mc-card.good .stripe{background:var(--thc-good);}
.mc-card.warn .stripe{background:var(--thc-warn);}
.mc-body{padding:.9rem 1.1rem;flex:1;min-width:0;}
.mc-head{display:flex;align-items:baseline;justify-content:space-between;margin-bottom:.35rem;}
.mc-market{font-weight:700;font-size:.95rem;color:var(--thc-ink);}
.mc-ticker{font-family:var(--thc-mono);font-size:.78rem;color:var(--thc-faint);}
/* 現價＋漲跌——真價格變動，用 --thc-up/--thc-down（紅漲綠跌），不跟下面 MA 判斷的
   good/warn/neutral 那組判斷色混在一起。 */
.mc-px{font-family:var(--thc-mono);font-size:.86rem;font-weight:600;margin-bottom:.5rem;
  font-variant-numeric:tabular-nums;}
.mc-px.up{color:var(--thc-up);}
.mc-px.down{color:var(--thc-down);}
.mc-px.flat{color:var(--thc-faint);}
.mc-row{display:flex;align-items:center;justify-content:space-between;gap:.6rem;
  padding:.55rem 0;border-top:1px solid var(--thc-line);}
.mc-row:first-of-type{border-top:none;}
.mc-ma{font-family:var(--thc-mono);font-size:.74rem;color:var(--thc-faint);width:3.4rem;flex-shrink:0;}
.mc-verdict{font-weight:700;font-size:.88rem;white-space:nowrap;}
.mc-verdict.good{color:var(--thc-good);}
.mc-verdict.warn{color:var(--thc-warn);}
.mc-verdict.neutral{color:var(--thc-neutral);}
.mc-stat{font-family:var(--thc-mono);font-size:.76rem;color:var(--thc-soft);
  text-align:right;font-variant-numeric:tabular-nums;}
/* 部分過期標記——卡片本身有數字（不是缺資料的 missing 狀態），只是比同批次
   其他 symbol 舊（見 reference/global_macro.py::load_stale_map）。用 --thc-warn
   跟 mc-verdict.warn 同色系但字級小、獨立一行，不跟漲跌/多空判斷搶視覺。 */
.mc-stale{margin-top:.4rem;padding-top:.4rem;border-top:1px dashed var(--thc-line);
  font-size:.72rem;color:var(--thc-warn);}
/* 總經導航——美股數字卡（VIX/殖利率/美元指數/個股）。這些不是「市場多空」，
   不套 good/warn/neutral 判斷色；漲跌用台股慣例的 --thc-up/--thc-down
   （紅漲綠跌，真價格變動才用這組色，不跟判斷色混）。 */
.gz-grid{display:grid;gap:.6rem;grid-template-columns:repeat(2,1fr);margin-top:.3rem;}
@media (min-width:640px){.gz-grid{grid-template-columns:repeat(3,1fr);}}
@media (min-width:960px){.gz-grid{grid-template-columns:repeat(4,1fr);}}
.gz-card{background:var(--thc-surface);border:1px solid var(--thc-line);
  border-radius:10px;padding:.75rem .9rem;}
.gz-head{display:flex;align-items:baseline;justify-content:space-between;margin-bottom:.3rem;}
.gz-name{font-weight:700;font-size:.85rem;color:var(--thc-ink);}
.gz-ticker{font-family:var(--thc-mono);font-size:.7rem;color:var(--thc-faint);}
.gz-value{font-family:var(--thc-mono);font-weight:600;font-size:1.3rem;color:var(--thc-ink);
  font-variant-numeric:tabular-nums;line-height:1.2;}
.gz-chg{font-family:var(--thc-mono);font-size:.76rem;margin-top:.15rem;
  font-variant-numeric:tabular-nums;}
.gz-chg.up{color:var(--thc-up);}
.gz-chg.down{color:var(--thc-down);}
.gz-chg.flat{color:var(--thc-faint);}
.gz-pct{display:block;font-family:var(--thc-mono);font-size:.7rem;color:var(--thc-faint);margin-top:.15rem;}
.gz-stale{margin-top:.4rem;padding-top:.4rem;border-top:1px dashed var(--thc-line);
  font-size:.7rem;color:var(--thc-warn);}
/* 總經導航——族群動向。刻意不用紅綠燈：排行順序本身就是訊號（上面領漲、
   下面落後），量條只用單一中性色階＋透明度表大小，不分正負色；逆風是純
   文字標籤，不是判斷色的燈號（跟 industry_headwind 那個既有旗標同語意）。 */
.ir-table{width:100%;border-collapse:collapse;font-size:.86rem;margin-top:.4rem;}
.ir-table th{text-align:left;font-weight:600;color:var(--thc-faint);font-size:.74rem;
  padding:.3rem .5rem;border-bottom:1px solid var(--thc-line);}
.ir-table th.num,.ir-table td.num{text-align:right;}
.ir-table td{padding:.5rem;border-bottom:1px solid var(--thc-line);vertical-align:middle;}
.ir-table tr:last-child td{border-bottom:none;}
.ir-name{font-weight:600;color:var(--thc-ink);}
.ir-n{color:var(--thc-faint);font-size:.76rem;}
.ir-val{font-family:var(--thc-mono);font-variant-numeric:tabular-nums;font-weight:600;
  color:var(--thc-ink);}
.ir-bar-wrap{display:inline-flex;align-items:center;gap:.4rem;justify-content:flex-end;width:100%;}
.ir-bar{height:.5rem;border-radius:2px;background:var(--thc-accent);flex-shrink:0;}
.ir-tag{display:inline-block;margin-left:.5rem;font-size:.7rem;color:var(--thc-soft);
  background:var(--thc-surface2,var(--thc-line));border:1px solid var(--thc-line);
  border-radius:4px;padding:.05rem .4rem;white-space:nowrap;}
</style>
"""


def _nav_badge_css(nav: str) -> str:
    """目前分頁文字後面疊一個小雷達徽章（同心圈＋掃描扇形＋中心點）。

    - 用 `nth-of-type` 對到選中的那個 `stRadioOption`（react-aria 把 `NAV` 幾個選項
      渲染成 radiogroup 底下對應數量的相鄰 `<label>`，順序由 `NAV` 保證），不用去猜
      BaseWeb 內部的 checked 狀態怎麼反映在 DOM 上。
    - 掃描扇形照 NAV 在「8 方位環」上的順位轉：`NAV[0]`＝正上方(0°)，
      之後每項順時針 +45°（跟著 `NAV` 排序自動轉，不寫死是哪一頁）。
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
    c1, c2 = st.columns([3, 2])
    pick = c1.pills("篩選 verdict（點掉不想看的）", cats, selection_mode="multi",
                    default=cats, key=f"_pick_{kind}") or cats
    sort_opts = list(SORT_KEYS[kind])
    sort_label = c2.segmented_control("排序依據", sort_opts, default=sort_opts[0],
                                      key=f"_sort_{kind}") or sort_opts[0]
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


_SWING_STOP_STATUS = {"pending_entry": "待進場（次日開盤）", "candidate": "候選中",
                      "dropped_from_pool": "已出候選池（停損未觸發）",
                      "stopped_out": "已跌破移動停損"}


def _swing_exit_table() -> None:
    """出場觀察表（2026-09-12 使用者要求）——**不是持倉追蹤**，不需要你輸入買在哪天/哪個價。
    系統用「第一次通過候選池六條件那天」當訊號日，**次一交易日開盤**才算進場（2026-09-14
    修正，見 `screener/swing_stops.py` docstring「進場口徑」——訊號當天收盤價買不到），
    之後逐日追蹤移動停損（進場後最高價 − 2×進場當天 ATR14，比照 tw-swing
    H2-trailatr2）。候選池把它移除後這裡**不會馬上停止**，繼續看價格走勢直到真的跌破
    停損才算出場——回答「被移除之後接下來怎麼走」。"""
    data = _load("swing_stops.json")
    if not data or not data.get("tracked"):
        return
    rows = []
    for tk, r in data["tracked"].items():
        is_pending = r.get("status") == "pending_entry"
        last = r.get("last_close")
        stop = r.get("trail_stop")
        dist = (last / stop - 1.0) if last and stop else None
        rows.append({
            "代號": tk, "狀態": _SWING_STOP_STATUS.get(r["status"], r["status"]),
            "入池日": r.get("first_seen") or r.get("signal_date"),
            "進場價": r.get("entry_price") or ("待次日開盤" if is_pending else "—"),
            "現價": last, "目前停損價": stop,
            "距停損%": f"{dist:+.1%}" if dist is not None else "—",
            "出池日": r.get("dropped_date") or "—",
            "出場日": r.get("exit_date") or "—", "出場價": r.get("exit_price") or "—",
        })
    order = {"待進場（次日開盤）": 0, "候選中": 1, "已出候選池（停損未觸發）": 2,
            "已跌破移動停損": 3}
    rows.sort(key=lambda r: (order.get(r["狀態"], 9), r["入池日"] or ""), reverse=False)
    with st.expander(f"📉 出場觀察表（移動停損，非官方持倉，{len(rows)} 檔｜點開看）"):
        st.caption(
            "**不是持倉追蹤**——系統用「第一次通過候選池六條件那天」當訊號日，**次一交易日"
            "開盤**才算進場（訊號當天收盤後才算得出達標，那個收盤價買不到，跟回測驗證過的"
            "`next_open` 口徑一致），之後逐日追蹤移動停損（進場後最高價 − 2×進場當天 "
            "ATR14，只漲不跌，比照 tw-swing `H2-trailatr2`）。從候選池被移除**不會馬上讓"
            "這裡停止**，會繼續看價格走勢直到真的跌破停損才算出場，方便回顧「被移除之後"
            "接下來怎麼走」。**只是觀察參考，不是買賣建議、不保證你當初真的買在進場價。**")
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        meta = data.get("_meta", {})
        st.caption(f"最後更新：{meta.get('asof', '—')}　·　移動停損倍數 {meta.get('trail_atr_mult', '—')}×ATR14")


def _swing_paper_section() -> None:
    """長波段模擬單（輕量版，2026-09-14 使用者要求「仿照 tw-swing 跑模擬單」）——
    見 `screener/swing_paper.py`。真實市場價格逐日累積的已實現結果，出場觀察表
    （`_swing_exit_table`）判定跌破移動停損那一刻記一筆，跟回測不是同一份資料、
    也不是同一個口徑。"""
    data = _load("swing_paper.json")
    if not data:
        return
    st_ = data.get("stats", {})
    n = st_.get("n", 0)
    with st.expander(f"📒 模擬單（自動累積，累計 {n} 筆已結算｜點開看）"):
        st.caption(
            "**不是回測，是真實市場價格逐日累積的已實現結果**——出場觀察表判定"
            "跌破移動停損的那一刻記一筆，進場口徑＝訊號日**次一交易日開盤**成交"
            "（跟出場觀察表的進場代理一致，訊號當天收盤後才算得出達標，不可能"
            "用當天收盤價成交）。用來驗證候選池上線後是不是真的照回測預期表現，"
            "**不是買賣建議**。")
        if n < 10:
            st.info(f"目前只有 {n} 筆已結算——長波段持有期可能拉很長，累積到能看"
                    "勝率需要一段時間，這是正常現象不是故障。")
        else:
            vs = st_.get("vs_backtest") or {}
            gap = vs.get("gap_pp")
            wr, exp = st_.get("win_rate"), st_.get("expectancy_net")
            diverge_txt = ("　⚠️ **差距超過 15pp，值得留意是不是規則失效**"
                           if vs.get("diverging") else "")
            st.markdown(
                f"- 累計 **{n}** 筆　·　勝率 **{wr:.0%}**　·　淨期望值（扣成本）"
                f" **{exp:+.2%}**\n"
                f"- 對照回測基準：勝率 {vs.get('backtest_win_rate', 0):.0%}"
                f"（差 {gap:+.1f}pp）{diverge_txt}")
        by_month = st_.get("by_month") or []
        if by_month:
            st.markdown("**月度分解（出場月）**")
            st.dataframe(pd.DataFrame([
                {"月": r["ym"], "筆數": r["n"], "勝率": f"{r['win_rate']:.0%}",
                 "平均淨報酬": f"{r['avg_ret_net']:+.2%}"} for r in by_month
            ]), hide_index=True, use_container_width=True)
        meta = data.get("_meta", {})
        st.caption(f"最後更新：{meta.get('updated_at', '—')}　·　"
                   f"成本假設 {meta.get('cost', 0):.3%} 往返")


def _swing_risk_explainer() -> None:
    """「可買上限」是候選池卡片上最常被問的一個數字（2026-09-22 使用者說
    「有些人會問我」）——不是估值，是風控算術，容易被誤會成「合理價」或
    「目標價」。獨立成一個頁尾 expander，講清楚公式跟它回答的問題，順便講
    清楚它跟模擬單真正的進場判斷（swing_stops.py）是兩把不同的尺，不能
    互推。"""
    with st.expander("📖 「可買上限」是什麼（點開看）"):
        st.markdown(
            "- **停損參考位** ＝ `max(50MA, 20 週前低, 現價 − 2×ATR14)`——"
            "取三者最高，是這個進場點合理的防守線。\n"
            "- **可買上限** ＝ `停損參考位 ÷ (1 − 10%)`——照這個停損位反推："
            "**如果買在可買上限，萬一真的跌到停損位，賠的正好是 10%**。\n"
            "- **現價超過可買上限，代表照這條規則的風控標準，現在買下去、"
            "萬一跌到停損位會賠超過 10%**——不是說這檔股票不好或太貴，是"
            "「這個進場點的風險已經超過設計容忍度」，跟估值、合理價、"
            "目標價都無關（這條線本來就不回答「會不會賺」，見上方警語）。\n"
            "- **這個數字不是買賣建議、系統不會因為現價超過就把它從候選池踢掉**——"
            "六個選股條件照樣可能持續成立，只是這個價位進場的風險划不來，"
            "由你自己判斷要不要等回檔。\n"
            "- **跟下面「模擬單」的進場判斷是兩把不同的尺，不能互推**：模擬單"
            "（`swing_stops.py`）決定要不要真的進場，看的是「次一交易日開盤價"
            "離停損位夠不夠留 1 倍 ATR14 的緩衝」，不是這裡的 10% 版本——"
            "同一檔股票完全可能一邊「現價超過可買上限」、一邊模擬單那把尺"
            "還是覺得緩衝夠而照樣進場，兩者算法不同、門檻不同，各自獨立看。"
        )


def _swing_page(payload: dict | None) -> None:
    st.header("長波段候選池")
    if payload is None or not payload.get("candidates_pool"):
        st.info((payload or {}).get("_meta", {}).get("pool_note", "候選池尚未產出。"))
        _swing_exit_table()
        _swing_paper_section()
        _strategy_backtest_expander("swing")
        _swing_risk_explainer()
        _disclaimer(SWING_DISCLAIMER)
        return

    meta = payload.get("_meta", {})
    st.caption(f"資料日期 {meta.get('trading_date', '—')}　·　{meta.get('pool_note', '')}"
               f"　·　重算 {meta.get('rebuilt_at', '—')}")
    _disclaimer()

    flags = _active_flags()

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
    _swing_paper_section()
    _strategy_backtest_expander("swing")
    _swing_risk_explainer()
    if flags:
        st.caption(_active_legend(flags))
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
        _strategy_backtest_expander("short")
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
        _strategy_backtest_expander("short")
        _disclaimer(SHORT_DISCLAIMER)
        return

    flags = _active_flags()
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
    _strategy_backtest_expander("short")
    if flags:
        st.caption(_active_legend(flags))
    _disclaimer(SHORT_DISCLAIMER)


@st.cache_resource(ttl=3600, show_spinner="第一次載入：從 tw-swing Release 拉 bundle…")
def _ensure_bundle():
    """回 `{檔名: 有沒有}`。下載中途斷線 / GitHub API 抽風 → 不要讓整頁吐 traceback，
    退化成「一個都沒有」，呼叫端已經有寫好的提示（2026-09-11 修）。

    `ttl=3600`：容器活著就一直用同一份 bundle，即使上游 Release 已經更新也不會
    跟進——0050／個股查詢頁都吃這支，2026-09-16 加 TTL 讓它每小時重新比對一次
    size（`ensure_assets` 本身已經是「沒變就不重抓」，TTL 只是讓「有沒有變」的
    檢查會發生，不是每小時整包重抓）。"""
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


def _render_checks(rows: list[dict], missing: str | None = None,
                   disclaimer: str | None = None) -> None:
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
    _disclaimer()
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

    qf, px, per, div, rev, chp = (d["qf"], d["px"], d["per"], d["div"], d["rev"], d["chips"])
    end = pd.to_datetime(px["date"]).max() if not px.empty else None

    def _ago(days):
        return end - pd.Timedelta(days=days) if end is not None else None

    t0, t1, t2, t3 = st.tabs(["⚡ 短線", "🟠 波段", "🔵 價值", "🟢 定存"])
    with t0:
        # 短線是日尺度 → 圖只看近 3 個月
        _render_checks(_safe_checks(cl.short_checks, d, active_etf=_aef),
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
                       missing=(None if fv is not None
                                else "這檔不在價值因子表（約 1000 檔），無法體檢價值軌。"))
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
                       missing=(None if fd is not None
                                else "這檔不在定存因子表（約 1000 檔），無法體檢定存軌。"))
        st.caption("——對應圖表（定存尺度：股利近 12 年、殖利率近 5 年）——")
        if not div.empty:
            _chart(ch.dividends_chart, div, nm)
        if not per.empty:
            _chart(ch.yield_trend, per, nm, _ago(1825))
        if not qf.empty:
            _chart(ch.balance_health, qf, nm, 24)
    st.caption("完整圖表（K 線可選區間、季 EPS、現金流、F-Score…）在「個股查詢」頁。")
    st.divider()
    with st.expander("📖 四軌各自怎麼算的（點開看）"):
        st.markdown("**⚡ 短線**：純日線技術面條件逐條攤開。融資融券變化 bundle 沒有 → 不出現。")
        st.markdown("**🟠 波段**：門檻取自主畫面「長波段候選池」（CANSLIM + Minervini）。"
                    "趨勢模板只做 7 條，不含相對強弱 RS（需全市場橫斷面）。")
        st.markdown("**🔵 價值**：F-Score + Magic Formula 精神；門檻與價值清單同一份因子。")
        st.markdown("**🟢 定存**：殖利率硬底線 5% + 填息率 / 含息報酬 / 配息穩定；門檻與定存清單一致。")
    if _aflags:
        st.caption(_active_legend(_aflags))
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
             names: dict | None = None, qty: dict | None = None,
             exit_notes: dict | None = None, note: str | None = None,
             holdings_html: str = "", meta_line: str = "") -> str:
    """主動式 ETF 單檔卡片——沿用版型 B 的 thc-card / sw-cols 語言（同長波段那張）。

    `qty`：{ticker: 這檔基金當天實際動了幾張}，來自 `by_fund`（見
    build_active_etf_flags.py）——**不是**跨基金淨額，是這一檔基金自己的股數差。
    `exit_notes`：{ticker: "出清"/"僅剩1張"}——賣出後這檔基金手上只剩 0 或 1 張，
    跟「大部位小減碼」意義差很多，特別標出來（2026-09-14）。"""
    names = names or {}
    qty = qty or {}
    exit_notes = exit_notes or {}

    def _li(tks: list | None) -> str:
        if not tks:
            return '<li class="flat">—</li>'
        parts = []
        for t in tks:
            q = qty.get(t)
            lots = f"　<b>{q / 1000:+,.0f} 張</b>" if isinstance(q, (int, float)) else ""
            en = exit_notes.get(t)
            exit_tag = (f'　<span class="thc-flag">⚠ {_esc(en)}</span>' if en else "")
            parts.append(f'<li><a href="?code={_esc(t)}" target="_self">{_esc(t)}</a>'
                         f'　{_esc(names.get(t, ""))}{lots}{exit_tag}</li>')
        return "".join(parts)

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
    if holdings_html:
        parts.append(holdings_html)
    if meta_line:
        parts.append(f'<div class="thc-barcap" style="margin-top:.5rem">{_esc(meta_line)}</div>')
    return (f'<div class="thc-card thc-{sev}"><div class="thc-stripe"></div>'
            f'<div class="thc-body">{"".join(parts)}</div></div>')


def _holdings_df(code: str, date: str) -> pd.DataFrame:
    """該檔基金當天 PCF 完整持股，依權重由大到小排序——直接讀快照的 `weight` 欄
    （PCF 本來就有全部持股，不是只算前幾大），跟差分（買賣）無關，純粹「這檔基金
    資金放在哪」。表格用，不是字串。"""
    p = REPO / "data" / "pcf" / code / f"{date}.parquet"
    if not p.exists():
        return pd.DataFrame()
    try:
        df = pd.read_parquet(p, columns=["stock_code", "stock_name", "weight"])
    except Exception:  # noqa: BLE001
        return pd.DataFrame()
    if df.empty or "weight" not in df.columns:
        return pd.DataFrame()
    return df.sort_values("weight", ascending=False).reset_index(drop=True)


def _holdings_table_html(df: pd.DataFrame) -> str:
    """完整持股（已依權重排序）→ 卡片內可展開的捲動表格，跟其他卡片「明細」用同一套
    `.thc-details` 語言（沿用 `_detail_html` 的視覺，這裡欄數/內容不同另建一份）。"""
    if df.empty:
        return ""
    rows = "".join(
        f'<tr><td>{_esc(r.stock_code)}</td><td>{_esc(r.stock_name)}</td>'
        f'<td class="num">{r.weight:.2f}%</td></tr>'
        for r in df.itertuples(index=False))
    return (
        f'<details class="thc-details"><summary>持股明細（{len(df)} 檔，依權重排序）</summary>'
        '<div class="ae-hold-wrap"><table class="ae-hold-table">'
        '<thead><tr><th>代號</th><th>名稱</th><th class="num">權重%</th></tr></thead>'
        f'<tbody>{rows}</tbody></table></div></details>')


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
        en = set((f.get("exit_notes") or {}).values())
        if "出清" in en:
            mix += '　<span class="thc-flag">⚠ 有基金出清</span>'
        elif "僅剩1張" in en:
            mix += '　<span class="thc-flag">⚠ 有基金僅剩1張</span>'
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
        qty = {tk: (fl[tk].get("by_fund") or {}).get(code) for tk in (*buys, *sells)}
        exit_n = {tk: (fl[tk].get("exit_notes") or {}).get(code) for tk in sells}
        return buys, sells, nm, qty, exit_n

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
        buys, sells, nm, qty, exit_n = _moved_by(code)
        aum_line = _fmt_aum_navps(fmd)
        meta_line = (f"抓取 {fetched}　·　持股 {fi.get('holdings_n', '—')} 檔"
                     f"　·　磁碟留存 {snaps_n} 份快照")
        cards.append(_ae_card(
            code, issuer, name, "good", "🟢 差分已算",
            f"{fmd.get('prev_date', '?')} → {date}　·　加碼 {len(buys)} 檔"
            f"　·　調節 {len(sells)} 檔"
            f"（濾掉零星微調後共動 {fmd.get('moved_n', 0)} 檔）"
            + (f"　·　{aum_line}" if aum_line else ""),
            buys=buys, sells=sells, names=nm, qty=qty, exit_notes=exit_n,
            holdings_html=_holdings_table_html(_holdings_df(code, date)),
            meta_line=meta_line))

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


_MC_VERDICT = {"bull": ("多頭", "good"), "bear": ("空頭", "warn"), "chop": ("盤整", "neutral")}
_MC_LABEL = {"ma60": "MA60", "ma200": "MA200"}
#: (代號, 市場標籤) ——0050 對應上市（大盤代理，同 reference.regime 用的那檔）、
#: 006201 元大富櫃50 是唯一追蹤櫃買（TPEx）指數的 ETF，對應上櫃。
_MC_MARKETS = [("0050", "上市"), ("006201", "上櫃")]


def _mc_row(label: str, v: dict | None) -> str:
    if v is None:
        return (f'<div class="mc-row"><span class="mc-ma">{label}</span>'
                f'<span class="mc-verdict neutral">暖機中</span>'
                f'<span class="mc-stat">資料不足</span></div>')
    text, sev = _MC_VERDICT[v["state"]]
    return (f'<div class="mc-row"><span class="mc-ma">{label}</span>'
            f'<span class="mc-verdict {sev}">{text}</span>'
            f'<span class="mc-stat">乖離 {v["gap_pct"]:+.1%}</span></div>')


def _mc_price_line(chg: dict | None) -> str:
    """卡頭的現價＋漲跌——跟 MA 判斷是分開的兩件事（純價格變動，不是判斷），
    沿用漲跌色 --thc-up/--thc-down，不用 good/warn 那組判斷色。"""
    if chg is None:
        return ''
    sign = "up" if chg["chg"] > 0 else ("down" if chg["chg"] < 0 else "flat")
    arrow = "▲" if sign == "up" else ("▼" if sign == "down" else "—")
    return (f'<div class="mc-px {sign}">{chg["value"]:,.2f}　{arrow} '
            f'{chg["chg"]:+,.2f}（{chg["chg_pct"]:+.2%}）</div>')


def _mc_card(ticker: str, market: str, card: dict, chg: dict | None = None,
             windows: tuple[str, ...] = ("ma60", "ma200"), stale: dict | None = None) -> str:
    # 卡片左側細條：顯示的窗口全一致就用那個顏色，分歧就用中性色（不硬湊一個結論）
    states = {card[w]["state"] for w in windows if card.get(w)}
    sev = _MC_VERDICT[next(iter(states))][1] if len(states) == 1 else "neutral"
    ma_rows = "".join(_mc_row(_MC_LABEL[w], card.get(w)) for w in windows)
    stale_line = (f'<div class="mc-stale">⚠️ 資料落後 {stale["lag_days"]} 天'
                  f'（最新只到 {stale["latest"]}）</div>' if stale else "")
    return (
        f'<div class="mc-card {sev}"><div class="stripe"></div><div class="mc-body">'
        f'<div class="mc-head"><span class="mc-market">{market}</span>'
        f'<span class="mc-ticker">{ticker}</span></div>'
        + _mc_price_line(chg) + ma_rows + stale_line
        + '</div></div>'
    )


#: 國際指數——收盤序列夠格套跟 0050/006201 一樣的 MA60/MA200 多空卡（畫面上只列
#: MA200，機構慣例）。日經/恆生/KOSPI 是亞股情緒領先指標，隔夜表現常直接影響
#: 台股開盤，2026-09-13 從「只有美股」擴大進來。
_INTL_INDICES = [("^DJI", "道瓊"), ("^IXIC", "那斯達克"), ("^SOX", "費城半導體"),
                  ("^N225", "日經225"), ("^HSI", "恆生指數"), ("^KS11", "韓國KOSPI")]
#: 七巨頭 + 美光——個股，維持「不幫個股打分」的立場，只顯示數字，不套多空判斷。
_US_STOCKS = [("AAPL", "Apple"), ("MSFT", "Microsoft"), ("GOOGL", "Alphabet"),
              ("AMZN", "Amazon"), ("META", "Meta"), ("NVDA", "NVIDIA"),
              ("TSLA", "Tesla"), ("MU", "美光")]
#: VIX/殖利率/美元指數——不是「市場」，數字卡 + 近一年分位，不套多空判斷。
#: 黃金/白銀/BTC 刻意不收——24/7 交易沒有「收盤」這個市場共識事件，跟這頁
#: 「只抓已完成收盤」的精神衝突（2026-09-13 使用者否決）。
#: (symbol, 名稱, 單位後綴)
_US_GAUGES = [("^VIX", "VIX", ""), ("DX-Y.NYB", "美元指數", ""),
              ("^IRX", "美債短天期(13週)", "%"), ("^TNX", "美債10年", "%"),
              ("^TYX", "美債長天期(30年)", "%")]


def _gz_card(symbol: str, name: str, close: pd.Series, *, suffix: str = "",
             show_pct: bool = True, stale: dict | None = None) -> str:
    from reference.global_macro import latest_change, percentile_rank
    ch = latest_change(close)
    if ch is None:
        # 剛上線的新序列只有 1 筆時，latest_change 算不出漲跌（回 None）——與其整張
        # 卡空白，先把那唯一一筆的值印出來，比等到第 2 天才有東西看更有用（2026-09-15
        # 台指期上線當天發現的：使用者看到「資料不足」還以為抓失敗）。
        s = close.dropna()
        if len(s) == 1:
            body = (f'<div class="gz-value">{s.iloc[-1]:,.2f}{suffix}</div>'
                    '<div class="gz-chg flat">尚無前一筆可比</div>')
        else:
            body = '<div class="gz-value">—</div><div class="gz-chg flat">資料不足</div>'
    else:
        sign = "up" if ch["chg"] > 0 else ("down" if ch["chg"] < 0 else "flat")
        arrow = "▲" if sign == "up" else ("▼" if sign == "down" else "—")
        pct_line = ""
        if show_pct:
            p = percentile_rank(close)
            if p is not None:
                pct_line = f'<span class="gz-pct">近一年 P{p * 100:.0f}</span>'
        body = (f'<div class="gz-value">{ch["value"]:,.2f}{suffix}</div>'
                f'<div class="gz-chg {sign}">{arrow} {ch["chg"]:+,.2f}{suffix}'
                f'　({ch["chg_pct"]:+.2%})</div>' + pct_line)
    stale_line = (f'<div class="gz-stale">⚠️ 資料落後 {stale["lag_days"]} 天'
                  f'（最新只到 {stale["latest"]}）</div>' if stale else "")
    return (f'<div class="gz-card"><div class="gz-head"><span class="gz-name">{name}</span>'
            f'<span class="gz-ticker">{symbol}</span></div>{body}{stale_line}</div>')


def _industry_rotation_summary(rows: list[dict]) -> str:
    """族群動向頁首一句話——固定句型代入數字，跟頁首「市場情緒摘要」同精神：
    只講事實（誰領漲/誰落後/幾個逆風），不做推論、不下多空判斷。"""
    ranked = [r for r in rows if r.get("ret_1m") is not None]
    if not ranked:
        return ""
    top, bottom = ranked[0], ranked[-1]
    n_hw = sum(1 for r in rows if r.get("headwind"))
    parts = [f"近1月領漲：{top['industry']}（{top['ret_1m']:+.1%}）"]
    if bottom["industry"] != top["industry"]:
        parts.append(f"落後最多：{bottom['industry']}（{bottom['ret_1m']:+.1%}）")
    parts.append(f"{n_hw} 個產業符合近6月逆風判定" if n_hw else "目前沒有產業符合近6月逆風判定")
    return "　·　".join(parts)


def _industry_rank_by_money(rows: list[dict]) -> list[dict]:
    """族群動向依資金(`net_1m`)由高到低重排——`.get()` 不是 `[]`，因為部署後第一次
    這頁被打開時 `industry_rotation.json` 可能還是舊 schema（沒有 net_1m/net_1w
    兩個欄位，要等 rebuild.yml 跑過一次新版 build_lists.py 才會補上），直接用
    `r["net_1m"]` 會 KeyError 把整頁炸掉（2026-09-15 上線當天在 Streamlit Cloud
    真的炸過一次）。缺欄位視同 None，排到最後面。"""
    return sorted(rows, key=lambda r: (r.get("net_1m") is None, -(r.get("net_1m") or 0)))


def _industry_rotation_table(rows: list[dict], mode: str = "漲跌幅") -> str:
    """族群動向表——排行本身就是訊號，不用紅綠燈（見上面 .ir-table CSS 註解）。
    量條只用單一色階＋透明度表 |1月| 的相對大小，逆風是純文字標籤。

    只畫 `mode` 對應的那組欄位（近1週/近1月 + 單位），不是兩組都塞進同一張表——
    2026-09-15 補資金排行時本來兩組（漲跌幅+資金）並排常駐，手機寬度放不下
    5 欄會橫向溢出；改成「排序依據選哪個、表就只畫哪個」，欄數跟補資金排行
    以前一樣還是 3 欄（產業＋近1週＋近1月），跟排序切換本來就綁在一起，不算
    少功能——想看另一組數字，切換排序依據就會換過來。"""
    if not rows:
        return ""
    field, fmt, suffix = (("net", "+.1f", "億") if mode == "資金" else ("ret", "+.1%", ""))
    w_key, m_key = f"{field}_1w", f"{field}_1m"
    max_abs = max((abs(r[m_key]) for r in rows if r.get(m_key) is not None),
                  default=0) or 1.0

    def _row(r: dict) -> str:
        w1 = r.get(w_key)
        w1_txt = f'{w1:{fmt}}{suffix}' if w1 is not None else "—"
        m1 = r.get(m_key)
        m1_txt = f'{m1:{fmt}}{suffix}' if m1 is not None else "—"
        tag = '<span class="ir-tag">近6月逆風</span>' if r.get("headwind") else ""
        if m1 is None:
            bar_cell = '<td class="num"><span class="ir-val">—</span></td>'
        else:
            pct = min(100, abs(m1) / max_abs * 100)
            opacity = 0.35 + 0.5 * (abs(m1) / max_abs)
            bar = f'<span class="ir-bar" style="width:{pct * 0.5:.0f}px;opacity:{opacity:.2f}"></span>'
            bar_cell = (f'<td class="num"><div class="ir-bar-wrap">{bar}'
                       f'<span class="ir-val">{m1_txt}</span></div></td>')
        return (
            '<tr>'
            f'<td><span class="ir-name">{_esc(r["industry"])}</span>'
            f'　<span class="ir-n">{r["n"]} 檔</span>{tag}</td>'
            f'<td class="num"><span class="ir-val">{w1_txt}</span></td>'
            + bar_cell + '</tr>')

    return (
        '<table class="ir-table"><thead><tr>'
        f'<th>產業</th><th class="num">近1週{mode}</th><th class="num">近1月{mode}</th>'
        '</tr></thead><tbody>' + "".join(_row(r) for r in rows) + '</tbody></table>')


_GH_REPO = "tongxiaooppo-boop/tw-hold"
#: 這頁的資料源分兩條獨立排程——手動重整按鈕兩條都觸發，使用者不用自己判斷
#: 卡片過期是哪一條的責任（見 [[tw-hold-macro-staleness-badge]]）。
_REFRESH_WORKFLOWS = [("rebuild.yml", "三清單/台股/族群動向"), ("global_macro.yml", "國際總經")]


def _latest_run(workflow_file: str, token: str) -> dict | None:
    """查這條 workflow 最新一次 run 的狀態——按鈕觸發前用來擋「上一輪還在跑」，
    觸發後把連結給使用者，不用再靠猜（2026-09-22 Opus 審出的兩個缺口一次補）。
    查不到就回 None（沿用同一套「拿不到就不擋」的容錯原則，不因為這個附加功能
    讓按鈕本身變得更脆弱）。
    """
    import json as _json
    import urllib.error
    import urllib.request

    url = (f"https://api.github.com/repos/{_GH_REPO}/actions/workflows/"
           f"{workflow_file}/runs?per_page=1")
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {token}",
                      "Accept": "application/vnd.github+json",
                      "X-GitHub-Api-Version": "2022-11-28"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = _json.loads(r.read().decode("utf-8"))
        runs = data.get("workflow_runs") or []
        return runs[0] if runs else None
    except Exception:
        return None


def _trigger_workflow(workflow_file: str, token: str) -> tuple[bool, str]:
    """打 GitHub REST API 的 workflow_dispatch，觸發雲端重跑（不在這裡本地抓資料——
    app 一律不即時抓資料的原則沒變，這裡只是「叫 CI 現在跑」，資料還是 CI 產生、
    commit 回 repo，app 純讀檔的路徑完全沒變）。

    刻意用 `urllib.request`（標準庫）不加 `requests`——跟 fetch_bundle.py／
    pcf_fetchers.py 同慣例，requirements.txt 檔頭寫明「刻意控依賴」。
    回傳 (成功與否, 錯誤訊息)。
    """
    import json as _json
    import urllib.error
    import urllib.request

    url = f"https://api.github.com/repos/{_GH_REPO}/actions/workflows/{workflow_file}/dispatches"
    req = urllib.request.Request(
        url, method="POST",
        data=_json.dumps({"ref": "main"}).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status == 204, ""
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}：{e.read().decode('utf-8', errors='replace')[:200]}"
    except Exception as e:
        return False, str(e)


@st.cache_resource
def _refresh_gate() -> dict:
    """按鈕冷卻的存放處——刻意用 `cache_resource`（同一個 Streamlit 行程內
    所有 session 共用）不是 `session_state`（per-browser-session）。

    這個 app 是公開連結、按鈕沒有身分驗證，`session_state` 版冷卻換一個無痕
    視窗/清 cookie 就繞過去了，等於形同虛設（2026-09-22 Opus 審出）。行程級
    冷卻讓「不管是誰按的」都受同一個節流限制，只有 app 重啟才會重置。
    """
    return {"until": 0.0}


def _macro_refresh_button() -> None:
    """頁尾手動重整——使用者發現卡片過期時按下去，觸發 rebuild.yml +
    global_macro.yml 雲端重跑，不用等排程時間到或自己去 GitHub Actions 點按鈕
    （2026-09-22 使用者要求）。

    需要 `st.secrets["GH_DISPATCH_PAT"]`：一顆只給 `actions: write` 權限的
    fine-grained PAT（範圍鎖 tw-hold 這個 repo 就好，不要給 contents write，
    這裡只需要觸發 workflow，不寫檔）。沒設就不顯示按鈕（本地開發環境本來就
    沒有，不用因為缺這個擋掉整頁）。
    """
    try:
        token = st.secrets.get("GH_DISPATCH_PAT")
    except Exception:
        token = None
    if not token:
        return

    st.subheader("手動重整")
    st.caption("發現上面卡片有 ⚠️ 過期標記時可以按這個——觸發雲端重跑，通常幾分鐘後"
               "資料就會更新，但這頁本身**不會自動跳新**，要手動重新整理瀏覽器再看一次。")

    gate = _refresh_gate()
    now = time.time()
    if now < gate["until"]:
        st.button(f"🔄 立即重新整理資料（{int(gate['until'] - now)}s 後可再按）",
                  disabled=True, key="macro_refresh_btn")
        return

    if st.button("🔄 立即重新整理資料", key="macro_refresh_btn"):
        gate["until"] = time.time() + 900   # 15 分鐘，行程級、任何人按都算數
        # 觸發前先問 GitHub 這兩條最近一輪跑完了沒——這層判斷在 GitHub 端，
        # 任何 client（不管是不是這個按鈕）都繞不過，比單純的本地冷卻更權威，
        # 也順便擋掉「連點兩次放大 push race 機率」（2026-09-22 Opus 審出）。
        busy = []
        for wf, label in _REFRESH_WORKFLOWS:
            run = _latest_run(wf, token)
            if run and run.get("status") in ("in_progress", "queued"):
                busy.append(label)
        if busy:
            st.info(f"「{'／'.join(busy)}」上一輪還在跑，這次先不重複觸發，"
                    "等它跑完（通常幾分鐘）再按。")
            return

        results = [(label, *_trigger_workflow(wf, token)) for wf, label in _REFRESH_WORKFLOWS]
        failed = [(label, err) for label, ok, err in results if not ok]
        actions_url = f"https://github.com/{_GH_REPO}/actions"
        if not failed:
            st.success(f"已觸發雲端重跑（三清單 + 國際總經），幾分鐘後重新整理頁面看看。"
                       f"想看執行進度可以開 [GitHub Actions]({actions_url})。")
        else:
            ok_labels = [label for label, ok, _err in results if ok]
            if ok_labels:
                st.warning(f"「{'／'.join(ok_labels)}」觸發成功；"
                           + "、".join(f"「{label}」失敗（{err}）" for label, err in failed)
                           + f" [GitHub Actions]({actions_url})")
            else:
                st.error("觸發失敗：" + "、".join(f"「{label}」{err}" for label, err in failed))


def _macro_compass_page() -> None:
    """總經導航——台股上市/上櫃的 MA60/MA200 多空卡 + 國際指數/個股/總經數字卡
    （2026-09-13 起）。頁首放「市場情緒摘要」（固定句型代入數字，見
    `reference/market_sentiment.py`——不是 AI，也不做任何跨指標的推論；台股/
    國際情勢兩段分開顯示，不接成一段話），方法論/資料源說明集中放頁尾一個
    expander，不散在各段落中間。

    ⚠️ 判斷邏輯是 `reference/market_status.py` 的獨立乖離帶規則，跟 `reference/regime.py`
    （回測分層用的市況旗標）完全脫鉤——這裡純顯示，不影響任何清單或 verdict。
    國際指數套同一套多空卡；VIX/殖利率/美元指數/個股不是「市場」，改用數字卡
    （現值 + 漲跌 + 個股/指數以外的再加近一年分位），不套多空判斷。

    AI 解說層（`docs/AI_LAYER.md`）2026-09-13 討論後暫緩到 10 月以後，這裡的摘要
    純粹是規則模板，不要看到「市場情緒」四個字就以為背後有 AI。
    """
    from reference import global_macro, index_proxy, market_sentiment, put_call_ratio, tx_futures
    from reference.market_status import latest_change, market_card

    st.header("總經導航", anchor="top")
    _disclaimer()

    def _bundle_close(ticker: str) -> pd.Series:
        """備援路徑——只有本地小檔缺資料時才會走到這裡，才真的去拉整包 bundle。
        2026-09-16 拿掉整頁前面那道 `_ensure_bundle()` 硬性關卡：這頁除了 0050，
        其餘（006201／國際指數／總經數字卡）全部純讀本地檔，不該讓 0050 一張卡
        （原本要拖 ~25MB 的 prices_adj.parquet）決定整頁能不能顯示。"""
        import bundle_data as bd
        got = _ensure_bundle()
        if not any(got.values()):
            return pd.Series(dtype="float64")
        px = bd.prices(ticker, lookback_days=900)
        if px.empty:
            return pd.Series(dtype="float64")
        return px.set_index("date")["close"].sort_index()

    fell_back: list[str] = []

    def _load_0050(_t: str) -> pd.Series:
        close = index_proxy.load_0050()
        if not close.empty:
            return close
        # 小檔缺／是空的 → 走備援。要留痕跡：CI 端若連續好幾天驗證沒過、
        # 小檔一直沒更新，使用者只會覺得「這頁最近怎麼變慢了」，不會聯想到
        # 0050 的資料被擋下來了（2026-09-16 審核）。
        fell_back.append("0050")
        return _bundle_close("0050")

    # ---- 先把所有資料算齊，摘要跟各段卡片共用同一份，不重算兩次 ----
    # 0050／006201 都改讀 tw-swing bundle 本來就有附的小檔，經
    # `scripts/promote_index_0050.py`／`scripts/fetch_index_proxy.py` 驗證後落地成
    # committed 小檔（各自檔頭有驗證邏輯：資料倒退／疑似損毀就保留舊檔不覆寫，
    # 「前一日資料錯誤不可原諒」）。本地小檔缺才退回 `_bundle_close` 吃整包 bundle
    # 當備援，不會讓 0050 這張卡直接消失。
    _TW_LOADERS = {"0050": _load_0050, "006201": lambda _t: index_proxy.load_006201()}
    tw_data, tw_missing = {}, []
    for ticker, market in _MC_MARKETS:
        close = _TW_LOADERS[ticker](ticker)
        if close.empty:
            tw_missing.append(f"{market}（{ticker}）")
            continue
        tw_data[ticker] = {"market": market, "card": market_card(close), "chg": latest_change(close)}

    stale_map = global_macro.load_stale_map()
    snap_meta = global_macro.load_snapshot_meta()

    intl_idx_data, intl_idx_missing = {}, []
    for symbol, name in _INTL_INDICES:
        close = global_macro.load_close(symbol)
        if close.empty:
            intl_idx_missing.append(f"{name}（{symbol}）")
            continue
        intl_idx_data[symbol] = {"name": name, "card": market_card(close), "chg": latest_change(close)}

    gauge_close = {sym: global_macro.load_close(sym) for sym, _n, _s in _US_GAUGES}

    # ---- 頁首：市場情緒摘要（固定句型代入，不是 AI）。台股/國際情勢分開兩段，
    # 不接成一段話——兩個話題不同，接在一起會模糊掉「這句在講哪裡」（2026-09-13）。
    tw_sents = [market_sentiment.tw_market_sentence(d["market"], d["card"]) for d in tw_data.values()]
    intl_sents = [market_sentiment.index_sentence(d["name"], d["card"]) for d in intl_idx_data.values()]
    vix_pct = global_macro.percentile_rank(gauge_close.get("^VIX", pd.Series(dtype="float64")))
    vix_txt = market_sentiment.vix_sentence(vix_pct)
    short_v = latest_change(gauge_close.get("^IRX", pd.Series(dtype="float64")))
    ten_v = latest_change(gauge_close.get("^TNX", pd.Series(dtype="float64")))
    curve_txt = market_sentiment.yield_curve_sentence(
        short_v["value"] if short_v else None, ten_v["value"] if ten_v else None)
    st.markdown(f"**台股：**{market_sentiment.tw_summary(tw_sents)}")
    st.markdown(f"**國際情勢：**{market_sentiment.intl_summary(intl_sents, vix_txt, curve_txt)}")

    st.divider()
    st.subheader("台股")
    if tw_data:
        cards = [_mc_card(t, d["market"], d["card"], d["chg"]) for t, d in tw_data.items()]
        st.markdown(f'<div class="mc-grid">{"".join(cards)}</div>', unsafe_allow_html=True)
    if fell_back:
        st.caption(f"·「{'／'.join(fell_back)}」這次改走備援資料來源，日期可能落後一兩天。")
    if tw_missing:
        # 原本整頁關卡失敗時會有 st.error 附具體錯誤（PAT 找不到／GitHub API 錯誤碼），
        # 拿掉關卡後診斷細節會消失——把 `_ensure_bundle` 存下的原因接回來（同 :1381）。
        st.info(f"這次沒拿到：{'／'.join(tw_missing)}（資料源缺這檔，或 `fetch_index_proxy.py` 還沒跑過）。"
                + (f"（{st.session_state['_bundle_err']}）"
                   if st.session_state.get("_bundle_err") else ""))

    st.divider()
    st.subheader("台指期／選擇權")
    tx_day, tx_night = tx_futures.load_session("day"), tx_futures.load_session("night")
    pcr_vol = put_call_ratio.load_series("put_call_volume_ratio")
    pcr_oi = put_call_ratio.load_series("put_call_oi_ratio")
    tx_cards = []
    if not tx_day.empty or not tx_night.empty:
        tx_cards += [_gz_card("TX", "日盤收盤", tx_day, show_pct=False),
                     _gz_card("TX", "夜盤收盤", tx_night, show_pct=False)]
    if not pcr_vol.empty or not pcr_oi.empty:
        tx_cards += [_gz_card("TXO", "量比", pcr_vol, suffix="%", show_pct=False),
                     _gz_card("TXO", "未平倉比", pcr_oi, suffix="%", show_pct=False)]
    if tx_cards:
        st.markdown(f'<div class="gz-grid">{"".join(tx_cards)}</div>', unsafe_allow_html=True)
        st.caption("台指期近月合約 + 台指選擇權 Put/Call Ratio，資料源 TAIFEX OpenAPI"
                   "（`DailyMarketReportFut`／`PutCallRatio`）。夜盤沒有獨立結算價，顯示的是"
                   "夜盤最後成交價，跨夜到隔天 05:00。Put/Call 比＝Put 量(或未平倉)÷Call 量"
                   "(或未平倉)×100，>100 偏防守、<100 偏樂觀，沒有官方多空分界線，看趨勢比"
                   "看單點有意義。")
    else:
        st.info("還沒有台指期/Put-Call Ratio 資料——`fetch_tx_futures.py`／"
                "`fetch_put_call_ratio.py` 應該還沒跑過或還沒重新部署。")

    st.divider()
    st.subheader("族群動向")
    ir = _load("industry_rotation.json") or {}
    ir_rows = ir.get("industries") or []
    if ir_rows:
        st.markdown(f"**{_industry_rotation_summary(ir_rows)}**")
        sort_mode = st.segmented_control("排序依據", ["資金", "漲跌幅"], default="資金",
                                         key="ir_sort_mode") or "資金"
        if sort_mode == "資金":
            ranked = _industry_rank_by_money(ir_rows)
            st.caption(f"資料日 {ir.get('asof', '—')}　·　依近1月三大法人合計買賣超金額排序"
                       "（上面買最多、下面賣最多），金額用「合計買賣超股數 × 收盤價」估算，"
                       "不是精確結算金額。跟漲跌幅排行是互補視角——資金流入不一定馬上反映在"
                       "報酬上，兩者常常不同步。")
        else:
            ranked = ir_rows
            st.caption(f"資料日 {ir.get('asof', '—')}　·　依近1月中位報酬排序（上面領漲、下面落後），"
                       "不做多空判斷。「近6月逆風」沿用既有的產業逆風判定（門檻是6個月報酬，"
                       "跟表上顯示的1週/1月是不同窗口，可能短線翻正但長線仍標記逆風，不是矛盾）。")
        top, rest = ranked[:10], ranked[10:]
        st.markdown(_industry_rotation_table(top, mode=sort_mode), unsafe_allow_html=True)
        if rest:
            with st.expander(f"看其他 {len(rest)} 個產業"):
                st.markdown(_industry_rotation_table(rest, mode=sort_mode), unsafe_allow_html=True)
        st.caption("樣本數 < 3 檔的產業不列（中位數/加總沒意義）。報酬用還原股價的中位數，"
                   "不是市值加權指數；資金缺口少數產業可能沒有 chips 資料。")
    else:
        st.info("還沒有族群動向產出——`build_factors.py` 應該還沒跑過或還沒重新部署。")

    st.divider()
    _snap_lag = snap_meta.get("snapshot_lag_days")
    if _snap_lag is not None and _snap_lag > 2:
        # 個別卡片的 ⚠️ 只抓得到「這批裡面某幾檔比其他檔舊」，抓不到「整批一起
        # 卡住不動」（連續好幾天沒跑成功，彼此之間沒有落差）——這裡另外用整批
        # 的 reference_date 跟今天比，才是使用者真正在意的「這批資料是不是新的」
        # （2026-09-22 Opus 審出的缺口，見 load_snapshot_meta 檔頭）。
        st.warning(f"⚠️ 國際指數／波動度／美股個股整批快照落後 {_snap_lag} 個營業日"
                   f"（最新只到 {snap_meta.get('reference_date', '—')}）——"
                   "`global_macro.yml` 這條排程可能連續沒跑成功，總經導航頁尾按"
                   "「立即重新整理資料」試試看。")
    st.subheader("國際指數")
    if intl_idx_data:
        cards = [_mc_card(s, d["name"], d["card"], d["chg"], windows=("ma200",), stale=stale_map.get(s))
                 for s, d in intl_idx_data.items()]
        st.markdown(f'<div class="mc-grid">{"".join(cards)}</div>', unsafe_allow_html=True)

    st.divider()
    st.subheader("波動度／殖利率／匯率")
    gauge_cards = [_gz_card(sym, name, gauge_close[sym], suffix=suf, stale=stale_map.get(sym))
                   for sym, name, suf in _US_GAUGES]
    st.markdown(f'<div class="gz-grid">{"".join(gauge_cards)}</div>', unsafe_allow_html=True)

    st.divider()
    st.subheader("美股個股（七巨頭＋美光）")
    stock_cards = [_gz_card(sym, name, global_macro.load_close(sym), show_pct=False, stale=stale_map.get(sym))
                   for sym, name in _US_STOCKS]
    st.markdown(f'<div class="gz-grid">{"".join(stock_cards)}</div>', unsafe_allow_html=True)

    if intl_idx_missing or not intl_idx_data:
        st.info(f"國際指數：{'全部沒拿到' if not intl_idx_data else ('部分沒拿到：' + '／'.join(intl_idx_missing))}"
                "（`fetch_global_macro.py` 是獨立排程，還沒跑過或跑失敗時會這樣）。")

    st.divider()
    with st.expander("📖 這頁怎麼算的（點開看）"):
        st.markdown(
            "- **純顯示，不影響任何清單判斷**——跟其他分頁的 verdict／候選池完全脫鉤。\n"
            "- **上市＝0050**（臺灣50指數，讀 bundle）；**上櫃＝006201**（元大富櫃50，"
            "唯一追蹤櫃買富櫃50指數的 ETF，不在 bundle 的 universe 裡，改直接向 FinMind 拉）。\n"
            "- **多空判斷**＝乖離帶：|收盤/均線-1| 在 ±2% 內算「盤整」，超過算當下窗口的多／空——"
            "示意用簡單門檻，**沒有回測調過**，不是進出場依據。\n"
            "- **台股列 MA60+MA200 兩條**（法人習慣同時盯季線/年線）；**國際指數只列 MA200**"
            "（國際機構慣例看年線）。日經/恆生/KOSPI 是亞股情緒領先指標，隔夜表現常直接"
            "影響台股開盤，跟道瓊/那斯達克/費半併在同一段。\n"
            "- **VIX／美元指數／美債殖利率**不是「市場」，沒有多空判斷，只有現值＋漲跌"
            "（＋近一年分位；分位是分佈位置，不是「貴不貴」的判斷）。黃金/白銀/BTC 刻意"
            "不收——24/7 交易沒有「收盤」這個市場共識事件，跟這頁的精神衝突。\n"
            "- **七巨頭＋美光**維持「不幫個股打分」的立場，只顯示數字。\n"
            "- **資料源**：yfinance，每日一次抓「已完成的常規盤收盤」，**絕不即時**——"
            "24 小時盤外交易讓收盤價更快過期，不是讓它失效。排程跟台股那條 `rebuild.yml` "
            "無關（獨立的 `.github/workflows/global_macro.yml`，美股收盤後才跑）。\n"
            "- **⚠️ 資料落後 N 天**：這批 symbol 有抓到資料（不是缺資料的「沒拿到」），"
            "只是比同一批次其他 symbol 舊——通常是 Yahoo 那批對特定 symbol 還沒補齊，"
            "不是這裡的程式壞了。台股清單跟總經快照是兩條獨立排程，其中一條更新了"
            "不代表另一條也是新的，這個標記就是在補這個落差。\n"
            "- **頁首摘要是規則模板，不是 AI**——固定句型代入數字，只講事實、不做評論，"
            "**不做跨指標推論**（例如不會因為「偏多」加「VIX偏低」就合成「風險偏好回升」"
            "這種需要判斷的話），台股／國際情勢兩段各自獨立、不接成一段話"
            "（真正的 AI 敘事層還在規劃階段，10 月以後才會再議）。"
        )

    with st.expander("📚 大盤多空／盤整怎麼定義的（機構標準參考，點開看）"):
        st.caption("設計這頁時查閱的機構通用方法論，列出來當背景參考——**跟上面「這頁怎麼算的」"
                   "用的乖離帶不是同一套**（乖離帶更陽春，這裡是完整的機構方法論，含 ADX 趨勢強度）。"
                   "這頁實際判斷仍然用乖離帶，這裡不是這頁在跑的規則。")
        st.markdown("**三種市場狀態（機構定義）**")
        st.markdown(
            "| 狀態 | 判定 |\n|---|---|\n"
            "| 多頭 Bull | 指數 > MA60　且　MA60 斜率 > 0 |\n"
            "| 空頭 Bear | 指數 < MA60　且　MA60 斜率 < 0 |\n"
            "| 盤整 Sideways | ADX < 20（不論指數相對均線位置） |"
        )
        st.markdown("**MA60 vs MA200：機構用哪條線**")
        st.markdown(
            "| 均線 | 常用場域 | 特性 |\n|---|---|---|\n"
            "| MA200（年線） | 國際機構／美股標準（S&P 500、道瓊） | "
            "全球最通用的長期多空分界，過濾季節性雜訊，反映真正長期趨勢，反應較慢 |\n"
            "| MA60（季線） | 台股／亞股法人常用 | "
            "貼近外資、投信季度調整部位的籌碼行為，轉折反應較即時 |"
        )
        st.markdown("**ADX 趨勢強度門檻**：ADX < 20 判定盤整；ADX > 25 趨勢成立，"
                     "再用 +DI／−DI 判斷多空方向。")
        st.code(
            'market_regime =\n'
            '  if 指數 > MA60 and MA60斜率 > 0 and ADX > 20 and +DI > -DI:\n'
            '      "bull"\n'
            '  elif 指數 < MA60 and MA60斜率 < 0 and ADX > 20 and -DI > +DI:\n'
            '      "bear"\n'
            '  else:\n'
            '      "sideways"  # ADX < 20，均線糾結',
            language="python")
        st.markdown("**10 年實測：MA60 版本（2016~2026）**——多頭 34.7%／空頭 13.0%／盤整 52.3%；"
                     "平均連續天數：多頭 17.0 天／空頭 11.4 天／盤整 16.3 天；10 年切換 163 次。")
        st.markdown(
            "| 年度 | 多頭% | 空頭% | 盤整% |\n|---|---:|---:|---:|\n"
            "| 2016 | 15% | 7% | 78% |\n| 2017 | 48% | 5% | 48% |\n"
            "| 2018 | 11% | 30% | 59% |\n| 2019 | 50% | 7% | 43% |\n"
            "| 2020 | 41% | 13% | 46% |\n| 2021 | 33% | 11% | 56% |\n"
            "| 2022 | 9% | 49% | 42% |\n| 2023 | 41% | 0% | 59% |\n"
            "| 2024 | 44% | 0% | 55% |\n| 2025 | 37% | 15% | 48% |\n"
            "| 2026* | 54% | 0% | 46% |"
        )
        st.caption("2022 空頭佔比最高（升息重挫），2018 次高（貿易戰）；2023~2024 空頭幾乎不存在，"
                   "對應 AI／半導體多頭週期。＊2026 為截至實測當下的資料。")
        st.markdown("**10 年實測：MA200 版本（2016~2026）**——多頭 31.9%／空頭 8.4%／盤整 59.7%；"
                     "平均連續天數：多頭 17.4 天／空頭 15.6 天／盤整 24.8 天；10 年切換 115 次。")
        st.markdown(
            "| 年度 | 多頭% | 空頭% | 盤整% |\n|---|---:|---:|---:|\n"
            "| 2016 | 2% | – | 98% |\n| 2017 | 48% | – | 52% |\n"
            "| 2018 | 11% | 17% | 71% |\n| 2019 | 26% | 5% | 69% |\n"
            "| 2020 | 41% | 7% | 52% |\n| 2021 | 34% | – | 66% |\n"
            "| 2022 | 6% | 45% | 49% |\n| 2023 | 29% | – | 71% |\n"
            "| 2024 | 44% | – | 56% |\n| 2025 | 36% | 9% | 55% |\n"
            "| 2026* | 54% | – | 46% |"
        )
        st.caption("2016 盤整高達 98%——當年波動不夠讓 MA200 斜率轉向；2023、2024 空頭幾乎消失，"
                   "反應速度比 MA60 更慢。＊2026 為截至實測當下的資料。")
        st.markdown("**MA60 vs MA200 對照**")
        st.markdown(
            "| 指標 | MA60 | MA200 |\n|---|---:|---:|\n"
            "| 盤整佔比 | 52.3% | 59.7% |\n"
            "| 空頭佔比 | 13.0% | 8.4% |\n"
            "| 盤整平均連續天數 | 16.3 天 | 24.8 天 |\n"
            "| 10 年切換次數 | 163 次 | 115 次 |"
        )
        st.markdown(
            "MA200 較鈍，訊號少、更穩，但空頭反應慢、抓得少；MA60 反應快，適合中期轉折，"
            "訊號雜訊也較多。實務上可疊加：MA200 決定「開不開放做多」，MA60 決定實際進出場時機。\n\n"
            "**結論（跟這頁的設計呼應）**：台股大盤建議以 MA60 為主、MA200 作長期濾網——"
            "所以這頁的台股卡兩條都列；美股／國際比較則以 MA200 為準——所以國際指數只列 MA200。"
            "實測資料來源 FinMind，僅供技術分析參考，不是這頁實際採用的規則。"
        )

    st.divider()
    _macro_refresh_button()
    _disclaimer()


APP_NAME = "股市雷達"          # repo 仍叫 tw-hold；網頁表頭用這個（非投顧語氣，2026-09-11 改名）
NAV = ["總經導航", "短線", "長波段", "價值", "定存", "個股查詢", "多軌體檢", "主動式 ETF"]


def _freshness_badge_html() -> str:
    """表頭右側新鮮度徽章——只看 bundle trading_date，純顯示不擋頁（使用者 2026-09-16
    裁決：badge-only、單一時鐘）。燈號用既有的 `.thc-pill`（good/warn 兩色點+底色），
    跟卡片上的判斷徽章同一套視覺語彙，不是另外找 emoji（同一天使用者要求
    「更符合UI風格」改的）。

    ⚠️ 文案寫死「清單資料」而不是籠統的「資料日期」：0050／006201 從 2026-09-16 起
    各自獨立落地、**不再跟 bundle 共用同一個時鐘**，這顆徽章已經涵蓋不到總經導航的
    那兩張卡了。寫成全站語氣會讓使用者站在總經導航頁把它誤認成那頁卡片的日期。
    那兩支的新鮮度由 `heartbeat.yml`（開盤前）顧，不上表頭——一顆徽章講三個時鐘
    只會變成沒人看得懂的東西。

    新鮮度判斷借 `reference/freshness.py`，跟 heartbeat 那邊「預期交易日」的定義
    是同一份，不要兩邊各自維護一套容忍天數。"""
    from datetime import date

    from reference.freshness import check_one, meta_trading_date
    c = check_one("bundle", meta_trading_date(), date.today())
    sev = "good" if c["ok"] else "warn"
    label = f"清單資料 {c.get('last_date') or '—'}"
    return f'<span class="thc-pill thc-{sev}">{_esc(label)}</span>'


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
    hc1, hc2 = st.columns([5, 2])
    hc1.title(f"📡 {APP_NAME}")
    hc2.markdown(f'<div class="thc-header-badge">{_freshness_badge_html()}</div>',
                 unsafe_allow_html=True)

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
    elif nav == "主動式 ETF":
        _active_etf_page()
    else:
        _macro_compass_page()

    st.divider()
    st.caption("價值 / 定存 / 長波段三清單 + 短線（tw-swing 轉呈）+ 個股查詢。**候選 + 為什麼，不是建議。**"
               + ("　·　本地進階模式" if LOCAL_ADVANCED else "　·　雲端唯讀模式"))


if __name__ == "__main__":
    main()
