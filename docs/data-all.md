# data-all.md — 數據抓取＋運算總表（階段 1 → 2 → 3）

> 2026-10-06 整理。範圍：tw-swing、tw-hold 中「資料抓取與資料運算」的程式；不含 UI 頁面、策略規則細節、AI 層。
> 說明依各檔檔頭與 workflow 整理，**排程時間為台北時間**；沒有逐行驗證程式行為。互動版見 [data-all.html](data-all.html)。

**狀態**：已上線＝Actions／雲端已在跑｜本機已 commit・未 push＝只在本機，下游沒人用｜規劃中＝還沒做。

## 一圖看三階段

```
階段1  他人 data_pack ─→ tw-swing(母表→掃描→清單→bundle) ─Release→ tw-hold(拉bundle→三清單→app)
                  官方OpenAPI/FinMind ─→ tw-swing 基本面/估值/集保/處置股；tw-hold 總經/PCF
階段2  TWSE/TPEx 官方端點 ─→ selfhost_* (raw_prices/inst/margin/事件表) ─→ 還原價/事件簿/對帳   [僅本機]
階段3  15日驗證→決定（切自建／維持上游／全停）→接縫訂正→下游接線                      [規劃]
```

## 階段 1　現況（前天 10-04 以前）

日線與籌碼依賴他人 repo 的 data_pack.zip（單點依賴）；基本面、估值、集保、處置股由 tw-swing 自抓，bundle 經 Release 交給 tw-hold。

*tw-swing 抓、算、發 bundle；tw-hold 拉 bundle、算三清單、自抓總經與 PCF。*

### tw-swing（19 項）

