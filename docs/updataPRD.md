> ⚠️ **本檔已被 [`updatePRD-opus.md`](updatePRD-opus.md) 取代**（2026-10-08 Opus 審查訂正版 + 拍板結果 + 事後審查）。兩檔矛盾以後者為準；本檔只留作初稿對照，**不要再依本檔施工**。

# updataPRD — 自建上游完整更換計畫 + 全資料線「主要／備援／監控」總表

> 版本：2026-10-08 上午草擬，給 Opus 審。**這份是計畫書，不是現況紀錄**；現況事實以各 HANDOFF 為準，本檔標出「已做／未做／未驗」。
> 範圍：①把母表主來源由他人上游 `data_pack.zip` 換成自建官方口徑（tw-swing 吃、tw-hold 間接受益）；②盤點 tw-swing + tw-hold 其餘所有資料線的主要／備援／監控，找出缺口。
> 取代／整合：`PLAN_OWN_UPSTREAM.md`、`PLAN_OFFICIAL_MASTER.md`、`DATAPACK_ADAPTER.md`、`HANDOFF_2026-10-07_pm.md §7–§12`、`DATA_FLOW.md §6`。矛盾處以本檔與使用者 10/6–10/8 拍板為準（§0.3）。
> 時間一律台北時間。

---

## 0. 一頁摘要

### 0.1 目標
把 tw-swing／tw-hold 唯一的價量籌碼來源（他人 repo `maosof007-collab/tw-stock-scanner` 的 `data_pack.zip`，匿名、無 SLA、有已知「還原接縫缺陷」）換成**自建官方口徑**：官方未還原價 + 官方事件因子，還原價在匯入時才算。換完後上游降為**備援**（自動退回）。

### 0.2 時程（使用者拍板）
| 日期 | 事項 |
|---|---|
| 10/8（四）23:58 | 第一次真正的每週收集（10/9 國慶補假，本週最後交易日＝週四） |
| **10/12（一）起** | **影子雙跑**：tw-hold 側每天產自建官方口徑母表並與上游比對；**swing 全程仍吃上游** |
| 10/16 前 | 做一次累積檢查（使用者 10/17–18 外出） |
| 10/19（一） | 母表比對（官方口徑 vs 現行） |
| 10/23（五） | go/no-go ＋ **退回演練** |
| **10/24（六）** | swing 實際切換自建來源（週末，週一前有兩天緩衝） |
| 10/25（日） | 驗證日：手動跑全流程、對帳，不通過即回滾 |
| 10/26（一） | 第一個交易日實戰 |

### 0.3 已拍板的決定（改寫舊決定）
1. 影子雙跑 10/12 起，切換維持 10/24；舊決定「連續 15 日達標才切」「維持舊管線、自建每週核對」「DATAPACK_ADAPTER 平時用上游」**作廢**，以本節為準。
2. 新日子進母表 = **方案 (a)**：每天把 OpenAPI／網站端點的日線、融資、法人（及之後的當日事件）併進自建 raw，再 adjust、產 zip。
3. 母表 = 官方未還原價 + 事件因子表另存；方案 A（接縫因子表）**取消**；回測／模擬單**整個重來**（「沒真金白銀前都沒差」）。
4. 唯讀 PAT `TWHOLD_DATA_READ_PAT`（tw-swing secret，到期約 2027-10-07）已建並驗證。
5. 資料抓取放 tw-hold CI，抓完存私有 Release（`tw-hold-data`），tw-swing 只讀成品。
6. 短線掃描**等融資齊了只跑一次**；推薦除依賴融資/券者，日線 + 法人到齊就重算。
7. **2026-10-08 新增**：上市日線改走官網 `MI_INDEX`（帶日期）為主、OpenAPI 備援；日線「取到就停」。
8. 使用者原則：**官方還沒公布不請求（不偷跑）**；手動觸發也限制在規律時段；GitHub 排程延遲 2～9 小時是常態，拿不準先問、不自行改頻率；Opus 審 → 問使用者 → 才 push；改 cron／程式後兩 repo 全套測試先過再 push，指令鏈不得讓 `pytest | tail` 吞失敗碼。

### 0.4 一句話現況
**資料收集端已就緒**（每日 OpenAPI／網站端點收集、每週官方收集、事件表、閘門、轉接層都已上線並在 CI 實跑），hold-data 已補到 10/7。**真正的缺口在「產 zip → swing 讀取 → 自動退回」這段下游**：B2（swing 開關＋自動退回）、B3（CI 產 zip）、B4（每日併入 raw）、B6（當日事件因子）、B7（因子口徑）、B11（zip 驗收）、B13（端到端乾跑＋退回演練）**幾乎零實作**。「退回上游」才是真備援，目前沒有。

---

## 1. 資料流（目標狀態）

