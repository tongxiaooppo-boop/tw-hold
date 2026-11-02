# P4 規格：畫面（Opus 定，2026-11-02 深夜；實作者不得改本檔、骨架介面與測試預期值）

範圍：個股頁估值速覽改讀 `val_card.build_card`、三個展開區（§9-1／9-2／9-3）、河流圖與體檢本益比改自建（§15-4）、刪舊引擎與舊畫面、全站改名（§15-1／15-2）。
規格以 `upgrade_guide.md` §9、§13、§15 為準；本檔只補「怎麼接」的決定。沒寫到的舊行為一律維持。

分三小步，**依序做、每步全套測試過才進下一步**：

| 步 | 內容 | 測試 |
|---|---|---|
| **P4a** 引擎補欄＋畫面資料層 | §1 val_card 補兩欄、§2 `val_inputs`、§3 `val_view`、§4 `river`、§5 `hist_position` | `test_val2_p4.py` 的 P4a 段 |
| **P4b** 接到 streamlit | §6 改 `_valuation_block`／河流圖／體檢、§7 刪舊 | `test_val2_p4.py` 全部、`test_consistency` 改寫 |
| **P4c** 全站改名 | §8 | `test_glossary.py` |

## 0. 架構決定（Opus）

| 決定 | 內容 | 理由 |
|---|---|---|
| 卡片即時算 | app 在個股頁呼叫 `build_card(..., asof=今天台北日期)`，不預先算全市場卡片 | 全市場卡 8 MB，每天進 git 太肥；單檔 build_card 約 0.2 秒 |
| 輸入集中 | 新模組 `app/val_inputs.py` 組 build_card 參數；**乾跑腳本與 app 用同一支**（不准兩套組法） | 避免 app 和乾跑的卡片不同 |
| 倍數檔位置 | 讀 `data/derived/multiples_hist.parquet`、`eps_revision.parquet`、`industry_pe.json`。怎麼送上雲端是 P5 的事（rebuild.yml＋gitignore 例外） | P4 只在本機驗 |
| 倍數檔缺 | 不呼叫 build_card，卡片位置寫 `MSG_NO_MULTIPLES`（不能讓全部掉到 B 層） | 缺檔時 build_card 會把每檔當 0 個有效月 |
| 排版與算數分開 | `app/val_view.py`：card dict → 字串與表格（純函式、不 import streamlit／pandas／numpy、不做四則運算）；`streamlit_app.py` 只負責畫 | `test_畫面不自己算`、`test_glossary_同名同源` 可以直接測 view |
| 格式化唯一來源 | 估值畫面所有數字只准經 `val_view.fmt_*` 格式化 | §9-3 同值同字 |
| 停損大量區 | 算法不動：`valuation.risk_levels(px)`、`hold_stop(px)`（px 用還原價，照舊）。「可買」改成「現價在新購買區間內（low ≤ 現價 ≤ high）」；不在區間 → 週線持股停損 | 舊的「買進區間停用中」是等分類完成的暫置，2.0 的購買區間就是它要等的東西 |
| `valuation.py` | 不刪：月營收分頁（封印中）還在用 `estimate`。個股頁不再呼叫 `va.estimate` | 月營收解封時再改讀 build_card |
| 體檢 PB 分位 | 跟 PE 一起改讀 `multiples_hist`（自建） | §15-4 只寫 PE；同一張表一個自建一個交易所，會被抓口徑不一致 |
| 匯出 | 個股頁估值卡目前沒有「複製給 AI」，P4 不新增；`同名同源` 只比卡片與展開區 | — |

## 1. `screener/val_card.py` 補兩欄（P4a；`build_card` 回傳多兩個 key）

