# tw-hold AI 解說層 — 設計備忘

> **狀態：設計，未實作。v2 的東西。** 這份把方向釘住，日後照著做。
> 起草 2026-09-08。相關：PRD §4.1（個股頁不打分）、§4.3（AI 敘事層）、§6.5（不做擇時）、
> §5.0–5.1（`me` 死因 + 四條守則）。參考實作見 §9。

---

## 0. 一句話

**AI 只解說規則已經算出來的東西、補規則抓不到的質化盲點；它不挑股票、不給 verdict、
不給買價、不排名。** 破了這條就是 `me` 復活。

---

## 1. 定位與紅線

| ✅ AI 可以 | ❌ AI 不可以 |
| :-- | :-- |
| 把三清單 / 個股頁的結構化結果講成人話 | 產生新的買賣清單 |
| 跨清單推理（「這檔同時在價值和長波段代表什麼」） | 合成「AI 分數」/ 給進場建議 |
| 解釋「為什麼這檔是觀望」 | 預測股價 / 報酬 |
| 檢索質化訊號（新聞、法說、供應鏈）當**盤前 context** | 把檢索到的訊息接進規則計算 |
| 永遠多空並陳 + 收在「會讓這個判斷失效的事」 | 只講一面、下結論 |

**規則層永遠凍結、可回測、point-in-time；AI 層是它上面的一層釉，剝掉不影響清單。**

---

## 2. 三層引擎（`reference/llm.py`）

抄 `books/claude/tw-stock-scanner-main/llm.py` 的三層自動降級：

```
① 本機 CLI headless   —— 騎訂閱、零 key、零 API 費用（僅本地進階模式）
     claude  -p "..." --output-format text       (Claude Pro/Max 登入)
     gemini  -p "..."                            (Google 登入，免費額度大)
     codex   exec "..."                          (ChatGPT 登入)
② BYOK API key        —— 使用者自己貼，按 token 付費（雲端 + 本地都可）
     Anthropic / OpenAI / Google，統一入口、各自 client
③ 「複製給 AI」        —— 現況，零依賴，永遠是最後的退路
```

- `generate(system, user) -> str | None`；`None` = 沒有可用引擎 → 呼叫端顯示「複製給 AI」。
- `engine_status()` 回報現在用哪一層 + 上次失敗原因（別只回「無引擎」）。
- 降級順序：① 有就用 ①（免費）→ 否則 ② 有 key 用 ② → 否則 ③。
- 本地優先偵測 CLI 是否存在且登入（`claude` / `gemini` / `codex` 在 PATH 且能跑）。

### 密鑰處理

- BYOK key 只進 **`st.session_state`**——不寫磁碟、不進 `st.secrets`、不 log、關分頁就沒。
- 「在這台裝置記住」= 選配，存 browser `localStorage`，明確警語（API key 存瀏覽器有風險）。
- 🔴 **誠實揭露**：key 在每次呼叫會經過 Streamlit 伺服器記憶體（app 是 server-side）。
  不儲存、但不是純前端。不信任 Streamlit 基礎設施就用 ① 或 ③。
- 這保住 PRD §8「雲端零密鑰」的精神——**伺服器上沒有我們的 key**。

---

## 3. 護欄（抄 `me/ai/analyzer.py` v4.0）

`me` 的 v4.0 改版已經踩過坑，直接沿用：

1. **AI 只看評分結果，不看原始未處理數據**——傳給 AI 的是規則算完的 dict（verdict、
   支持/反對、風險量化、因子值），不是原始財報 df。少了原料，它就編不出「我自己重算
   覺得應該買」。
2. **輸出 explanation 格式，不是 decision 格式**——prompt 明確要求「解說這個結果」，
   不是「給我建議」。降級回應也是 explanation 格式（不因為 AI 掛了就突然換口氣）。
3. **強制多空並陳**——每段解說都要有「支持這個判斷的」和「反對/風險」，比照長波段守則。
4. **收在失效條件**——每段以「什麼事會讓這個判斷失效」結尾。
5. **每個數字可追回來源**——AI 引用的數字都要對得上傳進去的 dict，前端能點回原始欄位。
6. **免責置頂**：「AI 沒有回測、會過度自信、可能把數字唸錯。它的話跟規則的 verdict
   一樣，都要你自己再查一次。」

