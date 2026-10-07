# 數據流、依賴與救援手冊（tw-swing + tw-hold）

> 2026-10-03 盤點。目的：**確認未來任何時候，資料斷了都有辦法救**，並誠實標出「救不回來」與「目前沒有備案」的地方。
> 時間一律台北時間（UTC+8）。`gh` 已登入 tongxiaooppo-boop，下面的救援指令都能直接跑。
> 這份是**事實盤點**，不是設計文件；改了排程／來源請同步更新。

---

## 0. 一張圖

```
【外部來源】                              【tw-swing（私有 repo）】                         【tw-hold（公開 repo）】
maosof007 data_pack.zip ─┐
  (日線還原+法人+融資券)  ├─> daily.yml(21:07/01:07/05:32) ──> update_data.py ──> data/store/（不進git）
TWSE/TPEx OpenAPI ───────┤     ├ 處置股快照 ─┐                   │
TDCC 開放資料 ────────────┤     ├ 月營收快照 ─┼─ commit 回 repo   └─> daily_list.py ─> data/daily/*.json (進git)
FinMind(token) ──────────┤                                                              │
                         │   publish_bundle.yml                                         ▼
                         │     ① workflow_run(daily完成) ② cron 06:09/07:09/08:38  share-latest.json ──(原生渲染)──┐
                         │     └ bundle_gate(新鮮度) → build_u1b_bundle ─> Release data-latest                        │
                         │         (prices_adj/prices_raw_close/chips/margin/revenue/index_0050/universe/財報五表)     │
                         │                                    │ repository_dispatch(TWHOLD_DISPATCH_PAT)            │
                         │   fundamentals.yml(週六10:07) ─ FinMind 財報/月營收歷史/TDCC週快照 ─ commit + U1a bundle     │
                         │                                    ▼                                                       │
FinMind(006201) ─────────┼───────────────────────────> rebuild.yml(dispatch主 + cron 16:17備援)                        │
TWSE STOCK_DAY_ALL ──────┤                               ├ fetch_bundle(PAT) ─> data/upstream/                         │
投信官網 PCF×3 ───────────┤                               ├ build_lists ─> value/deposit/swing_list.json                │
                         │                               ├ snapshot_pcf + build_active_etf_flags                       │
                         │                               ├ build_short_scan ─> short_scan.json                         │
                         │                               └ commit data/derived/ ──> Streamlit Cloud app 讀 ◄───────────┘
yfinance ────────────────┤   global_macro.yml(06:37)  ─ 國際指數/台指期日夜盤/外資淨空單/三大法人 ─ commit data/reference/
TAIFEX(OpenAPI+CSV) ─────┤   chip_flow_evening.yml(18:28) ─ 外資淨空單/三大法人（補當日）
TWSE BFI82U ─────────────┘   pcf_retry.yml(17:13/19:13) ─ PCF 補跑      heartbeat.yml(08:28) ─ 只檢查不修
```

---

## 1. 外部來源與依賴（誰是單點）

