# 執行計畫 · tw-hold v1（一個月內）

> **這份是 checklist，不是敘述。** 每完成一項就在這裡打勾並填數字，
> 讓任何一次新對話都能從「還沒打勾的第一項」直接接手。
> 規格與理由在 [`../PRD.md`](../PRD.md)（凍結）。介面長相在 `scratchpad/tw-hold-mock.html`。

**建立**：2026-09-07 ｜ **修訂**：2026-09-07 深夜（**v3.0 範圍重定**）
｜ **狀態**：🟡 **未開工，且 PRD 未定案**。

> 🔴 **第一件事不是 M0，是 M-1（回測驗證）。**
> 執行交接在 **[`BACKTEST_HANDOFF.md`](BACKTEST_HANDOFF.md)**（自足，不用先讀 PRD）。
>
> **為什麼**：tw-hold 原本用「決策支援、不上真錢」豁免回測。使用者盤點資產後
> 確定要投 ~300 萬（定存 200 萬分批 + 價值 100 萬）——**豁免的前提消失了**，
> 而價值/定存的因子從沒在台股測過。**回溯結果可能是「不要做」，那也是合法結論。**
>
> **v3.0 還砍掉了長波段**（移到 tw-swing 的 pool3，理由見 PRD §5）。本檔 M1 已作廢。

> 🔴 tw-swing 的 11 月關鍵路徑（G-5、10 月分池揭露）**優先**。tw-hold 是 tw-swing
> 顧好之後的空檔工（PRD §1.3）。
>
> ⚠️ **但「優先」不等於「tw-hold 要等到 11 月」**（opus 審核修正）：M0 已拆成
> **M0a（只動 `fundamentals.yml`，不在 G-5 時鐘上 → 現在可做）** 與
> **M0b（日線類，走新開的 `publish_bundle.yml`，完全不修改 `daily.yml` → 對 G-5 零風險）**。
> **紅線只有一條：不修改 `daily.yml`、不動 `rules.yaml` / pools / 回測。** 見 PRD §3.1.1。

---

## 為什麼要有這份計畫

這場需求討論在 2026-09-07 一天內就有 ~5 次架構／方法改判。**一個月內做完的最大
變數不是工作量，是發散。** 這份計畫的設計原則：

| 原則 | 做法 |
| :--- | :--- |
| **PRD 凍結** | 不再有架構討論、不改因子設計、不改估值公式、不改分軌。要改記 backlog、v2 再說 |
| **每個 Milestone 獨立可交付** | 做完一個 M 就是一個自洽的停點：能跑、清單合理、commit 乾淨 |
| **先核心後加分** | 三清單 + 買入建議是核心；個股查詢頁擺後面，來不及可溢出一個月 |
| **v1 允許粗糙** | 嗜好決策支援工具，不是產品。「會動、清單合理、個股頁能看」就是門檻 |
| **對話裡只貼一行結論** | 完整說明寫檔，不在對話重貼 |

---

## 凍結條件（沒守住就會拖）

1. **PRD 凍結**，跟 tw-swing 的 pool1 一樣。不再有架構討論、不改因子設計、
   不改估值公式、**不改分軌（長波段主動 / 價值定存規則化）**。
2. **M5（AI 整合）／ M6（自架 hosting）明確不做。**
3. **圖表夠用就好**：`me` 的圖搬成 plotly，不重新設計。只有本益比河流圖值得做好。
4. **長波段 v1 = 規則 + 合理預設，零參數調校。** 先出貨，refine 進 v2。
5. **估值引擎照 PRD §6/§7 逐條實作，不 re-litigate。**
6. **v1 允許粗糙。**
7. **tw-swing 的 11 月關鍵路徑優先**——具體化成一條可檢查的紅線：
   **不修改 `daily.yml`、不動 `rules.yaml` / pools / 回測**。其餘（`fundamentals.yml`、
   新開 workflow）可動。
8. **PRD v2.1 的 8 條審核修正不再 re-litigate。**
9. 🔴 **但 v3.0 的因子設計與門檻數字「未定案」**——那不是「可以隨便討論」的意思，
   是**等實驗 B 的數字來定**。數字出來之前不要改、也不要照它動工。

