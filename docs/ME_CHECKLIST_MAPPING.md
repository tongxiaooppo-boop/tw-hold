# me 專案 → tw-hold 個股檢核：對照表

> 建立 2026-09-09。**§7 已定案、已實作**（commit 見下）。
>
> ## 實作狀態（2026-09-09）
> - `app/checklist.py`：`swing_checks` / `value_checks` / `deposit_checks` → `[{項目,門檻,現值,狀態}]`。
>   價值/定存讀 `data/derived/factors_{value,deposit}.parquet`；波段現算（qf/rev/chips/per）。
> - `app/stockcharts.py`：新增 `roe_trend` / `balance_health` / `yield_trend`（TTM EPS 疊線
>   本來 `quarterly_eps` 就有 → 沒另做）。個股查詢頁已接這 3 張。
> - `app/streamlit_app.py`：NAV 加「三軌體檢」分頁（`_checklist_page`）；表頭 `tw-hold` → **「持股觀測站」**。
> - 測試：`tests/test_checklist.py`（5）+ `test_app_smoke` 加 1，共 79 passed。
> - 利息保障倍數：如定案，整條未出現。
> - **不加總、不顯示 N/M 通過**（跟 F-Score 頁一致）——只有表格。

> 目的：把 HANDOFF_2026-09-08 §4 那條「個股頁三軌門檻檢視」改用舊專案
> `books/claude/me/taiwan-stock-analyzer-v3` 的子項設計去做，但**不評分**——
> 打分（0–100 加權）全部改成檢核表（項目／現值／狀態），照 F-Score 9 分項的模式。
>
> me 專案定調：**完全廢掉**（PRD 是早期版本、經精修過，值得回收想法；多入口沒必要）。
> 只回收「波段／價值／定存三軌各 6 子項要看什麼」這份骨架，不搬程式、不搬 AI、
> 不搬回測、不搬新聞情緒、不搬短線軌。

---

## 0. 一句話結論

me 三軌（波段／價值／定存）子項要的原料，**tw-hold bundle 覆蓋約 95%**，
而且全是清單頁已經在載入的檔，**不需要為單股多打一次 FinMind**。
唯一真缺口：**利息保障倍數**（定存 1 個子項的一半）——標「資料不足」即可。
超出 bundle（~1000 檔）範圍的股票：維持現況不補抓。

---

## 1. 資料承接總表

| bundle 檔 | 覆蓋範圍 | 能算出的 me 指標 | 缺口 |
| :-- | :-- | :-- | :-- |
| `per.parquet` | 2015–2026、1978 檔，`per / pbr / dividend_yield` 日頻 | PE_TTM(≈per)、PB、**PE/PB 百分位**（11 年夠深）、殖利率、殖利率百分位 | — |
| `income.parquet` | 1018 檔、~42 季 | TTM_EPS、EPS_YoY、ROE_TTM（配 balance equity）、Gross_Margin、Operating_Margin、EPS/ROE/毛利率 **穩定度(std)**、Revenue CAGR（另有 revenue 檔更準） | **無利息費用欄** → Interest_Coverage 算不出 |
| `balance.parquet` | 1008 檔 | Debt_Ratio、Current_Ratio、equity（ROE 分母）、capital_stock | — |
| `cashflow.parquet` | `ocf / capex / icf` | TTM_OCF、TTM_FCF(=ocf−capex)、Cash_Conv_Ratio(OCF/NI)、FCF_Coverage | — |
| `revenue.parquet` | 2015– 長表、1980 檔 | Revenue_YoY / MoM / 加速度 / 1.5Y·3Y CAGR / 單月創 6·12 月高 | — |
| `prices_adj.parquet` | **2023-05–**（僅 3.3 年）、1969 檔 | close、MA5/20/60、MA20 斜率(OLS)、RSI_6 | 年線(MA240) 資料淺；me 這幾張圖用不到，波段趨勢模板另走清單邏輯 |
| `chips.parquet` | 外資／投信／自營淨額 | Inst_20D_Net（20 日累計）、Inst_Slope_20D(OLS) | — |
| `dividend.parquet` | 2014– | 連續配息年數、配息率(Payout)、現金股利總額、EPS Cover | — |