| key | 內容 |
|---|---|
| `nonop_hist` | 近 8 個已公布季（`eps_windows.NONOP_QUARTERS`，同試算取法：最近 8 個有實際財報的季）每列 `{"q": "2026Q2", "nonop": pretax−op_income, "pretax": pretax_income}`，舊→新；任一值非有限的季照列、值給 None。外加 `nonop_median`（float｜None）＝與 `eps_windows._estimate` 同一個中位數（有效 <4 季 → None）。所有層都給（D 層財報 <4 季給 `[]`／None） |
| `revision["last_event"]` | `rev_hist` 依 month 排序最後一列的 `event`（"normal"／"roll"／"report"）；沒有 rev_hist → None。`revision_streak` 本身不改 |
| `buy_range["where"]`、`buy_range["gap"]` | where＝"below"（現價 < low）／"in"／"above"（現價 > high）／None（沒現價）；gap＝above 時 現價 ÷ high − 1、below 時 現價 ÷ low − 1、其餘 None（demo「現價高於上緣 +230%」，畫面不准自己除） |
| `fwd_note` | 前瞻三價那格的短句（demo：前瞻沒有時也要有字）。fwd_prices 有值 → None；tier ≠ A → None；否則依序：試算停用 `FWD_NOTES["est_off"]`、route PB `["pb"]`、循環或高獲利區 `["cyclical"]`、前瞻季＝近 4 季 `["same"]`、前瞻窗口不 ok `["window"].format(reason)`、前瞻 EPS < EPS_MIN `["thin"]`、前瞻有效月不足 `["hist"]`。常數見骨架 |
| `b_tier` 多 `n_valid`、`n_loss`、`window` | B 層從 build_card 內部的 pe_stats 帶出（與 prices 同名欄位同義）；📊 的「有效月數／虧損月數／倍數期間」B 層讀這裡，A 層讀 prices。C／D 層沒有就**省略這幾列**（不寫「—」）。（P4a sol 回報後 Opus 補，11/2 深夜） |
| `nonop_hist` 每列 `share` | nonop ÷ \|pretax\|（pretax 0／缺 → None），「占稅前」欄用 |

- `CARD_VERSION = "card-v4-val2"`。模組 docstring「回傳欄位」補這兩項。
- `tests/test_val2_card.py` 的 `FIELDS` 由 Opus 在框架 commit 補上 `nonop_hist`、`nonop_median`（實作者不用動）。
- 業外中位數抽成 `eps_windows.nonop_median(actual_rows) -> float | None`，`_estimate` 與 val_card 共用（不准兩份算法）。

## 2. `app/val_inputs.py`（P4a；新檔，介面見骨架）

- `card_inputs(code, asof) -> dict`：回傳 `build_card` 的關鍵字參數（qf, rev, px, cls, mh, rev_hist, industry_pe, asof），或 `{"missing": "..."}`。
  - qf：bundle 的 income／balance／cashflow → `loader.merge_statements(inc, bal, cf)`（預設 how="outer"，**跟 loader.load_quarterly 一樣**）→ `disclosure_date = period_end + 1 天`（live）→ `corporate_actions.adjust_eps`。**不用** `factors.quarterly_factors`。
  - px：bundle `prices_raw_close.parquet`（原始收盤，date／close），只留 date ≤ asof。
  - rev：`bundle_data.revenue(code)`。cls：`stock_class.json` 該檔（沒有 → None，build_card 自己給 D）。
  - mh／rev_hist：`data/derived` 兩個 parquet 篩該檔（用 pyarrow filters，不整檔讀進記憶體再篩）；industry_pe：`industry_pe.json` 的 `industries`。三個檔任一不存在 → `{"missing": MSG_NO_MULTIPLES}`。
- `scripts/val2_dryrun_cards.py` 改用 `card_inputs` 組參數（乾跑來源目錄可用參數指到 `_dryrun/`）。
- 驗收：12 檔（2330 2327 2881 5289 1815 2317 2454 6505 2603 2002 1101 3008）app 路徑卡片 == 乾跑卡片（json 全等，`version` 除外）。

## 3. `app/val_view.py`（P4a；新檔，介面見骨架，所有函式的行為寫在 docstring）

### 3-1 卡片（**版面照使用者認可的 demo**：https://claude.ai/artifact/6iHMWkFFqd1ACXkopJyPWW ，HTML 副本 `docs/val2/card_demo.html`）

view 回傳結構化資料（`PriceCard`、`EpsCard`，見骨架），streamlit 端照 demo 的 HTML／CSS 畫（大字現價、三價三格、位置色塊、label＋去處提示、EPS 卡左標題小字副標右數值、年增率表）。CSS 併進現有 `_CSS`，色用 `:root` 既有變數（北歐靜謐主題，不搬 demo 的色碼）；位置色：便宜區 good、合理區 mid、昂貴區 bad。

**股價卡 `PriceCard`**

