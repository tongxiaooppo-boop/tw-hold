# tw-hold 交接 — 2026-10-07 下午（承 HANDOFF_2026-10-07.md）

> 新一輪先讀本檔最上面兩節。Windows；跑腳本先 `cd /d/g/claude/tw-hold`；python 一律 `PYTHONIOENCODING=utf-8`。
> ⚠ 使用者規則：Opus 審 → 問使用者 → 才 push；一律中文白話；外部說法（含 GPT）只當線索，拿真實資料驗證。
> ⚠ 對話超過數小時會被凍結，所以今晚的量測都是**獨立背景程式**，不依賴對話。

## 1. 今晚在跑的量測（電腦不能關機／睡眠）
| 程式 | PID | 做什麼 | 輸出 |
|---|---|---|---|
| `scratchpad/poll_openapi.py`（13:12 啟動） | 21272 | 量**官方**首次公布時間：目標資料日 10/7；日線 16:00 起、法人 18:00 起、融資券 00:30 起，每 2 小時，取到就停，硬停 08:00 | `C:\Users\Max\AppData\Local\Temp\claude\d--g-claude\5a9eecc3-39c1-4ff5-a4b4-510f43640172\scratchpad\poll_log.jsonl`（含 `first_seen`） |
| `data/selfhost/_measure_20261007/trigger_swing_daily.py` | 49660 | 量**上游資料包**實際何時好：台北 18:00／20:00／22:00／00:00 本機 `gh workflow run daily.yml -R tongxiaooppo-boop/tw-swing`（繞過排程延遲），看 log「母表最後交易日」，第一次＝2026-10-07 就停 | 同資料夾 `trigger_log.jsonl`（含 `first_fresh`）、`trigger_stdout/stderr.txt` |
- 檢查是否還活著：PowerShell `Get-CimInstance Win32_Process -Filter "Name='python.exe'"`。
- 兩支都只記錄；trigger 那支會讓 swing 真的跑 daily（產出會 commit、觸發 publish_bundle 與 hold 重算——這是預期的）。
- **明早第一件事**：讀兩份 jsonl，回答 ① 官方日線／法人／融資券各幾點首次公布 ② 上游資料包幾點好 → 決定排程重排。

## 2. 今天做完並已 push（tw-hold main）
| commit | 內容 |
|---|---|
| `e6c3ea1` | **上櫃日線改用 `tpex_mainboard_daily_close_quotes`**。舊端點 `tpex_mainboard_quotes` 量額有 860／889 檔與網站不同（總量少 2.2%）；新端點 889 檔 0 筆不同。交接寫的「少 2.2%、原因推測零股盤後」**作廢**（舊端點不含零股／盤後／鉅額，見 `data-fix.md` B4-3）。src 標 `openapi_dc`；merge_day 改單向升級（等級高可無視 Last-Modified 覆蓋舊端點資料，反方向略過，縮水保護不分來源，src 為 NaN／缺欄安全） |
| `ce378fd` | **上市融資 `MI_MARGN`**（網站端點帶日期，回應回傳自己日期；重用 `selfhost_chips.margin_twse`）。存同一張 `openapi_margin`，src=`web_mi_margn`。已存日子若最後抓取早於隔日 00:00（台北）再打一次，內容有差才整天替換（官方隔日調帳），縮水不覆蓋。真實驗證：10/6 共 1,059 列，融資恆等式 1,059/1,059 |
| `5099121` | 上市融資**台北 08:00～22:00 整段不請求**（今天、前一天都不打）；隔日 04:00 清晨班仍收（補漏＋調帳）。全套 428 passed |
- Opus 審過兩輪（端點切換 7 點、MI_MARGN 6 點），已修；Release `openapi-daily` 已有 10/6 的上市日線 1,095、上櫃日線 865（已蓋成新端點版）、上櫃融資 802、上市融資 1,059。
- 測試 416→428：差的 10 個是搬進 `_archive_plan_a_cancelled/` 的方案 A 測試，不是漏測。測試現已隔離真實 fetch log（autouse fixture）；本機 log 的 27 行假紀錄已清。