```
【官方】 TWSE/TPEx OpenAPI + 官網帶日期端點
   │ tw-hold CI（每日 openapi_daily 多班；每週 selfhost_collect 補 14 天）
   ▼
私有 Release（tw-hold-data）
   openapi-daily : openapi_prices / openapi_margin / openapi_inst / openapi_forecast / fetch_log
   selfhost-data : raw_prices / inst / margin / notrade / refmark / stophalt / corp_actions / ev_* / forecast_twt48u / snap-*
   [新] datapack-selfhost : 官方口徑 data_pack_selfhost.zip（帶日期＋雜湊＋manifest）
   │
   ▼ 每日：併入 raw（B4）→ selfhost_adjust → selfhost_to_datapack → zip 驗收（B11）→ 上傳
tw-swing update_data.py（PACK_SOURCE=selfhost）
   取 datapack-selfhost（PAT 讀）→ 驗收不過／過舊／下載失敗 → 自動退回 upstream（B2）
   → import_data_pack（selfhost 模式略過 apply_chips_baseline）→ 清單／bundle → tw-hold rebuild（不變）
```
- 切換點只有 `tw-swing/scripts/update_data.py` 一處（`daily.yml` 三槍 + `publish_bundle.yml` 四條觸發路徑都經過它）。
- tw-hold app／三清單 schema 不變，只是價格改官方口徑（約 1/3 歷史還原價列變動 >0.2%；成交量比上游高 3–11%；標的 ~2,147 vs 1,969 檔）。

---

## 2. 自建上游：各資料的「主要／備援／監控」

> 狀態：✅ 已上線並實跑　🟡 已寫未實測／部分　⬜ 未做　❓ 結果未知需驗證

### 2.1 日線（價）
| | 內容 | 狀態 |
|---|---|---|
| 主要（上市） | **官網 `rwd/zh/afterTrading/MI_INDEX?date=&type=ALLBUT0999`**（帶日期、回應自述日期必須等於目標日）。**2026-10-08 剛改，本機測試過、尚未 push** | 🟡 |
| 主要（上櫃） | OpenAPI `tpex_mainboard_daily_close_quotes`（16:00 起即有當日；含 `NextReferencePrice`／次日漲跌停；約 4MB 偶被截斷，已 3 次重試） | ✅ |
| 備援 | 上市：OpenAPI `STOCK_DAY_ALL`（**實測 T+1 清晨約 05:20 才換成前一日，當日價值低**）；上櫃：尚無網站端點備援（`dailyQuotes` 帶日期，`selfhost_raw_prices` 已有、每週收集在用，**每日版未接**）；最終備援＝退回上游 | 🟡 |
| 補洞 | 每週收集用帶日期網站端點補近 14 天 | ✅ |
| 監控 | 回應日期斷言、列數下限（上市 500／上櫃 400）、縮水保護、`openapi_fetch_log.jsonl`、缺交易日警告、`selfhost_gate`、`selfhost_status.json` | ✅ |
| 取到就停 | 目標日（平日 16:00 後＝今天，其餘＝前一平日）已存就不再請求；**2026-10-08 剛寫，未 push** | 🟡 |
- 已知：上櫃 OpenAPI 檔被櫃買定時重產（Last-Modified＝最後重產，不是首次公布）；取到就停可保留首次公布版。
- 已知：官方端點同時掛掉時**沒有免費可靠第三來源**（Yahoo 逐檔且與上游同源；FinMind 全市場未驗；其他第三方站不碰）。

### 2.2 三大法人
| | 內容 | 狀態 |
|---|---|---|
| 主要 | 上市 T86（網站端點）／上櫃 `insti/dailyTrade`（網站端點），帶日期；上市 18:00 起即有、**上櫃實測到 10/8 06:00 都還沒出現（公布時間未明）** | ✅ / ❓ |
| 備援 | 每週收集 14 天窗口補；最終退回上游 | ✅ |
| 監控 | 列數下限（500／300）、合計恆等式（不符 >2% 不存；2015–2026 回算 0 筆不符）、缺口只警告不自動補 | ✅ |
- 上櫃 OpenAPI `tpex_3insti_*` 可能比網站端點乾淨（**未驗證**）。

### 2.3 融資券
| | 內容 | 狀態 |
|---|---|---|
| 主要（上櫃） | OpenAPI `tpex_mainboard_margin_balance`；**官方首見 10/8 00:30** | ✅ |
| 主要（上市） | 網站端點 `MI_MARGN`（帶日期）；**官方首見 10/8 00:30**；已存日子在隔日 00:00 前最後抓取者再打一次（官方隔日調帳），內容有差才整天替換 | ✅ |
| 備援 | 每週收集補；最終退回上游 | ✅ |
| 監控 | 融資恆等式、列數下限、縮水保護；**上市融資缺日只警告不自動補**（週收集補另一個檔） | 🟡 |

