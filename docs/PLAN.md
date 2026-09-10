# 執行計畫 · tw-hold v1（一個月內）

> **這份是 checklist，不是敘述。** 每完成一項就在這裡打勾並填數字，
> 讓任何一次新對話都能從「還沒打勾的第一項」直接接手。
> 規格與理由在 [`../PRD.md`](../PRD.md)（凍結）。介面長相在 `scratchpad/tw-hold-mock.html`。

**建立**：2026-09-07 ｜ **修訂**：2026-09-08（**M0b 完成，完整上線**）
｜ **狀態**：✅ **M0 完整上線**——https://tw-hold-jchm8ooiwp7ewqisfzmpoo.streamlit.app/
（Streamlit Community Cloud）。M0.1a/M0.1b/M0.2/M0.3/M0.4/M0.5 + U1a/U1b/U2/U3 全綠。
`publish_bundle.yml`（U1b）跑綠、Release `data-latest` 12 資產 / `_meta.json` 11 檔、
`rebuild.yml` 接線並實測、清單補齊現價 + 年化週波動（`universe_filtered=True`）。
順帶修好 tw-swing G-5 斷線 + `_meta.json` 兩管線互蓋 bug。
**未接**：跨 repo `repository_dispatch` 自動觸發 rebuild（需 `TWHOLD_DISPATCH_PAT`）。
**下一棒**：M1 候選池（前置 M0b 已完成）或 M2 估值/verdict，可並行。進度見記憶 `tw-hold-m0-progress`。

> 🔴 **下一棒讀 [`M0_HANDOFF.md`](M0_HANDOFF.md)**（自足）。M-1 已完成——四個回測實驗
> （A/C/D/B）+ 地基 F1/F2/F3 全做完，使用者裁決 **tw-hold 照做**（實驗 B 從決策
> 門檻降級成期望值校準）。實驗結論見 `BACKTEST_HANDOFF.md` 的進度表。
>
> **M0 的第一件事是 U3（`universe.parquet`）**——定存線在「宇宙 = 市值前 500 ∪
> 成交值前 500」修好前是壞的（實驗 B：輸 0056 5.6pp、近年每季只剩 2 檔）。

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

- [x] 推 GitHub（2026-09-07）：`github.com/tongxiaooppo-boop/tw-hold`（**public**），
      預設分支 `main`（本地 `master` → `main`）
- [x] ⚠️ 建 repo 前掃一次（2026-09-07）：工作區 + git 全歷史掃過 `.env`/token/PAT/持倉
      → **乾淨**（只有程式碼裡的變數名 `FINMIND_TOKEN`，無實際憑證）。
      `positions.json` / `*.token` / `*.pat` / `.env.*` 已加進 `.gitignore`
- [x] ~~建公開 repo `tw-hold-data`~~ → **不建**，bundle 走 tw-swing Release + PAT（PRD §3.1）
- [x] repo 結構（2026-09-07）：`factors/ screener/ charts/ app/ reference/ tests/`
      `data/{upstream,derived,cache}/`；`data/derived/README.md` 說明產出
- [x] `.gitignore` 補 `data/upstream/`（✅）＋ `positions.json` ＋ `data/derived/*.parquet`
- [x] `.github/workflows/rebuild.yml`（骨架，2026-09-07）：`workflow_dispatch` +
      `repository_dispatch: [bundle-published]`，**無 cron**。拉 bundle / 算因子 /
      commit data/derived 三 step 目前是 TODO placeholder（等 fetch_bundle 接線 + build_lists）
- [x] `.github/workflows/heartbeat.yml`（骨架）：週一檢查 `_meta.json.rebuilt_at` 新鮮度
- [ ] 🔴 **rebuild 由 tw-swing publish 完成後 `repository_dispatch` 觸發**，
      不要自己排 cron 空跑（tw-hold 公開後額度已免費，但省冷啟與無意義的 commit）