## 3. 今天確認的事實（別再重查）
- **swing 早上兩個問題都修好**：測試擋住 daily（`ce5db37`）、收集閘門跨午夜（`3211263`＋`fa44379`，後者只有單元測試，要等 10/8 週收集才算實測）。10/7 月營收快照上市 1,086＋上櫃 892 完整（交接 §5-1 的疑慮解除）。
- **三槍真的都跑**（9/19～10/7 每個平日 3 個 run），**每槍都下載 data_pack.zip**。但排程延遲 2～9 小時：第一槍（設計 21:00）實際 **01:35～04:04**、第二槍 **04:04～06:28**、第三槍 **07:27～09:07**。
- **每天第一槍開跑時，日線／法人／融資的最後日期就已經一樣是當天**（上游整包一起更新，融資不比日線晚）。所以第三槍不是為了融資，是 `--require-fresh` 最後防線。第一槍才是真正產清單的那槍；瓶頸是排程延遲，不是上游慢。上游實際幾點好**還不知道**（log 最早只到 01:35）→ 今晚 trigger 那支要回答。
- 官方端點驗證（GPT 說法 vs 實測）：`tpex_mainboard_margin_balance` 存在（GPT 說無法確認，我們已實證）；`TWT49U`＝除權息、`TWTAUU`＝減資、`TWTB8U`＝面額；`MI_INDEX` 對日線與 `STOCK_DAY_ALL` 七欄相同；上櫃法人 OpenAPI 另有 `tpex_3insti_dealer_trading`／`summary`／`trading`，可能比現在用的 `daily_trading` 乾淨（**未驗證**）。規格文件別寫「官方 API 有 bug」，寫「欄位待驗證，以網站端點為準」。
- 全市場日線除官方兩條（OpenAPI＋網站端點）外，**沒有免費可靠的非官方備援**：Yahoo 逐檔且與 data_pack 同源、FinMind 全市場在免費層未驗證、其他第三方站 `data-dl.md` 列為不要碰。

## 4. 使用者今天拍板的設計（尚未實作）
1. **三種資料各自起跑、每 2 小時一次、取到就停**：日線 16:00 起、三大法人 18:00 起、融資券 **00:30 起**（上市＋上櫃融資一組）。班次是整點／半點的 2 小時格，**不是** 15 分鐘（我曾誤改成 15 分鐘被糾正）。
2. **短線掃描只跑一次、等融資到齊才做**（不做「待融資」半成品、不跑兩次）；其他（長波段、swing 清單、價值／定存）有日線就先做。
3. 觸發方向：**資料到了就觸發**（外部觸發／本機），不靠排程時間；hold 現有手動重整按鈕只重算 bundle，bundle 來源仍是 swing，要等自建上游切為主來源才有意義。按鈕前提檢查：日線＋法人最新日＝今天才執行。swing 登入頁（Cloudflare Pages Function）加按鈕之後再做。
4. 三槍重新定義：待觸發機制做好後，第一槍＝資料到即跑的主力，二三槍＝備援／最後防線。
5. 已定「明天依今天量到的時間重排 `openapi_daily.yml` 班次」；`daily.yml`、`publish_bundle.yml` 的班次同理。**今天不動排程**。

## 5. 還沒處理／待決定
1. 新增**三大法人每日收集**（目前只有每週收集有法人；上櫃法人要用網站端點 `insti/dailyTrade`，OpenAPI 欄位有疑慮）→ 需新累積檔 `openapi_inst.parquet`＋Release 上傳／下載。
2. 上市融資「班次到幾點為止」「上櫃融資是否也跟著 00:30 起」——我問過、使用者回覆是「融資券 0:30 開始」，視為一組；結束時間未明講。
3. `docs/data-all.html`（數據抓取與運算總表，10/6 版）已過期：缺 openapi_daily 與每日 OpenAPI／MI_MARGN；階段 3 的方案 A 接縫訂正時程作廢（改走官方口徑母表：10/19 比對、10/23 go/no-go、10/24 上線）；測試數 348→428；階段 1 全部標「已上線（排程自動跑）」，手動腳本也被標成自動——要區分。**使用者要討論，未動**。
4. `openapi_daily.yml` 檔頭註解沒提上市融資（只是註解）；缺日偵測對上市融資只會警告、不會自動補（週收集補的是另一個檔）。
5. 交接舊項仍有效：10/6 晚 21:00 那槍 swing `daily.yml` 無 run 紀錄（原因未查）；預告表快照每週一份太稀疏；10/8 週四 23:59 第一次真正週收集（10/9 國慶補假）；`docs/HANDOFF_2026-10-07.md` §1、§5 的其餘項目。
6. 時程不變：10/12 起每日累積、10/19 母表比對、10/23 go/no-go、10/24 上線；使用者 10/17–18 外出，建議 10/16 前先做一次累積檢查。
7. 上櫃日線 OpenAPI Last-Modified 10/6 15:30、上市日線 10/6 21:20（隔日 05:20）——是「最後重新產生」不是首次公布，別拿來當公布時間。