| 欄 | A 層 PE | 其他情況 |
|---|---|---|
| `head` | `股價`，副標 `{代號} {股名}｜{display_type}` | 同 |
| `price`、`price_sub` | `fmt_px(price)`；`現價（MM/DD）` | 沒現價 → `—` |
| `tri_label`、`tri_hint` | `三價（相對自身歷史）`；`推導見 🔍 ③` | PB：`三價（相對自身股價淨值比歷史）` |
| `tri` | 三格 (便宜價, a)、(合理價, b)、(昂貴價, c) | 沒有三價 → None |
| `tri_note` | None | **一定有字**：`{price_note}，詳見 📊 估值定位細節` |
| `pos` | (位置名, tone)：cheap→(便宜區, good)、fair→(合理區, mid)、dear→(昂貴區, bad)；na → None | None |
| `base_text` | `基準：近 4 季 EPS 98.73 元`；較低獲利情境：`基準：較低獲利情境 11.45 元（3 年平均 11.45；近 4 季 16.79）`（3 年平均 None 寫「—」）；PB：`基準：每股淨值 52.30 元` | None |
| `extra` | 金融：`ROE 12.3%（近 4 季）` | B：`現價本益比 X 倍｜同產業排名 p%（n 家）｜反推 EPS 門檻 Y 元`（缺的段省略）；C：`c_tier.text` |
| `buy` | (`2,034～2,592`, `{狀態}｜{位置}`)：狀態 normal＝`一般`、fwd_up＝`前瞻上調`；位置 in＝`現價在區間內`、above＝`現價高於上緣 +230%`、below＝`現價低於下緣 -5%`（% 用引擎 gap）；label `購買區間`、hint `推導見 🔍 ④` | buy_range None → None（整段不畫） |
| `fwd_tri`／`fwd_note` | 有前瞻三價 → 三格；否則 `fwd_note`（引擎短句）。label `前瞻三價（相對自身前瞻倍數）` | tier ≠ A → 兩者皆 None（整段不畫） |
| cls None（不在範圍） | — | 只有 head、price、`tri_note="不在估值範圍"`；`CardView.full=False`：EPS 卡、展開區都不畫 |

**EPS 卡 `EpsCard`**（`kv` 每列＝(標題, 小字副標, 數值)）
1. (`近 4 季 EPS`, `2025Q4～2026Q3，含 1 季試算`／`…，4 季皆已公布`／`…，試算停用：原因`, `98.73 元`)。
2. 前瞻：有值且季別≠近 4 季 → (`前瞻 4 季 EPS`, `2026Q1～2026Q4，含 n 季試算（{上修文字}）`, `X 元`)；季別＝近 4 季 → (`前瞻 4 季 EPS`, `新季營收未出（{上修文字}）`, `＝近 4 季`)；fwd None → 數值 `—`，副標依 eps.fwd 狀態寫 `財報延遲`／`新季營收未出`／`試算停用：原因`，不合併成「退回」。
3. 上修文字 `revision_text(rev)`：last_event roll → `窗口更換，本月不比較`；report → `改用財報，本月不比較`；streak≥1 且 direction up/down → `比上月 +3.1%，連續上修 n 個月`／`連續下修`；last_pct 有值但 streak 0 → `比上月 +0.4%`；其餘 `比上月持平`。不顯示 0%。
4. `growth_label`＝`年增率（對去年同期）`；`growth_table` 三欄「期間｜營收｜EPS」（`kind="grid"`）：

| key | 期間欄 | 營收 | EPS |
|---|---|---|---|
| month | `最新月（09 月）` | rev.text | `—` |
| last_q | `2026Q3（試算；營收已公布 3 個月）`；actual 寫 `2026Q2（財報）` | rev.text | eps.text |
| ttm | `近 4 季` | rev.text | eps.text |
| fwd | `前瞻 4 季` | `—` | eps.text |
文字一律用引擎的 `Growth.text`，view 不自己組百分比。

`pins`（卡片標籤 → 卡片上的字，同值同字測試用）：`近 4 季 EPS`、`前瞻 4 季 EPS`（有數值才放）、`基準`（A 層）、`便宜價`／`合理價`／`昂貴價`（有才放）、`前瞻便宜價`…（有才放）、`購買區間`（`lo～hi`）、`反推 EPS 門檻`（B 層有才放）。數值字串不含「元」（`98.73`），卡片顯示時再接單位。

`coverage_line(meta)`：`coverage_mktcap_k` ≥ `COVERAGE_MIN_K`(100) → `估值涵蓋市值前 K 大（共 N 檔）`；否則或缺 → `估值收錄 N 檔`；N 也缺 → `""`。