- [x] `heartbeat` + `notify-failure`（守門員 G4）——見上；`notify-failure` job
      抄自 tw-swing `daily.yml`（自己絕不失敗：無 webhook → warning + exit 0）
- [ ] ⚠️ **`data/derived/` 只 commit 清單 JSON**（小、可 diff）；
      `factors.parquet` 放 Release 覆蓋——每天 commit 一個 parquet blob，
      一年會讓 repo 長到數百 MB，而 Streamlit Cloud 每次冷啟都要 clone
- [x] Streamlit App 骨架（2026-09-07）：`app/streamlit_app.py`——無絕對路徑
      （`Path(__file__).parents[1]`）、只讀 `data/derived/*.json`、
      `LOCAL_ADVANCED` 偵測 `FINMIND_TOKEN`/`.env` 決定進階模式開關。
      `fetch_bundle.py` 骨架（G1/G3/G5 待接線，`main()` 目前拋清楚的 NotImplemented 訊息）。
      `requirements.txt`（pandas/pyarrow/streamlit/plotly）
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

- [x] **五**個檔搬進 tw-hold、改 import（2026-09-07）
      — `factors/factors.py`、`screener/screen.py`、`reference/loader.py`、
      `build_factors.py`、`tests/test_value.py`；`loader.py` 改讀 bundle
      （`TWHOLD_BUNDLE_DIR`，預設 `data/upstream/`），帶 `equity_parent` 修正
- [x] tw-swing 端刪掉 `src/twswing/value/`（整包）＋ `scripts/build_value_factors.py`
      ＋ `tests/test_value.py`，`pytest` **780 passed**（786 − 6）
- [x] tw-hold `tests/` 綠（**6 passed**）
- [ ] ⚠️ `build_factors.py` 目前是退化版：bundle 未發佈，日線類欄位留 NaN、
      universe 用 capital_stock×收盤 估市值前 500。待 U1a/U1b/U3 補齊（M0.5 收尾）

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

- [x] regime / finmind_client 複製進來（2026-09-07）——`reference/regime.py`、
      `reference/finmind_client.py`，檔頭標 `複製自 tw-swing @c310b60`。
      `finmind_client.read_token()` 的 .env 路徑改成 tw-hold repo 根。
      登錄在 `reference/UPSTREAM.md`（G5）。indicators / price_adjuster 延到 M1/M4
- [ ] ⚠️ **不抽獨立 pip package**——一個人、兩個 repo、共 ~200 行共用碼，
      維護第三個 repo 的版本相依比漂移貴。複製 + 檔頭註記就夠

### M0.5 拉 + 算 + 顯示

- [x] `fetch_bundle.py`（2026-09-07）：GitHub API 抓 Release `data-latest` 資產（PAT，
      stdlib urllib）→ `data/upstream/`（rel 路徑照 `_meta.json`）+ `_fetch_result.json`
- [x] 🔴 **G1 schema assert**：`schema_version` 對不上 raise `BundleError`；每檔比
      sha256 + parquet 欄位清單 vs `_meta.json`
- [x] **G3**：`trading_date` 距今 > 5 天 → warning（不失敗），帶進 `_fetch_result.json`
- [x] **G5**：`check_upstream_drift.py`（2026-09-07）——比 tw-swing 來源檔現在的
      SHA-256 vs baseline（記在檔內 `BASELINE`）；`[DRIFT]` 提醒、永遠回 0
- [x] ⚠️ **只有 U1a 資產時正常收工**——U1b 檔（universe/prices/revenue/chips）缺 →
      `u1b_available=False` + warning，不拋錯
- [x] `build_factors.py`：`screen_all()`（`build_lists` 共用）跑 `screen_value/deposit`；
      讀 bundle universe.parquet（有就用、沒有退化估市值前500 / 不篩）
- [x] `build_lists.py`：`screen_all()` → `data/derived/{value,deposit,swing}_list.json`
      + `_meta.json`。「新進/移除」讀上一期 JSON `holdings` 比對（不靠 git diff）。
      swing_list 是 M1 placeholder。tests：`tests/test_lists.py`（3 個，合成 bundle）
