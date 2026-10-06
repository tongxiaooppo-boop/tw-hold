# tw-hold 交接 — 自建上游：對帳收尾、防呆補齊、事件簿（2026-10-06 下午，承 HANDOFF_2026-10-06）

> **自足執行指令。你在全新對話、沒有上下文。** Windows；`d:\g\claude\` 下有 `tw-swing\`、`tw-hold\`、`books\`。
> ⚠ 跑腳本先 `cd /d/g/claude/tw-hold`；python 一律 `PYTHONIOENCODING=utf-8`。
> ⚠ **使用者規則：Opus 審 → 問使用者 → 才 push。** 本機有未 push 的 commit，pull 前先 `git status`／`git log origin/main..`。
> ⚠ **口徑結論先 grep 再寫**：`books/new-book6/tw-stock-data-main/CLAUDE.md`（120KB）與 `docs/READ_CONTRACT.md`（177KB）是別人踩坑的紀錄；我 2026-10-06 沒讀就下了錯的成交量口徑結論。彙整版：**`docs/data-fix.md`**（避坑指南＋「我們有沒有防」對照表）、`docs/data-qu.md`（外部 AI 查證題與核對結果）。
> ⚠ 外部 AI（Gemini／GPT）只做「查證事實」；回覆一律拿資料驗（它們錯過：Yahoo Close 含不含配股、6201 轉板、2026-04-09 是不是連假後、編造 2614 的預估參考價…）。

---

## ⭐ 明天（2026-10-07）第一件事：查昨天自建收集有沒有真的跑成功

**背景**：今天 13:00 起 `selfhost_collect.yml` 已在 Actions 上線，今天 16:30／18:45／23:59（台北，GitHub 排程常延遲 30～60 分鐘）是**第一次由排程觸發**（之前都是手動 dispatch）。失敗只會留紅色 run、**不會通知**（使用者選「自癒不要告警」），所以一定要有人去看。

```
gh run list --workflow=selfhost_collect.yml -R tongxiaooppo-boop/tw-hold --limit 10
gh run view <id> --log | grep -E "閘門|::error|::warning|Release 尚無|下載 .* 失敗"
gh release view selfhost-data -R tongxiaooppo-boop/tw-hold-data --json assets --jq '.assets[]|"\(.updatedAt) \(.size) \(.name)"'
```

逐項檢查（約 5 分鐘）：
1. 三班都 success？（若某班缺＝排程沒觸發；若紅＝看 log 的第一個 `::error`）
2. 閘門訊息「閘門 通過」，且 raw_prices／inst／margin 最新日 ＝ 2026-10-06（收盤後資料已進）。
3. 私有 Release（`tongxiaooppo-boop/tw-hold-data`）檔案更新時間是今天晚上；公開 repo **沒有** `selfhost-data` Release（已刪）。
4. 23:59 那班的「近 3 日曆日重抓」有實際覆蓋更正（可比對 10-05 投信／成交量是否與 10-05 首次抓的不同）。
5. `FINMIND_TOKEN` 在 Actions 上生效：log 內 FinMind 分割／面額那步沒有 400／401／402（⚠ 該步 `continue-on-error`，run 顯示綠色也可能實際失敗，**一定要 grep log 的 `Token is illegal`／`HTTPError`**）。今晚已修（見 §5.95），修後驗證結果見該節。
6. `ev_official_meta.jsonl` 有在增長（CI 上每次 events 步驟都會 append，下載→append→上傳）。
7. 本週五 10-09 第一次跑 FinMind 減資輪詢（週二被略過）。
8. **PAT 到期日**：`DATA_REPO_PAT`（fine-grained，只授權 tw-hold-data 的 Contents 讀寫）建於 2026-10-06，使用者設定一年期；**2027-09-29 起提醒換**（記憶 `tw-hold-bundle-pat-expiry` 已加）。

9. **私有參考資料（2026-10-06 晚已切換）**：`data/pcf/`、`data/reference/` 已從公開 repo 移除（`git rm --cached`＋`.gitignore`），改存私有 repo `tw-hold-data` 的 Release `refdata-latest`（一檔一資產；PCF 每基金一個 zip）。確認 `rebuild`／`global_macro`／`chip_flow_evening`／`heartbeat` 這幾條 log 有 `[refdata] pull … 項`、`[refdata] push …`，job 沒有紅；`pcf_retry` 只在補跑時才觸發。app 頁尾應顯示「私有參考資料：已從私有 Release 還原 14 項」。若出現「還原失敗」＝Streamlit secrets 的 `DATA_READ_PAT`（唯讀、Contents: Read-only）有問題。**注意**：`rebuild` 的還原是 `--strict`＋`continue-on-error`，失敗時會跳過推送（避免殘缺 PCF 目錄蓋掉 Release 歷史）並讓 job 變紅。

之後依 §5 順序：2026-10-12 起連續 15 個交易日 `selfhost_recon.py` 逐日比對 → 通過後切主來源 → 接縫訂正。

## 0. 現況

| | |
| :-- | :-- |
| tw-hold `main` | ✅ 2026-10-06 已全部 push（Opus 審查後；最新 `b9ea3fc`）。工作樹只剩三個 `data/derived/selfhost_*` 執行產出檔未進版控 |
| 自建庫 | 全在本機 `data/selfhost/`（gitignored，約 500MB）：`raw_prices`（含 `chg`）、`inst`、`margin`（含 `margin_prev`／`short_prev`／`note`）、`notrade`、`refmark`、`stophalt`、`corp_actions`、`adj_prices`、`ledger`；2015-01-05～2026-10-05，2,864 天 |
| 沒接下游 | tw-hold／tw-swing 現行仍用上游 data_pack（接縫 1,576 件還在）；自建庫尚未被任何頁面消費 |
| GitHub | ✅ `selfhost_collect.yml` 已上線；資料 Release 在**私有 repo `tongxiaooppo-boop/tw-hold-data`**（tag `selfhost-data`）；tw-hold 公開 repo 的舊 Release 已刪（2026-10-06）。手動演練 3 次通過，排程首次觸發為 10-06 16:30 |
| 測試 | `python -m pytest -q` → 354 passed |

## 1. 今天做完的（程式；細節看 commit 訊息與各檔檔頭）

**收集端**：近 3 日曆日重抓覆蓋（官方收盤後會更正，實測 10-05 投信 14 檔、成交量 17 檔）；排程加台北 23:59 第三班；休市複本守門（TPEx 融資券休市日回前一日複本）；跨市場同日重複去重（merge **與**每日路徑）；`margin_prev`／`short_prev`／`note`；`notrade` 旁表（有量無價列）；`refmark` 旁表（官方行情的漲跌標記：上市 X／上櫃 除息、除權）；`chg`（官方漲跌價差，close−chg＝官方參考價）；`selfhost_stophalt.py`（停止買賣每日快照，累積檔只增不減）；上櫃變更面額官方來源 `tpex_par`（pvChgRslt）。

**還原端**：同日減資＋除權息只套減資；事件日晚於最後實價日的事件不套用（今天抓到 6 件被套進 `adj_prices`，最新價≠未還原價）。

**閘門**：融資恆等式改看「逐日不符比例中位數」並升級為擋上傳；單日 >30% 只警告（官方隔日調帳）。

**分析／偵測**：`selfhost_recon.py`（自建還原價 vs 上游快照 `books\n`，近 250 日：1,762/1,969 檔相符，其餘歸因到上游缺陷）；`selfhost_ledger.py`（每檔事件簿 `ledger.parquet`＋flag 偵測；`--ticker 2614` 印時間軸）；`selfhost_monthly_review.py`（月初完整性＋官方事件對帳＋待 AI 查證清單）。

## 2. 今天查證出的重要事實（別重查）

1. **官方行情自己標事件日**：上市「漲跌(+/-)」欄 `X`、上櫃「漲跌」欄寫「除息／除權／除權息」。全史相鄰交易日標記日 16,967 個，事件表對上 16,941 個，**其餘 26 個全是轉板首日**（市場別改變）→ 事件表完整性有獨立證據。事件簿 `refmark_no_event` 就是這個偵測器（目前 0 筆）。
2. **價格跳動 flag 381 個全部能歸因**：三個來源收盤逐列一致（資料沒壞）、tw-stock-data 的 adj 事件我們一件沒漏；原因是無成交日後「官方參考價≠我們前一筆收盤」（官方 `close−漲跌價差` 才是參考價，官方漲跌幅都在限制內）。成因規則（無成交日參考價改變）已查證＝營業細則 §58-3（data-qu.md §6.9）；買賣揭示價無資料，無法逐筆驗。
3. 還原後仍跳的 `adj_jump` flag 剩 70 個（42 檔）：20 個在事件日（例 2429 2024-07-02 現增因子 0.749 但收盤 +46.7%、6225 2026-08-18 +62.5%）、50 個是官方標 X 但無事件的長缺日後復牌（例 6131 2019-04-10 −74.4%，缺 219 天）。**這 70 個是目前最可能的「真缺口」候選**，還沒逐一查。
4. 成交量／成交金額口徑：上市我們與 tw-stock-data 逐列相同（含零股）；**上櫃我們的量一律較大（0.7%～2%），兩個上櫃端點口徑不同，上櫃含不含零股未定論**（待用 TPEx 大盤統計加總驗證）。「2020-10-26 斷點」資料不支持。
5. 融資「前日餘額≠昨日今日餘額」是官方隔日調帳（2019-02-11、2026-04-09 約 54% 個股；全期 33 天超過 10%）；以前日餘額為準；`note` 講的是**次一營業日**。
6. FinMind 不能當備援（投信上櫃 2018–2020、補班週六自營是錯的）；Yahoo `Close` 含配股調整；FinMind／tw-stock-data 都是官方轉載，**沒有真正獨立的第二來源**。
7. 現增：官方除權息參考價 A（我們存這個）≠ 減除股利參考價 B（官方開盤／漲停基準）；2614（10-06 除權息，權息＋現增 38.2%@12.80）A=16.13、B=17.31；上游 Yahoo 在除權息日**前一晚**就套事件。**A/B 的決策文件還沒寫**（tw-stock-data 與我們用 A、tick-stock-panel 主張 B）。
8. 減資併現增：我們用 TWTAUU 的「除權參考價」，tw-stock-data 用「恢復買賣參考價」，差約 2%（3536 於 2015-03-20；3312 於 2018-04-10），其餘 238/240 件相同。

## 2.5 事件整理與命名（使用者 2026-10-06 要求：用官方用語、不自建名詞）

- **`docs/EVENTS.md`**：官方事件總表（除息／除權／除權息／減資〔退還股款・彌補虧損・現金減資〕／變更股票面額）、各自的官方來源表與基準價欄位、與 Gemini／GPT 兩份清單的逐項核對（Gemini 的「恢復交易首日無漲跌幅限制」與官方表矛盾；官方沒有獨立的「現金增資」事件）。
- `corp_actions` 新增欄：`event`（官方事件名稱）、`reason`（官方減資原因）、`open_base`（開盤競價基準）、`div_ref`（減除股利參考價）、`limit_up`／`limit_down`（官方漲跌停價）；舊 `type`（ex_div、cap_reduction…）只為相容保留，**新程式用 `event`**。官方事件表已全史重抓（2015～；減資／面額 2011～）。
- 實測：事件日有實價的 18,027 筆，收盤**全部**在官方漲跌停價內（0 筆例外）。
- 事件簿用官方詞顯示；`flag`／`jump`／`gap` 是分析用語、不是事件。

## 3. 演練結果（證明增量正確）

把 raw／inst／margin／notrade／refmark 截到 2026-09-30，用 `selfhost_collect.yml` 同一批指令（raw_prices、chips、stophalt）追到今天：實價 4,939,294、法人 4,260,372、融資券 4,576,551 列，**與現有資料逐列相同、欄位全一致**（只有 6 列漲跌標記的推定值有出入，見 data 說明）。融資券 `margin_prev`／`note` 用 tw-stock-data 回填的歷史，與官方 10-01～10-05 重抓結果完全一致。演練目錄在 session 暫存區（不進 repo）。**⚠ 還沒在 GitHub Actions 上跑過**（TPEx TLS：tw-stock-data 說 certifi 也驗不過，我們註解說可以，兩邊衝突）。

## 4. Opus 審查範圍（建議）

重點檔：`scripts/selfhost_adjust.py`（同日減資規則、`drop_future`）、`selfhost_chips.py`（REFRESH_DAYS 窗口、休市複本守門、`_note`、`margin_prev`、跨市場去重）、`selfhost_raw_prices.py`（`NOTRADE`／`REFMARK` 旁表、`_mark`、`chg`、RECHECK_DAYS）、`selfhost_merge.py`（`_drop_cross_market_dups`）、`selfhost_gate.py`（融資恆等式中位數）、`selfhost_stophalt.py`、`selfhost_ledger.py`（flag 規則是否合理）、`selfhost_events.py`（`tpex_par`）、`.github/workflows/selfhost_collect.yml`（三班 cron、Release 檔清單）。
請 Opus 特別看：①每日排程路徑是否都經過去重／守門（agent 審查指出過一次不經 `selfhost_merge`）；②累積型旁表（notrade／refmark／stophalt）有沒有可能被整份覆蓋；③`chg`／`refmark` 新欄進 Release 後舊版本讀取端會不會炸（讀取端一律 `.get()`／讀 schema 取交集）；④重抓窗口與 `closed`／`unavailable` 記帳的互動；⑤`selfhost_status.json` 沒有消費端（無警報；使用者偏好自癒不要告警）。

## 5. 審過之後（順序）

1. 問使用者 → push。
2. 建 Release 種子（`selfhost_collect.yml` 檔頭有指令；檔案清單已含 `notrade`／`refmark`／`stophalt`）：`gh release create selfhost-data data/selfhost/{raw_prices,inst,margin,notrade,refmark,stophalt,corp_actions,ev_fm_reduction}.parquet data/selfhost/ev_fm_reduction_done.json --title "自建上游資料" --notes "由 selfhost_collect.yml 維護；勿手動覆蓋"`（⚠ 合併前不要啟用排程；現有檔都已合併）。
3. 手動 `workflow_dispatch` 跑一次當演練，檢查：三個步驟成功、閘門 log、Release 上檔案更新、TPEx 沒有 TLS 錯誤。
4. 驗證期：2026-10-12 起連續 15 個交易日，自建 vs 現有上游逐日比對（`selfhost_recon.py` 已有骨架）；通過後切為還原價主來源（使用者 10-05 已定）。
5. tw-hold 訂正排程（週三 dry-run＋報告、週四 Opus、週五接線 push、週六 06:00 驗證；`seam_fix_log.json` 要記每檔每事件的跡）；tw-swing 下週（先出訂正前後影響報告，含 OHLC 不一致 8,327 列）。
6. 月初：`python scripts/selfhost_monthly_review.py` → 把「第 3 節 flag 清單＋提示詞」貼給 Gemini 查證（程式能對帳的不給 AI）。

## 5.5 給 Gemini 的待查證題（只要事實與出處，不要建議）

1. **新上市／上櫃首日起幾日無漲跌幅限制？** 我們事件簿假設「前 5 日不查漲跌幅」，沒有出處。請給：現行規則、2015-06-01 前後是否不同、興櫃轉上櫃是否適用。
2. **全額交割（變更交易方法）與分盤交易**是否改變開盤基準價或漲跌幅限制？
3. **TWSE 歷史除權的現金增資欄位**（認購價、現金增資配股率）官方歷史來源是 `TWT49UDetail` 嗎？欄位與參數？
4. **ETF 受益權單位分割／反分割**的官方公告名稱與來源表。
5. **公司分割減資**（分割並減資）在 TWSE／TPEx 是否有計算結果表？
6. 無成交日後的**參考價規則**（我們實測 381 例官方參考價與前一筆收盤不同，原因推測未驗證）。

## 5.9 Opus 審查結果（2026-10-06 晚）與處理

結論原為「先不要 push」，阻擋項與建議項已修（354 passed，修法都做過突變驗證、workflow shell 語法 `bash -n` 通過）：
- ✅ **阻擋**：Release 下載失敗被當成「尚無舊版」→ 閘門放行小檔覆蓋整份歷史。現在 workflow 先列 Release 資產、有列卻下載失敗（重試 3 次）就中止；`selfhost_gate.py --assets` 對「Release 有、基準缺」直接擋；notrade／refmark／stophalt 納入「不得變少」。
- ✅ 休市複本守門把「實價那天抓失敗」誤記成休市：距今不足 30 日曆日（`CLOSED_MIN_AGE`）只丟棄、不記休市，下一班重試。
- ✅ `ev_official_meta.jsonl` 加進 Release 下載／上傳清單（不進閘門，只增不減）。
- ✅ `selfhost_twse_ca_detail.py`：無輸出檔時 KeyError(-1)、失敗列永遠不重試，兩個都修。
- 停牌缺口閘門、notes 形狀：Opus 實測無反例（573 件減資／面額事件收盤與官方前收偏差皆 0）。

**審查標為「可之後」、尚未處理**：TWT49UDetail 改依欄名（現用位置）；現增配股率公式在 ca_orig=0（9105）時退回 ca_per_1000／1000（目前程式沒實作、無除零風險；現增事件實為 504 件，文件寫 503 要核對）；實價半邊失敗時 notrade／refmark 仍寫進當天；`selfhost_ledger.py:289` 明確讀 chg 欄、舊檔會丟例外；meta 檔放 Release 後會持續長大（約 7.5MB／年，可依內容雜湊去重）；`data-fix.md` §4 的 C1、C2、D7、A12 標記已過時；TPEx 在 Actions 上的 TLS 要靠 push 後第一次 workflow_dispatch 驗證。**審查沒涵蓋**：ledger flag 規則、recon、seam_check、xsrc、monthly_review。

## 5.95 2026-10-06 晚的架構決定與設定（使用者決定「1＋3」）

- **程式公開、資料不公開**：tw-hold 是公開 repo，但自建上游收集的資料不再放公開 Release。`selfhost_collect.yml` 的 job env：`GH_TOKEN: ${{ secrets.DATA_REPO_PAT || github.token }}`、`GH_REPO: ${{ vars.DATA_REPO || github.repository }}`；目前 `DATA_REPO=tongxiaooppo-boop/tw-hold-data`（repo 變數）、secret `DATA_REPO_PAT` 已設。⚠ 順序：先設 secret 再設變數。若要回到寫本 repo：刪掉變數即可。
- **為什麼**：證交所與櫃買中心網站使用條款（證交所第 6、8 項；櫃買中心第五、七條）禁止腳本下載網站資料、禁止重製散布，**但書只豁免已授權 data.gov.tw 的資料**（OpenAPI＝OGDL v1，須顯名）。我們用的是網站 `rwd`／`www/zh-tw` 端點，不是 OpenAPI。→ README 加「資料來源與授權」（顯名、不公開散布、下架聲明、各目錄來源表）。
- **OpenAPI 可否取代**：實測日行情端點只回最新一天（日期參數被忽略），無歷史、不能補抓、不能做「近 3 天更正重抓」。若要往後合法公開，需先做涵蓋度探測（欄位、法人、融資券、更正）再評估「歷史用現有、增量改 OpenAPI」。**使用者尚未決定要不要探測。**
- **長期**：自建上游驗證通過後，資料專案（公開、Actions 無限）與策略專案（私密）分家；已記入記憶 `tw-hold-data-layer-split-plan`。使用者 2026-10-06 說「現有歷史公開沒差」。
- **Secrets（tw-hold）**：`DATA_REPO_PAT`（新）、`FINMIND_TOKEN`（今天補，同 tw-swing 的值；本機 token 驗證有效，額度 600／小時）、`TWSWING_BUNDLE_PAT`（2026-12-07 到期，11-30 起提醒）。
- **手動演練結果**：run 37413944270（寫公開 Release，TPEx TLS 無誤）、37416328750（改寫私有 repo，閘門通過）、37417176629（補 FINMIND_TOKEN 後，結果見下）。
- **FinMind token 踩坑（2026-10-06）**：secret `FINMIND_TOKEN` 貼上時結尾帶了換行，Actions 上 FinMind 回 `HTTP 400 {"msg":"Token is illegal"...}`（回應的 `token_tail` 尾巴是 `
` 才看出來）。該步 `continue-on-error`，整個 run 顯示綠色，**靜默失敗**。修法：`selfhost_events._token`／`selfhost_xsrc._token` 一律 `.strip()`（`reference/finmind_client.py` 本來就有）；已加測試。**修後驗證**：run 37417691902 的 log 出現「FinMind 分割／面額變更：51 件」（與本機 ev_fm_split 51 件一致），無 `Token is illegal`。**教訓**：continue-on-error 的綠色不等於成功，驗證要 grep log。
- **私有參考資料設計**：程式 `reference/refdata.py`＋`scripts/refdata_sync.py`（pull／push／`--strict`）；secrets：GitHub `DATA_REPO_PAT`（CI 讀寫）、Streamlit `DATA_READ_PAT`（app 唯讀，一年期，**2027-09-29 起提醒換**）。本機開發照讀 `data/`（已 gitignore，不會被 pull 覆蓋，除非手動跑 `refdata_sync.py pull`）。新 clone 的環境跑 `tests/test_app_smoke.py`／`test_snapshot_pcf.py` 前先 `python scripts/refdata_sync.py pull`（需 token），否則缺檔。
- **使用條款與風險（使用者已知）**：證交所／櫃買中心／期交所網站條款禁止腳本下載與散布（已授權 data.gov.tw 者除外）。目前：抓取這條仍違反（改走 OpenAPI 才能消除，但 OpenAPI 只回最新一天、不能補抓）；散布這條已降低（資料不在公開 repo，但 app 公開頁仍顯示衍生內容，例如主動式 ETF 的持股明細）。是否做 OpenAPI 涵蓋度探測：待使用者決定。
- **操作教訓**：`gh release download` 在本機網路下極慢（約 12KB/s），別用它搬 180MB；用本機檔案直接 `gh release create`。中途殺下載會讓後續的 `gh release create _seed/*` 把**殘缺檔**傳上去（今天發生過一次，已刪重建）。

## 6. 還沒做／待決定

- **Opus 審查前待辦（2026-10-06 晚；①②已實作，③待決定）**：
  1. ✅ **停牌缺口閘門**（`selfhost_adjust.stop_gap_gate`；真實資料 573 件減資／面額變更全數放行、0 拒收、0 警告；拒收會寫 `adjust_rejected.csv`）（TSD CLAUDE.md C1）：停止買賣型事件（減資、面額變更）一定有停牌缺口——①事件日前最後一筆收盤＝事件日前一交易日→沒缺口；②且官方「停止買賣前收盤」對不上我方→兩條同時成立才判不成立（只有②是我方價格問題，報給人看）。擋在 `selfhost_adjust` 連乘之前。
  2. ✅ **保存官方回應的 `notes`／`hints`／`title`／`total`／`params`**：目前收集端只斷言 `date`，其餘丟掉；`TWTAUU` 的 notes 夾「除息併案減資」現金股利等自由文字。保存原文、不解析（同融資 `note` 做法）。實作：`selfhost_events._record_meta` → `data/selfhost/ev_official_meta.jsonl`（只增不減，每次請求一列；下次跑 `--official`／`--official-act` 起累積，**歷史請求的 notes 補不回**）。測試 348 passed，閘門已做突變驗證。
  3. 現增旁表 `ev_twse_ca_detail.parquet`（`scripts/selfhost_twse_ca_detail.py`）：維持旁表、不併 `corp_actions`；4 件失敗已補、9105 官方就是原股東認購為 0（不是漏抓）；排程要不要週更待決定。

- **A/B 現增決策文件**（用 A 的理由：官方除權參考價、報酬連續）；`corp_actions` 沒存 B／開盤基準欄。
- **70 個 `adj_jump` flag 逐一查證**（可先查 20 個事件日的，用官方 TWT49U 漲跌停價驗收盤）。
- 保留「無成交」列的歷史是 tw-stock-data 的種子（上櫃量口徑不同），官方版本進來會覆蓋同一天。
- `ref_price`＝A 對「減資併現增」的取捨（見 2.8）。
- 停止買賣快照上櫃沒有來源；從今天才開始累積，補不回舊歷史。
- 排程停機超過 14 天會留永久洞（收集器預設只補近 14 天）；`selfhost_status.json` 沒消費端。
- 還原價／接縫／對帳／事件簿**不在 CI**（只有收集在 CI）；要不要加每週衍生層步驟待決定。
- 財報 PIT（期末＋45 天，Q4 法定次年 3/31）、融資 `note` 沒被 `checklist.py`／tw-swing 規則 A1 使用——agent 審查指出，**未驗證**，屬下游，不在本輪。
- `data-dl.md` 三處更正（見 HANDOFF_2026-10-06 §3）、tw-swing `bundle_gate` 恆等式守門、tw-swing `chips.py` 上櫃自營補位（已 commit 未 push）。

## 7. 踩坑（新增；舊的見 HANDOFF_2026-10-05 §7、docs/data-fix.md）

- 用 `str.replace()` 改檔時 `old` 切錯範圍會把整檔寫壞（今天因此從 git 還原過 `selfhost_gate.py`）：改檔用精確匹配的 Edit，改完先跑測試。
- 在 bash heredoc 裡寫含 `\r\n` 的 Python 字串，經 shell 展開會變成真的換行；字串裡要換行字元就用 `chr(13)`／`chr(10)`。
- Windows 上 python 讀 `D:/g/...` 要用正斜線 Windows 路徑，不要用 `/d/g/...`（Git Bash 路徑 python 讀不到）。
- 跨來源對帳：先按市場拆開量（TWSE／TPEx 口徑不同），並雙向比（只比一個方向會漏）。
- 重跑 `selfhost_events.py --official-act` 之後要重跑 `selfhost_seam_check.py`／`selfhost_adjust.py`／`selfhost_ledger.py`，否則衍生檔是舊的。