| # | 來源 | 我們拿什麼 | 驗證/認證 | 有歷史可回補？ | 掛了的後果 | 目前備案 | 風險 |
| :-: | :-- | :-- | :-- | :-- | :-- | :-- | :-: |
| 1 | **他人 repo `maosof007-collab/tw-stock-scanner` 的 `data_pack.zip`**（Release `data-v1`，220MB） | **還原日線、法人買賣超、融資券**（tw-swing 全部日線規則＋tw-hold 全部日線的唯一來源） | 無（公開 Release） | 整包完整歷史 2015 起 | tw-swing 日線／籌碼／融資券全停；bundle 停更；tw-hold 清單停在舊日 | ⚠️ **L2/L3 自建「尚未實作」**（`update_data.py` 檔頭明講）；只有保存的 workflow 藍圖 `tw-swing/docs/reference/upstream_datapack_workflow.yml` ＋ `twse_tpex_pitfalls.md`；本機有一份舊 zip（09-03） | 🔴 |
| 2 | FinMind API（`FINMIND_TOKEN`） | 財報五表、`TaiwanStockPrice`（006201、未還原收盤歷史）、分割事件（`resolve_splits`）、歷史 PER | token，免費層有額度 | 有（但免費層部分端點回 400，如 TDCC 歷史） | 財報週更停、006201 停、分割解析停 | 財報已 commit 進 repo（可回退）；006201／0050 守門員（`price_series_guard`）保留舊檔 | 🟡 |
| 3 | TWSE／TPEx OpenAPI（`openapi.twse.com.tw`、`tpex.org.tw/openapi`） | 處置股、月營收、PER/PBR/殖利率每日快照 | 無 | **多數只給最新一天，無歷史** | 當天快照漏掉＝**永久缺** | 無（見 §4 不可回補表） | 🟡 |
| 4 | TDCC 開放資料 `opendata.tdcc.com.tw` | 集保股權分散週快照 | 無 | 無（只有最新一週） | 該週永久缺 | 無 | 🟢（規則挖掘 2029 前用不到） |
| 5 | TAIFEX：OpenAPI `DailyMarketReportFut`、網站 CSV `futContractsDateDown` | 台指期日夜盤、外資期貨未平倉 | 無 | 日夜盤**無**；外資期貨 CSV **有（3 個月/次）** | 日夜盤該天夜盤永久缺；外資淨空單可補回 | 外資：CSV 主＋OpenAPI 備；每次重抓近 14 天自癒 | 🟢 |
| 6 | TWSE `www.twse.com.tw/rwd/zh/fund/BFI82U` | 三大法人買賣超 | 無（⚠️ `openapi.twse` 同名端點回 HTML，別用） | **有（帶日期）** | 補近 14 天缺的平日自癒 | 無需 | 🟢 |
| 7 | yfinance（Yahoo） | 國際指數/個股/總經 | 無 | 每次全量重抓 2 年 → 自癒 | 當天缺但隔天補齊；Yahoo 介面改版全停 | 無（單源） | 🟡 |
| 8 | 投信官網 PCF×3（統一 ezmoney / 群益 capitalfund / 復華 fhtrust）＋TWSE `STOCK_DAY_ALL` | 主動 ETF 持股、規模、折溢價 | cookie／內部 API，**非官方承諾** | **無（只給當天）** | 該天缺＝前後兩日差分跨日；三家各自可能改版 | `pcf_retry.yml`（17:13/19:13）當日補跑；差分用 `span_days` 標示跨日 | 🟡 |
| 9 | GitHub（Actions／Release／repo） | 排程、bundle 儲存、資料版控 | 兩顆 PAT（見 §5） | — | 全部 | 本機備份（`backup/backup.ps1`，D→G 鏡像＋memory→OneDrive）；兩 repo 皆有 GitHub 遠端 | 🟡 |
| 10 | Streamlit Cloud | app 託管 | secrets：`TWSWING_BUNDLE_PAT` | — | app 打不開（資料不受影響） | 資料都在 repo，換託管可重建 | 🟢 |

---

## 2. 「自己抓」的腳本清單

**tw-swing**（資料收集）：
| 腳本（`scripts/`） | 抓什麼 | 來源 | 在哪個排程 |
| :-- | :-- | :-- | :-- |
| `update_data.py`（呼叫 `import_data_pack.py`＋`import_chips.py`＋`apply_chips_baseline.py`） | 還原日線／法人／融資券 | **data_pack.zip（#1）** | daily、publish_bundle |
| `fetch_watchlist.py` | 處置／注意股 | TWSE/TPEx（#3） | daily |
| `fetch_revenue.py` | 月營收當日快照 | TWSE/TPEx（#3） | daily |
| `fetch_valuation.py` | PER/PBR/殖利率每日快照 | TWSE/TPEx（#3） | publish_bundle |
| `fetch_fundamentals.py` | 財報五表（每週一批） | FinMind（#2） | fundamentals |
| `append_revenue_history.py` | 月營收長表併入 | 版控快照 | fundamentals |
| `append_tdcc_history.py` | 集保週快照 | TDCC（#4） | fundamentals |
| `fetch_raw_prices.py` / `fetch_finmind.py` | 未還原收盤、籌碼底稿（一次性/手動） | FinMind（#2） | 手動 |