### 2.4 除權息／減資／面額（事件→因子）
| | 內容 | 狀態 |
|---|---|---|
| 主要（結果） | 官方事件結果表（TWT49U 除權息、TWTAUU 減資、TWTB8U 面額）→ `corp_actions` | ✅（每週） |
| 預告 | 上市 `TWT48U_ALL`、上櫃 `tpex_exright_prepost`（每日快照 `openapi_forecast.jsonl`，同市場間隔 ≥3h）；與週收集的 `forecast_twt48u.jsonl` 並存，**需指定以誰為準** | 🟡 |
| 當日事件因子 | **無來源、無寫入點**（B6）：事件日前一晚母表要有因子，否則還原價在事件日出現假跳空。上櫃可用官方 `NextReferencePrice`；上市要驗 TWT49U 當晚是否含當日事件，或用預告表＋公式暫定（source=forecast，官方結果出來後覆蓋並記差異） | ⬜ ❓ |
| 備援 | 減資 FinMind 逐檔輪詢（僅交叉驗證，每週 150 檔）；上游階梯反推（退回時） | ✅ |
| 監控 | `resolve_events` conflict、`refmark_no_event`（官方漲跌欄標記 X／除息 vs 我們事件表互為對帳）、`selfhost_recon` | ✅ |
- 因子口徑三項未定（B7）：官方參考價取整（上市截斷到分／上櫃四捨五入到分，純現金息已驗 100%）、現增用減除股利參考價、同日權息＋減資。
- 切換週 10/12–16 有 21 件事件，4 碼 7 件落在未驗的配股／現增公式。

### 2.5 母表產出（adjust → zip）
| | 內容 | 狀態 |
|---|---|---|
| 主要 | `selfhost_adjust`（raw × 因子）→ `selfhost_to_datapack`（zip 格式同現行 data_pack，tw-swing 匯入不用改）。本機驗收：2,147 檔 0 解析失敗，融資 100% 相符，法人 99.4–99.95% | 🟡 本機 |
| CI 產出 | **從沒在 CI 跑過**（B3）：耗時、記憶體（全表 + 202MB zip）未知；`selfhost_collect.yml` 沒接 adjust／to_datapack；`datapack-selfhost` Release 不存在 | ⬜ ❓ |
| 備援 | 退回上游（B2，未實作） | ⬜ |
| 監控 | zip 驗收（B11）：最新日、各市場檔數、最後一列 raw＝官方收盤、0050 連續、籌碼恆等式；現有 `selfhost_gate` 只涵蓋 `selfhost-data`，不含每日 OpenAPI／法人／zip | ⬜ |

### 2.5b 事件因子與還原日線：怎麼算（實作對照 `EVENTS.md`、`selfhost_adjust.py`）

**公式**：`adj(t) = raw(t) × Π { factor_e : 事件日 date_e > t }`。事件日當天與之後的列不乘（事件日是新價格水位的第一天）；高低開收同乘；**成交量保持官方原值**（不隨分割調整，Yahoo 只對分割調量，口徑差另行對帳）。存「原始價＋事件因子表」，還原價是衍生物，匯入時才算。

**因子來源**：`factor = ref_price ÷ prev_close`，**直接用官方給的參考價，不自己從公式算**（官方值 vs 公式自算互為對帳）。
| 事件（官方原詞） | 官方表 | 基準價欄位 | 備註 |
|---|---|---|---|
| 除息／除權／除權息 | TWSE `TWT49U`；TPEx `exDailyQ` | 除權息參考價（因子用這個）、減除股利參考價、開盤競價基準、漲跌停 | 純現金息公式驗證：上市「前收−現金股利，**無條件捨去到分**」5,390 件 100%；上櫃「**四捨五入到分**」3,739 件 100% |
| 減資 | TWSE `TWTAUU`；TPEx `revivt` | 恢復買賣參考價（減資併現增＝除權參考價） | 退還股款：(停止買賣前收−每股退還股款)÷換股率；彌補虧損另一套；與 tw-stock-data 有 2 件差約 2%（3536、3312） |
| 變更股票面額 | TWSE `TWTB8U`；TPEx `pvChgRslt` | 恢復買賣參考價 | 64 筆（含 FinMind 補 40） |
| 分割（ETF） | **官方來源未找到**，只有 FinMind | 分割前後價 | 2 件（0050 2025-06-18、0052 2025-11-26）；反分割 0 件 |
- 官方**沒有**獨立的現金增資／轉增資事件，都是「除權」欄位；不另立名詞。
- 現金增資：官方因子＝理論除權價÷前收，認購價高於市價時 factor>1（TPEx 約 483 件、TWSE 約 11 件）。**開盤競價基準**含現增時取最接近「減除股利參考價」的檔位，與「除權息參考價」不同，另存一欄不混用。

**去重（同一件事多來源只套一次）**`resolve_events`：每檔每日按類別分組——`div`（除息／除權／除權息）、`par`（面額／分割／反分割）、`red`（減資）；同組取優先序第一筆（官方 > `fm_split` > `fm_par`／`fm_reduction`），**因子差 >0.5% 記 `conflict`** 供人工檢視；不同類別同一天各自套用並記 `multi_class`；唯一例外：**減資＋除權息同日只套減資**（官方減資參考價已含息值，兩邊都乘會扣兩次；目前資料 0 組，是防呆）。

**停牌缺口閘門**`stop_gap_gate`（連乘前）：減資／面額變更事件日前一交易日就有實價、且收盤對不上官方停止買賣前收盤 → 拒收（寫 `adjust_rejected.csv`）；只有收盤對不上 → 警告。

**輸出與追溯**：`adj_prices.parquet`（含 `raw_close`）、`adjust_log.csv`（每個被套用的事件：class、type、factor、source、重複來源因子、conflict）——任何還原價階梯都能追到事件與來源。