⚠️ 這場對話已有 ~5 次架構/方法改判。PRD 凍結是那個變數的解藥。

---

## M-1 · 🔴 回測驗證（**動工前置，不做完不要進 M0**）

**目標**：拿到數字，決定這個專案值不值得做。**timebox 1–2 session。**
**執行細節全在 [`BACKTEST_HANDOFF.md`](BACKTEST_HANDOFF.md)，這裡只放打勾。**

### M-1.1 地基補齊（本地補，補完先本地跑，**不推**）

- [x] **F1** `fetch_fundamentals.py` 的 `capital_stock` / `cash`：BALANCE_FIELDS 本來就有，
      舊資料是加欄前抓的 → 備份後刪 balance.parquet 全量重抓 500 檔（`data/fundamentals/balance.parquet`）。
      **順手抓到 loader 的 `equity_parent` 取錯欄位**（損益表版本是「淨利」不是「權益」）→
      修 `value/loader.py`，roe 從爛值（中位數 3.75）變正常（中位數 11.7%）。
- [x] **F2** `TaiwanStockInfo` → `data/fundamentals/industry.parquet`（3147 檔）。加進 FinMind 免費層白名單。
- [~] **F3** `scripts/fetch_raw_prices.py` → `data/fundamentals/prices_raw.parquet`。抓取中
      （節流器 seed bug 卡過一次、已修）。
- [ ] 🔴 **除息跳空驗證**：`research/check_raw_prices.py`（0056/2412/2882），F3 完成後跑。
- [x] ⚠️ 2026-09-07 是週一，`fundamentals.yml` 週六排程已過，本地抓取不衝突。

### M-1.2 實驗 B · 組合層歷史回溯（2016 起，季換股）· **✅ 首版完成 2026-09-07**

- [x] `research/backtest_rebalance.py`（獨立腳本）
- [x] 價值線、定存線各跑；N = 10 與 20；對照組（0050/0056 含息 + 過門檻等權全買）
- [x] 公告日遞延（財報 +45 天、月營收 available_date +9 天）已套
- [x] 生存者偏差寫明（宇宙 = 今天前 500 大），結論當上界
- [x] 報告 → `docs/reports/rebalance_backtest_20260907.md` + **`expectations_20260907.md`**（總結）

**M-1 數字（含息年化，上界；真實更差）**：

| | 策略 | 對照 | 回撤 | 每期候選 |
| :-- | --: | --: | --: | :-- |
| **價值線** | +20% (N10) / **+25%** (N20) / +30%(全買) | 0050 **+24%** | −21% | 130–360 檔 |
| **定存線** | **+12%** | 0056 **+16%** | 🔴 **−30%** | 🔴 2016–2019 建不起來、近年 2–6 檔 |

🔴 **使用者裁決 2026-09-07：tw-hold 照做，這不是要不要做的關卡。** M-1 從「決策門檻」
降級成「期望值校準」。三種結果三條路作廢。

**結論**：
- **價值線 ≈ 0050**（扣生存者偏差後略輸），Magic Formula 的便宜 tilt 沒加分——
  有效的只有「F-Score ≥ 6」品質門檻，但廣撒 189 檔才贏、取前 10–20 反而拖累。
- **定存線輸 0056 3–4pp、回撤兩倍**，做不出低波動。**根因：universe 是成交值前 500，
  安靜的大型金融傳產排不進去** → 需要 PRD §2A 的 U3 修正（市值前 500 ∪ 成交值前 500）。
  在那之前，定存線先當觀察名單、不真的照它建倉。
- 填息率門檻目前只覆蓋部分候選（F3 抓完補完整版）。

⏳ **待補**：F3 完成 → 除息守門 → 定存線完整版重跑 → 更新 `expectations_20260907.md`。

---

## M0 · 遷移 + 骨架 + 佈署管線

> 🔴 **M-1 沒做完不要進 M0。** 先蓋資料管線再驗證，可能蓋完才發現不該做。