---

## 4. 資料邊界：Tier 1（規則）vs Tier 2（解說）

| | Tier 1 · 規則層 | Tier 2 · AI 解說層 |
| :-- | :-- | :-- |
| 資料 | 只有 bundle（point-in-time 乾淨） | bundle 切片 + 規則結果 + **AI 自己的網路檢索** |
| 性質 | 凍結、可回測、公告日遞延 | 即時、會過時、標記為 context |
| 回饋 | — | **絕不回饋進 Tier 1**（不改因子、不改門檻、不進 verdict） |
| 失敗影響 | 清單算錯（有守門員） | 一段話不準（有免責、可切掉） |

**這條線是整個設計的骨架**：外部/質化資訊可以幫「讀頁面的人」，永遠不進「規則的計算」。

---

## 5. 功能形態（由貼合到外圍）

### 5.1 每頁「問 AI」助理 ✅ 建議先做
清單頁 / 個股頁一個輸入框，AI 只回答**當頁資料範圍內**的問題：
- 「定存清單裡填息率最穩的三檔」
- 「這 15 檔價值股，哪幾檔的便宜門檻靠 normalized EPS 撐（比較脆）」
- 「3293 為什麼被標產業逆風」

= 現在「複製給 AI」按鈕的內建版，資料預載、不用複製貼上。

### 5.2 個股頁 AI 敘事段落 🟡 要克制
個股頁底下一段：綜合三率趨勢 / 現金流 / 估值位置 / F-Score / 產業逆風 → 「這檔的多空面」。
⚠️ 文章有說服力——寫得好的「反對」跟「支持」會左右人。永遠兩面、永遠收在失效條件。

### 5.3 盤前 briefing 🟡 這是你問的「美國收盤 / 產業趨勢 / 資金流向」的落點
一天生成一次、快取，一段話：
- **美國收盤重點**（那斯達克 / 費半 / 關鍵權值股）→ 對台股電子權值的可能影響
- **法人 / 產業資金流向**（用 bundle 的 `chips.parquet` + `industry_headwind`）
- **對三清單持股的影響**（哪幾檔今天值得多看一眼）

明確標：「AI 網路檢索 + bundle，**非即時、非建議、盤前參考**」。生成一次的成本很低。

---

## 6. 外部 / 質化資訊的接入邊界

你問的「產業趨勢 / 美國收盤 / 資金流向」——分三類：

### 6.1 已經在手邊（不用接外部，把它做好就是）
| 訊息 | 來源 | 現況 → 可擴充 |
| :-- | :-- | :-- |
| **資金流向（法人買賣超）** | bundle `chips.parquet` | 個股圖已做 → 加「三大法人整體市場趨勢」「產業別法人淨流向」視圖 |
| **產業趨勢（動能）** | `screener/industry.py`（近 6 月報酬中位數） | 逆風旗標已做 → 擴成完整「產業動能排行表」 |

### 6.2 AI 檢索（Tier 2、重度免責、盤前 briefing 性質）
| 訊息 | 怎麼拿 |
| :-- | :-- |
| **美國收盤 / 費半 / 那斯達克** | AI 自己 web search（Claude/GPT/Gemini 都有搜尋）；或接免費行情源（stooq / yfinance） |
| **產業新聞 / 供應鏈消息** | AI web search per 產業 |
| **法說會 / 經營層變動 / 訴訟** | AI web search per 個股 |

原則：**AI 檢索的東西一律標「即時、可能錯、非建議」，只進 briefing 和「問 AI」的回答，
不進清單卡片臉上、不進任何欄位。**

### 6.3 明確不做
- 把美國收盤 / 新聞情緒 / 資金流向**接進規則計算**（改因子、改門檻、進 verdict）——
  那是擇時，PRD §6.5 已否決；也毀掉可回測性。
- 即時逐筆行情 / 盤中推播——tw-hold 是「一週看一次」的工具，不是看盤軟體。

---

## 7. MCP server 方案（替代 / 補充「問 AI」）

不想在 app 裡放 AI，就把 tw-hold 的資料開放給**你現有的 Claude / GPT / Gemini**：