| 檔案 | 類型 | 抓什麼／做什麼 | 輸出 | 排程 | 狀態 |
| :-- | :-: | :-- | :-- | :-- | :-: |
| `scripts/update_data.py ＋ import_data_pack.py` | 抓取 | 他人 repo（tw-stock-scanner）的 data_pack.zip：日線 2015 起全量重匯（冪等）；L1 偵測母表落後並告警；串起 import_chips → apply_chips_baseline | data/store 日線母表 parquet | daily.yml 台北 21:00／01:00／05:30 | 已上線（排程自動跑） |
| `scripts/import_chips.py` | 抓取 | data_pack 內的三大法人、融資券、股票清單 → 籌碼母表 | data/store 籌碼母表 | 隨 update_data | 已上線（排程自動跑） |
| `scripts/apply_chips_baseline.py ＋ pack_chips_baseline.py` | 運算 | 把 FinMind 修好的籌碼歷史底稿（cutoff 以前）疊回重匯後的母表；底稿放 GitHub Release | 籌碼母表（歷史段） | 隨 update_data | 已上線（排程自動跑） |
| `scripts/merge_finmind.py ＋ verify_chips_twse.py ＋ audit_chips.py` | 守門 | FinMind 整段取代籌碼歷史（預設只對帳）；TWSE 官方當第三來源抽驗；母表完整性稽核（缺日、複本、空值） | 稽核報告 | audit_chips 隨 daily | 已上線（排程自動跑） |
| `scripts/fetch_finmind.py ＋ src/twswing/data/finmind.py` | 抓取 | FinMind 取數工具（節流、續跑、落地）；刻意不併入現有管線 | data/finmind（gitignore） | 手動 | 已上線（排程自動跑） |
| `scripts/fetch_raw_prices.py` | 抓取 | FinMind TaiwanStockPrice 未還原日線收盤 | data/fundamentals/prices_raw.parquet | 手動／補洞 | 已上線（排程自動跑） |
| `scripts/fetch_watchlist.py ＋ src/twswing/data/watchlist.py` | 抓取 | TWSE／TPEx 處置股、注意股清單（無歷史，每天不抓即永久缺） | data/watchlist 每日快照 | daily.yml | 已上線（排程自動跑） |
| `scripts/fetch_revenue.py ＋ append_revenue_history.py ＋ build_revenue_history.py` | 抓取 | OpenAPI 月營收（只回最新一期）每日快照 → 併回版控的 revenue_history.parquet | data/revenue 快照、fundamentals/revenue_history.parquet | daily（快照）、週六（併檔） | 已上線（排程自動跑） |
| `scripts/fetch_valuation.py ＋ build_per_parquet.py` | 抓取 | TWSE／TPEx 每日 PER／PBR／殖利率增量 | data/valuation 快照、fundamentals/per.parquet | publish_bundle.yml | 已上線（排程自動跑） |
| `scripts/fetch_fundamentals.py` | 抓取 | FinMind 財報三表、股利、產業；每週限速跑一批累積成整併檔 | fundamentals/income、balance、cashflow、dividend、industry.parquet | fundamentals.yml 週六台北 10:00 | 已上線（排程自動跑） |
| `scripts/append_tdcc_history.py ＋ src/twswing/data/tdcc.py` | 抓取 | TDCC 集保股權分散表（只回最新一週，漏一週永久缺） | data/tdcc 週快照 | fundamentals.yml 週六 | 已上線（排程自動跑） |
| `scripts/build_universe.py` | 運算 | 標的宇宙（市值、成交值排名） | fundamentals/universe.parquet | publish_bundle | 已上線（排程自動跑） |
| `scripts/build_u1b_bundle.py ＋ make_bundle_meta.py ＋ bundle_gate.py` | 運算 | 打包日更 bundle 給 tw-hold，寫 _meta.json（唯一正式介面）；新鮮度閘門（本機 store 比 Release 新才發） | Release tag data-latest | publish_bundle.yml 台北 06:00／07:00／08:30 | 已上線（排程自動跑） |
| `src/twswing/screener/precompute.py ＋ engine.py` | 運算 | 指標預計算（所有規則共用欄位算一次）＋全市場掃描引擎（唯一掃描實作） | 掃描結果 | daily | 已上線（排程自動跑） |
| `src/twswing/indicators/* ＋ rules/*` | 運算 | 均線、型態、樞紐、趨勢線、箱型；規則登錄與積木式進場條件 | — | daily | 已上線（排程自動跑） |
| `scripts/daily_list.py ＋ src/twswing/dashboard.py` | 運算 | 每日候選清單（HTML、CSV、分享版 share-*.json） | data/daily | daily | 已上線（排程自動跑） |
| `scripts/paper_capital.py ＋ src/twswing/paper/*` | 運算 | 資金天花板模擬單（各自 100 萬＋市值前 N）、台帳與權益曲線 | data/paper_capital | daily | 已上線（排程自動跑） |
| `scripts/check_daily.py ＋ heartbeat.py` | 守門 | 每日產出健檢、管線心跳（靜默斷掉看得見） | data/daily/_pipeline.csv | daily 尾端 | 已上線（排程自動跑） |
| `scripts/backtest_rules.py ＋ backtest_pools.py ＋ scan_history.py ＋ src/twswing/backtest/*` | 運算 | 規則逐條驗證、兩桶資金組合回測、歷史訊號掃描 | 回測報告 | 手動 | 已上線（排程自動跑） |

### tw-hold（13 項）