**清單 JSON 已算好、可直接抄的欄位**（`data/derived/*_list.json` 的 holdings/candidates）：
`value_score→不用`、`f_score`、`roe`、`norm_pe`、`fcf_yield`、`gross_margin`、`cheap_threshold`、
`cur_yield`、`yield_floor`、`fill_rate`、`ret3y_incl`、`avg_yield_3y/5y`、`yield_pctile_5y`、
`div_years`、`payout_ratio_ttm`、`debt_ratio`、`ann_vol`、`industry_headwind`… ——
**這些是清單頁口徑，個股檢核若要跟清單一致，優先讀這裡而不是重算。**

---

## 2. 波段軌 — 子項對照

me 權重（廢）：營收動能 25 / 中期趨勢 20 / 籌碼趨勢 20 / 獲利成長 15 / 估值位置 10 / 催化 10

| me 子項 | me 門檻（取「良」級當達標線） | 需要欄位 | bundle 來源 | tw-hold 已有等價？ | 建議檢核設計（不評分） |
| :-- | :-- | :-- | :-- | :-- | :-- |
| 營收 YoY | ≥ 20% 佳 / ≥ 10% 普通 / < 0 差 | Revenue_YoY | revenue.parquet | 候選池 `c_rev_yoy`(>0)、`revenue_accel` | 現值 + 三態燈（≥20 ✓ / 0–20 △ / <0 ✗） |
| 營收 MoM | ≥ 2% 佳 / ≥ 0 普通 | Revenue_MoM | revenue.parquet | 無 | 現值 + 三態 |
| 營收加速度 | 本月 YoY > 上月 YoY | Revenue_YoY diff | revenue.parquet | 候選池 `revenue_accel` 同義 | ✓/✗ |
| 1.5Y 營收 CAGR | ≥ 8% 佳 / ≥ 0 普通 | 18 個月營收比值 | revenue.parquet | 無 | 現值 + 三態 |
| 單月營收創高 | 創 12 月新高 / 創 6 月新高 | rolling max | revenue.parquet | 無 | 「創 N 月新高」文字狀態 |
| 中期趨勢 | MA20 斜率 > 0 且 close > MA60 | close, MA20 斜率, MA60 | prices_adj | 候選池趨勢模板 t1–t8（更嚴） | 建議**直接用候選池 8 項趨勢模板**（tw-hold 已有、已在 swing 清單用），不引 me 的簡化版 |
| 籌碼趨勢 | Inst_Slope_20D ≥ 0，或 Inst_20D_Net ≥ 0 | chips 20 日 | chips.parquet | 候選池 `c_inst`(net20>0) | 現值(20 日累計張數) + ✓/✗；斜率當補充 |
| 獲利成長 | TTM_EPS ≥ 8 佳、EPS_YoY ≥ 15% 佳 | income TTM | income.parquet | 候選池 `c_eps_yoy`(>25%)、`c_eps_3y_growth` | 用候選池門檻（>25% / 3 年成長），現值並列 |
| 估值位置 | PE 百分位 ≤ 40% 佳、PB 百分位 ≤ 40% 佳 | per 百分位 | per.parquet | 價值軌 `pe_p30/p70` | 現值(百分位) + 三態 |
| 催化因子 | 單月創 12 月高 / YoY > 30% | 同營收創高 | revenue.parquet | 無 | 與「單月營收創高」合併一項，避免重複 |
| Modifier: 負債比 penalty | > 70% 扣分（非金融） | Debt_Ratio | balance.parquet | 有 `debt_ratio` | 風險提示列：負債比 > 70% → ⚠️ |
| Modifier: RSI 超賣 bonus | RSI_6 < 30 | RSI_6 | prices_adj | 無 | 風險/機會提示列 |

**波段軌小結**：中期趨勢直接接 tw-hold 候選池的趨勢模板；獲利成長接候選池 EPS 門檻；
真正要新做的只有營收 MoM / 1.5Y CAGR / 營收創高 / 估值百分位 這幾條。

---

## 3. 價值軌 — 子項對照

me 權重（廢）：成長能力 30 / 獲利品質 20 / 估值安全 15 / 財務安全 15 / 現金流品質 10 / 股東報酬 10