**目標**：能跑、看得到價值/定存兩清單、bundle 拉得到。**timebox 3–4 session。**

> ⚠️ **v2.0 寫「1–2 session」是低估**（opus 審核）：M0 含一條新的上游發佈管線
> （U1a 本身就 1–2 session）＋ 市值資料源修復 ＋ 遷移 ＋ 骨架。
>
> **M0 拆成 M0a（現在做）/ M0b（隨後，獨立 workflow）**——理由見 PRD §3.1.1。

### M0.1a tw-swing 端 · U1a（週更半邊，**不在 G-5 時鐘上，現在就能做**）

> 只動 `fundamentals.yml`。價值/定存清單的核心欄位全部落在這半邊。

- [ ] 🔴 **先修 `capital_stock` / `cash` 補抓**（STATUS 記「補抓當掉」）——市值算不出來，
      宇宙定義就是錯的，而且**不會報錯**。修不好就用 `PBR × 股東權益` 起步，
      但要在 `_meta.json` 標市值口徑，UI 標「估算值」
- [ ] `universe.parquet`（U3）：**新寫**——`twswing.data.universe` 現在只有
      `stock_list` / `equity_tickers` / `restrict_to_equities`，**沒有市值也沒有產業別**。
      宇宙 = **市值前 500 ∪ 成交值前 500**（上游的 500 是成交值排的，會漏掉安靜的
      大型定存股）；產業別取 FinMind `TaiwanStockInfo.industry_category`
- [ ] `per` 逐檔 → 整併成 `per.parquet`（U2）
- [ ] `fundamentals.yml` 加 publish step：財報四表 + `per.parquet` + `universe.parquet`
      + `_meta.json` → **tw-swing 私有 repo 的 Release，移動 tag `data-latest`**
- [ ] ⚠️ **紅線**：不改 `daily.yml`、不改 rules / pools / pipeline

### M0.1b tw-swing 端 · U1b（日更半邊，**開新 workflow，不碰 `daily.yml`**）

> `data/store/` 不進版控（CI 現抓），所以日線類必須在自己抓好 store 的 job 裡打包。
> 新開一支 workflow 自己抓一次，**對 G-5 的 60 天時鐘零風險**。
> 順便解掉 tw-swing pool2 的 Y4 卡點（FinMind 資料進 CI）。

- [ ] 新開 `.github/workflows/publish_bundle.yml`：自己跑 `update_data.py`
      → 打包 `prices_adj` / `prices_raw_close` / `revenue` / `index_0050`
      → 併進同一個 Release tag
- [ ] ⚠️ **一個字元都不要改 `daily.yml`**
- [ ] 🔴 **用 `actions/cache` 快取上游資料包（220MB）**——不快取的話這支每月多吃
      ~330 分鐘，會把 tw-swing 的 Actions 額度餘裕吃光（PRD §10.1）
- [ ] 抄 `daily.yml` 的 `notify-failure` job（⚠️ 告警 job 自己不可以失敗）
- [ ] 🔴 **`prices_raw_close` 的來源照 PRD §10.3 定案**：歷史用 FinMind
      `TaiwanStockPrice` 本地一次性回補（500 req），**每日增量改用 TWSE OpenAPI
      收盤整批（1 req/日）**。⚠️ 不要做成「每天 500 檔逐檔抓」——那是每天一小時
      純抓取，會撞 500/hr 天花板
- [ ] 排程避開 `daily.yml` 三槍的時段（守 FinMind 500/hr）

### M0.2 tw-hold repo + 佈署地基

- [ ] 推 GitHub（同帳號新 repo，**public**——使用者裁決 2026-09-07，PRD §10.1）
- [ ] ⚠️ 建 repo 前掃一次：`.env` / token / 個人持倉有沒有混進版控
      （`positions.json` 之後會有進場價，**要進 `.gitignore`**）