**官方對帳（已驗證）**：事件日有實價的 18,027 筆，收盤全落在官方漲停與跌停價內（0 例外）；官方行情「參考價被重設」標記（上市漲跌欄 `X`／上櫃寫除息除權）16,967 個，事件表對上 16,941 個，其餘 26 個全是轉板首日。

**切換後每日怎麼算（目標，B4／B6 尚未實作）**
1. 當日收盤併入 raw（官方未還原價）。
2. **事件日前一晚**母表就要有該事件因子（否則事件日出現假跳空）。三層保險：① **預掛**：事件一定提前一週以上公告，每日抓預告表（上市 `TWT48U_ALL`、上櫃 `tpex_exright_prepost`），取參數（除權息日、現金股利、無償配股率、現增配股率、認購價）；② **暫定因子**：以預告參數＋純現金息公式（上市截斷、上櫃四捨五入；上櫃另可直接取 `daily_close_quotes.NextReferencePrice`）算，source=`forecast`、標 `provisional`，**除權息日母表有官方價才啟用**；③ **官方覆蓋**：當日／每週官方結果表出來後覆蓋暫定因子，**差異記入 conflict 報表**。優先序：官方結果 > 暫定（forecast）> 上游階梯反推（退回時）。
3. 重算範圍：因子表只新增／更新少數事件，受影響的只是該檔事件日前的歷史列；**建議只重算有新事件的檔**（全市場整份重算需先實測 B3 耗時）——此取捨待 Opus 審。
4. 預告限制：ETF 現金股利常「待公告」（10/6 快照 62 件中 40 件）→ 這些不能預掛，靠官方當日結果；減資／面額變更預告端點與提前天數**未驗證**；預告表歷史不可回溯（`TWT48U` 只有未來），旺季代表性要等明年夏天。
5. 未驗項（結果未知）：① TWT49U 當晚是否含當日事件（B6）；② 配股／現增暫定公式準確度（切換週 10/12–16 有 21 件事件，4 碼 7 件：1449 配股、1727 現增、1463、1565、2938、4903、6548 正落在未驗公式）；③ 6129 現增單一樣本偏支持「減除股利參考價」。

**口徑拍板項（B7，需使用者決定）**：①官方參考價取整規則（上市截斷／上櫃四捨五入已驗）；②現增用「除權息參考價」還是「減除股利參考價」；③同日權息＋減資。

**不屬事件但會讓價格序列斷開的狀態**（官方原詞另存，不併入因子）：停止買賣（`stophalt`，每天快照只增不減，無歷史）、無成交（`notrade`）、漲跌欄標記（`refmark`）、融資券註記（`margin.note`，次一營業日）、轉板（無價格調整，行情首日標 X）。

**其他還原相關口徑（已知、已接受或待決）**
- 分割／面額手動對照：`reference/corporate_actions.py` 的 `SPLITS`（4 筆）＋`IGNORE_JUMPS`，加 build 時自動偵測；上游偶爾沒還原面額變更／分割，靠此表補。切換後官方事件表是否完全取代它**待驗**（ETF 分割官方來源缺）。
- Yahoo 與官方的約 0.7% 口徑差：使用者拍板「不管」；Yahoo 只當交叉對帳，不當真值。
- 73 件 `seam_factor_diff`（上游因子與官方不同）、70 個還原後仍跳動的 `adj_jump`：方案 A 取消後，切換自建母表即以官方因子為準（這些差異來自上游缺陷，自建不繼承）；仍要在 B8 比對報告列出歸因，並留意「官方因子製造約 0.7% 小跳動」的 case。
- 成交量：官方含零股／盤後定價，比上游高 3–11%；分割點的量能／成交值類指標在切換源時會不連續。
- 不在收集範圍：5–6 碼 ETF、上櫃 ETF；TWSE 歷史現增欄位（`TWT49UDetail` 未接）；公司分割減資、股票分割／反分割官方名稱待查。

### 2.6 tw-swing 讀取端（切換開關）
| | 內容 | 狀態 |
|---|---|---|
| 現況 | `update_data.py:76` URL 寫死、`download_pack` 匿名 GET（私有 Release 沒匿名網址）、`--require-fresh` 看上游 Last-Modified、`apply_chips_baseline` 寫死 | — |
| 要做 | `PACK_SOURCE`（repo 變數，預設 `upstream`）；`gh`＋PAT 下載私有 Release；新鮮度改看 zip 內最新交易日；失敗／過舊（>10 天）／驗收不過 → 自動退回上游並 `::warning::`＋來源標示；selfhost 模式**略過** `apply_chips_baseline`（DATAPACK_ADAPTER 與 PLAN 兩文件矛盾，以「略過」為準，理由：FinMind 底稿非官方、投信上櫃 2018–2020 有誤） | ⬜ |
| 回滾 | 變數改回 `upstream`，下一班即恢復，不用 revert | 設計 |
| 兩 repo 時序（B10） | tw-hold 產 zip 若晚於 swing 第一槍，每槍都退回上游＝等於沒切；需 repository_dispatch（新 PAT）或 swing 輪詢 | ⬜ |