7. **tw-swing 盤前管線守門（雲端 routine，週二～六 08:16，skill `/tw-swing-check-pipeline`，腳本 `tw-swing/scripts/check_daily.py`）——使用者決定改天再處理**（今天排程動太多，避免互相影響）。已查到的事實：
   - 10/7 早上報「整體 OK」結論是對的（清單、新鮮度、處置股、月營收都過；唯一 WARN「籌碼完整性：沒有本機母表」是乾淨 clone 的預期現象）。
   - 但 `check_actions_runs` 用 `gh run list --limit 3` **沒指定 workflow**，看的是整個 repo 最近 3 次；10/6 兩槍 `daily.yml` 失敗被後面成功的 `publish_bundle`（workflow_run 跟在失敗後也會跑）擠出視窗，所以「最近 3 次皆 success」字面對、卻看不到 daily 失敗。
   - 守門自己的環境不穩：那次執行「Run daily pipeline health check」Failed ×2，花多輪重裝套件、改裝進 Python 3.11 環境，最後用 JSON 輸出模式才成功。
   - **使用者要的是「完成了沒」，不是「有 failure 就 WARN」**：08:00 前 swing 清單／bundle／hold 三清單的資料日都是最新交易日＝完成；中間哪一槍失敗不重要。沒完成時偏好**自動補跑（自癒）**而非通知（需雲端 routine 有 `actions:write` 才能 dispatch，未確認）。擬議：拿掉或降級「Actions 最近 3 次」那項；固定守門的 Python 版本與套件；之後才做自動補跑。**尚未動任何檔案。**

## 6. 踩坑（今天新增）
- **別在使用者說「觸發」「2 小時」時自行改成別的頻率／主體**：他說 00:30／02:30／04:30 是指**排程班次**，我誤當成輪詢時間並未經同意啟動背景程式；說 2 小時就是 2 小時。拿不準先問一句。
- 使用者講的「前日」「官方第一時段」都是在說**不要在資料還沒公布時請求**；白天打 MI_MARGN 是白打。
- 新增的測試別寫進真實的 `data/selfhost/` log（已用 fixture 隔離）。
- OpenAPI／網站端點「沒資料」不等於錯：TPEx 網站端點沒資料時**仍會回傳我請求的日期**，判斷「取到」要再看有沒有資料列。
- 驗證 GPT／外部說法：先打真實端點逐項比對（這次抓到「`tpex_mainboard_quotes` 名稱不精確」實際是兩個端點都存在、內容不同——結論是對的，理由要拿資料補）。

## 7. Opus 審查結果（2026-10-07 晚）：預告快照改動＋「自建上游還差什麼」
### 7.1 預告表每日快照（未 commit，已按審查修完，435 passed）
- 內容：`selfhost_openapi_daily.py` 新增 `collect_forecasts`（上市 `TWT48U_ALL`＋上櫃 `tpex_exright_prepost`，兩者都是 OpenAPI；同市場至少間隔 3 小時；`openapi_forecast.jsonl` 每次抓取記一筆，內容相同 rows=None＋same_as）；workflow 多一個資產檔。
- 審查修掉：①Release 缺預告檔但 fetch log 已有成功記錄 → 中止（防 `--clobber` 中斷後從空檔重來）；②預告上傳移到最後、失敗只警告（不擋當班日線／融資上傳）；③壞列跳過計數、保留原字串 `cash_raw`／`sub_price_raw`（上市 '' 可能是不適用或待公告；上櫃「尚未公告」＝待公告、0.00000000＝不適用）；④依 (ex, code) 排序，比對不受排列影響；⑤累積檔壞行跳過；⑥測試隔離 FORECAST／PRICES／MARGIN。
- 仍存在：週收集的 `forecast_twt48u.jsonl`（只上市、有網站退路、台北日期）與每日版並存，**要指定以誰為準**。
- 驗證：預告表 62 列（上市）／76 列（上櫃），欄名、民國 7 碼日期、(代號,日期) 無重複。純現金息參考價公式：上市「前收−現金股利，**無條件捨去到分**」5,390 件 100%、上櫃「**四捨五入到分**」3,739 件 100%。