**tw-hold**（資料收集）：
| 腳本 | 抓什麼 | 來源 | 在哪個排程 |
| :-- | :-- | :-- | :-- |
| `fetch_bundle.py`（根目錄） | 拉 tw-swing 的 Release bundle | GitHub Release（PAT） | rebuild |
| `scripts/promote_index_0050.py` | 0050 小檔驗證後搬進 repo | bundle | rebuild |
| `scripts/fetch_index_proxy.py` | 006201 | FinMind（#2） | rebuild |
| `scripts/resolve_splits.py` | 分割事件 | FinMind（#2） | rebuild |
| `scripts/snapshot_pcf.py`（＋`pcf_fetchers.py`） | 主動 ETF PCF | 投信官網（#8） | rebuild、pcf_retry |
| `scripts/fetch_global_macro.py` | 國際指數/總經 | yfinance（#7） | global_macro |
| `scripts/fetch_tx_futures.py` | 台指期日夜盤 | TAIFEX（#5） | global_macro |
| `scripts/fetch_foreign_futures.py` | 外資期貨未平倉 | TAIFEX（#5） | global_macro、chip_flow_evening |
| `scripts/fetch_inst_flow.py` | 三大法人買賣超 | TWSE（#6） | global_macro、chip_flow_evening |

合計：tw-swing 約 **8 支＋上游匯入鏈**（`update_data`→`import_data_pack`／`import_chips`／`apply_chips_baseline`）、tw-hold **9 支**（含 bundle 拉取），**8 條排程 workflow**（tw-swing 3：daily／publish_bundle／fundamentals；tw-hold 5：rebuild／global_macro／chip_flow_evening／pcf_retry／heartbeat，詳見 §3）。

---

## 3. 排程與觸發鏈（台北時間）

| Workflow | 觸發 | 備援 | 手動 | 產出 |
| :-- | :-- | :-- | :-- | :-- |
| **tw-swing `daily.yml`** | 21:07／01:07／05:32（三槍，平日） | 三槍本身互為備援；第三槍 `--require-fresh` | ✅ dispatch | `data/daily/*.json`、模擬單、share-latest.json |
| **tw-swing `publish_bundle.yml`** | ① **`workflow_run`（daily 完成即接）** ② cron 06:09／07:09／08:38 | 三個 cron＋閘門（`bundle_gate.py`，沒新資料就跳過，取不到資訊一律發佈） | ✅ dispatch（**不過閘門**，救援用） | Release `data-latest`（13 個資產）＋`repository_dispatch` 叫 tw-hold |
| **tw-swing `fundamentals.yml`** | 週六 10:07 | — | ✅ | 財報五表／TDCC／月營收歷史，U1a bundle |
| **tw-hold `rebuild.yml`** | **`repository_dispatch`（publish 完）** | cron 16:17（UTC 08:17，實測落在 22:00–00:00） | ✅ | `data/derived/*`（三清單、flags、short_scan）、`derived-latest` Release |
| **tw-hold `global_macro.yml`** | 06:37 | 傍晚 18:28 班補外資/三大法人 | ✅ | `data/reference/*` |
| **tw-hold `chip_flow_evening.yml`** | 18:28（平日） | 06:37 那班 | ✅ | `foreign_futures.parquet`、`inst_flow.parquet` |
| **tw-hold `pcf_retry.yml`** | 17:13／19:13 | rebuild 內也有一次 | ✅ | `data/pcf/`、`active_etf_flags.json` |
| **tw-hold `heartbeat.yml`** | 08:28 | — | ✅ | **只檢查不修**（實測 GitHub 延遲到 13:00–14:00 才跑） |

**時間鏈（目標）**：data_pack 05:08 好 → daily 第三槍 05:32（實落 05:4x）→ publish ~05:50 → rebuild ~05:55 → 清單開盤前更新。
⚠️ **新時間鏈（workflow_run 接 daily＋閘門放行）尚未在真實環境驗過**，週一 10-05 才有第一輪（見 HANDOFF_2026-10-03 §3）。

---

## 4. 漏抓／壞掉之後：能補、補不回、怎麼救

### 4.1 可自癒（不用人管）
| 資料 | 為什麼 |
| :-- | :-- |
| 外資期貨未平倉 | CSV 每次重抓近 14 天 upsert，首次回補 90 天 |
| 三大法人買賣超 | 每次補近 14 天缺的平日（可帶日期） |
| 國際指數/總經 | yfinance 每次全量 2 年覆寫 |
| 日線／法人／融資券（只要 data_pack 還活著） | 整包完整歷史、`update_data` 全量冪等重匯 |
| 財報 | 每週一批滾動、已 commit |