`asof_line(card)`：`財報 {最新實際季}｜月營收至 {growth month 的 period}｜股價 {px_date}　｜　試算不是預測、不是目標價`（缺的段落省略）。

### 3-2 展開區（每區第一列都是圖例 `PIN_LEGEND`，用 `legend_row()` 產生）

| 函式 | 表 |
|---|---|
| `detail_tables(card)` 📊 | 一張 kv：分層（`A 層：自身歷史倍數足夠`／`B 層：自身歷史太短，看產業`／`C 層：…`／`D 層：{reason}`）、估值方法（本益比／股價淨值比）、類型（display_type・state・subtags）、分類原因（why）、可信度四組（`資料：正常`，非正常列出 items 的 name＋why；停用寫「停用了哪個窗口或方法」＝item.why）、有效月數 n_valid／虧損月數 n_loss（分兩列）、倍數期間 window、ROE（有才列）、營業現金流 ÷ 淨利、應計比率、備註（notes）、樣本（存活者偏差；分類基準 class_asof；版本 version）。**不放推導、不放三價** |
| `explain_tables(card)` 📐 | 一張 kv「項目｜規則」：名詞（近 4 季 EPS／前瞻 4 季 EPS／試算）、三價、倍數窗（一般 60 月／高成長 36 月／股價淨值比全歷史；有效月條件）、分層 A～D、購買區間（normal／fwd_up 規則、上修 ±2% 連續 2 次）、較低獲利情境（循環股）、反推 EPS 門檻、可信度四組、已知限制（§13 五條各一列）、`規則未經驗證，情境估算，非買進建議`。**不放這檔的任何數字**（常數門檻如 20%、2% 可以）；PB 路線把本益比相關列換成股價淨值比版本 |
| `trial_tables(card)` 🔍 | 照 demo 的四段寫法，依序：**① 窗口表**（季｜實際／試算｜EPS（元）；近 4 季 4 列＋`近 4 季合計` 📌；前瞻：與近 4 季相同時一列 `前瞻 4 季｜新季營收未出 → 與近 4 季相同`，否則另列前瞻 4 季與合計 📌）**② 每個試算季一張推導表**（標題 `2026Q3 試算`，近 4 季與前瞻共用加 `（近 4 季、前瞻 4 季共用）`，只畫一次；列序照 demo／§9-1：`07 月營收`…、`＝ 季營收`、`×（毛利率 − 營業費用率）`、`＝ 營業利益（試算）`、`＋ 業外`、`×（1−稅率）×（1−少數股權比）`、`＝ 歸母淨利（試算）`、`÷ 股數`、`＝ 試算 EPS`；flags 進來源欄）**③ 三價推導**（`倍數窗`（window｜`近 36 個月（高成長），自建本益比`）、`有效月數`（`36／36`｜`門檻 30 個月`）、`基準 EPS` 📌（＝卡片『基準』）、`× 歷史 20% 位置本益比`（`只有 20% 的月份比這更低`）、`＝ 便宜價` 📌、50%（`中位數`）、`＝ 合理價` 📌、80%、`＝ 昂貴價` 📌；截斷時倍數列來源寫 `原始 X 倍，上限 Y 倍截斷`；PB 換字；有前瞻三價再一張 `③-2 前瞻三價推導`）**④ 購買區間**（`下緣`｜值｜`見 ③ 便宜價`；`上緣`｜值｜`見 ③ 合理價；前瞻沒有連續 2 個月上修 → 不改用前瞻合理價` 或 `見 ③-2 前瞻合理價；前瞻連續 n 個月上修`；`購買區間` 📌，來源 `＝卡片『購買區間』；{位置}`）**⑤ B 層**：`反推 EPS 門檻`＝現價 ÷ 產業中位本益比（📌）**⑥ 近 8 季業外**（標題 `近 8 季業外（中位數 X 億，用在試算）`，欄：季｜業外｜稅前｜占稅前，占稅前用引擎 `share`）。窗口表與 ③ 之外的推導列，數值欄 `num` 對齊；📌 列整列底色（demo `tr.hl`）＝`VTable.hl` 列號 |

⑦ 停損與大量區：不在 view，沿用 streamlit_app 現有表格程式，只改名（§15-2：`週線進場停損`、`週線持股停損`、`大量區支撐`、`大量區壓力`）與 §0 的可買條件。