### 2.7 排程與觸發
| 項目 | 現況 |
|---|---|
| `openapi_daily` | cron 台北 16:02／18:02／20:02／23:02／隔日 04:02（UTC 08:02／10:02／12:02／15:02／20:02，週一至五）。**10/7 晚首次真排程：5 班只啟動 3 班**（實際台北 01:21／02:50／04:21，全成功），16:02／18:02 兩班無 run（疑 GitHub 延遲／丟棄，未證實） |
| `selfhost_collect` | cron 23:58（UTC `58 15`，週一至五）+ `last_trading_day_guard`（當週最後交易日才跑；LATE_CUTOFF_HOUR=12 處理跨午夜）；**內部兩處 `date -u +%u = 5` 的寫死週五判斷 2026-10-08 剛改為跟 guard 走，未 push** |
| 觸發原則 | 手動／外部 dispatch 不經排程器、會準時，但只在規律時段；防呆測試 `tests/test_workflow_schedules.py`（兩 repo 各一份）：cron 不在 :00/:30/:59、`event.schedule ==` 字串須存在於同檔 cron、同 repo cron ≥10 分鐘 |
| 官方公布時間實測（10/7→10/8） | 上櫃日線 16:00 即有；上市 T86 18:00 即有；上櫃法人 06:00 仍無（未明）；上市／上櫃融資 00:30 首見；**上市 OpenAPI 日線 06:00 才換成 10/7（Last-Modified 05:20）**；上游資料包約 00:00 前後才好 |

---

## 3. 其他資料線（tw-swing + tw-hold 現有）：主要／備援／監控

> 這些**不在本次更換範圍**，但盤點出缺口，列入改善項（§6）。

| # | 資料 | 主要 | 備援 | 監控 | 漏了能補？ | 缺口 |
|---|---|---|---|---|---|---|
| 1 | 還原日線／法人／融資券（現況） | 上游 data_pack | 自建（本計畫） | `bundle_gate`（只比日期）、`--require-fresh` | 上游活著＝可全量重匯 | 🔴 單點；`data-latest` 以 `--clobber` 覆蓋無歷史版本；缺「內容縮水」檢查 |
| 2 | 財報五表 | FinMind（週六 10:07） | 已 commit 進 repo 可回退 | 無 | 可（滾動） | 🟡 token 額度；免費層部分端點 400 |
| 3 | 006201／0050 | FinMind `TaiwanStockPrice` | `price_series_guard` 保留舊檔 | 守門員 | 可 | 🟡 單源 |
| 4 | 分割事件 | FinMind `resolve_splits` + `corporate_actions.py` 手動表 + build 時自動偵測 | 手動對照表 | 偵測 | 可 | 🟡 |
| 5 | 處置／注意股快照 | TWSE/TPEx OpenAPI（daily 三槍） | 三槍互為備援 | 無 | 🔴 **永久缺** | 三槍全掛該天歷史缺 |
| 6 | 月營收當日快照 | TWSE/TPEx OpenAPI | 同上 | 無 | 🔴 永久缺（影響 PEAD 可用日） | 同上 |
| 7 | PER/PBR/殖利率 | OpenAPI 每日增量（publish_bundle 內） | FinMind 一次性回補 | 無 | 🔴 缺的那天無快照 | — |
| 8 | 主動 ETF PCF | 三家投信官網（非官方承諾） | `pcf_retry` 17:13／19:13 + rebuild 內一次 | `span_days` 容錯 | 🔴 只給當天 | 無改版偵測 |
| 9 | 國際指數／總經 | yfinance（06:37） | 傍晚班 | 卡片「落後 N 天」標記 | 可（每次重抓 2 年） | 🟡 單源；Finnhub 備援**待真的連續過期才寫** |
| 10 | 台指期日夜盤 | TAIFEX OpenAPI | 無 | 夜盤缺失告警（但 webhook 未設＝靜默） | 🔴 夜盤永久缺 | — |
| 11 | 外資期貨未平倉 | TAIFEX CSV | OpenAPI | 每次重抓近 14 天 | 可 | 🟢 |
| 12 | 三大法人（總經導航用 BFI82U） | TWSE BFI82U（帶日期） | 補近 14 天 | — | 可 | 🟢 |
| 13 | TDCC 集保週快照 | TDCC 開放資料 | 無 | 無 | 🔴 該週缺 | 🟢 2029 前用不到 |
| 14 | bundle 傳遞 | swing `data-latest` Release → tw-hold `fetch_bundle`（PAT） | rebuild cron 備援 | `heartbeat`（只檢查不修；`freshness_check --json` 缺 `|| true` 已知 bug） | — | 🟡 |

### 3.1 全域監控與告警現況
- **`ALERT_WEBHOOK` 從沒設**（使用者回絕設定）：所有 notify-failure 形同空。使用者偏好「**自癒／備援優先於告警**」。
- swing 盤前管線守門（雲端 routine 週二～六 08:16，`/tw-swing-check-pipeline`、`check_daily.py`）：`check_actions_runs` 用 `gh run list --limit 3` 未指定 workflow，會漏看 daily 失敗；使用者要的是「**完成了沒**」（08:00 前清單／bundle／hold 三清單資料日＝最新交易日），不是「有 failure 就 WARN」。尚未修。
- tw-hold `heartbeat.yml`：只檢查不修，GitHub 實測延遲到 13:00–14:00 才跑。
- 自建側：`openapi_fetch_log.jsonl`、`selfhost_status.json`（commit 進 repo）、`selfhost_gate`（新版不得比舊版差）、缺日警告。
- 憑證到期：`TWSWING_BUNDLE_PAT` ~2026-12-07、`TWHOLD_DISPATCH_PAT` ~2027-09-08、`TWHOLD_DATA_READ_PAT` ~2027-10-07、`DATA_REPO_PAT` ~2027-09-29。