- 做一個 MCP server，tool 大致：
  - `list_holdings(track)` — 回三清單之一的當季成分 + verdict + 依據
  - `explain_ticker(code)` — 回該檔的規則結果 + bundle 因子切片
  - `list_changes(track)` — 本季換股 / 候補變動
  - `industry_momentum()` — 產業動能排行
  - `institutional_flow(code | industry)` — 法人買賣超
- 資料來源：`data/derived/*.json`（公開 repo）+ bundle Release，MCP server 讀 GitHub raw 即可，工程量小。
- 消費端支援度：**claude.ai 連接器成熟 > ChatGPT connectors（付費層、開發者模式）> 消費版 Gemini（走 CLI）**。
- 好處：app 裡零密鑰、用訂閱零額外費用、對話在 claude.ai（比嵌入式小框好用）。
- 代價：AI 體驗不在 tw-hold 頁面內。

**「問 AI」和 MCP 不互斥**——可以都做，或先做 MCP（成本低、不碰 app）。

---

## 8. 成本與失敗模式

| 失敗 | 處理 |
| :-- | :-- |
| API 掛 / 額度用盡 | 降級到下一層 → 最後「複製給 AI」；`engine_status()` 講清楚 |
| 幻覺 / 唸錯數字 | 護欄 §3.5（可追回來源）+ 免責置頂；敘事段落永遠附原始數字表 |
| BYOK key 外洩 | session-only、不 log；localStorage 記住是選配 + 警語 |
| 檢索到過時 / 假新聞 | Tier 2 一律標「即時、可能錯」；不進任何欄位 |
| LLM 成本失控（BYOK） | 使用者自己的帳單；app 端設每 session 呼叫上限 |
| 破「雲端零密鑰」 | 本機用 ① 完全不碰；雲端 BYOK 只在記憶體、不落伺服器 |

---

## 9. 參考實作

| 檔 | 學什麼 |
| :-- | :-- |
| `books/claude/tw-stock-scanner-main/llm.py` | 三層降級（API → CLI headless → None）、`engine_status` |
| `books/claude/tw-stock-scanner-main/apikey.py` | key 統一讀取（env / config / secrets），tw-hold 改成 session_state |
| `books/claude/me/taiwan-stock-analyzer-v3/ai/analyzer.py` | v4.0 護欄：只看結果不看原料、explanation 不 decision、降級也守格式 |
| `books/claude/me/taiwan-stock-analyzer-v3/ai/prompts.py` | `build_system_prompt` / `build_evidence_json` 的分工 |
| tw-swing skill `tw-swing-solicit-strategies` | 給外部 AI 的簡報怎麼寫（已測過的黑名單、DSL、輸出格式） |

---

## 10. 分期建議

| 期 | 做什麼 |
| :-- | :-- |
| **現在（v1）** | 維持「複製給 AI」。不動。 |
| **v2-a** | `reference/llm.py` 三層 + 每頁「問 AI」助理（§5.1）+ 護欄（§3）。本機騎訂閱、雲端 BYOK。 |
| **v2-b** | 盤前 briefing（§5.3）：美國收盤 + 法人/產業流向 + 對清單影響。AI 檢索、重度免責。 |
| **v2-c** | MCP server（§7），或個股頁敘事段落（§5.2，看 v2-a 的克制程度）。 |
| **不做** | AI 選股、AI 分數、外部訊息進規則、盤中推播。 |

---

## 11. 2026-09-09 討論定調（多軌體檢上線後）

> **優先序：主架構先做穩、讓朋友測；AI 層不急。** 下面是想清楚了、日後照做的方向。

### 11.1 證據包 = 多軌體檢的輸出（不用另建）

`app/checklist.py` 的 `{short,swing,value,deposit}_checks(d)` + `summarize()` 產出的
「項目／門檻／現值／狀態」＋「未達門檻／待確認／風險命中」，**就是要餵給 AI 的東西**
——剛好命中 §3.1「只看規則結果、不看原始財報」。

- 抽 `checklist.evidence_packet(d, fv, fd) -> dict | markdown`：把四軌 rows + summaries
  + `factors_*` 的 verdict / cheap_threshold / flags 組成一包。
- **一次寫、三處用**：①「複製給 AI」的內容 ② app 內 AI 呼叫的 payload ③ 未來 MCP tool。

### 11.2 AI 的最佳任務 = 失效條件匹配（不是情緒分數）