| 檔案 | 類型 | 抓什麼／做什麼 | 輸出 | 排程 | 狀態 |
| :-- | :-: | :-- | :-- | :-- | :-: |
| `fetch_bundle.py` | 抓取 | 從 tw-swing 私有 repo 的 Release（tag data-latest）拉 bundle，跑守門員 | data/upstream/ | rebuild.yml 台北 16:00 | 已上線（排程自動跑） |
| `scripts/fetch_index_proxy.py ＋ promote_index_0050.py` | 抓取 | FinMind 006201（櫃買代理）；bundle 內 0050 小檔驗證後複製 | data/reference 收盤序列 | rebuild.yml | 已上線（排程自動跑） |
| `scripts/fetch_global_macro.py` | 抓取 | yfinance 一天一次抓國際指數、美股已完成的常規盤收盤 | data/reference/global_macro | global_macro.yml 台北 06:00 | 已上線（排程自動跑） |
| `scripts/fetch_tx_futures.py ＋ fetch_foreign_futures.py ＋ fetch_inst_flow.py（10-03 加入）` | 抓取 | 台指期日盤／夜盤收盤；外資台指期未平倉淨空單；三大法人買賣超金額 | data/reference/*.json | global_macro.yml、chip_flow_evening.yml 台北 18:30 | 已上線（排程自動跑） |
| `scripts/snapshot_pcf.py ＋ pcf_fetchers.py` | 抓取 | 統一、群益、復華三家主動式 ETF 官網每日 PCF | data/pcf/<code>/<date>.parquet | rebuild.yml 備援、pcf_retry.yml 台北 17:00／19:00 | 已上線（排程自動跑） |
| `scripts/resolve_splits.py ＋ reference/corporate_actions.py` | 運算 | 自動解析未還原的分割、面額變更、減資；手動對照表補缺 | reference/corporate_actions_resolved.json | rebuild.yml | 已上線（排程自動跑） |
| `build_factors.py ＋ factors/factors.py ＋ reference/loader.py` | 運算 | 財報季度面板 → 價值／定存因子表 | data/derived/factors_*.parquet | rebuild.yml（由 build_lists.py 呼叫） | 已上線（排程自動跑） |
| `build_lists.py ＋ screener/{screen,pricing,deposit_pricing,candidate_pool,industry,gates}.py` | 運算 | 三清單（價值、定存、長波段候選池）：剔除門檻、買價、verdict、產業上限 | data/derived/*_list.json | rebuild.yml | 已上線（排程自動跑） |
| `screener/swing_stops.py ＋ swing_paper.py ＋ scripts/backfill_swing_history.py` | 運算 | 長波段出場觀察表（移動停損）、輕量版模擬單 | swing_stops.json、swing_paper.json、swing_history.json | rebuild.yml | 已上線（排程自動跑） |
| `build_active_etf_flags.py` | 運算 | 三家 PCF 每日快照差分 → 主動式 ETF 認領旗標 | data/derived/active_etf_flags.json | rebuild.yml、pcf_retry.yml | 已上線（排程自動跑） |
| `build_short_scan.py ＋ reference/chip_flow.py（10-03 加入）` | 運算 | 短線條件掃描第四名單（含融資券、進榜日期） | data/derived/short_scan.json | rebuild.yml | 已上線（排程自動跑） |
| `reference/{price_series_guard,freshness,chips_guard}.py ＋ check_upstream_drift.py ＋ scripts/freshness_check.py` | 守門 | 收盤序列落地前守門、新鮮度判斷、法人籌碼恆等式與補位、上游來源檔漂移偵測 | heartbeat／_meta.json | heartbeat.yml 台北 08:30 | 已上線（排程自動跑） |
| `app/*（streamlit_app、bundle_data、checklist、stockcharts）` | 運算 | 唯讀顯示層：執行期拉 Release、讀預算 JSON | — | Streamlit Cloud | 已上線（排程自動跑） |

## 階段 2　自建上游＋新增 py（10-05～10-06）

自己向 TWSE／TPEx 官方端點抓未還原日線、法人、融資券、事件表，自己重算還原價，並用事件簿與對帳工具檢查。全部在 tw-hold，已 push。**收集與閘門已在 Actions 排程上線（2026-10-06 起，資料存私有 repo）；還原、對帳、事件簿等分析腳本仍手動執行；尚無下游消費者**。

*只列「新增功能」；修 bug 不列（例：reference/chips_guard.py 的上櫃自營補位、tw-swing chips.py 補位、drop_future）。*

### tw-hold（17 項）

| 檔案 | 類型 | 抓什麼／做什麼 | 輸出 | 排程 | 狀態 |
| :-- | :-: | :-- | :-- | :-- | :-: |
| `scripts/selfhost_raw_prices.py` | 抓取 | TWSE MI_INDEX／TPEx dailyQuotes 官方未還原日線依日期收集（每個回應斷言自己的日期）。10-06 增補：官方漲跌價差 chg、無成交旁表 notrade、漲跌標記旁表 refmark | data/selfhost/raw_prices、notrade、refmark.parquet | selfhost_collect.yml 台北 16:30／18:45／23:59 | 已上線（排程自動跑） |
| `scripts/selfhost_chips.py` | 抓取 | 三大法人（T86／TPEx insti）＋融資融券（MI_MARGN／TPEx margin）個股，依欄名／欄數解析。10-06 增補：前日餘額 margin_prev／short_prev、備註 note | data/selfhost/inst、margin.parquet | 同上 | 已上線（排程自動跑） |
| `scripts/selfhost_stophalt.py` | 抓取 | TWSE violation/stop 停止買賣中每日快照（無歷史，從 10-06 起累積） | data/selfhost/stophalt.parquet | 同上 | 已上線（排程自動跑） |
| `scripts/selfhost_events.py` | 抓取 | 官方除權息 TWT49U／exDailyQ、減資 TWTAUU／revivt、面額變更 TWTB8U／pvChgRslt；FinMind 分割／減資為交叉驗證。增補：官方用語欄位（event、reason、open_base、div_ref、漲跌停價）、官方回應 notes 原文保存 | data/selfhost/corp_actions.parquet、ev_official_meta.jsonl | selfhost_collect.yml | 已上線（排程自動跑） |
| `scripts/selfhost_twse_ca_detail.py` | 抓取 | TWSE TWT49UDetail 逐件抓現金增資明細（認購價、現增股數、原股東認購）；驗證官方參考價 A 公式，503 件中 99.6% 相符 | data/selfhost/ev_twse_ca_detail.parquet | 手動（可續跑） | 已 push・手動執行（未入排程） |
| `scripts/selfhost_xsrc.py` | 抓取 | FinMind、Yahoo 平行回補，只做交叉驗證與缺口備援，不覆蓋官方資料 | data/selfhost/xsrc/ | 手動 | 已 push・手動執行（未入排程） |
| `scripts/selfhost_backfill.py ＋ selfhost_merge.py` | 運算 | 一次性全量回補（依序、可續跑）；把平行回補的各市場檔合併（含跨市場同日重複去重） | raw_prices、inst、margin | 手動 | 已 push・手動執行（未入排程） |
| `scripts/selfhost_adjust.py` | 運算 | 官方實價 × 事件表重算還原價；多來源事件去重、同日減資＋除權息只套減資。增補：停牌缺口閘門 stop_gap_gate（連乘前拒收假事件） | adj_prices.parquet、adjust_log.csv、adjust_rejected.csv | 手動（尚未入 CI） | 已 push・手動執行（未入排程） |
| `scripts/selfhost_gate.py` | 守門 | 新版資料要不比舊版差才可覆蓋 Release：日期連續、融資恆等式（逐日不符比例中位數）、內容守門 | 閘門結果 | selfhost_collect.yml | 已上線（排程自動跑） |
| `scripts/selfhost_seam_check.py` | 運算 | 以官方未還原價偵測上游還原接縫，產可追溯清單（只讀分析） | seam_events.csv、seam_residual.csv | 手動 | 已 push・手動執行（未入排程） |
| `scripts/selfhost_recon.py` | 運算 | P3 對帳：自建還原價 vs 上游 data_pack，近 250 交易日；1,762／1,969 檔相符 | recon_detail.csv、data/derived/selfhost_recon.json | 手動；2026-10-12 起每日 | 已 push・手動執行（未入排程） |
| `scripts/selfhost_ledger.py` | 運算 | 每檔事件簿：事件、缺日、停牌、價格跳動 flag、官方漲跌標記對帳 | ledger.parquet、data/derived/selfhost_ledger_summary.json | 手動 | 已 push・手動執行（未入排程） |
| `scripts/selfhost_monthly_review.py` | 運算 | 月初完整性檢查＋官方事件對帳，產可貼給 AI 查證的 Markdown | data/derived/selfhost_monthly_review_*.md | 月初手動 | 已 push・手動執行（未入排程） |
| `tests/test_selfhost.py ＋ test_twse_ca_detail.py` | 守門 | 自建上游的單元測試（348 passed） | — | pytest | 已 push・手動執行（未入排程） |
| `.github/workflows/selfhost_collect.yml` | 排程 | 三班收集（raw_prices → chips → stophalt → events → gate → 上傳 Release selfhost-data） | Release selfhost-data | 台北 16:30／18:45／23:59（2026-10-06 起；資料存私有 repo Release） | 已上線（排程自動跑） |
| `reference/refdata.py ＋ scripts/refdata_sync.py` | 運算 | 私有參考資料（PCF 快照、總經／期貨／法人／指數序列）的存取：pull／push 私有 repo tw-hold-data 的 Release refdata-latest；先傳暫名再改名、預期清單、不倒退閘門（防殘缺目錄蓋掉歷史） | 私有 Release refdata-latest（14 個資產） | rebuild／global_macro／chip_flow_evening／pcf_retry／heartbeat 與 Streamlit app | 已上線（排程自動跑） |
| `.github/workflows/check_secrets.yml` | 守門 | 手動：量 FINMIND_TOKEN 長度與結尾字元，並用未處理的原值打 FinMind（secret 貼上常帶結尾換行） | log | 手動 | 已上線（排程自動跑） |

## 階段 3　自建上線（規劃，尚未發生）

Opus 審查通過、push、建 Release、Actions 演練、15 日驗證後，切自建為還原價主來源，再做接縫訂正與下游接線。

*依 HANDOFF_2026-10-06_pm.md；以下每列都是「還沒做」。使用者 2026-10-06 決定：驗證後才決定要不要切（切自建／維持上游／全停三條路）。*

### tw-swing（1 項）

| 檔案 | 類型 | 抓什麼／做什麼 | 輸出 | 排程 | 狀態 |
| :-- | :-: | :-- | :-- | :-- | :-: |
| `接縫訂正（下週，可提前）` | 運算 | 先出訂正前後影響報告（規則驗證、回測、保留段都建立在舊數字上；OHLC 不一致 8,327 列）再改母表；bundle_gate 加同款恆等式守門 | tw-swing 日線母表 | hold 之後 | 規劃中（尚未發生） |

### tw-hold（6 項）

| 檔案 | 類型 | 抓什麼／做什麼 | 輸出 | 排程 | 狀態 |
| :-- | :-: | :-- | :-- | :-- | :-: |
| `scripts/selfhost_recon.py（驗證期）` | 守門 | 2026-10-12 起連續 15 個交易日，自建 vs 現有上游逐日比對；通過後切為還原價主來源，上游降為每週核對 | recon 報告 | 2026-10-12 起 | 規劃中（尚未發生） |
| `還原／接縫／對帳／事件簿上 CI` | 排程 | 目前只有收集在 CI，衍生層（adjust、seam、recon、ledger）還在本機；要不要加每週衍生層步驟待決定 | — | 待決定 | 規劃中（尚未發生） |
| `接縫訂正（週三 dry-run／週四 Opus／週五接線 push／週六驗證）` | 運算 | 把 1,576 件接縫以官方因子訂正；seam_fix_log.json 記每檔每事件的跡 | 訂正後的 tw-hold 價格 | 驗證通過後 | 規劃中（尚未發生） |
| `app／build_*.py 接線` | 運算 | 下游頁面改讀自建 adj_prices 與事件簿；舊上游 data_pack 降頻；FinMind price 封存 | 三清單、個股頁 | 切主來源後 | 規劃中（尚未發生） |
| `月檢查流程` | 守門 | 每月初跑 selfhost_monthly_review → 貼給 Gemini 查證（程式能對帳的不給 AI） | 月報 md | 每月初 | 規劃中（尚未發生） |
| `排程容錯（未備案缺口）` | 守門 | 收集器預設只補近 14 天，停機超過 14 天會留永久洞；selfhost_status.json 沒有消費端（使用者偏好自癒不要告警） | — | 待設計 | 規劃中（尚未發生） |

## 各階段之間的銜接

- **階段 1 → 2**：階段 2 不碰階段 1 的任何程式與資料；`raw_prices` 等是平行的新檔（`data/selfhost/`，gitignore）。唯一交集是對帳：`selfhost_recon.py` 讀上游 data_pack 的還原價比較。
- **階段 2 → 3**：階段 2 的收集已上線；差的是「15 日驗證與決定」，不是再寫新抓取程式。
- **單點依賴**：階段 1 的日線、籌碼來自他人 repo；階段 3 切主來源後上游降為每週核對（使用者 10-05 已定）。

## 沒列進來的東西

- 修 bug 類：`reference/chips_guard.py`、tw-swing `chips.py` 上櫃自營補位（已 commit 未 push）、`selfhost_adjust.drop_future`、休市複本守門等。
- 研究／回測腳本：`tw-hold/research/*`、`tw-swing` 的 bench、tearsheet、mine_rules 等。
- 出處：各檔檔頭 docstring、`.github/workflows/*.yml`、`docs/HANDOFF_2026-10-06_pm.md`。