### 7.2 更正我自己先前說錯的
- 「207 檔不相符原因沒拆」**錯**：`docs/data-qu.md:201` 已拆過——factor_diff 128（現增口徑）、upstream_stepwise 50、seam 8、single_day 5、unadjusted 2、unexplained 14，合計 207。
- 「上櫃預告表沒有參考價、要公式」**不精確**：上櫃 OpenAPI `daily_close_quotes` 有官方 `NextReferencePrice`／次日漲跌停（2947：收盤 62.60、次日參考價 61.60、現金股利 1.0，完全吻合）；但 `parse_prices` 目前沒存這欄。

### 7.3 上線阻擋項（Opus 盤點，依風險）
| # | 項目 | 現況 | 工作量 | 結果未知？ |
|---|---|---|---|---|
| B1 | 決定互相衝突未撤銷：PLAN_OWN_UPSTREAM「連續 15 日達標、上游仍主來源、切換由使用者拍板」、DATAPACK_ADAPTER「平時用上游」、10/06「維持舊管線、自建每週核對」 | 需使用者明確改寫 | 小時 | 否 |
| B2 | **tw-swing 沒有切換開關／自動退回**：`update_data.py:76` 網址寫死、`download_pack` 匿名 GET（私有 Release 沒匿名網址）、`--require-fresh` 看上游 Last-Modified、`apply_chips_baseline` 寫死（DATAPACK_ADAPTER 要緊接 baseline、PLAN 要略過，**兩文件矛盾**）、tw-swing repo 變數空 | 要加 PACK_SOURCE、gh＋PAT 下載、新鮮度改看 zip 內最新日、失敗退回上游、selfhost 模式略過 baseline、來源標示、退回演練 | 約 1 天＋Opus 審 | 低 |
| B3 | **官方口徑 zip 從沒在 CI 產出**：`selfhost_collect.yml` 沒跑 selfhost_adjust／selfhost_to_datapack；tw-hold-data 無 datapack-selfhost；本機 adj_prices 只到 10/05 | 新 workflow：adjust→to_datapack→帶日期／雜湊／manifest 上傳；實測 runner 耗時與記憶體（全表＋202MB zip） | 半天 | **是** |
| B4 | **10/12 後新日子怎麼進母表**：openapi_daily「不接下游」、raw_prices 只每週更新 → 10/12 晚 zip 只到 10/08 | 二選一：(a)每日把 OpenAPI 日線／融資併進 raw 再 adjust（推翻 10/06「每週一次」，每天約 10 個請求，Opus 建議）；(b)官方底包＋上游尾巴拼接 | 1～1.5 天 | 中 |
| B5 | **沒有每日法人收集**（上市 T86 只有網站端點） | 沒有則 chips 卡在 10/08，短線掃描缺料守衛凍結；重用 selfhost_chips 的 T86／dailyTrade＋恆等式守門 | 半天～1 天 | 低 |
| B6 | **當天事件因子無來源、暫定因子無寫入點**：`drop_future` 只丟不存；全 repo 無 provisional；切換週 10/12–16 有 21 件事件（4 碼 7 件：1449 配股、1727 現增、1463、1565、2938、4903、6548，正落在未驗的配股／現增公式） | 每日抓 TWT49U／exDailyQ 當天結果，或預告表＋公式算暫定因子（source=forecast、優先級在官方後、用 resolve_events 的 conflict 標差異）；上櫃可直接存 NextReferencePrice | 半天～1 天 | **是**（TWT49U 當晚是否含當日事件未驗） |
| B7 | **因子口徑三項未定**（官方參考價取整、現增用減除股利參考價、同日權息＋減資）；6129 現增單一樣本偏支持「減除股利參考價」 | 本機用 ev_official 比對兩欄位（483＋11 件）；最後要使用者拍板口徑 | 半天 | **是** |
| B8 | 原 10/19 比對報告未做（`selfhost_datapack_parity.py` 已有） | 檔數（2,147 檔中 159 檔最後交易日早於 9/01，多為下市股）、還原價變動分布、量／turnover 翻面、籌碼、daily_list 重播、0050 | 半天～1 天 | **是** |
| B9 | PAT：tw-swing secrets 只有 FINMIND_TOKEN、TWHOLD_DISPATCH_PAT，**沒有讀 tw-hold-data 的 token** | 使用者建 fine-grained 唯讀 PAT（contents:read、限 tw-hold-data），加進到期清單 | 0.5 小時 | 否 |
| B10 | 兩 repo 時序：swing 排程延遲 2～9h，tw-hold 產 zip 也延遲，可能每槍都退回上游 | tw-hold 產完 zip 後 repository_dispatch 觸發 swing daily（新 actions:write PAT）或 swing 輪詢 | 小時＋一顆 PAT | 中 |
| B11 | zip 驗收／閘門：selfhost_gate 只涵蓋 selfhost-data，不含每日 OpenAPI／法人／zip；bundle_gate 只比日期 | 最新日、各市場檔數、最後一列 raw＝官方收盤、0050 連續、chips 恆等式；不過就退回 | 半天 | 低 |
| B12 | 同一天兩來源不一致以誰為準：無任何程式定義 | 建議週收集網站端點（帶日期、含官方更正）> OpenAPI 快照 > 上游；延伸 merge_day 的 src 等級 | 小時 | 低 |
| B13 | 端到端乾跑＋退回演練：10/9 補假、10/10–11 週末**沒有新交易日**，第一個真實增量日就是 10/12 | 用 10/08 資料跑兩 repo 的 selfhost 模式＋切回 upstream 驗證恢復 | 半天 | **是** |