| me 子項 | me 門檻（達標線） | 需要欄位 | bundle 來源 | tw-hold 已有等價？ | 建議檢核設計 |
| :-- | :-- | :-- | :-- | :-- | :-- |
| 估值安全 | PE_TTM ≤ 15 且 PB 百分位 ≤ 40% | per | per.parquet | 價值軌 `cheap_threshold` / `norm_pe` / `pe_p30/p70` / `upside_pct` | **用 tw-hold 便宜門檻**：現價 vs `cheap_threshold` → 便宜/合理/貴；PE 百分位並列 |
| 獲利品質 | ROE_TTM ≥ 10% 且 毛利率 ≥ 30% | income+balance | income/balance | 清單 `roe`、`gross_margin` | ROE ≥ 10 / 毛利率 ≥ 30 各一格 ✓/△/✗ |
| 成長能力 | TTM_EPS ≥ 8、Revenue_YoY ≥ 10% | income, revenue | income/revenue.parquet | 候選池 EPS 門檻 | TTM_EPS 現值 + 三態；營收 YoY 現值 + 三態 |
| 財務安全（金融跳過） | 負債比 ≤ 45%、流動比 ≥ 2.0 | balance | balance.parquet | 清單 `debt_ratio` | 負債比 / 流動比各一格；金融業標「不適用」 |
| 現金流品質（金融跳過） | TTM_FCF > 0、TTM_OCF > 0 | cashflow | cashflow.parquet | 清單 `fcf_yield` | FCF / OCF 正負 ✓/✗；金融「不適用」 |
| 股東報酬 | 殖利率 ≥ 3%、有配息 | per, dividend | per/dividend.parquet | 定存軌 `cur_yield` | 殖利率現值 + 三態；連續配息年數並列 |
| Modifier: 產業負債 bias | 負債比 > 同業中位 ×1.2 | 需同業中位數 | 需另算（screener/industry.py 有近似） | `industry_headwind` 旗標 | 提示列，不影響檢核 |
| Modifier: F-Score | — | — | — | **F-Score 9 分項已在個股頁** | 直接沿用現有那張表，不重做 |

---

## 4. 定存軌 — 子項對照

me 權重（廢）：配息紀錄 25 / 配息品質 20 / 現金流 20 / 財務安全 15 / 獲利穩定 10 / 長期成長 10

| me 子項 | me 門檻（達標線） | 需要欄位 | bundle 來源 | tw-hold 已有等價？ | 建議檢核設計 |
| :-- | :-- | :-- | :-- | :-- | :-- |
| 配息紀錄 | 連續 ≥ 7 年 且 殖利率 ≥ 4.5% | dividend, per | dividend/per.parquet | 定存軌 `div_years`、`cur_yield`、`yield_floor`(5%) | 連續年數 + 殖利率 vs 5% 門檻（用 tw-hold 硬底線 5%，不用 me 的 4.5%） |
| 配息品質 | Payout 60–80% 且 EPS Cover ≥ 2.0 | dividend, income | dividend/income.parquet | 清單 `payout_ratio_ttm` | Payout 區間燈；EPS Cover 現值 |
| 現金流（金融跳過） | OCF/NI ≥ 80% 且 FCF > 0 | cashflow, income | cashflow/income.parquet | 清單 `fcf_yield` | 轉換率現值 + FCF 正負 |
| 財務安全（金融跳過） | 負債比 ≤ 45% 且 **利息保障 ≥ 5** | balance, income | balance | 清單 `debt_ratio` | 負債比一格；**利息保障 → 標「資料不足（bundle 無利息費用）」** |
| 獲利穩定 | ROE std ≤ 5%、EPS std ≤ 4 | income 多季 | income.parquet | 無 | 兩個 std 現值 + 三態（越低越好） |
| 長期成長 | 營收 CAGR ≥ 10%、EPS_YoY ≥ 15% | revenue, income | revenue/income.parquet | 無 | 現值 + 三態 |
| 填息率 / 含息報酬 | — | — | — | 定存軌 `fill_rate`、`ret3y_incl`（清單硬門檻） | **加進來**：tw-hold 有、me 沒有，比 me 的更該看 |
| 週化波動 | — | — | — | 清單 `ann_vol` | 並列參考 |

---

## 5. 圖表對照（me 有、tw-hold `stockcharts.py` 沒有）

tw-hold 現有 8 類：K線+MA、PE 河流、單季 EPS、三率、現金流、股利、月營收+YoY、法人買賣超、F-Score 表。