- [ ] ~~建公開 repo `tw-hold-data`~~ → **不建**，bundle 走 tw-swing Release + PAT（PRD §3.1）
- [ ] repo 結構：`factors/ screener/ charts/ app/ reference/ tests/ data/{upstream,derived,cache}/`
- [ ] `.gitignore` 補 `data/upstream/`（✅ 已補）
- [ ] `.github/workflows/rebuild.yml`（每日重算骨架，先手動跑也行）
- [ ] 🔴 **rebuild 由 tw-swing publish 完成後 `repository_dispatch` 觸發**，
      不要自己排 cron 空跑（tw-hold 公開後額度已免費，但省冷啟與無意義的 commit）
- [ ] `heartbeat` + `notify-failure`（守門員 G4：連續失敗沒人看，60 天後
      GitHub 會自動停用排程）
- [ ] ⚠️ **`data/derived/` 只 commit 清單 JSON**（小、可 diff）；
      `factors.parquet` 放 Release 覆蓋——每天 commit 一個 parquet blob，
      一年會讓 repo 長到數百 MB，而 Streamlit Cloud 每次冷啟都要 clone
- [ ] Streamlit App 骨架**寫成雲端可佈署**：無絕對路徑、**bundle PAT 走 `st.secrets`**
      （雲端**不要**放 `FINMIND_TOKEN`，即時補抓在雲端是停用的）、
      偵測環境變數決定「本地進階模式」開關
- [ ] 🔴 **PAT 用 fine-grained、只給 tw-swing 一個 repo 的 `contents: read`**——
      tw-hold 是公開 repo，權限要有界（PRD §10.1）。到期日記進 `reference/UPSTREAM.md`

### M0.3 遷移（tw-swing → tw-hold，搬走）

| tw-swing | tw-hold | 改什麼 |
| :--- | :--- | :--- |
| `src/twswing/value/factors.py` | `factors/factors.py` | import 改 `from reference.loader import ...` |
| `src/twswing/value/screen.py` | `screener/screen.py` | 同上 |
| `src/twswing/value/loader.py` | `reference/loader.py` | **v2.1 改為一起搬走**（見下） |
| `scripts/build_value_factors.py` | `build_factors.py` | 讀 `data/upstream/`（bundle），不讀 tw-swing 磁碟 |
| `tests/test_value.py` | `tests/` | fixture 改用 bundle 樣本 |

> 🔴 **`loader.py` 從「留 tw-swing + 複製一份」改成「搬走、tw-swing 端刪除」**
> （opus 審核 2026-09-07）。實查依賴：`grep "load_quarterly|load_dividends"` 在 tw-swing
> **只命中 `scripts/build_value_factors.py`**，而它 M0 要搬走；`tests/test_value.py`
> 根本沒測到 loader，而且也要搬走。→ 留下來就是**零消費者、零測試覆蓋的死碼**，
> 然後還要擔心它跟 tw-hold 那份漂移。**不要留兩份。**
> `value/` 整包從 tw-swing 移除（`__init__.py` 一併刪）。

- [ ] **五**個檔搬進 tw-hold、改 import
- [ ] tw-swing 端刪掉 `src/twswing/value/`（整包）＋ `scripts/build_value_factors.py`
      ＋ `tests/test_value.py`，跑 `pytest` 確認仍綠（應為 786 − test_value 的數量）
- [ ] tw-hold `tests/` 綠

### M0.4 複製參考碼（tw-swing 保留原件、不再 import）

> ⚠️ `loader.py` 不在這張表——它是**搬移**，在 M0.3。這裡只有「tw-swing 端還活著、
> 因此真的會漂移」的檔案。每個複製進來的檔案**檔頭要寫**：
> `# 複製自 tw-swing @<commit>，<日期>；上游改動不自動同步`。

| 來源 | tw-hold | 用途 | 漂移後果 |
| :--- | :--- | :--- | :--- |
| `src/twswing/data/regime.py` | `reference/regime.py` | 市況顯示旗標（PRD §6.5） | 無害（只是顯示） |
| `src/twswing/data/finmind.py`（client） | `reference/finmind_client.py` | 個股即時查（僅本地） | 小（API 變更才有感） |
| `src/twswing/indicators/{core,ma_rules,pivots,trendlines}.py` | `reference/indicators/` | 長波段 screener（M1） | 小（tw-hold 不上真錢，用舊季線定義可接受） |
| `me/.../data/price_adjuster.py` | `reference/price_adjuster.py` | 500 大以外還原股價（M4） | 無（me 已凍結） |
| `me/.../data/fetcher.py` | `reference/fetcher.py` | 即時個股補抓參考（M4） | 無（同上） |

