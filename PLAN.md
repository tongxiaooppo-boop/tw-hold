# tw-hold（暫名 me2）開發計劃

> `me`（`taiwan-stock-analyzer-v3`）的升級版。獨立專案，暫訂本地跑。定案日 2026-09-07。
> 這份是計劃，還沒開工。
>
> **架構最終版**（前面在「完全遷移／當上游」之間反覆過幾版）：**資料層共用——
> tw-swing 是上游，每週抓 FinMind 財報並整併成版控 parquet；tw-hold 讀那些 parquet，
> 做價值/定存/長波段的 domain 邏輯與 UI。**
>
> `me` 原始碼路徑：`d:\g\claude\books\claude\me\taiwan-stock-analyzer-v3\`（2026-09-07 目錄整理後）。

---

## 0. 一句話

本地跑的台股決策支援工具：**產出長波段 / 價值 / 定存三種推薦清單**（含買入建議價
或「不推薦」），且能**查詢單一個股**（不打分、用數據展開常見圖表；不在市值前 500
大的即時補 FinMind）。

---

## 1. 分工（2026-09-07 定案）

| | **tw-swing**（上游 + 自己的短線系統） | **tw-hold**（下游） |
| :--- | :--- | :--- |
| FinMind 抓取 | `fetch_fundamentals.py` + `.github/workflows/fundamentals.yml`（週跑 Actions）——**財報三表 + 股利只這裡抓一次** | 只做「查詢不在 500 大的個股」的即時補抓（量小、有快取） |
| 整併 parquet | `data/fundamentals/*.parquet`（版控） | **直接讀** `d:\g\claude\tw-swing\data\fundamentals\` |
| 資料層工具 | `twswing.data.finmind`（client + 節流器）、`twswing.value.loader`（parquet → 季度面板 + 45 天公告日遞延） | `import` 它們 |
| 月營收 / PE 特徵 | `twswing.data.fundamentals`（Y 系短波段規則也在用） | `import` |
| 因子 | — | `factors/`：Piotroski F-Score、normalized PE、FCF 殖利率、存股安全分（**從 `twswing.value.factors/screen` 搬來**、改 tw-hold native） |
| 篩選 / 建議 / UI / 圖表 | — | `screener/` `charts/` `app/` **全新寫** |
| 還原股價（500 大以外） | — | 移植 `me/data/price_adjuster.py` |

- **FinMind 一個帳號、一個 token**（`FINMIND_TOKEN` 環境變數）。tw-swing 週跑 + tw-hold
  即時查，排程錯開、都守 500/hr → 不撞。**不開新帳號**（配額綁 FinMind 帳號不是
  GitHub；一人多免費帳號有 ToS 風險）。真卡到 → 先改抓 TWSE 官方 OpenAPI（免費無時限）。
- tw-hold **不是**交易系統：不進資金池、不走 gate + 樣本外。決策支援而已。
- tw-hold **不碰** tw-swing 的 rules / pools / pipeline。

---

## 2. 三個推薦清單 + 個股查詢

### 2A. 推薦模式（三清單）

| 清單 | 邏輯 |
| :--- | :--- |
| **長波段**（2–12 週以上，使用者指定） | 自建多因子 screener（§5）+ 投信選股 rank（§6.1）+ §6 的估值/verdict |
| **價值** | F-Score ≥ 6 gate → 剔除價值陷阱 → Magic Formula rank(品質)+rank(便宜)（§6.4 詳）+ §6 的估值/verdict |
| **定存** | 參考 5 檔高股息 ETF：硬門檻 + 存股安全分 + 殖利率法估買價（§7） |

- 清單長度 **10–20**，限**市值前 500 大**（市值 = PBR × 股東權益 或 收盤 × 股本/10）。
- 每檔輸出：排序 + **量化理由** + **買入建議價** 或 **「不推薦」（明確原因）**。
- **先剔除、再排序**——價值/配息陷阱是硬門檻，不被其他分項高分蓋過。

### 2B. 個股查詢（不打分）

- 輸入代號 → **前 500 大**：讀 tw-swing 的 parquet；**不在**：即時打 FinMind 補那一支
  → 存 `tw-hold/data/cache/<ticker>/`。
- **不給評分、不給買賣 verdict**。給：原始數據表 + 常見圖表（§4）+ Piotroski F-Score
  9 分項當診斷清單（打勾/打叉，**不加總**）。
- 精神：攤開數據讓人 / AI 判斷，不代替判斷。

### 2C. AI 敘事層（選配，後期）

- 「複製給 AI」：數據 + 因子整理成文字 → 貼給 GPT/Gemini/DeepSeek 問產業趨勢、
  買入價、要不要投入。或整合 DeepSeek API（參考 `me/ai/analyzer.py`）。只傳整理過的數據。

---

## 3. 資料層細節

| 資料 | 誰負責 | 說明 |
| :--- | :--- | :--- |
| 財報三表 + 股利政策（整併 parquet） | tw-swing | tw-hold 讀 `tw-swing/data/fundamentals/{income,balance,cashflow,dividend}.parquet` |
| PER / PBR / 殖利率 | tw-swing（`fetch_finmind.py` 的 `per`） | tw-hold 讀 `tw-swing/data/finmind/per/`；估值「vs 自身歷史區間」要用（要不要請 tw-swing 整併成一張表，M2 前決定） |
| 日線股價（前 500，已還原） | tw-swing（`data/store/`） | tw-hold 讀 |
| 月營收 | tw-swing | `import twswing.data.fundamentals` |
| panel 組裝 | `twswing.value.loader` | `import` |
| 還原股價（500 大以外） | **tw-hold** | 移植 `me/data/price_adjuster.py`（除權息/減資/面額變更斷層）——填息計算、長歷史圖要用 |
| 個股即時補抓 | **tw-hold** | `import twswing.data.finmind` 的 client；`tw-hold/data/cache/<ticker>/`，TTL 見 §11 |

**M0 資料**：`tw-swing/data/fundamentals/` 已 backfill 前 500 大（2015Q1–2026Q2，
income/balance/cashflow 各 514 檔、dividend 511，共 ~3MB）——直接讀，不用搬。
（⚠️ `cash`／`capital_stock` 兩欄的補抓當掉了；tw-swing 下次週跑補，或先用 PBR × 股東權益算市值。）

---

## 4. 個股圖表清單（§2B；參考 `me/ui/waterfall_charts.py`，升級為互動圖）

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

## 5. 長波段 screener（tw-hold 自建）

- **持有 2–12 週以上**——比 tw-swing 的短波段（3–10 天）長一個量級，接近部位交易 / CANSLIM-lite。
- **進場條件**（多因子；指標運算複製 tw-swing 的 `core` / `ma_rules` / `pivots` / `trendlines`）：
  - 趨勢：站上季線且季線上彎 / 站上年線
  - 動能：近 8–12 週相對強度 > 大盤
  - 基本面順風：月營收 YoY 加速 或 季 EPS 成長 或 F-Score ≥ 6
  - 時機：回檔到均線/前高支撐未破，或 突破數週整理帶量
- **剔除**：下降趨勢 / 營收連續衰退 / 財務惡化
- **輸出**：清單 + 為什麼 + 建議進場區間
- **不回測、不進資金池**——參數用合理預設。（想驗有沒有效可之後拿 tw-swing 回測引擎另跑，加分不是前提。）

---

## 6. 選股 + 買入建議價 + 推薦判定（投信經理人視角）

> 使用者 2026-09-07：帶投信經理人的角度。核心是「找相對優秀的股票 + 用市況調整的
> PE 倍數估目標價」。這一節是**長波段**與**價值**清單共用的推薦引擎（選股邏輯各異、估值方法共用）。

### 6.1 選股：相對優秀（rank，不是絕對門檻）

投信看「現在這產業/這個池子裡，它算不算相對好的」。用分位數 rank。

| 面向 | 免費資料指標 |
| :--- | :--- |
| **營收動能**（台股投信最看重） | 月營收 YoY、YoY 加速度、近 3 月營收 vs 12 月均、創新高與否 |
| **獲利成長** | 季 EPS YoY、TTM EPS YoY、成長穩定度（連續幾季正成長） |
| **獲利品質** | ROE、三率走勢向上 |
| **財務體質** | Piotroski F-Score（≥ 5 才進 rank，< 5 直接不推薦） |
| **籌碼**（選配，之後） | 外資 + 投信近 N 日同買 |

- 長波段清單：上述 rank + §5 的技術時機
- 價值清單：上述 rank 偏重「品質 + 便宜」+ §6.4 的價值陷阱剔除

### 6.2 目標價 = forward EPS × 市況調整 PE

```
目標價 = forward_EPS × target_PE

forward_EPS = TTM_EPS × (1 + g)
g = clip( 0.5×(近4季營收YoY) + 0.5×(近8季EPS年化成長率),  -0.10,  +0.30 )
```

| 市況（複製 `twswing.data.regime`：MA200 + 60 日報酬 + 回撤） | 基準 target_PE |
| :--- | :--- |
| 空頭 `bear` | **15** |
| 中等 `chop` | **20** |
| 多頭 `bull` | **22** |

再依個股微調（各 ±20% 為限）：
- 成長溢價：g > 20% → ×1.15；g < 5% → ×0.85（PEG 精神）
- 自身歷史錨：基準 target_PE 高於「該股近 5 年 PE 的 80 分位」→ 拉回 80 分位
- 產業：金融/營建等資產型 → 改用 PB 估（forward_BVPS × target_PB，target_PB 分市況 0.8 / 1.2 / 1.5）

### 6.3 買入建議價：目標價打安全邊際，不追高

```
估值買價 = 目標價 × (1 − 安全邊際)     安全邊際 = 15%(chop) / 25%(bear) / 10%(bull)
技術買價 = max(季線, 近 20 週前低)
買入區間 = [ 技術買價 , min(估值買價, 現價) ]
```

### 6.4 推薦判定（明確、寫死）

| 條件 | verdict |
| :--- | :--- |
| F-Score < 5 / 營收連 3 季衰退 / EPS 連 2 季 YoY 負 / 產業逆風 | **不推薦（品質）** |
| 現價 ≥ 目標價 | **不推薦（已達目標價 / 高估）** |
| 買入區間上緣 < 現價 < 目標價 | **觀望（合理但無安全邊際）** |
| 現價 ≤ 買入區間上緣 | **推薦** ＋ 標買入區間、目標價、預期報酬 |
| 流動性不足（日均量 < 門檻） | **不推薦（流動性）** |

價值清單的 §6.4 補充剔除：毛利率 5 年趨勢向下 / 近 3 年 FCF 有 2 年以上為負。

### 6.5 展示

每檔推薦附：選股 rank 明細、forward_EPS 與 g 的推算、市況與 target_PE、目標價、
買入區間、預期報酬，及「不推薦」時的**確切原因**。

---

## 7. 定存區（殖利率導向，不用 target PE）

參考 5 檔高股息 ETF（00713 最像存股經理人）：

- **硬門檻**：近 4 季 EPS 每季為正 / 連續配息 ≥ 5 年無減配 / 近 3 年 FCF 覆蓋現金股利 /
  現金股利主要來自盈餘（非公積/減資）/ 負債比 ≤ 產業中位數 × 1.5
- **存股安全分**（rank 平均）：FCF 殖利率 + 價格低波動 + ROE 品質 + 填息率 +
  配息穩定度 × **景氣循環懲罰**（營收/毛利波動）
- **買入價（殖利率法）**：
  ```
  買入殖利率門檻 = max( 該股近 5 年平均殖利率 , 4% )
  估值買價 = 近 3 年平均現金股利 ÷ 買入殖利率門檻
  買入區間 = [ max(季線, 近20週前低) , min(估值買價, 現價) ]
  ```
- **推薦判定**：現價殖利率 ≥ 門檻 且過所有硬門檻 → 推薦；否則觀望 / 不推薦（原因）
- **揭露欄**：當期殖利率、近 3 年平均殖利率、殖利率 vs 5 年區間、產業

> §6/§7 的因子計算 tw-swing `twswing.value.factors/screen` 已寫好（F-Score、
> normalized PE、存股安全分、剔除門檻）——**M0 搬進 tw-hold**、改 native。市況分期
> `twswing.data.regime` 也複製一份（target PE 用）。

---

## 8. 技術棧 · repo

- Python 3.14、Streamlit、**plotly**、pandas、pyarrow、requests
- repo：暫 `d:\g\claude\me2\`（**建議改名 `tw-hold`**——跟 `tw-swing` 成對：swing 進出 /
  hold 抱著；不撞 `books/claude/tw-invest-suite-main`）。獨立 git，**推 GitHub**（同帳號新 repo）。
- **週更財報 = tw-swing 的 `fundamentals.yml`（Actions）在管**，不是 tw-hold 的事。
- `import twswing.data.finmind` + `twswing.value.loader` + `twswing.data.fundamentals`（資料層，共用）。
- 不要 gunicorn（Streamlit 內建）。

---

## 9. 分期 · **v1 目標：一個月內（使用者 2026-09-07）**

> **能，但有條件**（見 §9.1）。順序**刻意重排**：先把「三清單 + 買入建議」做完
> （核心交付），個股查詢頁擺後面——它是加分，真的來不及可以溢出一個月。

| # | 階段 | 內容 | timebox | 產出 |
| :-: | :-- | :--- | :--: | :--- |
| **M0** | 遷移 + 骨架 | §10：4 個檔搬進 tw-hold、repo 結構、讀 tw-swing parquet、最陽春價值/定存清單 | 1 session | 能跑、看得到兩清單 |
| **M1** | 長波段 screener | §5，第三清單。指標運算複製 tw-swing 的 `core`/`ma_rules`/`pivots`/`trendlines`。**純規則預設、不調參** | 2–3 | 三清單到齊 |
| **M2** | 推薦判定 | §6 選股 rank + forward EPS + 市況 PE + 目標價 + 買入區間 + verdict。**照 §6 寫死，不重議** | 2 | 清單有買入建議價 / 不推薦 |
| **M3** | 清單 UI + 匯出 | 篩選、排序、「複製給 AI」的文字格式 | 1 | 推薦模式完整 |
| **M4** | 個股查詢 | 代號 → 前 500 讀 / 不在則即時補 → 數據表 + 核心圖（K線、營收、EPS、三率、股利、**本益比河流圖**、F-Score 分項） | 3 | 個股頁能用 |
| — | M5 AI 整合 / M6 hosting | **v1 不做**。「複製給 AI」的文字格式在 M3 就夠 | — | 之後有興趣再說 |

**≈ 9–10 個 session。** 使用者一週 3 個 session、不發散 → 3–4 週，一個月內。

### 9.1 一個月內的條件（沒做到就會拖）

1. **這份 PLAN 凍結**，跟 tw-swing 的 pool1 一樣。**不再有架構討論、不再改因子設計、
   不再改估值公式**——要改記 backlog，v2 再說。
2. **M5/M6 明確不做**。
3. **圖表「夠用就好」**：`me` 的圖直接搬成 plotly，不重新設計。只有本益比河流圖值得做好。
4. **長波段 screener v1 = 規則 + 合理預設，零參數調校**。先出貨，refine 進 v2。
5. **估值引擎照 §6 逐條實作，不 re-litigate**。§6 的 spec 就是 spec。
6. **v1 允許粗糙**。這是嗜好決策支援工具不是產品，「會動、清單合理、個股頁能看」就是門檻。
7. tw-swing 的 11 月關鍵路徑（G-5、10 月分池揭露）**優先**——tw-hold 是 tw-swing 顧好之後的空檔工。

⚠️ 這場對話已經有過 ~4 次架構改判。一個月內做完的**最大變數不是工作量，是發散**。
PLAN 凍結是那個變數的解藥。

---

## 10. M0 遷移清單

**tw-swing → tw-hold**（搬走、從 tw-swing 移除）：

| tw-swing | tw-hold | 改什麼 |
| :--- | :--- | :--- |
| `src/twswing/value/factors.py` | `tw-hold/factors/factors.py` | import 改 `from twswing.value.loader import ...` |
| `src/twswing/value/screen.py` | `tw-hold/screener/screen.py` | 同上 |
| `scripts/build_value_factors.py` | `tw-hold/build_factors.py` | 讀 `d:\g\claude\tw-swing\data\fundamentals\` |
| `tests/test_value.py` | `tw-hold/tests/` | |

**留在 tw-swing**（共用資料層 or 短波段在用）：
- `src/twswing/value/loader.py`、`scripts/fetch_fundamentals.py`、`fundamentals.yml`、
  `data/fundamentals/`、`fetch_finmind.py`（含財報 bundle）、`test_fetch_fundamentals.py`、
  `test_fetch_finmind_bundles.py`
- `src/twswing/data/fundamentals.py`（月營收/PE → Y 系）、`daily_list.py` 的接線

**複製到 tw-hold 當參考**（tw-swing 保留原件；前兩個也可直接 import）：
- `src/twswing/data/finmind.py`（client）— 個股即時查
- `src/twswing/data/regime.py`（市況分期）— §6 target PE
- `src/twswing/indicators/`（`core` `ma_rules` `pivots` `trendlines`）— 長波段 screener
- `books/claude/me/taiwan-stock-analyzer-v3/data/price_adjuster.py`（還原股價）
- `books/claude/me/taiwan-stock-analyzer-v3/data/fetcher.py`（即時個股補抓）
- `books/claude/me/taiwan-stock-analyzer-v3/ui/waterfall_charts.py`（圖表參考）

---

## 11. 決定與待定（2026-09-07）

**已定**：
1. 買入建議價 / 推薦判定 → §6（投信視角：forward EPS × 市況 PE 15/20/22 → 目標價 →
   安全邊際 → 買入區間 → 明確 verdict）。定存區用殖利率法（§7）。
2. 即時補抓快取：`tw-hold/data/cache/<ticker>/`（gitignore）。TTL：財報 30 天、PE 7 天、
   股價 1 天、月營收 7 天。每 ticker 一個 `_meta.json`。
3. F-Score 顯示：9 分項打勾清單、不加總、不當 verdict → **不算打分**。
4. 週更財報：**用 tw-swing 的 `fundamentals.yml`（Actions）**，tw-hold 不管。
   個股即時查跟它排程錯開、守 500/hr。**不開新 GitHub / FinMind 帳號。**
5. tw-hold 上 GitHub：要（同帳號新 repo）。M0 後建。

**待定**：
- repo/目錄改名 `me2` → `tw-hold`：目錄被 IDE 鎖住，關掉編輯器再 `mv me2 tw-hold`。
- 長波段參數：v1 純規則預設（§9.1 條件 4）。要不要拿歷史挑一次 → v2。
- 產業逆風怎麼判（§6.4）：用同產業其他股票的營收/EPS 動能中位數當代理。→ M2 實作時定。
- PER/PBR/殖利率要不要請 tw-swing 整併成一張表（現在是逐檔）。→ M2 前（估值要用）。