---

## 4. 現在做到什麼程度（Checklist）

### 4.1 收集端（tw-hold）
- [x] 每週官方收集（日線／法人／融資券／事件）→ 私有 Release `selfhost-data`，閘門＋單向 src＋縮水保護
- [x] 每日 OpenAPI 收集：上櫃日線（改 `daily_close_quotes` 含次日參考價）、上櫃融資、上市融資（網站端點）、三大法人（T86／insti）、預告表（上市＋上櫃）
- [x] 請求時段限制（日線 16:00～隔日 08:00、融資 22:00 起、法人 18:00 起）、統一重試 3 次（10／20 秒）、fetch log
- [x] 所有 cron 避開 :00／:30／:59，防呆測試兩 repo 各一份
- [x] 10/7 資料已補齊（日線 TW 1089／TWO 873、法人 1083／782、融資 1059／802；gate OK）
- [x] 唯讀 PAT 建立並驗證（`check_data_pat.yml`）
- [x] 10/7–10/8 量測：官方各資料首次公布時間、上游資料包好的時間（見 §2.7）
- [~] 上市日線改官網 `MI_INDEX` 為主＋日線取到就停＋`selfhost_collect` 週快照改跟 guard（**本機寫完、兩 repo 全套測試過，未經 Opus 審、未 push**）
- [ ] 上櫃日線第二來源（網站 `dailyQuotes` 帶日期）
- [ ] 每日法人缺日自動補（目前只警告）；上市融資缺日自動補
- [ ] 指定預告表以誰為準（每日 vs 週收集）

### 4.2 母表／轉接（上線阻擋項 B1–B13，Opus 10/7 盤點；狀態已更新）
| # | 項目 | 狀態 | 結果未知？ |
|---|---|---|---|
| B1 | 舊決定撤銷 | ✅ 本檔 §0.3 + 使用者 10/7 拍板 | 否 |
| B2 | **swing 開關＋自動退回＋略過 baseline＋來源標示** | ⬜ **零實作** | 低 |
| B3 | **CI 產官方口徑 zip 並實測耗時／記憶體** | ⬜ | **是** |
| B4 | 每日併入 raw → adjust（方案 a） | ⬜（10/12 影子期需要） | 中 |
| B5 | 每日法人收集 | ✅（10/7 實寫入 1083／782） | — |
| B6 | 當日事件因子／暫定因子寫入點 | ⬜（上櫃 `next_ref` 已存） | **是**（TWT49U 當晚是否含當日事件） |
| B7 | 因子口徑三項驗證＋拍板 | ⬜ | **是** |
| B8 | 10/19 母表比對報告（`selfhost_datapack_parity.py` 已有） | ⬜ | **是** |
| B9 | 唯讀 PAT | ✅ | — |
| B10 | 兩 repo 時序（產 zip 晚於 swing 第一槍） | ⬜ 需設計 | 中 |
| B11 | zip 驗收／閘門 | ⬜ | 低 |
| B12 | 同日兩來源不一致以誰為準 | ⬜ 建議：週收集網站端點（帶日期、含官方更正）> OpenAPI 快照 > 上游；延伸 `merge_day` 的 src 等級 | 低 |
| B13 | 端到端乾跑＋退回演練 | ⬜（10/9 補假、10/10–11 週末無新交易日，第一個真實增量日是 10/12） | **是** |

### 4.3 文件
- [ ] `data-all.html／md`：階段 3 的方案 A 接縫訂正時程作廢、測試數、階段 1「已上線」vs 手動腳本要區分（演進分頁已加）
- [ ] `PRD.md` 嚴重過期（架構敘述與現況不符）
- [ ] 文件矛盾 8 項（見 HANDOFF_2026-10-07_pm §7.6）收斂到本檔

---

## 5. 還要改動多少 + 測試多少

> 估計來自 Opus 10/7 盤點 + 今天已完成的部分扣除；「天」＝工作天，含自測、不含 Opus 審與使用者拍板等待。