- [ ] regime / finmind_client 複製進來（indicators / price_adjuster 可延到 M1/M4）
- [ ] ⚠️ **不抽獨立 pip package**——一個人、兩個 repo、共 ~200 行共用碼，
      維護第三個 repo 的版本相依比漂移貴。複製 + 檔頭註記就夠

### M0.5 拉 + 算 + 顯示

- [ ] `fetch_bundle.py`：從 tw-swing Release（PAT）下載 bundle → `data/upstream/` + `_meta.json`
- [ ] 🔴 **守門員 G1：schema assert**——`_meta.json` 帶 `schema_version` + 每檔欄位清單，
      對不上就**大聲失敗**。這是兩個 repo 之間唯一的正式介面，不要「盡力而為」
- [ ] **守門員 G3**：比對 `_meta.json` 的 `trading_date` 與預期最新交易日，
      不符**不失敗**、在清單頁標記資料日期
- [ ] **守門員 G5**：`reference/UPSTREAM.md`（檔案 / 來源路徑 / commit / PAT 到期日）
      ＋ `check_upstream_drift.py` 比 hash（只提醒、不自動同步）
- [ ] ⚠️ **`fetch_bundle.py` 要能在「只有 U1a 資產」時正常運作**——缺 U1b 的日線檔就
      標記「日線類特徵不可用」而**不是拋錯**。M0a 才跑得起來
- [ ] `build_factors.py`：跑 `screen_value()` / `screen_deposit()` → `data/derived/`
- [ ] 最陽春 Streamlit：顯示價值 / 定存兩清單（先剔除、再 rank 的原樣）

**M0a 驗收**：本機 `streamlit run` 看得到兩清單（財報類欄位齊、日線類欄位標「不可用」）；
`fetch_bundle.py` 從 Release 拉得到；tw-hold `tests/` 綠；tw-swing `pytest` 仍綠。
**M0b 驗收**：日線類欄位補齊（現價、季線、20 週前低、波動度）。

---

## ~~M1 · 長波段 screener~~ ❌ **v3.0 作廢**

**長波段移到 tw-swing 的 pool3**（Y4/Y1 + 長出場 + 週批次），理由見 PRD §5.0：
Y4 已通過四門檻 + 樣本外（每筆超額 +1.773%、MAR 2.34、回撤 −7.2%），
而 tw-hold 這版沒停損、沒部位控制、沒回測。**同一件事不做兩次。**
pool3 的回測是 `BACKTEST_HANDOFF.md` 的**實驗 A**，在 tw-swing 做。

以下原內容保留當留痕，**不要執行**：

### ~~M1（原）· 長波段 screener~~

**目標**：第三清單到齊。**timebox 2–3 session。** 純規則預設、不調參（凍結條件 4）。

- [ ] `reference/indicators/` 複製完整（`core`/`ma_rules`/`pivots`/`trendlines`）
- [ ] `screener/longswing.py`：PRD §5.1 進場條件 + §5.2 剔除
- [ ] 🔴 **`data/positions.json` 最小持倉登錄**（手動填 `代號 / 進場日 / 進場價`，
      不需要 UI）——沒有它，§5.3 的「進場滿 12 週未創新高 / 未達 +8%」**算不出來**，
      因為「在清單內」≠「你持有」，12 週起算點完全不同（opus 審核發現，PRD §5.3）
- [ ] **§5.3 出場規則檢查表**——對**持倉中**的標的標 續抱/出場，逐條標未觸發；
      對「在清單內但未持倉」的只標條件狀態
- [ ] 風報比計算（到季線距離 = 風險、到前波高 = 報酬）
- [ ] ⚠️ 措辭：輸出欄位叫 **「條件成立區間」不叫「建議進場區間」**（PRD §5）
- [ ] `build_factors.py` 加長波段清單 → `data/derived/lists/longswing.json`
- [ ] Streamlit 加長波段分頁