| me 分頁的圖 | tw-hold 現況 | 建議 | 資料（都在 bundle） |
| :-- | :-- | :-- | :-- |
| ROE / 毛利率 走勢（季） | 三率圖無 ROE | **新增 ROE 走勢**（可疊毛利率） | income+balance |
| TTM EPS 走勢線 | 只有單季 EPS 柱 | 現有 `quarterly_eps` **疊一條 TTM 線** | income 四季滾動 |
| 負債比 / 流動比 走勢 | 完全沒有 | **新增財務結構圖** | balance |
| 殖利率 走勢線 | PE 河流只有 PE | `pe_river` **加殖利率右軸**，或獨立小圖 | per.parquet |
| 營收 YoY 疊股價 | 月營收圖無股價 | `monthly_revenue` 加股價右軸（可選） | revenue+prices |
| 法人 20 日累計 疊股價 | `institutional_net` 是每日淨額 | 加一條 20 日累計線 + 股價（可選） | chips+prices |

不搬 me 的 matplotlib —— tw-hold 全 plotly／深色／已做手機觸控處理，是照 tw-hold 風格重畫。
**必做 3~4 張**：ROE 走勢、TTM EPS 疊線、財務結構、殖利率線。其餘 2 張是加分。

---

## 6. 檢核表的「狀態」怎麼呈現（要討論）

me 每子項是 5 級分（100/85/70/50/0）。不評分後，選項：

- **A. 二態**（照 F-Score）：每項一條門檻，✓ 成立 / ✗ 未達 / — 無資料。最乾淨、最不像評分。
- **B. 三態**：✓ 達標 / △ 普通 / ✗ 不佳 / — 無資料，另欄顯示現值。資訊多，但「△」有點像分數。
- **C. 二態 + 現值欄**：門檻用 tw-hold 既有的（EPS>25%、殖利率≥5%…），旁邊always顯示現值。

傾向 **C**：跟清單頁門檻一致、跟 F-Score 一致、現值讓使用者自己判斷程度。

---

## 7. 決策（2026-09-09 定）

1. **新開分頁**，不併個股查詢。分頁名 **「三軌體檢」**。
   NAV 變 6 個：價值／定存／長波段／個股查詢／**三軌體檢**。
   輸入代號 → 三軌各一張檢核表（`st.tabs` 波段／價值／定存）+ §5 必做圖。
2. 狀態呈現用 **C**：二態（✓ 成立 / ✗ 未達 / — 無資料）+ 永遠顯示現值欄。
   門檻優先用 tw-hold 清單既有口徑。
3. 圖表：先做**必做 4 張**（ROE 走勢、TTM EPS 疊線、負債比/流動比、殖利率線）。
   加分 2 張之後再說。
4. 波段「中期趨勢」**直接吃候選池 8 項趨勢模板**，不列 me 簡化版。
5. **利息保障倍數整條拿掉**——不出現、也不標「資料不足」。定存「財務安全」子項
   只剩負債比一格。

### App 表頭改名

repo 仍叫 `tw-hold`，但網頁 `st.title` 不用 `tw-hold`。
定 **「持股觀測站」**（見 `streamlit_app.main()` 的 `st.title` / `page_title`）。
理由：三軌都是長期持有導向、產品定調是「觀測 + 候選 + 為什麼，不是建議」，
「觀測站」對得上非投顧語氣；避免「分析/推薦/選股」這類字眼。

---

## 8. 相關檔案

| 事 | 位置 |
| :-- | :-- |
| me 三軌子項細節 | `books/claude/me/taiwan-stock-analyzer-v3/docs/{波段,價值,定存}評分程式實說.md` |
| me 圖表原始碼 | `books/claude/me/.../ui/waterfall_charts.py`（中長線三 sub-tab，L257~513） |
| tw-hold 個股頁 | `app/streamlit_app.py` `_stock_page`（L520~624）、`app/stockcharts.py` |
| tw-hold 資料層 | `app/bundle_data.py` |
| tw-hold 清單門檻 | `screener/candidate_pool.py`（EPS_YOY_MIN=0.25 等）、`screener/deposit_pricing.py`、`screener/pricing.py` |
| 相關記憶 | `tw-hold-ai-layer-design`（AI 只解說不選股，同精神）、HANDOFF_2026-09-08 §4 |
