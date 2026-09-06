# me2 開發計劃

> `me`（`taiwan-stock-analyzer-v3`）的升級版。**完全獨立的專案**，暫訂本地跑。
> 定案日 2026-09-07。這份是計劃，還沒開工。
> `me` 原始碼現在在 `d:\g\claudeooks\claude\me	aiwan-stock-analyzer-v3\`（2026-09-07 整理）。

---

## 0. 一句話

一個本地跑的台股決策支援工具：**產出長波段 / 價值 / 定存三種推薦清單**，
且能**查詢單一個股**（不打分、用數據展開各種常見圖表）。

**價值/定存/長波段整條 stack 都在 me2**——資料抓取、因子計算、篩選、UI，
全部自己來。tw-swing 只是「可以參考的程式碼」，不是 runtime 依賴。

---

## 1. 是什麼 / 不是什麼（2026-09-07 使用者裁決：完全遷移）

| 是 | 不是 |
| :--- | :--- |
| `me` 的下一版，獨立 repo（`d:\g\claude\me2\`），獨立 git，push 到 GitHub | tw-swing 的一部分、tw-swing 的下游 |
| **自己**抓財報三表 + 股利、**自己**算因子（F-Score / normalized PE / 存股安全分…） | 讀 tw-swing 產的因子表 |
| **複製**參考程式碼進來：FinMind client、`price_adjuster`、指標運算 | `import twswing.*`（零 runtime 依賴，tw-swing 改東西不會弄壞 me2） |
| 長波段（2–12 週以上）/ 價值 / 定存 三清單 + 個股查詢 | 短線 / 短波段（那是 tw-swing 的事，維持現狀） |
| 決策支援：清單 + 個股數據視圖 + 買入建議價 | 交易系統（不進資金池、不走 gate + 樣本外） |
| 暫訂本地 Streamlit | （之後可選 HF Spaces 私有） |

**tw-swing 這邊**：`twswing.value`、`fetch_fundamentals.py`、`fundamentals.yml`、
`data/fundamentals/`、`fetch_finmind.py` 的財報 datasets、相關測試——**全部遷來 me2、
從 tw-swing 移除**。tw-swing 回歸純短線/短波段。清理清單見 §10。

> ⚠️ 例外：tw-swing 的 `twswing.data.fundamentals`（月營收動能 / PE 百分位）
> **留在 tw-swing**——那是 Y 系短波段規則（Y1/Y3/Y4/Y7）在用的，是短波段不是價值。

---

## 2. 三個推薦清單 + 個股查詢

### 2A. 推薦模式

| 清單 | me2 怎麼做 |
| :--- | :--- |
| **長波段**（2–12 週以上，使用者指定） | 自建多因子 screener，見 §5 |
| **價值** | Piotroski F-Score ≥ 6 gate → 剔除價值陷阱 → Magic Formula 精神 rank(品質)+rank(便宜)。設計見 §6 |
| **定存** | 參考 5 檔高股息 ETF（00713 最像存股經理人）：硬門檻 + 存股安全分。設計見 §7 |

- 清單長度 10–20，限**市值前 500 大**。
- 輸出：排序 + **量化理由** + **買入建議價** 或 **「不推薦」（明確原因）**。
- 「先剔除、再排序」——價值陷阱 / 配息陷阱是硬門檻，不被其他高分蓋過。

### 2B. 個股查詢（不打分）

- 輸入代號 → **前 500 大**：讀本地快取財報；**不在**：即時打 FinMind 補那一支。
- **不給評分、不給買賣 verdict**。給：原始數據表 + 常見圖表（§4）+ F-Score 9 分項
  當診斷清單（打勾/打叉，**不加總**）。
- 精神：攤開數據讓人 / AI 判斷，不代替判斷。

### 2C. AI 敘事層（選配，後期）

- 「複製給 AI」：把數據 + 因子整理成文字 → 貼給 GPT/Gemini/DeepSeek 問產業趨勢、
  買入價、要不要投入。或整合 DeepSeek API（參考 `books/claude/me/taiwan-stock-analyzer-v3/ai/analyzer.py`）。
- 只傳整理過的數據，不傳原始母表。

---

## 3. 資料層（me2 自己的）

| 資料 | 來源 | 實作 |
| :--- | :--- | :--- |
| **財報三表 + 股利政策** | FinMind（`TaiwanStockFinancialStatements` / `BalanceSheet` / `CashFlowsStatement` / `Dividend`） | 移植 tw-swing 的 `fetch_fundamentals.py`（週限速抓、邊抓邊整併 pivot、checkpoint、市值前 500） |
| **PER / PBR / 殖利率** | FinMind `TaiwanStockPER` | 逐日；「vs 自身歷史區間」要用 |
| **日線股價** | FinMind `TaiwanStockPrice` + **還原** | 移植 `books/claude/me/taiwan-stock-analyzer-v3/data/price_adjuster.py`（除權息/減資/面額變更的價格斷層） |
| **月營收** | FinMind `TaiwanStockMonthRevenue` | 營收動能因子、長波段基本面順風 |
| **即時個股補抓** | 查詢不在 500 大時觸發 | 抓完存本地快取，設過期時間 |
| **FinMind 額度** | token 走環境變數 `FINMIND_TOKEN` | me2 自己的節流器，**上限守 500/hr**。⚠️ 跟 tw-swing 的 Y 系 fetch 共用同一帳號額度——排程錯開，或 me2 撞到就等 |

整併檔存 `me2/data/`（版控，同 tw-swing 對 `data/fundamentals/` 的做法：pivot 後個位數 MB）。

**M0 帶資料**：tw-swing 已 backfill 的前 500 大財報（`income/balance/cashflow/dividend`，
2015Q1–2026Q2，2.9MB）直接搬過來當起點，不用重抓。

---

## 4. 個股圖表清單（§2B；參考 `books/claude/me/taiwan-stock-analyzer-v3/ui/waterfall_charts.py`，升級為互動圖）

| 類別 | 圖 |
| :--- | :--- |
| 價格 | K 線 + 均線（周/季/年線）+ 量；相對大盤強弱（vs 0050） |
| 成長 | 月營收 YoY / MoM 柱狀；季度 EPS；年度 EPS |
| 獲利品質 | 三率（毛利 / 營益 / 淨利）趨勢；ROE / ROA |
| 財務結構 | 負債比 / 流動比；現金與約當現金 |
| 現金流 | OCF / FCF / 資本支出 逐季 |
| 股利 | 逐年現金 + 股票股利；殖利率 + 股價；**填息天數 / 填息率** |
| 估值 | **本益比河流圖**（台股經典）；PBR 河流圖；normalized PE vs trailing PE |
| 診斷 | Piotroski F-Score 9 分項打勾表（不加總） |

技術：**plotly**（互動、hover、縮放——比 `me` 的靜態 matplotlib 是實質升級）。

---

## 5. 長波段 screener（me2 自建）

- **持有 2–12 週以上**——比 tw-swing 的短波段（3–10 天）長一個量級，接近部位交易 / CANSLIM-lite。
- **進場條件**（多因子；指標運算**複製** tw-swing 的 `core` / `ma_rules` / `pivots` / `trendlines` 進 me2）：
  - 趨勢：站上季線且季線上彎 / 站上年線
  - 動能：近 8–12 週相對強度 > 大盤
  - 基本面順風：月營收 YoY 加速 或 季 EPS 成長 或 F-Score ≥ 6
  - 時機：回檔到均線/前高支撐未破，或 突破數週整理帶量
- **剔除**：下降趨勢 / 營收連續衰退 / 財務惡化
- **輸出**：清單 + 為什麼 + 建議進場區間
- **不回測、不進資金池**——決策支援不是交易策略。參數用合理預設。
  （想驗有沒有效可以之後拿 tw-swing 回測引擎另跑一次，加分不是前提。）

---

## 6. 選股 + 買入建議價 + 推薦判定（投信經理人視角）

> 使用者 2026-09-07：帶投信經理人的角度。核心是「找相對優秀的股票 + 用市況
> 調整的 PE 倍數估目標價」。這一節同時是**長波段清單**與**價值清單**的推薦引擎
> （兩者選股邏輯不同、估值方法共用）。

### 6.1 選股：相對優秀（rank，不是絕對門檻）

投信不看「有沒有到某個絕對標準」，看「**現在這產業／這個池子裡，它算不算相對
好的**」。用 rank（分位數），不用硬門檻。

| 面向 | 免費資料指標 |
| :--- | :--- |
| **營收動能**（台股投信最看重） | 月營收 YoY、YoY 加速度、近 3 月營收 vs 12 月均、創新高與否 |
| **獲利成長** | 季 EPS YoY、TTM EPS YoY、成長的**穩定度**（連續幾季正成長） |
| **獲利品質** | ROE、三率（毛利／營益／淨利）走勢向上 |
| **財務體質** | Piotroski F-Score（≥ 5 才進入 rank，< 5 直接不推薦） |
| **籌碼**（選配，之後） | 外資 + 投信近 N 日同買 |

- **長波段清單**：上述 rank + §5 的技術時機（趨勢 + 相對強度 + 進場時機）
- **價值清單**：上述 rank 偏重「品質 + 便宜」，且加 §6.4 的價值陷阱剔除

### 6.2 目標價：forward EPS × 市況調整 PE

```
目標價 = forward_EPS × target_PE
```

**forward_EPS**（沒有付費財測 → 保守自估）：
```
forward_EPS = TTM_EPS × (1 + g)
g = clip( 綜合成長率, -0.10, +0.30 )
綜合成長率 = 0.5 × (近 4 季營收 YoY) + 0.5 × (近 8 季 EPS 年化成長率)
```
（上限 +30%：投信不會用超過 30% 的成長率去 justify 估值；下限 −10%：衰退股給折價但不歸零。）

**target_PE**（市況調整，使用者給的錨）：

| 市況（複製 `twswing.data.regime`：MA200 + 60 日報酬 + 回撤） | 基準 target_PE |
| :--- | :--- |
| 空頭 `bear` | **15** |
| 中等 `chop` | **20** |
| 多頭 `bull` | **22** |

再依個股微調（各 ±20% 為限）：
- **成長溢價**：g > 20% → ×1.15；g < 5% → ×0.85（PEG 精神）
- **自身歷史錨**：若基準 target_PE 高於「該股近 5 年 PE 的 80 分位」→ 拉回到 80 分位
  （不給一支歷史上從沒享受過 20 倍的成熟股 20 倍）
- **產業**：金融／營建等資產型，改用 PB 估（目標價 = forward_BVPS × target_PB，
  target_PB 同樣分市況：0.8 / 1.2 / 1.5），不用 PE

### 6.3 買入建議價：目標價打安全邊際，且不追高

```
估值買價 = 目標價 × (1 − 安全邊際)      安全邊際 = 15%（chop）/ 25%（bear）/ 10%（bull）
技術買價 = max(季線, 近 20 週前低)       （回檔支撐，不追高）
買入區間 = [ 技術買價 , min(估值買價, 現價) ]  ——若現價已低於估值買價，區間上緣就是現價
```

### 6.4 推薦判定（明確、寫死）

| 條件 | verdict |
| :--- | :--- |
| F-Score < 5 / 營收連 3 季衰退 / EPS 連 2 季 YoY 負 / 產業逆風 | **不推薦（品質）** |
| 現價 ≥ 目標價 | **不推薦（已達目標價 / 高估）** |
| 買入區間上緣 < 現價 < 目標價 | **觀望（合理但無安全邊際）** |
| 現價 ≤ 買入區間上緣 | **推薦** ＋ 標出買入區間、目標價、預期報酬 |
| 流動性不足（日均量 < 門檻） | **不推薦（流動性）** |

### 6.5 展示（給人 + 給 AI）

每一檔推薦附：選股 rank 明細（哪幾個因子讓它上榜）、forward_EPS 與 g 的推算、
市況與 target_PE、目標價、買入區間、預期報酬、以及「不推薦」時的**確切原因**。

---

## 7. 定存區設計（估值方法不同——殖利率導向，不用 target PE）

參考 5 檔高股息 ETF（00713 最像存股經理人）：

- **硬門檻**：近 4 季 EPS 每季為正 / 連續配息 ≥ 5 年無減配 / 近 3 年 FCF 覆蓋現金股利 /
  現金股利主要來自盈餘（非公積/減資）/ 負債比 ≤ 產業中位數 × 1.5
- **存股安全分**（rank 平均）：FCF 殖利率 + 價格低波動 + ROE 品質 + 填息率 +
  配息穩定度 × **景氣循環懲罰**（營收/毛利波動）
- **買入價（殖利率法，不用 target PE）**：
  ```
  買入殖利率門檻 = max( 該股近 5 年平均殖利率 , 4% )
  估值買價 = 近 3 年平均現金股利 ÷ 買入殖利率門檻
  買入區間 = [ max(季線, 近20週前低) , min(估值買價, 現價) ]
  ```
- **推薦判定**：現價殖利率 ≥ 買入殖利率門檻 且 過所有硬門檻 → **推薦**；
  現價殖利率 < 門檻 → **觀望**；硬門檻沒過 → **不推薦（原因）**
- **揭露欄**：當期殖利率、近 3 年平均殖利率、殖利率 vs 5 年區間、產業

> §6/§7 的因子計算已在 tw-swing `twswing.value` 寫好（loader / factors / screen），
> **整包搬進 me2**，改成 me2 native、去掉 `twswing` import。市況分期（`regime`）
> 也複製一份進 me2（target PE 要用）。

---

## 8. 技術棧 · repo · 週更（2026-09-07 定案）

- Python 3.14、Streamlit、**plotly**、pandas、pyarrow、requests
- **repo**：`d:\g\claude\me2\`，獨立 git；**推到 GitHub**（同帳號 `tongxiaooppo-boop`，
  新 repo，使用者已同意）——為了 code 備份 + 版控 + 版控的財報 parquet。
- **週更財報：跑本地，不用 GitHub Actions**（我的建議，理由見下）：
  - Windows 工作排程器每週跑一次 `python build_factors.py --refresh`，或 app 啟動時
    偵測資料 stale（> 7 天）就跳一顆「更新」按鈕。
  - 為什麼不用 Actions：① 同帳號的 Actions 免費額度（2000 分/月）tw-swing 的
    G-5 關鍵管線已用 ~1100 分，me2 再吃 ~340 分 → 71%，能塞但擠掉 tw-swing 的
    餘裕不值得；② me2 本來就本地跑、電腦開著，本地排程零成本、零額度、零 secret 管理；
    ③ me2 週更斷了只是資料晚一週，不像 tw-swing 的處置股快照漏了永遠補不回來。
  - **新 GitHub 帳號：不需要**。FinMind 額度是綁 FinMind 帳號不是 GitHub 帳號，
    開新 GitHub 帳號不會多給 FinMind 配額；而 Actions 額度問題用「跑本地」就解了。
- **FinMind token**：環境變數 `FINMIND_TOKEN`，同一個 FinMind 帳號。me2 的節流器
  上限守 **500/hr**（同 tw-swing 的裁決）。⚠️ 之後 tw-swing 的 Y 系規則若也要每日
  抓 FinMind，兩邊排程要錯開（現在 tw-swing 每日管線不碰 FinMind，無衝突）。
- 不要 gunicorn（Streamlit 內建）
- **零 `import twswing`**——要的程式碼用複製的

---

## 9. 分期

| 階段 | 內容 | 產出 |
| :-- | :--- | :--- |
| **M0 遷移 + 骨架** | §10 從 tw-swing 搬過來（因子庫 / fetch / 資料 / 測試），去 twswing 依賴，repo 結構，最陽春三清單顯示 | 能跑、看得到價值/定存清單（用搬來的 backfill 資料） |
| **M1 個股查詢** | 代號輸入 → 前 500 讀快取 / 不在則即時補 → 數據表 + 4 個核心圖 | 個股頁能用 |
| **M2 圖表完整** | §4 全部 + 本益比河流圖 + F-Score 分項 | 個股頁完整 |
| **M3 長波段 screener** | §5，第三份清單 | 三清單到齊 |
| **M4 推薦判定** | 買入建議價 + 「不推薦」標記 + 篩選 UI | 推薦模式完整 |
| **M5 AI 敘事層** | 「複製給 AI」or DeepSeek（選配） | |
| **M6 hosting** | HF Spaces 私有 or 本地（選配） | |
| **M7 週更財報** | 本地排程（Windows 工作排程）跑 `build_factors.py --refresh`，或 app 偵測 stale 跳更新鈕。**不用 Actions**（見 §8） | 資料自動更新 |

---

## 10. tw-swing 清理清單（遷移時執行）

**搬到 me2**（然後從 tw-swing 移除）：

| tw-swing 路徑 | me2 對應 |
| :--- | :--- |
| `src/twswing/value/`（`loader.py` `factors.py` `screen.py`） | `me2/factors/`，去 `twswing` import |
| `scripts/fetch_fundamentals.py` | `me2/data/fetch_fundamentals.py` |
| `scripts/build_value_factors.py` | `me2/build_factors.py` |
| `.github/workflows/fundamentals.yml` | 拆成 `me2/build_factors.py` 的 `--refresh` 模式（本地排程跑，不做 Actions） |
| `data/fundamentals/*.parquet`（backfill 成果） | `me2/data/` |
| `tests/test_value.py` `test_fetch_fundamentals.py` `test_fetch_finmind_bundles.py` | `me2/tests/` |
| `fetch_finmind.py` 的 `financials/balance/cashflow/divpolicy` + `BUNDLES` + `--bundle` | `me2` 的 fetcher（`fetch_fundamentals.py` 已自足） |

**留在 tw-swing**（短波段在用，不動）：
- `src/twswing/data/fundamentals.py`（月營收動能 / PE 百分位 → Y 系規則）
- `scripts/fetch_finmind.py` 的 `per` / `revenue` / `dividend` datasets
- `daily_list.py` 的 `required_feature_sets` 基本面接線（Y4 用）
- `.gitignore` 的 `data/finmind/`

**複製到 me2 當參考**（tw-swing 保留原件）：
- `src/twswing/data/finmind.py`（FinMind client + 節流器）
- `src/twswing/indicators/`（`core` `ma_rules` `pivots` `trendlines` → 長波段 screener）
- `books/claude/me/taiwan-stock-analyzer-v3/data/price_adjuster.py`（還原股價）
- `books/claude/me/taiwan-stock-analyzer-v3/data/fetcher.py`（即時個股補抓）

**tw-swing STATUS 要改**：
- 〈tw-swing 當 me2 的上游〉整節作廢 → 改成「價值/定存已遷 me2，tw-swing 純短線/短波段」
- V1/V2/Y4 相關：Y4 的基本面接線留著（它是短波段）；價值因子庫的部分標「已遷出」
- 計畫表 row V 移除

---

## 11. 決定與待定（2026-09-07 使用者回覆）

**已定**：
1. **買入建議價 / 推薦判定** → 投信經理人視角，見 §6（forward EPS × 市況調整 PE
   〔空頭 15 / 中等 20 / 多頭 22〕→ 目標價 → 安全邊際 → 買入區間 → 明確 verdict）。
   定存區用殖利率法（§7）。
2. **即時補抓快取**（我決定）：`me2/data/cache/<ticker>/`（gitignore）。TTL：
   財報 30 天、逐日 PE 7 天、股價 1 天、月營收 7 天。每 ticker 一個 `_meta.json`
   記各資料的抓取時間。查詢時 stale 就重抓。
3. **F-Score 顯示**：9 分項當診斷清單（打勾/打叉），不加總、不當 verdict——**不算打分**。
4. **週更財報跑哪**（我建議、使用者授權我決定）：**跑本地**（Windows 工作排程
   或 app 內「更新」按鈕），不用 GitHub Actions。理由見 §8。**不開新 GitHub 帳號**。
5. **me2 上 GitHub**：要（同帳號新 repo）。M0 遷移後建。

**待定**（開工中再決）：
- **長波段參數**：純規則預設，還是拿歷史挑一次不尷尬的參數（不是 gate 校準）。→ M3 前。
- **產業逆風怎麼判**（§6.4 的「不推薦（品質）」有這條）：用同產業其他股票的
  營收/EPS 動能中位數當代理？→ M4 前。
- **repo 名稱**：`me2` 只是暫名。建 GitHub repo 時定（`tw-value`？`stock-advisor`？）。