**M1 驗收**：三清單到齊；長波段每檔有條件成立區間 + 出場條件檢查表 + 風報比；
`positions.json` 有值時算得出時間停損。

---

## M2 · 估值 + verdict + 季換股

**目標**：清單有買入建議價 / 不推薦 + 出場依據。**timebox 2 session。**
照 PRD §6/§7 寫死，不重議（凍結條件 5）。

- [ ] 價值：`normalized_EPS` / `TTM_EPS`、自身近 5 年 trailing PE 的 P30/P70
- [ ] 價值：便宜門檻 / 估值上緣 / 你買進的殖利率（盈餘、FCF、EV-EBIT）→ §6.3 verdict
- [ ] ⚠️ **verdict 只由便宜門檻驅動**，估值上緣**不進 verdict**（PRD v2.1 §6.3）
- [ ] ⚠️ 買入區間**倒置處理**（下界 > 上界時不吐負寬度區間，PRD §6.3）
- [ ] 循環高峰旗標：`TTM_EPS / normalized_EPS > 1.5` → 明細標「估值上緣偏樂觀」
- [ ] 定存：填息率計算（`prices_raw_close` + `dividend.ex_date`）
- [ ] 🔴 **守門員 G2（做填息率的同一批就要寫）**：抽 `0056` / `2412` 的除息日，
      assert **raw 序列有跳空、adj 序列沒有**。
      理由：`prices_raw_close` 若被誤填成還原序列，**填息率會恆等於 100%、
      定存清單全綠、而且沒有任何東西會報錯**（PRD §10.2 G2）
- [ ] 定存：近 3 年含息年化報酬計算 → 兩道新硬門檻
- [ ] 季換股：「公告後」對齊日定案；每期輸出「新進 / 移除 + 原因」+ 換手率
- [ ] ⚠️ 「新進/移除」**讀上一期 `lists/*.json` 的 `previous` 欄位**比對，
      **不可以靠 git diff**（那不是資料流、重跑不出來）（PRD §3.2）
- [ ] 產業集中度上限（**產業 ≤ 40%**；「單檔 ≤ 30%」是空條件已刪，等權 10–20 檔
      單檔本來就是 5–10%）
- [ ] 產業逆風判定（同產業動能中位數代理）

**M2 驗收**：三清單每檔有買價或「不推薦（明確原因）」；換股面板顯示新進/移除。

---

## M3 · 清單 UI + 匯出 + Action 上線

**目標**：推薦模式完整、每日自動重算。**timebox 1 session。**

- [ ] 清單頁：篩選、排序、展開明細（照草模）
- [ ] 「複製給 AI」文字格式
- [ ] `rebuild.yml` 正式上線：每日 `fetch_bundle` → `build_factors` → commit `data/derived/`
- [ ] Streamlit Community Cloud 佈署 + app 密碼
- [ ] ⚠️ 先手動跑幾天再開排程（知道正常長什麼樣，才分得出不正常）

**M3 驗收**：雲端打得開、三清單完整、每日自動更新。

---

## M4 · 個股查詢

**目標**：個股頁能用。**timebox 3 session。** 真的來不及可溢出一個月（加分項）。

- [ ] 🔴 **app 端 bundle 載入器**（雲端個股頁的資料路徑，PRD §3.2）：
      `data/upstream/` 是 gitignore 的、**不在佈署出去的 repo 裡** → app 要用
      同一顆 PAT 執行期拉一次、`st.cache_resource` 快取。
      ⚠️ **按需讀取**：`pyarrow` 的 `filters=[("ticker","==",x)]` + `columns=[...]`，
      **不可以整張 `pd.read_parquet()`**——Streamlit Cloud 只有 1GB RAM
- [ ] 代號 → 前 500 讀 bundle / 本地不在則即時補抓（`data/cache/`，TTL 見 PRD §3.3）
- [ ] 數據表 + 核心圖：K 線、月營收、季 EPS、三率、股利、**本益比河流圖**、F-Score 9 分項
- [ ] plotly 互動（hover / 縮放）
- [ ] `price_adjuster.py` 移植（500 大以外還原股價）
- [ ] ⚠️ F-Score 9 分項打勾、**不加總、不給 verdict**