情緒分數雜訊高、又會變成 de-facto 因子。真正有價值的問法：
**「這幾則新聞，有沒有具體踩到某條判準的失效條件？逐條對應，沒有就說沒有。」**
（多軌體檢的 `未達的門檻` / `風險命中` 摘要正好當對照清單。）

固定三段 prompt：① 四軌結論講人話 ② 新聞逐條對失效條件 ③ 收在「什麼會翻盤」。

### 11.3 AI 的存在理由 = 補「規則的時間差」

規則是公告日遞延（PIT），可能還看著 Q2 財報。新聞 + 月營收快報是即時的。
AI 的獨門價值＝橋接這個 lag（「規則建立在 Q2，但 9 月營收 + 這則新聞顯示 Q3 轉弱」）。

### 11.4 引擎：三種形態，手動選（不靜默降級）

一個 radio：`複製 / 用我的 API key / 本機 CLI`，用不到的灰掉 + 寫原因。哪個 AI 分析的要看得到。

| 形態 | 說明 | 環境 |
| :-- | :-- | :-- |
| 複製給 AI | 顯示 `evidence_packet` + 新聞 + 三段問題，零依賴 | 都可 |
| BYOK API key | 使用者貼 key，`st.session_state` only（§2 密鑰處理） | 雲端 + 本地 |
| 本機 CLI headless | `claude -p` / `gemini` / `codex`，騎訂閱免費 | **僅 `LOCAL_ADVANCED`** |

**BYOK 函式庫只要兩個**：
- `openai` SDK（改 `base_url`）一次吃 **GPT + DeepSeek + Gemini**（Gemini 有 OpenAI 相容端點）
- `anthropic` SDK 吃 Claude
- DeepSeek 最便宜（`deepseek-chat`），設預設。

**選模型 = 混合式**：貼 key 當下呼叫一次 list-models（同時當金鑰驗證）→ 過濾
chat 能力 + 合理家族白名單 → **便宜的排最前標「推薦」**（haiku / flash / mini /
deepseek-chat）→ list 失敗退回寫死 shortlist → 結果存 `session_state` 不重抓。
四家都有 list models 端點（OpenAI 那份最吵、要用名稱前綴過濾）。

**MCP server 另列**（§7）——不是「第 3 層」，是「乾脆不把 AI 放進 app」的替代路線。

### 11.5 新聞：on-demand RSS，標題為主

- **個股查詢頁（任意檔）**：點進去才即時抓 RSS（Google News 關鍵字 + 鉅亨 + MOPS 重大訊息），
  **只顯示標題 + 連結**，`st.cache_data(ttl≈30min)` keyed by code，沒 AI 也能看。
- **清單股（holdings + candidates ≈ 50–80 檔）**：CI 每日批次抓 + 情緒 → `data/derived/news.json`。
- **盤前 briefing**：port `books` 的 `tw-stock-scanner-main/morning_brief.py`（隔夜美股 yfinance
  + 隔夜新聞 RSS + Claude 逐則評論 + 行事曆，無引擎退化成純數據）。CI 批次、repo secret。
- 參考框架：`tw-stock-scanner-main` 的 `fetch_news.py` / `analyze_news.py`（Haiku 批次
  15 則/請求 + prompt caching）/ `llm.py` / `apikey.py`。**不要用 `me/news` 的 SnowNLP**（財經很不準）。

### 11.6 落點：全放「個股查詢」（使用者要一站式）

個股查詢：圖 → 最近新聞（標題列）→「AI 解說」按鈕（帶 `evidence_packet` + 新聞）。
多軌體檢維持純判準深看，底部放同一顆 AI 按鈕（共用 `evidence_packet`）。兩頁已有互跳鍵。

### 11.7 紅線（不變，再強調）

- 傳給 AI 只有 `evidence_packet`（規則結果），**永不傳原始財報 df** → 不然它自己重算跟規則吵 = `me` 復活
- 新聞情緒**不給數字、不上頁面欄位、不上卡片** → 只在 AI 散文和標題列
- AI 輸出 display-only：不寫 `data/derived`、不回饋任何 checklist 狀態
- prompt 是 explanation 格式；三段固定；換引擎不換口氣

### 11.8 待確認

- 使用者提到「之前幫忙做的 Gemini 選 key 模式」參考專案——**路徑未定，等使用者給**，再對齊 UI / 存 key 寫法。
