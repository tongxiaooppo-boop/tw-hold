# M0 交接 — 給下一棒

> **自足執行指令。你在全新對話、沒有上下文。** 讀完這份就能動工。
> 環境：Windows，`d:\g\claude\` 底下有 `tw-swing\`、`tw-hold\`、`books\`。
> ⚠️ **bash 工具的 cwd 是 `d:\g\claude`**，跑腳本要 `cd /d/g/claude/tw-swing &&` 或 `tw-hold`。
>
> **建立**：2026-09-07 ｜ **前一棒做完**：M-1（四個回測實驗 + 地基 F1/F2/F3）
> ｜ **這一棒**：M0（遷移 + 骨架 + 佈署管線），細節在 [`PLAN.md`](PLAN.md) §M0

---

## 0. 一分鐘現況

**四個回測實驗全做完**（`BACKTEST_HANDOFF.md` 有完整交接，都標 ✅）：

| 實驗 | 結論 | 對 M0 的影響 |
| :--- | :--- | :--- |
| **A** pool3 週波段 | ❌ 否決——事件式訊號的超額集中在訊號後兩週，跟「一週看一次」衝突 | 波段軌道 = tw-hold 的「主動選股候選池」（PRD §5），**不宣稱報酬** |
| **C** tw-swing 現行五條真實成交口徑 | 只有 H2 勉強撐住；A3/C3 每筆超額翻負但**絕對不賠錢**（機會成本） | 使用者裁決 **tw-swing = 賭場**；Y4 是最強的、原則進 pool2 但**卡 FinMind-in-CI**（見 §4） |
| **D** 候選池每週剩幾檔 | ✅ 可行——2019+ 每週中位數 3–5 檔、空頭接近空 | 候選池照 PRD §5 實作 |
| **B** 價值/定存組合層回溯 | 🔴 **價值線 ≈ 0050（略輸）；定存線輸 0056 5.6pp、回撤 −25%、近年每季只剩 2 檔** | 見 §3——**定存線在 U3 修好前是壞的** |

🔴 **使用者裁決 2026-09-07：tw-hold 照做，實驗 B 不是關卡。** 報告的用途是「放多少錢進去」。
完整期望值報告：[`docs/reports/expectations_20260907.md`](reports/expectations_20260907.md)。

---

## 1. M0 是什麼（timebox 3–4 session）

**PLAN.md §M0 是權威，這裡只給地圖。** 拆四塊：

| 塊 | 在哪 | 內容 | 現在能做？ |
| :-- | :-- | :-- | :-- |
| **M0.1a** U1a | tw-swing | `fundamentals.yml` 加 publish step：財報四表 + `per.parquet` + **`universe.parquet`（U3，新寫）** + `_meta.json` → 私有 Release tag `data-latest` | ✅ 現在（不碰 `daily.yml`） |
| **M0.1b** U1b | tw-swing | **新開** `publish_bundle.yml`：自己抓 store → 打包 `prices_adj`/`prices_raw_close`/`revenue`/`index_0050` → 併進同一 Release | ✅ 現在（新 workflow，不碰 `daily.yml`） |
| **M0.2** repo + 佈署 | tw-hold | 推 GitHub（**public**）、Streamlit Cloud 骨架、PAT 走 `st.secrets`、rebuild.yml | ✅ |
| **M0.3** 遷移 | 兩邊 | `twswing.value` 整包（**含 loader**）搬 tw-hold、tw-swing 端刪除 | ✅ |
| **M0.4** 複製參考碼 | tw-hold | `regime.py` / finmind client / indicators 複製進 `reference/`，檔頭標 commit | ✅ |

🔴 **M0 的真正難點是 U3（`universe.parquet`）**——`twswing.data.universe` 只有
`stock_list()` / `equity_tickers()` / `restrict_to_equities()`，**沒有市值、沒有產業別**，是從零寫。
市值 = `收盤 × capital_stock / 10`（capital_stock 已在 `data/fundamentals/balance.parquet`）。
宇宙 = **市值前 500 ∪ 成交值前 500**（見 §3 為什麼）。產業別用 `data/fundamentals/industry.parquet`。

---

## 2. 前一棒已完成的地基（都 commit 了，別重做）

### tw-swing（commit `57d81e7`→`5b2bb72`）

| 檔 | 狀態 |
| :-- | :-- |
| `data/fundamentals/balance.parquet` | ✅ 500 檔、含 `capital_stock` + `cash`（M0.1a「先修補抓」那條**已完成**——欄位本來就在 `BALANCE_FIELDS`，舊資料是加欄前抓的，備份後刪檔全量重抓） |
| `data/fundamentals/{income,cashflow,dividend}.parquet` | ✅ 現成 |
| `data/fundamentals/industry.parquet` | ✅ **F2 新增**（3147 檔，`stock_id / industry / stock_name / type`）。`TaiwanStockInfo` 已加進 `finmind.FREE_DATASETS` 白名單 |
| `data/fundamentals/prices_raw.parquet` | ✅ **F3 新增**（未還原日線，500 檔 2015–2026，1.32M 列）。⚠️ 只給填息率／定存回溯用，**不進 `daily.yml`、不進掃描、不進 tw-swing 回測** |
| `scripts/fetch_raw_prices.py` | ✅ 新腳本（F3 用）。續跑可用 |
| `src/twswing/value/loader.py` | 🔴 **修了一個真 bug**（見 §5.1）——搬去 tw-hold 時**帶著這個修正** |

### tw-hold（commit `63c2500`→`1d32d92`）

| 檔 | 用途 |
| :-- | :-- |
| `research/backtest_rebalance.py` | 實驗 B 回溯腳本（季換股、含息、公告日遞延、生存者偏差）。**M0 的 `build_factors.py` 可參考它的 screen 呼叫方式** |
| `research/candidate_pool_survey.py` | 實驗 D。**候選池的條件邏輯（CANSLIM + Minervini 8 條全寫成狀態）在這裡，M0/M1 實作候選池時直接搬** |
| `research/check_raw_prices.py` | 除息跳空守門（G2）。**每次重抓 `prices_raw` 後跑一次** |
| `docs/reports/{expectations,rebalance_backtest,candidate_pool_survey}_*.md` + `rebalance_*.csv` | 實驗產出 |

---

## 3. 🔴 定存線是壞的——M0 要處理的第一件事

實驗 B 完整版：定存線含息年化 **+10.8%** vs 0056 **+16.4%**、回撤 **−25%**（0056 −17%）、
**2024–2026 每季只有 2 檔合格**。

**根因**：`data/fundamentals/` 的 universe 是 `fetch_fundamentals.py` 用**成交值**前 500 抓的。
台股最安靜的大型定存股（某些金控／傳產）成交值排不進 500 → 剩下能過「殖利率 ≥ 5% +
七道硬門檻」的，全是**波動大的中小型高息股**，等權 2–10 檔 = 集中賭注，不是低波動組合。

**M0 的解**（PLAN §M0.1a 已寫）：`universe.parquet` 的宇宙 = **市值前 500 ∪ 成交值前 500**。
市值算得出來了（`capital_stock` 已補齊）。這會把安靜的大型金融傳產納入。

⚠️ **但要重抓那些新納入標的的財報**——`data/fundamentals/` 目前只有成交值前 500 的四表。
市值前 500 多出來的（估計 50–150 檔）要補抓 income/balance/cashflow/dividend/per/prices_raw。
→ **M0.1a 的順序**：先寫 U3 算出「市值前 500 ∪ 成交值前 500」的清單 → diff 出缺的 → 補抓 → 才有完整地基。

⚠️ **5% 殖利率硬底線本身也很緊**（台股大盤殖利率 3–4%）。使用者裁決值是「目標 5.5%、硬底線 5%」
（PRD §7.0.1）。U3 修好後若候選還是太少，**回報使用者**，不要自己放水到 4%。

---

## 4. tw-swing 這邊的紅線與待辦

### 🔴 紅線（M0 期間絕對不碰）
- **不改 `daily.yml`**（在 G-5 的 60 天時鐘上，斷一次跳明年 2 月）
- **不改 `rules.yaml` / `portfolios` / pipeline / 回測**
- U1a 只動 `fundamentals.yml`；U1b **新開** `publish_bundle.yml`

### Y4 → pool2（使用者原則同意，卡工程）
真實成交口徑下 Y4 是 tw-swing 五條裡最強的（每筆超額 +0.66%、樣本外驗證段比訓練段還好、
回撤 −12.5%，只 FAIL ②a MAR）。**比現在 live 在 pool2 的 V6-trailatr2 好。**
🔴 但 Y4 進場要 `revenue_accel` / `pe_percentile`，`daily.yml` 的 CI runner 沒這批資料 →
`daily_list.py` 偵測到會**硬失敗拒絕產清單** → G-5 斷。
**M0.1b 的 U1b 順便解這個**（FinMind 資料進 Release → 佈給 CI）。U1b 做完後另開一輪把
`portfolios.pool2` 換成 `pool2_y4`（`[V6-trailatr2, Y4]`），**那是 tw-swing 的事、不是 M0 的事**。

### tw-swing 這場改過的東西（遷移 loader 時要知道）
- `backtest_rules.py` 加 `--entry-at {signal_close,next_open,limit_at_close}`
- `engine.py` 加 `entry_at="limit_at_close"`（限價單成交模型）
- `paper_update.py` 主口徑改成 `limit_at_close`（模擬單反映真實成交）
- `finmind.py` `FREE_DATASETS` 加 `TaiwanStockInfo`
- 這些**都不影響 M0**，只是別看到 diff 以為是誰亂改

---

## 5. 這場踩到的坑（M0 會再遇到）

### 5.1 `equity_parent` 取錯欄位（已修，`value/loader.py` commit `63711c2`）
損益表的 `EquityAttributableToOwnersOfParent` = 歸屬母公司**淨利**（≈ net_income），
資產負債表的同名欄位才是歸屬母公司**業主權益**。舊 `load_quarterly` 的「以損益表為準」是反的
→ `roe = 淨利 / 淨利 ≈ 3～4`。修後 roe 正常（中位數 11.7%、TSMC 34.8%）。
🔴 **搬 loader.py 去 tw-hold 時帶著這個修正。** roe 仍有離群值（股本小/負權益的公司），
screen 用 rank 所以影響有限，但別當它乾淨。

### 5.2 ticker 格式：裸代號 vs `.TW`
- 財報四表、`dividend`：**裸代號**（`1101`）
- 日線 `store`、`revenue`、`inst`、`prices_raw`、`industry.parquet`：**`1101.TW` / `1101.TWO`**
- `fd._code_to_ticker_map()`（`twswing.data.fundamentals`）給 `1101 → 1101.TW`
🔴 **不統一就靜默 merge 出全 NaN**——這場在實驗 D 和 B 各中一次。M0 的 `build_factors.py` 一定要處理。

### 5.3 `Throttle.seed()` 會死等一小時
`finmind.Throttle.seed(n)` 把 n 個**同時間戳**灌進滾動視窗，滿了就一次 `sleep(~3600s)`。
F3 首跑卡在這裡 47 分。`fetch_raw_prices.py` 改成**不 seed**（只靠 `min_gap` 節流，撞上限吃 402 退避）。
🔴 **M0 的 publish workflow 抓 FinMind 時，rate 設保守（≤450/hr）、不要 seed，或先確認 quota 有餘裕。**
`fetch_fundamentals.py` 還有 seed（跑得完但慢），要動它的話一起改。

### 5.4 FinMind 免費層 / 額度
- Token 600/hr。`RATE_CEILING = 500`（tw-swing）。
- 免費層可取：見 `finmind.FREE_DATASETS`（含 `TaiwanStockPrice`、`TaiwanStockInfo`、
  `TaiwanStockPER`、財報三表、`TaiwanStockDividend` / `TaiwanStockDividendResult`、
  月營收、法人、融資券）。`TaiwanStockPriceAdj`（還原價）**免費層拿不到**。
- ⚠️ 避開 `fundamentals.yml` 週六排程（UTC 週六 02:00 = 台灣週六 10:00）。
- 🔴 Actions 分鐘數是**帳號級共用**，tw-swing 私有 repo 上限自訂 1600/2000。
  U1b 的 220MB 資料包**必須 `actions/cache`**，否則每月多吃 ~330 分（PRD §10.1）。

### 5.5 `prices_raw_close` 每日增量不要逐檔抓
歷史已用 FinMind 一次性回補（`prices_raw.parquet`）。每日增量照 PRD §10.3：
**TWSE/TPEx OpenAPI 收盤整批（1 req/日）**，不是每天 500 檔逐檔（那是每天一小時純抓取）。

---

## 6. 建議順序

0. 讀本檔 + `PLAN.md` §M0 + `PRD.md` §3（bundle）§5（候選池）§6（價值）§7（定存）
1. **M0.3 遷移**先做（最確定、無外部依賴）：`twswing.value` 整包搬 tw-hold `factors/`+`screener/`+`reference/loader.py`，
   改 import，tw-swing 端刪 `value/` + `build_value_factors.py` + `test_value.py`，兩邊 `pytest` 綠
2. **M0.4 複製參考碼**（`regime.py` / finmind client / indicators → `reference/`，檔頭標 commit）
3. **U3（`universe.parquet`）**：市值 + 產業別 + 「市值前 500 ∪ 成交值前 500」→ diff 出缺的財報 → 補抓
4. **M0.1a U1a**：`fundamentals.yml` 加 publish step → 私有 Release `data-latest`
5. **M0.2 tw-hold repo**：推 GitHub public（先掃 token/持倉）、Streamlit 骨架、`build_factors.py` 讀 bundle
6. **M0.1b U1b**：新開 `publish_bundle.yml`（`actions/cache`！+ `notify-failure`）
7. 定存線用 U3 修正後的宇宙**重跑一次實驗 B**，更新 `expectations_20260907.md`
8. 回報使用者

### 入口點
| 要做 | 讀 |
| :-- | :-- |
| M0 全貌 | `tw-hold/docs/PLAN.md` §M0 |
| 為什麼這樣設計 | `tw-hold/PRD.md`（v3.1，§3.1.1 拆 M0a/M0b 的理由、§10 失敗模式） |
| 四個實驗結論 | `tw-hold/docs/BACKTEST_HANDOFF.md` + `docs/reports/*_20260907.md` |
| tw-swing 現況 | `tw-swing/docs/STATUS.md`〈一分鐘接手〉（**先看 G-5 管線今天沒斷**） |
| 遷移清單 | `PLAN.md` §M0.3 表 + `tw-swing/PRD.md` §7.1.1 |

⚠️ **開工前**：`git status` 兩個 repo 都應該乾淨（前一棒全 commit 了）。
tw-swing 的 G-5 關鍵路徑仍優先——`python scripts/check_daily.py` 確認管線沒斷再動 M0。