### 7.4 Opus 對時程的獨立判斷
- **10/12 週一正式切換：不可行**（B2～B6 零實作，合計約 4～5 工作天；B3/B6/B7/B8/B13 結果未知；休市三天無法真實乾跑；15 天規則未撤銷）。
- **可行的是 10/12 起「影子雙跑」**（新路線每天照算、與現行比對，swing 仍用上游），前提 B1 拍板、B3 與 B4 在週末跑通。
- 正式切換建議維持 10/24；最早 10/16 晚 go/no-go，但 10/17–18 使用者外出無人看守，不建議。
- **任一項沒過就不切**：自動退回演練失敗、CI 產 zip 耗時晚於 swing 第一槍、每日法人或當天事件因子缺、影子期 zip 驗收未連續 5 個交易日全綠、比對有未歸因大差異、因子口徑未拍板、PAT 未建。

### 7.5 非阻擋但建議
`parse_prices` 多存上櫃 NextReferencePrice；`prices_raw_close`（填息率用）改官方 raw（目前 FinMind 一次性回補不更新）；新標的名稱／產業別空白可能影響定存線產業 ≤40% 上限（未驗）；tw-swing stock_list 把 ETF 存成 '50' 而非 '0050'（8 檔）；`selfhost_collect` 週快照條件 `date -u +%u = 5`（UTC 週五）在週四收盤的週（如 10/8）或延遲跨到 UTC 週六時會跳過；`import_data_pack` 先刪 DAILY_FULL 再寫非原子（本機有風險）；DATA_FLOW.md（10/03）整份早於自建上游、時間鏈與實測不符；兩個預告收集器擇一；app 頁尾顯示母表來源；check_daily 改判「完成了沒」。

### 7.6 文件矛盾（Opus 找到）
①DATAPACK_ADAPTER「匯入後緊接 apply_chips_baseline」vs PLAN「selfhost 必須略過」②PLAN §2.5 上市融資用 OpenAPI MI_MARGN 推定日期，實作已改帶日期的網站端點③night §8／PLAN §4-2「櫃買預告端點未找到」，現已在用 tpex_exright_prepost④PLAN「原始價＋因子表另存」vs 轉接層其實仍存還原價每次整份重算⑤HANDOFF 10-07 §5-6「10/12 起每日 OpenAPI 累積」，實際 10/7 起就在跑（排程尚未在真實交易日跑過）⑥selfhost_collect.yml 第 3 行與註解寫「每日收集」，實為每週⑦data-all.md recon「10/12 起每日」但沒有 workflow 在跑 recon⑧「2,148 vs 1,969 檔」其中 159 檔最後交易日早於 9/01 多為下市股，不是涵蓋變大。