### 4.2 🔴 **漏了就永久補不回**（只能事前防止、事後註明「歷史未涵蓋」）
| 資料 | 原因 | 現有防護 | 殘餘風險 |
| :-- | :-- | :-- | :-- |
| **處置股／注意股快照** | TWSE/TPEx 只給當前清單 | daily 三槍＋「先做且失敗不擋」 | 三槍全掛那天缺；該區間「歷史一律未排除」 |
| **月營收當日快照（`first_seen` 可用日）** | 同上，沒有歷史序列 | 同上 | 影響 PEAD 類回測的「可用日」 |
| **PER/PBR/殖利率每日快照** | 只給最新一天（歷史靠 FinMind 一次性回補） | publish 內每日刷新 | 缺的那天沒有快照 |
| **主動 ETF PCF** | 各家只給當天 | pcf_retry＋rebuild 內各一次 | 該天缺 → 差分跨日（`span_days`），不是錯但粗 |
| **台指期夜盤收盤** | API 只回最新一天、`date` 參數無效 | 夜盤缺失才告警（但**沒設 webhook＝靜默**） | 該夜永久缺 |
| **TDCC 週快照** | 只有最新一週 | fundamentals 週六抓 | 該週缺（規則挖掘 2029 前用不到） |

### 4.3 手動救援指令（都已實測可用）

| 症狀 | 救援 |
| :-- | :-- |
| 清單停在舊日、bundle 沒更新 | `cd tw-swing && gh workflow run publish_bundle.yml --ref master`（**不過閘門**，會發佈並叫 tw-hold 重算）。先看 daily 有沒有跑：`gh run list --workflow daily.yml --limit 5` |
| daily 沒跑／失敗 | `gh workflow run daily.yml --ref master`（冪等，當日清單已存在會 SKIP） |
| tw-hold 清單沒重算（bundle 已發佈、dispatch 沒送到） | `cd tw-hold && gh workflow run rebuild.yml --ref main`（或等 cron 16:17 備援） |
| 總經導航卡片停更 | `gh workflow run global_macro.yml --ref main`（外資/三大法人另有 `chip_flow_evening.yml`） |
| 主動 ETF 旗標缺天 | `gh workflow run pcf_retry.yml --ref main`（當天內才補得到） |
| 本機要最新資料（本機無自動化、`data/store/` 不進 git） | `cd tw-swing && python scripts/update_data.py "D:/g/claude/books/claude/tw-stock-scanner-main-data/data_pack.zip"`（⚠️ 預設路徑已不存在，必須帶路徑；跑完 `git checkout --` 還原被改髒的 `data/revenue/`、`data/watchlist/` 當日檔再 `git pull`） |
| 短線掃描凍結（缺料守衛）／要重置進榜追蹤 | 刪 `tw-hold/data/derived/short_scan.json` 後等下一輪 rebuild，或手改 `_meta.has_margin/has_chips` |
| Streamlit 噴 `AttributeError ... no attribute` | Manage app → Reboot（舊模組快取，非 bug） |
| 本機要對照 CI 的 bundle | `cd tw-hold && python fetch_bundle.py`（需 `.env` 的 `TWSWING_BUNDLE_PAT`，約 5 分鐘） |

### 4.4 **上游 data_pack 死掉時的救法（目前只有藍圖，沒有實作）**
這是**最大的洞**。現況能做的：
1. **止血**：bundle 是滾動覆寫，Release 上最後一份好資料會一直留著（日線 1200 天、法人全期、融資券 400 天），tw-hold 不會立刻壞，只是停在最後一天。`bundle_gate` 在上游停更時不會發佈新版（不會用壞資料覆蓋）。
2. **短期（落後 1–5 天）**：沒有程式——`update_data.py` 的 L2「自建 TWSE/TPEx 補洞」**尚未實作**。
3. **長期（> 5 天）**：藍圖＝`upstream_datapack_workflow.yml`（yfinance 還原歷史一次性＋官方每日 append＋`price_adjuster` 補分割）＋`twse_tpex_pitfalls.md`。**最難的不是抓，是還原股價**（官方給未還原價，直接接會在每次除權息生出假跳空，污染所有均線指標）。
4. 實際動工的觸發條件：資料包 `Last-Modified` 超過 30 小時未更新（`update_data.py --require-fresh` 已會在第三槍報錯）。

---

## 5. 憑證與到期（過期＝整條鏈斷）