### 5.1 改動
| 區塊 | 動到的檔 | 估計 |
|---|---|---|
| B3 CI 產 zip | `selfhost_collect.yml`（或新 `selfhost_datapack.yml`）、`selfhost_adjust.py`、`selfhost_to_datapack.py`；stock_list 取得方式（CI 沒有 tw-swing 的 stock_list → 用 bundle universe 或把 stock_list 放私有 repo）；Release 命名／保留份數／雜湊 manifest | 0.5～1 天 |
| B4 每日併入 raw | `selfhost_openapi_daily.py` 下游或新 `selfhost_daily_merge.py`；`openapi_*` → `raw_prices/inst/margin` 的 schema 對映、src 等級、冪等 | 1～1.5 天 |
| B6 當日事件因子 | `selfhost_events.py`／`selfhost_adjust.py` 加 provisional 因子（source=forecast，官方後蓋）；上櫃用 `next_ref`；先驗 TWT49U 當晚內容 | 0.5～1 天 |
| B7 因子口徑 | 本機以 `ev_official` 比對 483＋11 件，產報告；程式改動小，**主要等使用者拍板** | 0.5 天 |
| B2 swing 切換 | `tw-swing/scripts/update_data.py`、`daily.yml`、`publish_bundle.yml`、新 `fetch_selfhost_pack.py`、來源標示寫入 bundle meta、`_chips_guard`／`audit_chips` 在新來源下確認 | 1 天 |
| B10 時序 | tw-hold 產完 zip → `repository_dispatch` swing（新 PAT，actions:write）或 swing 輪詢 | 小時～0.5 天 + 一顆 PAT |
| B11 驗收 | 新 `selfhost_zip_gate.py`（最新日、各市場檔數、最後一列 raw＝官方收盤、0050 連續、chips 恆等式） | 0.5 天 |
| B8 比對報告 | 執行既有 `selfhost_datapack_parity.py` + 補：檔數（159 檔最後交易日早於 9/01 多為下市股）、還原價變動分布、量／turnover 翻面、籌碼、`daily_list` 重播、0050 | 0.5～1 天 |
| B13 乾跑＋退回演練 | 用 10/8 資料跑兩 repo selfhost 模式 → 切回 upstream 驗恢復；故意弄壞 zip 驗自動退回 | 0.5 天 |
| 監控補強 | 守門改判「完成了沒」＋固定 Python/套件；`heartbeat` `|| true`；`bundle_gate` 內容縮水檢查；上櫃日線第二來源；缺日自動補 | 1～1.5 天 |
| 文件 | data-all／PRD／DATA_FLOW 收斂 | 0.5 天 |
| **合計** | | **約 7～10 工作天**（Opus 10/7 估 4～5 天為「必要阻擋項」，不含監控補強與文件） |

### 5.2 測試
現況：tw-hold 454 passed、tw-swing 834 passed。新增需求（每項都要有）：
- **單元**：zip 驗收各檢查項的通過／失敗案例；`PACK_SOURCE` 三條路徑（upstream／selfhost 成功／selfhost 失敗退回）；provisional 因子被官方覆蓋並記差異；每日併入的冪等、src 等級、縮水保護；日線取到就停＋`price_target` 邊界（週末／週一清晨／國定假日）；`fetch_twse_web` 日期不符丟棄、空表＝未公布不退備援、失敗退備援。
- **契約**：轉接層 zip 能被 tw-swing 的 `import_data_pack.parse_one`／`chips.normalize_*` 解析（已有 parity，需納入 CI 或固定樣本）。
- **防呆**：cron／`event.schedule` 字串同步測試（已有）；新增「workflow 讀的 Release 資產名稱存在」靜態檢查。
- **整合（手動/乾跑）**：B13 端到端；退回演練（故意弄壞 zip、斷 PAT、過舊 zip 三種）；影子期每日比對自動報告。
- **回歸**：改完兩 repo 全套測試，指令鏈不得吞失敗碼。
- 估計新增測試 **40～70 個**；乾跑／演練各至少 1 次完整紀錄。

---

## 6. 改善項（非阻擋，依價值排序）

1. **備援 A（最高）**：swing 自動退回上游（= B2）——真備援，且是 10/24 能不能切的前提。
2. **監控 A**：管線守門改判「完成了沒」＋固定環境；失敗自動補跑（需雲端 routine 的 `actions:write` 是否可行**未確認**）。
3. **監控 B**：zip 驗收（B11）＋`bundle_gate` 加內容縮水檢查（擋壞資料覆蓋好 bundle；`data-latest` 目前無歷史版本）。
4. **備援 B**：上櫃日線網站端點第二來源；每日法人／上市融資缺日自動補。
5. **永久缺資料線**（§3 #5–8、#10）：目前只靠多班；可評估是否把 daily 三槍之外再加一條獨立備援，但這些多數 2029 前用不到，優先度低。
6. 排程可靠度：openapi_daily 5 班只起 3 班（10/7 晚）——先觀察 10/8 晚是否重現，再決定是否加班或改外部觸發；**使用者原則：不自行改頻率**。
7. 其他：`prices_raw_close`（填息率）改官方 raw；tw-swing stock_list ETF 存成 '50'（8 檔）；`import_data_pack` 先刪再寫非原子（本機風險）；上市日線端點變動後 `data-all`／DATA_FLOW 同步。

---

## 7. 更換前注意事項（Go／No-Go 與風險）

### 7.1 No-Go（任一成立就不切，維持上游）
- 自動退回演練失敗（含 PAT 失效、zip 缺失、zip 過舊、驗收不過四種）
- CI 產 zip 完成時間晚於 swing 第一槍，導致每槍都退回上游（B10 未解）
- 每日法人或當日事件因子缺（B5／B6）
- 影子期 zip 驗收未連續 **5 個交易日**全綠
- 比對有**未歸因**的大差異
- 因子口徑三項使用者未拍板（B7）
- 唯讀 PAT 失效或未驗證