📌 規則（§9-3）：被標的列「數值」欄＝`f"📌 {卡片上的字}"`、「來源／假設」欄＝`f"＝卡片『{標籤}』"`；同一個數字在三個展開區合計只標一次（在 🔍）。其他地方要引用寫「見 🔍 試算細節」。

### 3-3 資料型別

**三個展開區全部是表格**（使用者 11/2 深夜再確認，附舊版「試算細節」推導表截圖）：一律用現有 `_vtable`／`_kv_table`（.thc-vt 樣式、字級、手機把來源收到步驟下），不寫段落、不搬 demo 的表格 CSS；demo 只決定列的內容、順序與 📌。每個小節標題（① 窗口表、② 2026Q3 試算…）用 `**粗體**` 一行，跟舊版「2026Q3 推算推導表」同位置。📌 列底色加在 `.thc-vt tr.hl`（新增一條 CSS，桌面＋手機截圖確認）。

`VTable(title, kind, headers, rows, hl)`（hl＝要整列底色的列號，📌 列與「＝ 試算 EPS」列）：kind ∈ `"derive"`（步驟｜數值｜來源／假設）／`"kv"`（項目｜內容）／`"grid"`。rows 每格是 str（多行用 `\n`）。streamlit 端：derive → `_vtable(headers, rows, {1}, {2})`（手機來源收到步驟下）、kv → `_kv_table`、grid → `_vtable(headers, rows, 數字欄)`。

## 4. `screener/river.py`（P4a；新檔，§15-4）

`river_frame(q, px_raw, mh, card, ticker, asof) -> dict`（介面與回傳見骨架）：
- 股價：原始收盤 ÷ `share_basis.share_factor_after(ticker, t)`（不含息）；`share_factor_after` 對每個日期算太慢 → 依事件日切段向量化，結果須與逐日呼叫相同。
- PE 路線：EPS 階梯＝每個月底 t 的 `eps_windows.reported_window(q, t, live=False).eps`（當時可見的已公布 4 季；不 ok → NaN），日線向前填。PB 路線：每股淨值＝mh 的 `bvps` 月底值向前填。
- 河道：`base × card["prices"]["mults"]`（截斷後倍數，三條）；`card["prices"]` 為 None 或任一倍數 None → `lines=None`、`reason`＝`card["price_note"]` 或 `"沒有估值倍數"`。
- 圖例：PE `已公布 4 季 EPS × 歷史 20%／50%／80% 本益比`；PB `每股淨值 × 歷史 20%／50%／80% 股價淨值比`。`note`：PE 路線且 card 的 `prices.base_name` ≠ 已公布 4 季 → `估值卡三價用{base_name}，河道用已公布 4 季 EPS，兩者可能不同`。
- `stockcharts.pe_river(fr, name, start)` 改吃 river_frame 的結果畫圖（不再收 px／per）；lines None → 只畫股價與 EPS（右軸），標題寫 reason。

## 5. `screener/multiples_self.py::hist_position`（P4a）

`hist_position(mh, metric, asof, months) -> dict | None`：取 `month ≤ last_complete_month(asof)` 且 `valid_{metric}` 的列；`months` 不是 None 時只取最近 `months` 個完整月（以月份計，不是列數）；沒有列 → None。`now`＝最後一列值、`pct`＝(值 ≤ now 的列數) ÷ 列數、`n`＝列數、`month`＝最後一列 month。

體檢（`app/checklist.py` swing_checks「估值位置」）：asof＝`d.get("asof")`，沒有就今天台北日期；讀 `d["mh"]`（`_stock_data` 新增，`val_inputs.load_mh(code)`；缺檔＝空表）。PE：`hist_position(mh, "pe", 今天, 60)`，項目名 `本益比歷史位置（自建）`、門檻 `近 5 年分位 ≤ 40%`、現值 `本益比 15.3 倍（分位 35%）`（倍數一位小數、分位整數）；PB：`hist_position(mh, "pb", 今天, None)`，`股價淨值比歷史位置（自建）`、`全歷史分位 ≤ 40%`、現值 `股價淨值比 2.00 倍（分位 100%）`。缺 → 狀態「— 無資料」。不再讀 `per`／`pbr`。

## 6. 接到 streamlit（P4b）