**M4 驗收**：輸入代號看得到數據表 + 圖；不打分。

---

## 不做（v1）

- **M5 AI 整合**：DeepSeek API / analyzer.py。「複製給 AI」文字格式在 M3 就夠。
- **M6 自架 hosting**：Streamlit Cloud 夠用。
- 長波段**參數**用歷史挑一次 → v2（**注意：v1.5 那次回測不是調參**，見下）。
- 個股出場推播 → v2。

## ~~v1.5~~ ❌ **v3.0 作廢**（長波段已移出到 pool3，那邊本來就要過四門檻 + 樣本外）

以下保留當留痕，不要執行：

- [ ] **長波段整套跑一次 tw-swing 回測引擎**（§5.1 進場 + §5.3 出場已寫死 → 可回測）。
      **只看期望值是不是負的，不調參**（調參違反凍結條件 4）。~1 session。
      跑過之前，長波段輸出一律用「條件成立區間」的措辭（PRD §5）。

---

## 額度不足時的停損點

**任一個 Milestone 做完就是合理停點。** 每個 M 結束時系統自洽：能跑、`tests/` 綠、
`data/derived/` 與 UI 一致、commit 乾淨。

| 停在哪 | 交接狀態 |
| :--- | :--- |
| M0 中間 | tw-swing publish step 已落的話，bundle 可拉；tw-hold 這邊搬到哪算哪 |
| M1 中間 | 價值/定存兩清單仍可跑，長波段未完成不影響前兩者 |
| M2 中間 | 清單有 rank 無 verdict——仍看得到成分，只是沒買價 |
| M4 中間 | 三清單完整可用；個股頁沒做完不影響前面（雲端就先不開那個分頁） |

**絕對不可以留下的狀態**：`build_factors.py` 產出的清單欄位與 UI 期待的不一致、
或 `data/derived/` 是舊 schema 但 code 是新的。

---

## 給下一次對話的接手指令

0. 🔴 **先確認 M-1 做完了沒**——沒有就去讀 [`BACKTEST_HANDOFF.md`](BACKTEST_HANDOFF.md)，
   不要從 M0 開始
1. 讀本檔，找**第一個沒打勾的項目**（現在是 **M-1.1 的 F1**）
2. 讀 [`../PRD.md`](../PRD.md) 對應章節（§ 已標在每個 M 的項目裡）
3. **不要**重新討論架構/因子/估值——PRD v2.1 凍結（含 opus 審核的 8 條修正），
   要改記 backlog
4. 開工前確認起點乾淨：tw-hold `python -m pytest tests/ -q`（M0.3 之前是空的，正常）；
   tw-swing `python -m pytest -q` 應為綠
5. **紅線自查**（tw-swing 那邊）：這次要動的檔案裡有沒有 `daily.yml` / `rules.yaml` /
   `portfolios` / 回測？有 → 停，改用新 workflow 的做法（PRD §3.1.1）
5.5 **額度自查**：這次要不要新增/改排程？改了就重估 Actions 分鐘數——
   **超過 2000 分/月，tw-swing 的 `daily.yml` 會停跑、G-5 時鐘歸零**（PRD §10.1）
6. tw-swing 的 11 月關鍵路徑優先——先讀 `tw-swing/docs/STATUS.md`〈一分鐘接手〉
   確認 G-5 管線今天沒斷

---

## Backlog（v2 再說）

- 長波段參數：拿歷史挑一次
- 個股出場推播（Discord/Slack webhook）
- 估值：產業相對 PE（現在是自身歷史）
- 季換股改月換股 / 事件觸發換股
- 個股頁 AI 敘事層整合
- ~~`tw-hold-data` 若嫌公開不妥 → 改私有 + PAT~~ → **v2.1 已定案走私有 Release + PAT**
- U1b 併回 `daily.yml`（G-5 過關、真錢上線之後，省掉一次重複抓取）