### 7.2 已知風險與對策
| 風險 | 對策 |
|---|---|
| 官方端點同時掛／改版，無免費第三來源 | 退回上游（真備援）；web／OpenAPI 雙端點；回應日期斷言 |
| OpenAPI 只回最新一天、漏了補不回 | 多班 + 取到就停 + 每週帶日期網站端點補近 14 天（日線、法人、上市融資補得回；**上櫃融資 OpenAPI 漏了週收集是否補得回需確認**） |
| GitHub 排程延遲 2～9 小時、可能丟班（10/7 晚 5 班只起 3） | 不靠 cron 準時；規律時段手動／外部 dispatch；`last_trading_day_guard` 容忍跨午夜 |
| 上游本身（別人 repo）出問題的接縫缺陷：data_pack 6/2 後除權息事件舊歷史水位偏高（1297 檔受影響） | 這正是換官方口徑的原因；影子期比對量化 |
| 口徑變動：約 1/3 歷史還原價列變動、成交量 +3～11%、標的數 2,147 vs 1,969、流動性門檻 3,000 萬邊緣翻面 | 10/19 比對報告；回測／模擬單整個重來（已拍板） |
| 切換日剛好有大量事件（切換週 21 件，含配股／現增） | B6／B7 先解；影子期涵蓋；切換選週末 |
| 私有 Release／PAT 單點 | 到期清單；`check_data_pat.yml`；退回上游 |
| 官方資料事後更正（會更正前日餘額） | 前日餘額為準；融資隔日調帳重打；每週覆蓋 |
| 籌碼來源改變：FinMind 底稿（cutoff 2026-08-26）與官方 | selfhost 模式略過 baseline；確認 `_chips_guard`／`audit_chips` |
| 公開 app 顯示官方原始價的條款風險 | 已決定個股頁**不做還原/原始切換**；app 仍顯示還原價 |

### 7.3 切換當天流程
1. 10/23 go/no-go + 退回演練全過；使用者點頭。
2. 10/24（六）設 repo 變數 `PACK_SOURCE=selfhost`；手動跑 `daily.yml`、`publish_bundle.yml` 各一輪；對帳。
3. 10/25（日）全流程再跑一輪；檢查頁尾來源標示、三清單、短線頁、0050 基準。
4. 不通過 → 變數改回 `upstream`（不 revert 程式），下一班即恢復。
5. 10/26（一）觀察 21:07／01:07／05:32 三槍與 bundle 發佈；上游保留至少 2 週並行比對，不立刻降頻（降頻條件另議，見 `tw-hold-upstream-downgrade-rule`）。

### 7.4 動手前須知（踩過的坑）
- 外部說法（含 GPT）只當線索，**拿真實端點／資料驗證**；規格文件別寫「官方 API 有 bug」，寫「欄位待驗證，以網站端點為準」。
- 改 cron：先 `grep -rn "event.schedule" .github`、檢查 `tests/` 是否寫死分鐘、`check_daily.py` 的 `_cron_since`、文件同步、兩 repo 全套測試。
- 新測試不得寫進真實 `data/selfhost/` log（用 fixture 隔離）。
- 判斷「取到」要看有沒有資料列：TPEx 網站端點沒資料時仍回傳請求日期。
- 新欄位讀 CI 產出 JSON 一律 `.get()`（app 部署比資料快）。
- 改 `candidate_pool.py` 等邏輯後要重跑 build，app 讀的是預算 JSON。
- 不在官方還沒公布時請求；手動觸發只在規律時段。

---

## 8. 給 Opus 的審查重點（請特別挑）
1. §0.2 時程：影子雙跑 10/12、切換 10/24，B3／B4／B6／B7 在 10/11 前能否真的做完？有無更穩的切分？
2. B10：產 zip 與 swing 三槍的時序方案（dispatch vs 輪詢 vs 固定時間）哪個最不會「每槍都退回上游」？
3. 退回上游的**觸發條件與防「半新半舊」**：zip 部分檔缺／日期不一致時，退回是整包還是逐項？
4. 方案 (a) 每日併入 raw 與「週收集官方網站端點覆蓋」的**優先序與覆蓋規則**（B12）有無漏洞（含官方事後更正）。
5. 今天新寫的上市日線官網主來源：回應日期斷言、`src` 等級、舊 OpenAPI 來源被覆蓋的行為、取到就停對「首次公布版 vs 重產版」的取捨。
6. 影子期驗收標準「連續 5 個交易日全綠」是否足夠（10/9 補假＋週末，真實增量日只有 10/12–10/16）？
7. 監控缺口排序（§6）是否合理；「完成了沒」的判準定義。
8. §2.5b 事件因子：暫定因子三層保險的優先序與「重算範圍」（只重算有新事件的檔 vs 全市場）是否可靠；配股／現增公式未驗就上影子期的風險。
9. 有沒有我漏掉的單點、或「切換後才會暴露」的相依（stock_list／產業別、新標的名稱空白影響定存線產業 ≤40% 上限、`DAILY_RECENT` 重切、`prices_raw_close` 口徑）。