- [x] screen.py：沒股價時 `value_score` 只用品質排序、不變全 NaN（M0a 清單才有序）
- [ ] Streamlit：`app/streamlit_app.py` 骨架已能讀這些 JSON；接真 bundle 後驗一次 UI

**M0a 驗收**：本機 `streamlit run` 看得到兩清單（財報類欄位齊、日線類欄位標「不可用」）；
`fetch_bundle.py` 從 Release 拉得到；tw-hold `tests/` 綠；tw-swing `pytest` 仍綠。
**M0b 驗收**：日線類欄位補齊（現價、季線、20 週前低、波動度）＋ bundle 有
`universe.parquet`（市值前500 過濾）＋ `chips.parquet`（法人買賣超，M1 候選池要用）。

---

## M1 · 主動選股候選池（v3.1 復活——狀態型）

> **三次改判**：v2.2 tw-hold 自己做長波段（給買價、不回測）→ ❌ 砍；
> v3.0 移到 tw-swing pool3（走四門檻）→ ❌ **回測否決**（實驗 A：事件式訊號的
> 超額集中在突破後兩週，跟「一週看一次」衝突）；**v3.1 回 tw-hold，改成
> 「主動選股候選池」**——狀態型條件、**不給 verdict、不給買價、買賣由人決定**。
> 完整脈絡 PRD §5.0。pool3 的東西不要重做（`BACKTEST_HANDOFF.md` 實驗 A）。

**目標**：第三清單到齊。狀態型候選池，守則見 PRD §5.1。**✅ 主體完成 2026-09-08**。
`screener/candidate_pool.py` + `build_lists.py` swing_list + app 長波段分頁。實測 **19 檔**。

- [x] `chips.parquet` 已在 bundle（publish_bundle.yml，M0b 就打包了）
- [x] indicators 直接 pandas 算，**沒搬** tw-swing `reference/indicators`（簡化，PRD §9）
- [x] `screener/candidate_pool.py`：CANSLIM 基本面（EPS YoY>25%、3 年 TTM EPS 成長、
      ROE>15%、毛利率未連兩季惡化、F-Score≥6）+ 月營收 YoY>0（**加速判定待 revenue
      歷史進 bundle**，實驗 D 說 revenue 非綁定關卡）+ 法人 20 日淨買超>0 + Minervini 8/8
- [x] §5.3 風控：停損位 = max(50MA, 20週前低, 現價−2×ATR14)、風險%、可買上限 = 停損位÷0.9、位置揭露
- [x] §5.2.3 失效條件檢查表（目前狀態，v3.1 不追蹤持倉）
- [x] 🔴 支持/反對並列——放「門檻之外」的判斷證據；反對空 → 標「檢查不足」
- [x] 🔴 UI 警語（`SWING_DISCLAIMER`）+ 🔴 **每個分頁頂部+底部都放 `_disclaimer()`**（使用者要求 2026-09-08）
- [x] `build_lists.py` → `swing_list.json`（`candidates_pool` + 本週新增/退出）
- [x] app 長波段分頁（卡片式：代號/現價/停損/可買上限 + 支持反對 + 展開明細）
- [x] 措辭：「條件成立狀態」不叫「建議進場」；「候選池」不叫「推薦清單」；無 verdict/總分/排名
- [ ] 每週排程（跟其他清單一起在 rebuild.yml，目前手動 dispatch）——M3 處理

**M1 驗收**：✅ 三清單到齊；候選池每檔有 8 條件狀態 + 支持/反對 + 風控可買上限 + 失效條件檢查表 + 無回測支撐警語。細節見記憶 `tw-hold-m1-progress`。

**不做**（v3.1 明確，PRD §5.0.1 / §9.8.5）：verdict、目標價 / 合理價、單一總分、
排名次、配權重、回測、資金池、`positions.json`（持倉失效條件靠使用者週末自己看 +
券商停損單）。