| 憑證 | 用途 | 放哪 | 到期 | 過期後果 |
| :-- | :-- | :-- | :-- | :-- |
| `TWSWING_BUNDLE_PAT`（tw-hold-bundle-read，唯讀 tw-swing contents） | tw-hold 拉 tw-swing 私有 Release | tw-hold `.env`＋tw-hold Actions secret＋Streamlit Cloud secret（**三處**） | **~2026-12-07**（11-30 起提醒） | rebuild 的 `fetch_bundle` 失敗、個股查詢頁拉不到 bundle |
| `TWHOLD_DISPATCH_PAT`（Actions:write 到 tw-hold） | tw-swing publish 後叫 tw-hold 重算 | tw-swing Actions secret | **~2027-09-08**（08-25 起提醒） | 沒有 dispatch → 只剩 cron 16:17 備援（清單晚更新，不是斷） |
| `FINMIND_TOKEN` | 財報／006201／分割 | tw-swing＋tw-hold Actions secret | 不明（免費層額度） | 財報週更、006201、分割解析停 |
| `ALERT_WEBHOOK` | 所有 notify-failure／告警 | — | **從沒設過**（使用者回絕設定） | **所有告警步驟形同空的**，只剩 GitHub 紅叉與 heartbeat |

---

## 6. 目前沒有備案／偏弱的地方（要知道、不一定要修）

1. 🔴 **data_pack 單點**：L2/L3 自建未實作（§4.4）。
2. 🔴 **告警是啞的**：`ALERT_WEBHOOK` 沒設，失敗只留在 Actions 紅叉；使用者偏好「自癒優於告警」，但**自癒只做到部分資料**（§4.1）。
3. 🟡 **心跳只檢查不修**，且 GitHub 延遲到 13:00 才跑；已知 bug（2026-10-03 重驗屬實）：`heartbeat.yml` 檢查步驟第二行 `freshness_check.py --json > ...` 缺 `|| true`，過期時 job 直接紅燈、後面告警步驟沒機會跑。
4. 🟡 **Release `data-latest` 用 `--clobber` 覆蓋，沒有歷史版本**：上游若某天吐壞資料並通過閘門，好版本就被蓋掉（`price_series_guard` 只守 0050/006201 小檔；整包日線只有 G1 的 sha256＋欄位檢查，沒有「內容縮水」檢查）。回退靠 tw-swing 本機 store＋備份。
5. 🟡 **Actions 快取（220MB 資料包）會被 7 天未使用 evict**；快取沒了就重下載，上游死了就沒得下載。
6. 🟡 **主動 ETF PCF 依賴非官方端點**（三家各自可能改版），有 `span_days` 容錯但沒有「改版偵測」。
7. 🟡 **tw-swing 私有 repo 每月 2000 分鐘**（上次查 195/2000）；tw-hold 公開 repo 無限。
8. 🟡 **本機沒有自動化**，`data/store/` 不進 git；本機備份只有「D→G 鏡像週跑＋memory→OneDrive 日跑」，`backup.ps1` 對 tw-swing 排除 `data\raw`、`data\store`、`data\cache`、`data\scan`（2026-10-03 重驗）——上游死了就**沒有第二份歷史**，除了 Release 上的 bundle 與 `books\claude\...\data_pack.zip`（09-03 舊版）。

> 📌 **上游單點的長期解法已列入計畫（2026-10-03，使用者定調「hold 未來建立自己的上游」，**不是今天做**）：見 `docs/PLAN_OWN_UPSTREAM.md`。
> 重點：**TPEx 日線端點只回最新一天**，所以「影子收集」要比還原引擎更早開始；現有上游當種子與對帳基準，不做鏡像轉載。

### 建議的補強順序（都還沒做）
1. **把最新 `data_pack.zip` 定期留一份到 G 碟／另一處**（成本最低、直接堵 #1 的最壞情況：至少有 2015→某日的完整歷史可重建）。
2. 修 `heartbeat.yml` 的 `|| true`，並讓它偵測過期時 `workflow_dispatch` 觸發 rebuild（自癒；使用者偏好）。
3. `bundle_gate` 加「日線最新一天檔數／總列數不得明顯少於前一版」的內容縮水檢查（同 short_scan 的 `_thin_latest` 思路），擋住壞上游覆蓋好 bundle。
4. 寫 L2（官方每日 append 補洞）——僅在上游真的出事時才動，先備好 §4.4 的觸發條件。
5. 兩顆 PAT 到期前日曆提醒（11-30、2027-08-25）；有每週雲端 routine「tw-hold 週檢」對照。