- `_valuation_block(d, label, code)` 重寫：`val_inputs.card_inputs` → missing 就 `st.caption(MSG_NO_MULTIPLES)` 收工 → `build_card`（例外 → 「估值卡算不出來：{型別}: {訊息}」）→ `val_view` → 畫。版面沿用現在的兩欄（股價卡在前、EPS 卡在後，手機股價卡在上）、`key="valcards"`／`valcard_px`／`valcard_fin`（CSS 靠這些 key）。標題 `#### 💰 估值速覽`＋下一行 `coverage_line`（讀 `stock_class.json` 頂層）＋ `asof_line`。「開發中」字樣 P4 先保留（P5 才拿掉）。
- 展開區標題：`📊 估值定位細節`、`📐 怎麼算`、`🔍 試算細節`（⑦ 停損與大量區放在 🔍 最後）。`full=False` 時不畫展開區。
- 河流圖：`_chart(ch.pe_river, river.river_frame(...), name, start)`，需要的 card 用同一次 `_valuation_block` 算出的（存在 `st.session_state` 或改成 `_valuation_block` 回傳 card 給 `_stock_page`；**不准算兩次**）。
- 體檢：`_stock_data` 加 `"mh"`。

## 7. 刪除（P4b）

| 刪 | 備註 |
|---|---|
| `screener/eps_nowcast.py` 整檔、`tests/test_eps_nowcast.py` 整檔 | 刪前 grep 確認沒有別的 import（`app/`、`screener/`、`build_*.py`、`scripts/`、`tests/`）；有就停下回報 |
| `tests/test_bug4.py` 裡 import eps_nowcast 的測試 | 其他測試留著 |
| `tests/test_val_card.py`（card-v2 舊測試） | 確認全檔測的是已不存在的舊介面再刪；混有新介面測試就停下回報 |
| `streamlit_app.py`：`_NC_KIND_TEXT`、`_card_explain_rows`、`_render_explain`、`_card_lines`、`_card_detail_rows`、`_card_block`、`_mult_text`、`_eps_quarter_tables`、`_card_eps_lines`、`_buy_lines`、`_risk_lines`（若只剩舊估值用）、`_POS_ZH` | 用函式名找，不靠行號；`_px`、`_kv_table`、`_vtable`、`_stock_class*` 留著（別處也用就留） |
| `tests/test_valuation_text.py` 的 `_buy_lines`／`_risk_lines` 測試 | 週 ATR 序列、最近一次跌破這類測 `valuation.py` 算法的保留 |
| `tests/test_consistency.py` 5 條 skip | 改寫成測 `val_view`（同一概念同一字串），或確定已被 `test_val2_p4` 取代就刪並在回報列出對應 |

## 8. 全站改名（P4c）

- 依 `upgrade_guide.md` §15-1、§15-2「統一寫法／禁用」改 `app/`、`screener/`、`build_*.py` 的**畫面文字**（非 docstring 的中文字串）。不改算法、不改 schema 欄名、不改 JSON key。
- `tests/test_glossary.py`（框架已寫好禁用清單與掃描法）全過。白名單只准放程式內部訊息（log、例外訊息），每條註明理由；月營收封印頁（`_rev_view_value`、`_rev_view_hold`、`app/valuation.py`）整段排除，解封時移除排除。
- 改完列「改了哪些字串（舊→新、檔案）」給 Opus。

## 9. 驗收（Opus）

- P4a：`test_val2_p4.py` P4a 段全過；12 檔 app 路徑 == 乾跑；全套不退步（基準 val2 `62246ed`：1290 passed／14 skipped）。
- P4b：全套過；本機 `streamlit run` 用 Playwright（`D:\prog\pw-venv`）截 2330、2881、2327（循環？依實際分類）、一檔 B 層、一檔 C 層、一檔不在範圍，桌面 1280 寬＋手機 390 寬，每檔：卡片、三個展開區展開、河流圖。截圖先給 luna 看疑點，Opus 看標記的。
- P4c：`test_glossary.py` 全過；改名清單 Opus 抽查。

## 不准做的事
- 改骨架介面（函式名、參數、回傳結構、dataclass、常數名與值）、測試預期值、本檔。覺得有問題停下回報。
- view 裡做四則運算或 import pandas／numpy／streamlit。
- 改 cron、workflow、`data/derived` 下 commit 的 JSON。
- 網路搜尋；在 repo 與 `d:/g/claude/` 以外寫檔。