---

### ~~M1（v3.0）· 長波段移到 pool3~~ ❌ 已被 v3.1 取代

v3.0 曾把長波段移到 tw-swing pool3（Y4/Y1 + 長出場 + 週批次，走完整回測門檻）。
**pool3 被實驗 A 回測否決**（`BACKTEST_HANDOFF.md`）→ v3.1 改成上面的候選池。

以下 v2.2 原內容保留當留痕，**不要執行**：

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

## M2 · 估值 + verdict + 季換股 · **✅ 主體完成 2026-09-08**

**目標**：清單有買入建議價 / 不推薦 + 出場依據。照 PRD §6/§7 寫死，不重議（凍結條件 5）。
`screener/{pricing,deposit_pricing,gates}.py` + `build_lists.py` 季表凍結。全套 32 tests 綠。
使用者裁決：定存季換、價值維持季表 + 候補變動、N = 15。
⚠️ 冷啟：8/14 這期成分用 9/8 資料選（一次性）。細節見記憶 `tw-hold-m2-progress`。
剩：產業逆風判定（低優先）、流動性 verdict（可能不必）、rebuild 排程（M3）。

- [x] 價值：便宜門檻 = normalized_EPS × P30、估值上緣 = TTM_EPS × P70、空間 %（讀 bundle `per.parquet`）
- [x] verdict 只由便宜門檻驅動、估值上緣不進 verdict；買入區間倒置處理（`screener/pricing.py`）
- [x] 循環高峰旗標 `TTM_EPS/normalized_EPS > 1.5`（欄位已算；UI 文字留 M3）
- [x] 🔴 自加門檻 `eps_basis_suspect`：normalized_EPS 隱含 PE < 市場 PE 一半 → 「EPS 基準存疑」（抓到 5904）
- [x] 定存 §7.1：填息率（`prices_raw_close` × `CashExDividendTradingDate`）+ 近 3 年含息報酬 → 兩道硬門檻（資料缺不擋、標記）
- [x] 定存 §7.3/§7.4：殖利率法買價（門檻 `max(近5年均殖利率, 5%)`）+ verdict + 揭露欄
- [x] 🔴 守門員 G2（`screener/gates.py`）：抽 2412/1216/2884/2892 除息日 assert raw 有跳空、adj 沒有
- [x] 季表凍結（換股日 3/31、5/15、8/14、11/14）+ 新進/移除+每檔原因 + 換手率（讀上一期 JSON，非 git diff）
- [x] 候補變動 `candidates.likely_in / likely_out`（若今天重選，提示、不進正式變動表）
- [x] 產業集中度 ≤ 40%（`select_composition`，N=15、單一產業 ≤ 6）
- [x] 產業逆風判定（`screener/industry.py`）：同產業近 6 月報酬中位數 < −10% 且落後大盤 8pp
      → `industry_headwind` 旗標。**只顯示、不進 verdict**（比照循環高峰旗標）。2026-09-08。

**M2 驗收**：✅ 三清單每檔有買價或「觀望 / 不推薦（明確原因）」；季表 + 換股面板 + 候補變動都上了。
⚠️ 冷啟：8/14 這期成分用 9/8 資料選（一次性，下期 11/14 起正常）。

---

## M3 · 清單 UI + 匯出 + Action 上線 · **✅ 完成 2026-09-08**

- [x] 清單頁：卡片式（大代號+股名+verdict icon + 3–4 個 metric，其餘收 expander 明細）；
      verdict 篩選（multiselect）+ 排序（分數/空間%/殖利率/現價）