### 7.7 建議 10/8～10/11 逐日（Opus）
10/8 讀今晚兩份量測結果→修預告快照（已修）→Opus 審→使用者拍板 B1／B4／影子模式→寫每日法人（B5）＋存 NextReferencePrice→晚上看 openapi_daily 首次真排程與 23:59 週收集；10/9 查週收集、寫 CI 產 zip 並實跑量耗時（B3）、本機驗因子口徑（B7）、設計每日事件因子（B6）；10/10 寫 swing PACK_SOURCE／自動退回／略過 baseline（B2）、使用者建 PAT（B9）、產比對報告（B8）、寫 zip 驗收（B11）；10/11 Opus 全審、用 10/08 資料端到端乾跑＋退回演練（B13）、go/no-go 題目為「10/12 起影子雙跑」而非切換。

## 8. 使用者 2026-10-07 下午拍板（針對 §7）
1. **影子雙跑從 10/12 起、正式切換維持 10/24**（最早 10/16 晚 go/no-go 不採用，因 10/17–18 使用者外出）。B1 的舊決定（15 日規則、「維持舊管線、自建每週核對」、DATAPACK_ADAPTER「平時用上游」）視為改寫：以本節為準。
2. **新日子進母表＝方案 (a)**：每天把 OpenAPI 日線／融資（以及之後的每日法人、當天事件）併進自建資料，再跑 adjust／產 zip；等於推翻 10/06「自建只跑週末」。官方請求仍要節制（每天約 10 個）。
3. **建一顆唯讀 PAT**（fine-grained、只選 `tw-hold-data`、Contents: Read-only、期限一年），secret 名稱 `TWHOLD_DATA_READ_PAT`，設在 tw-swing repo；由使用者自己建（`gh secret set TWHOLD_DATA_READ_PAT -R tongxiaooppo-boop/tw-swing`，token 不貼進對話）。**建好後要：驗 swing workflow 讀得到私有 Release、記入到期提醒清單。**（狀態：使用者尚未建，待回報。）

> **更正（使用者指出）**：swing 實際改用自建來源是 **10/24**，不是 §7.7 逐日排程字面上的 10/10。§7.7 的「10/10 寫 swing PACK_SOURCE／自動退回」指的是**寫好開關與退回程式**，不是切換。影子雙跑（10/12 起）只在 tw-hold 側：自建官方口徑資料每天與上游比對，**swing 全程仍吃上游**。因此 PAT（§8-3）最早用在 swing 第一次用自建 zip 乾跑（原計畫 10/19 母表比對），建在那之前都行，非今天必須。
> 時程維持：10/12～18 影子期、10/19 母表比對、10/23 go/no-go＋退回演練、10/24 切換；使用者 10/17–18 外出期間 swing 不動。tw-hold 側 10/8～10/11 的工作：B5 每日法人、存上櫃 NextReferencePrice、B3 CI 產 zip、B4 每日併入、B6 事件因子、B7 因子口徑驗證。

## 9. 傍晚進度（15:50 更新）：誰做了什麼、下一步
### 9.1 已 push（`d14edf6`）
- **每日三大法人收集**：`collect_inst`（上市 T86＋上櫃 `insti/dailyTrade`，網站端點帶日期；重用 `selfhost_chips` 解析）。台北 18:00 起試今天、隔日清晨班補前一晚、08:00～18:00 不請求、取到就停；列數下限（上市 500／上櫃 300）＋法人合計恆等式（不符 >2% 不存；2015～2026 共 2,864 交易日回算 0 筆不符）。存 `openapi_inst.parquet`。Release 缺該檔但 fetch log 有寫入記錄時只設 `INST_DISABLED`（停用法人），**不拖垮日線／融資／預告表**。缺口檢查已納入法人（只警告，不自動回填；漏的日子由每週收集 14 天窗口補進 `selfhost-data` 的 `inst.parquet`）。→ **§5-1（每日法人）、§7.3 B5 完成**（尚待 18:00 後班次實際寫入驗證）。
- **上櫃次日參考價**：`PRICE_COLS` 新增 `next_ref`／`next_limit_up`／`next_limit_down`（`daily_close_quotes` 的 NextReferencePrice／NextLimitUp／NextLimitDown；上市 NaN，固定 float）。→ B6 的上櫃當天因子可直接用官方次日參考價。
- **PAT 完成（B9）**：tw-swing secret `TWHOLD_DATA_READ_PAT` 已建，tw-swing 新增手動 workflow `check_data_pat.yml`（`0dd7d28`、`8d96159`）驗證讀得到 `tw-hold-data` 私有 Release、且讀不到其他私有 repo。到期約 2027-10-07，記憶檔 `tw-hold-bundle-pat-expiry.md` ⑤。
- 使用者三項決定見 §8（影子雙跑 10/12、方案 (a) 每天併入、唯讀 PAT）；swing 切換仍是 10/24。