- [x] 中文欄名（`LABELS`）、股名（`universe.parquet` `stock_name` → 三清單都帶 `name`）
- [x] 「複製給 AI」：每個分頁 expander 裡 `st.code` 一段結構化文字
- [x] 🔴 每個分頁頂部+底部警語（使用者要求）；長波段另加無回測支撐警語
- [x] `rebuild.yml` 已接線並實測（workflow_dispatch + repository_dispatch）
- [x] Streamlit Cloud 已佈署（M0a）+ app 密碼（使用者設）
- [ ] ⚠️ **自動排程刻意還沒開**（PLAN 原則「先手動跑幾天」）——`rebuild.yml` 註解寫了
      兩條路（tw-swing 發 repository_dispatch / 加 cron），等使用者觀察後決定

**M3 驗收**：✅ 雲端打得開、三清單卡片式完整、篩選排序、複製給 AI、警語齊。
自動重算「能開」（一行 uncomment / 加一顆 PAT），使用者決定何時開。

---

## M4 · 個股查詢 · **✅ 主體完成 2026-09-08**

`app/bundle_data.py` + `app/charts.py` + `streamlit_app.py` 個股分頁。AppTest 實測
2330 / 6488(OTC) / 9999(不存在) 都不爆。全套 43 tests 綠。

- [x] 🔴 app 端 bundle 載入器（`app/bundle_data.py`）：`ensure_assets()` 執行期從 Release
      拉、`st.cache_resource` 一次；按需讀 `pyarrow filters=[("ticker","in",[...])]` + `columns=`
- [x] 代號 → 讀 bundle；不在 bundle 內給明確提示
- [x] 圖：還原日K+均線、季 EPS、三率、現金流、逐年股利、**本益比河流圖**、F-Score 9 分項表
- [x] plotly 互動
- [x] ⚠️ F-Score 9 分項打勾、不加總、不給 verdict
- [ ] 月營收走勢圖——bundle 只有單月快照，待 revenue 歷史併入 bundle（degraded：顯示 info）
- [ ] `price_adjuster.py` 移植（本地進階模式、500 大以外）——低優先

**M4 驗收**：✅ 輸入代號看得到數據表 + 7 類圖；不打分。細節見記憶 `tw-hold-m4-progress`。

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
- 個股頁 AI 敘事層整合（→ `docs/AI_LAYER.md`）
- **個股查詢 / 多軌體檢：可設定 500 外的擴充清單（~10 檔）** —— 避免被
  「因子表 ~1000 檔」鎖死。作法：一份使用者維護的 `extra_tickers`（config / repo
  檔），rebuild.yml 把這幾檔一起算進 `factors_*.parquet` + bundle 需要的切片。
  🔴 **仍不做即時查詢**——不在「因子表 + 擴充 10 檔」名單內的股票一律不抓單股資料
  （守 PRD §M4 雲端唯讀 + FinMind 額度）。
- ~~`tw-hold-data` 若嫌公開不妥 → 改私有 + PAT~~ → **v2.1 已定案走私有 Release + PAT**
- U1b 併回 `daily.yml`（G-5 過關、真錢上線之後，省掉一次重複抓取）
- **自建「主動式 ETF PCF」上游** —— 「主動式ETF認領旗標」v1 的資料源是 `etfinfo.tw/api/active/summary`
  （第三方彙總、有付費牆層、每次約 1/3 主動 ETF stale）。當旗標變 load-bearing 或該 API 被關進牆
  → 自己抓 PCF：各家主動 ETF 的 PCF 頁 + 證交所/櫃買彙整 + 集保，逐日 diff。
  ⚠️ 查證結果，別再重查：
  · TWSE OpenAPI **沒有** consolidated PCF holdings feed（`fund/T86` 是三大法人、`ETFReport/ETFRank` 只有排行）。
  · FundClear（集保 `www.fundclear.com.tw/api/etf/*`）有官方 JSON API 但**只到基金/類別層級**
    （受益權單位數變動、規模、折溢價、配息），**無每日個股 PCF**，且統計落後數週。
    → 拿來當「官方 ETF 主檔清單 / 每檔規模・折溢價・配息」來源可以，認領旗標用不上。
  單一來源脆弱見記憶 `upstream-datapack-single-point`。