### 9.2 ⚠️ 今天線上實測發現：上櫃日線 OpenAPI 會被截斷
`d14edf6` 之後手動跑 `openapi_daily.yml`（15:48）：**`tpex_day` 失敗「Response ended prematurely」**（`daily_close_quotes` 一次回 12,194 列約 4MB，官方偶爾回被截斷的 JSON；Opus 審查時本機也遇過）。`fetch()` 原本失敗就放棄，OpenAPI 只回最新一天、漏了補不回來。
- **已修但尚未 commit／push**：`fetch()` 最多試 3 次（失敗後等 5、15 秒），截斷／連線錯誤／5xx 重試，4xx 與「回應不是非空列表」不重試；新增 2 個測試，全套 446 passed。**檔案在工作樹（`scripts/selfhost_openapi_daily.py`、`tests/test_selfhost_openapi_daily.py`），沒經 Opus 審，等使用者同意再 push。**
- 仍可考慮：上櫃日線改用網站端點 `dailyQuotes`（帶日期、補得回來）當第二來源；重試仍失敗時整天缺資料（缺日偵測會警告，網站端點補得回來）。

### 9.3 備援盤點（使用者問「自建上線有什麼備援」）
- 已有：官方 OpenAPI↔官方網站端點（網站帶日期）、原上游（10/24 前就是正式來源，自建出問題不影響現行）、每日 5 班＋每週一次（補近 14 天）、寫入守門（新版不得比舊版差、縮水保護、缺檔中止、單向 src）、轉接層（本機版）。
- **沒有**：swing 切換開關＋自動退回上游（B2，零實作；10/23 要演練）、zip 驗收（B11）、官方 zip 在 CI 產出（B3）、產出太晚的退回（B10）。
- 單點：官方端點同時掛掉（無免費可靠第三來源）、上游本身（別人 repo 無 SLA）、私有 Release／PAT、GitHub 排程延遲 2～9 小時。
- 結論：真正的備援是「退回上游」，而退回機制還沒寫；10/24 能不能切取決於 B2 與退回演練。

### 9.4 今晚量測（§1）狀態
兩支背景程式（官方輪詢 PID 32868、swing 觸發 PID 49660）仍在跑；15:48 時 `T86` 與上市日線尚未公布 10/7，上櫃法人已有 782 列（Opus 15:35 實打）。明早讀 `poll_log.jsonl`、`trigger_log.jsonl`。

### 9.5 下一步（排序）
1. 使用者決定是否 push 9.2 的重試修正（建議今晚 18:00 班次前 push，否則上櫃日線可能再被截斷而漏當天）。
2. 18:00 後看 `openapi_daily` 的班次：`twse_inst`／`tpex_inst` 是否寫入、`openapi_inst.parquet` 是否出現在 Release。
3. 10/8：讀量測結果；B6 事件因子設計（先驗證 TWT49U 當晚是否含當日事件、預告表公式對含配股／現增的準確度）；B7 因子口徑本機驗證；10/8 週四 23:59 第一次真正週收集（含 selfhost 閘門修正 `fa44379` 的實測）。
4. 10/9～10/11：B3 CI 產官方口徑 zip 並實測耗時／記憶體、B4 每日併入 raw 再 adjust、每日事件因子寫入（暫定因子 `provisional`，除權息日有官方價才啟用，官方結果出來覆蓋並記差異）；10/12 起影子雙跑；swing 側 B2 在影子期寫、10/19 乾跑。
