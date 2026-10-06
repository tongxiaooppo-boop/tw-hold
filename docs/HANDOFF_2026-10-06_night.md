# tw-hold 交接 — 母表改用官方口徑：決策、計畫、待確認（2026-10-06 深夜，承 HANDOFF_2026-10-06_pm）

> **自足執行指令。你在全新對話、沒有上下文。** Windows；`d:\g\claude\` 下有 `tw-swing\`、`tw-hold\`、`books\`。
> ⚠ 跑腳本先 `cd /d/g/claude/tw-hold`；python 一律 `PYTHONIOENCODING=utf-8`。
> ⚠ **使用者規則：Opus 審 → 問使用者 → 才 push。** 使用者一律用中文溝通；使用者看不懂時要用白話＋舉例，不要繞。
> ⚠ 外部 AI（Gemini／GPT）只當線索，回覆一律拿資料驗；口徑結論先 grep 文件再寫（`docs/data-fix.md`、`docs/data-dl.md`、`books/new-book6/tw-stock-data-main/CLAUDE.md`）。
> 使用者說「太晚了腦袋不清醒」→ **下一輪先讀本檔，再繼續討論**；今晚什麼都沒動線上流程。

---

## 0. 一句話
**接縫因子表「方案 A」已退回；改走「母表完全用官方口徑」：官方原始價＋官方因子表另存，歷史由自建每週官方底包提供，每天尾巴用官方 OpenAPI，上游降為備援（外加每日法人尾巴）。時程：10/9–10 提早做「只存不使用」的兩件事，10/19 母表比對，10/24–25 上線。**
線上（tw-swing／tw-hold）數據**仍是上游、仍有接縫**，要到 10/24 才換；10–12 月事件少（每月約 15–50 件，7 月約 600），等待成本低。

## 1. 使用者已拍板的決定（別重新討論）
1. **方案 A 退回**（用因子表修上游接縫）。母表完全用官方；Yahoo 與官方約 0.7% 的 `seam_factor_diff` 口徑差「不管」。
2. **模擬單整個重來、回測重做**，「沒真金白銀前都沒差」→ 不處理持倉停損連續性、權益曲線跳動、舊口徑標註。（實測現行 27 筆模擬單報酬差中位 0.00%、最大 0.13%。）
3. **所有事件都要還原**（含除息；維持含息還原口徑，不改成只還原權值）。**個股查詢頁繼續只顯示還原價，不加切換**（別再提）。
4. **向上游 repo 回報「做不到」→ 不要再提。**
5. **母表結構**：存官方原始價＋因子表另存（同 tw-stock-data：存因子不存還原價），還原價匯入／讀取時才算；新事件＝加一列因子，不重寫歷史。
6. **每天尾巴用官方 OpenAPI 日線**（解掉 Yahoo 在除權息前一晚就乘因子的問題）；沒有 OpenAPI 的用網站端點；再沒有才用上游（備援順序：OpenAPI → 網站端點（有日期參數）→ 上游；每列記來源）。
7. **每日 OpenAPI 步驟放 tw-hold**（新增 tw-hold CI 每日 workflow，存私有 Release 小檔，tw-swing 之後讀）；**上市融資券只在日線日期一致時才收**；**預告表改用 OpenAPI `TWT48U_ALL`**（已驗證與網站版內容相同）。
8. **事件一定提前一週以上公告** → 每週末預掛下一週事件的**參數**（除權息日、現金股利、無償配股率、現增配股率、認購價；因子＝參考價÷前收，要等前一天收盤才算得出，所以預掛的是參數不是最終因子）。三層保險：預掛參數 → 上游近幾天階梯反推 → 每週官方結果表對帳。
9. **本月「靜默收集」**：不改線上管線；自建每週一次（當週最後交易日 23:59）；預告快照約 10/9、10/17、10/24 累積。使用者 10/17–18 外出。
10. **官方請求要節制**（使用者不想對官方暴露抓取行為）；OpenAPI 是 OGDL 授權、可用。

## 2. 現況
| 項目 | 狀態 |
| :-- | :-- |
| 四條線回補（Yahoo／TWSE／TPEx／FinMind） | ✅ 2026-10-05 23:35 結束，已合併上傳私有 Release `tongxiaooppo-boop/tw-hold-data`（tag `selfhost-data`），本機 `data/selfhost/` 也有（gitignore）。FinMind 那條輸出檔我讀不到（UTF-16），**沒親眼確認跑完**，但後續合併／對帳用的是完整資料 |
| `selfhost_collect.yml` | 手動演練 5 次成功（10/6 12:29–14:45）；**排程首次觸發＝2026-10-06 23:59（指定補跑日）**；之後每週當週最後交易日 23:59 |
| 線上母表 | tw-swing `daily_full.parquet` ＝ 上游 data_pack 原樣（接縫還在）；tw-hold bundle 同源 |
| 自建 `adj_prices` | 有用官方因子，**沒接任何下游** |
| 轉接層 `selfhost_to_datapack.py` | ✅ 完成並驗收（`docs/DATAPACK_ADAPTER.md`）；缺：tw-swing `--pack-source selfhost`、手動 workflow `selfhost_datapack.yml`、tw-swing 唯讀 PAT、影響報告 |
| 預告表快照 | ✅ `scripts/selfhost_forecast_snapshot.py`（OpenAPI 優先、失敗退網站端點；累積檔 `forecast_twt48u.jsonl` 進 Release）；已接進 `selfhost_collect.yml`；**10/8 起排程帶 OpenAPI 版**（已 push） |
| tw-hold git | `main` ＝ `origin/main` ＝ `44b4e93`（含 `cda2e60`）。**未進版控**（方案 A，已退回、保留備查）：`scripts/selfhost_seam_fix.py`、`tests/test_selfhost_seam_fix.py`、`docs/SEAM_FIX_STAGE0.md` |
| 測試 | `python -m pytest -q` → 411 passed（含方案 A 的測試） |

## 3. 時程（使用者）
| 日期 | 事項 |
| :-- | :-- |
| 10/7 | 查 10/6 23:59 那班（見 §4） |
| 10/8（週四）23:59 | **第一次真正的每週收集**（補 10/6–10/8）；10/9 早上查 |
| **10/9（補假休市）–10/10（週六）** | ★使用者要求：把原定 10/19 的「母表比對」提早，但**只存不使用**。我的理解與計畫見 §5，**待使用者確認三點後才動手** |
| 10/12 起 | 每日 OpenAPI 累積 |
| 10/17–18 | 使用者外出（預告快照約 10/17、10/24 各一份） |
| **10/19（週一）** | 母表比對（本機：轉接層產官方口徑 data_pack → tw-swing 匯入暫存 store → 與現行母表比） |
| 10/20–23 | 實作＋Opus 審＋乾跑；**10/23 晚上 go/no-go**（不過就延期，不硬上線） |
| **10/24（週六）** | 上線 |
| 10/25（週日） | 手動跑全流程驗證，不過就回滾 |
| 10/26（週一） | 第一個交易日實戰（tw-swing 三槍 21:00／01:00／05:30＋bundle 發佈） |

## 4. 明天（10/7）第一件事：查 10/6 23:59 那班
`gh run list --workflow=selfhost_collect.yml -R tongxiaooppo-boop/tw-hold --limit 5`；`gh run view <id> --log | grep -E "閘門|::error|::warning|Token is illegal|HTTPError|forecast"`。
1. 排程有沒有觸發並成功（GitHub 排程常延遲 30–60 分鐘；10/6 是指定補跑日 `FORCE_RUN_DATES`，應完整跑約 6–7 分鐘）。
2. 「閘門 通過」；raw_prices／inst／margin 最新日＝2026-10-06；無 `Token is illegal`／`HTTPError`／TPEx TLS 錯誤（FinMind 那步 `continue-on-error`，綠燈不代表成功，要 grep log）。
3. 私有 Release 檔案更新時間是 10/7 凌晨；公開 repo 沒有 `selfhost-data`。
4. **新增**：log 有「除權除息預告表快照」步驟，Release 多了 `forecast_twt48u.jsonl`（10/6 那班跑的是 `cda2e60` 的網站端點版；OpenAPI 版從 10/8 起）。
5. 10/7 23:59 那班應是 guard 輸出 `run=false`、其餘步驟 skipped（綠燈、幾秒）。
6. tw-swing 10/6 晚 21:00 `daily.yml`（第一次用新程式、守門改成不擋清單）、`rebuild`／`global_macro` 等 log 有 `[refdata] pull/push`。
7. 10/8 23:59 那班的**實測耗時**（補 5 天的真實時間）：既有 workflow `timeout-minutes: 60`，必要時調。

## 5. 待使用者確認（我已回覆理解，他說太晚、下次再討論）
使用者要求：原定 10/19 的比對提早到 10/9–10，「**僅先存不使用**」。我的理解與擬做：
1. 實作兩件**只存不用**的東西（Opus 審、使用者同意才 push）：
   - **tw-hold 每日 OpenAPI 收集 workflow**：多班、回應日期斷言、自己對交易日曆檢查有無洞、每列記來源、存私有 Release 獨立小檔（例 `openapi-daily`）、不進閘門、失敗不擋其他。休市期間會抓到 10/8 的資料，正好觀察「新日期出現前一直回前一天」與公布時間（**實測 10/6 19:33：上櫃日線已回 10/6、上市日線仍回 10/5 → 兩市場公布時間不同，上市較晚**）。
   - **每週官方底包產出 workflow**：轉接層接上，存私有 Release 獨立檔；目的是**提早在 Actions 上試跑看耗時與記憶體**（約 200MB zip），不是給 tw-swing 用。
2. **需使用者確認三點**：①「只存不使用」＝這兩件、tw-swing 完全不動（不加 `PACK_SOURCE`、不建 PAT）？②每天多 OpenAPI 請求（約 3–4 次、各 <1 秒）與新增 CI 執行量可接受？③照規則：寫完→Opus 審→問使用者→才 push？
3. 開工前還有：`docs/PLAN_OFFICIAL_MASTER.md` §4 的待拍板／風險清單（尾巴處理、預掛參數完整度、官方底包產出時間、籌碼略過 `apply_chips_baseline`、涵蓋範圍變動、口徑變動、daily `--require-fresh` 判準、轉接層未完成項）。

## 6. 今天查證的重要事實（別重查）
- **OpenAPI 涵蓋度**（實打＋讀 swagger）：TWSE OpenAPI 143 路徑，**沒有 T86／BFI82U／任何個股法人端點**，且**所有路徑都沒有日期參數**（只回最新一天）。有：上市日線 `STOCK_DAY_ALL`（1,381 列、0.1 秒、0.32MB）、上櫃日線 `tpex_mainboard_quotes`（1,013 列、0.3 秒）、上櫃融資 `tpex_mainboard_margin_balance`（918 列、0.4 秒）；上市融資 `MI_MARGN` **無日期欄**；上櫃法人欄名有 bug。減資／面額／上市除權息結果／漲跌標記無 OpenAPI。詳見 `docs/data-dl.md` §11。
- **Gemini／GPT 的法人說法**：T86／上櫃 dailyTrade 是**網站端點**（我們 `selfhost_chips.py` 已在用，可指定日期補抓），不是 OpenAPI；GPT 較準（承認 OpenAPI 沒有）。GPT 提到證交所網路資訊商店賣「三大法人買賣超檔」（TWT86UC／TWTAIUC）——**可能是付費授權管道，價格／格式／能否自動下載都沒查**。Gemini 給的「櫃買變更面額預告表」連結實為可轉債頁（錯）。
- **預告表 OpenAPI `TWT48U_ALL` 與網站版內容完全相同**（62 件、(代號,日期) 一致、配股率／現增配股率／認購價／現金股利全相同；網站版「待公告」＝OpenAPI 空字串；OpenAPI 多 4 欄且僅 6 件現增有值，未存；耗時約 9.5 秒）。**只比了一天一份快照。**
- **預告表現況（2026-10-06 快照）**：62 件、除權息日距抓取日 −4～23 天、多數約 13 天；**現金股利「待公告」40 件，全是 ETF**（48 件 ETF／14 件個股）→「事件一定提前一週知道」對個股大致成立、對 ETF 的金額不一定；提前最短天數需累積多週快照（10–12 月事件少，旺季 6–8 月代表性要等明年夏天）。
- **法人上游尾巴不能假設乾淨**：上游籌碼歷史有過 121 個複本日、11 個非交易日假資料、41% 空值、上櫃自營欄 8/27 起空白（已修）。尾巴要過守門（恆等式、複本日、非交易日、空值比例、日期斷言），不過就先不收、等週收集補。**法人網站端點有日期參數，補得回來**；「漏一天永久缺」的是 OpenAPI（只回最新一天）、處置股／月營收／停止買賣快照。
- **tw-stock-data 的還原做法**（`books/new-book6/tw-stock-data-main/adjust.py`，只讀了說明與範例）：存因子不存還原價；因子＝參考價÷前收；累積因子＝事件日嚴格大於該列日期的因子連乘、事件當天不乘、最新價因子＝1；減資因子常 >1（各事件種類範圍分開）；上市除權息用未捨入參考價（官方捨去到分、單邊偏差）；不還原成交量、不從價格跳空推估事件；法人每個平日抓兩次（18:23、23:47）、冪等合併。可借：上市參考價用未捨入值（我們實測累積約 −0.033%、單件最大 0.41%）。
- **自建 vs 上游還原價**（0.2% 內相符率）：上游原樣 全期 26.0%／近 250 日 48.7%；修完接縫 65.6%／93.8%；`seam` 事件階梯日前一天偏差中位 3.4%→0.00%；`seam_factor_diff` 73 件修後仍中位 0.69%（P90 1.55%、最大 20%）。6949（面額 0.05）、4747（面額 0.5）差 20 倍／2 倍＝上游不處理「變更股票面額」，自建有處理。→ 換成官方口徑時**約三分之一歷史還原價列變動 >0.2%**（含早年上游雜訊、因子口徑、減資／面額）；官方成交量比上游高 3–11%；涵蓋 ~2,148 vs 1,969 檔。
- **既有上游每次 1–2 小時（逐檔 Yahoo）；自建一次小量補抓約 6 分鐘**（日線 46 秒、法人＋融資 81 秒、事件 54 秒、減資輪詢 124 秒＝週五／手動才跑）；補 5 天、停機 >14 天或全量回補會慢很多（官方限流約每 5 秒 3 次；昨天單條上櫃舊籌碼回補 3.7 小時）。
- tw-swing 每天整份從上游 zip 重寫日線母表（`import_data_pack.py` 先刪 `DAILY_FULL`）；籌碼整份重匯後靠 `apply_chips_baseline.py` 疊回 FinMind 歷史。**selfhost 模式必須略過這一步**（官方底包已有完整官方籌碼，疊 FinMind 會用非官方蓋掉官方）。切換點只能放 `update_data.py`（`daily.yml` 三槍＋`publish_bundle.yml` 四條路徑都跑它）。

## 7. 方案 A 的乾跑結果（保留備查，已退回）
`scripts/selfhost_seam_fix.py`（未 commit）＋`docs/SEAM_FIX_STAGE0.md`：兩份上游快照（tw-swing 母表 10/3、books\n 10/5）各乾跑：納入 1,270 件（seam 1,197＋factor_diff 73）、排除兩階梯 4 件（2442、3546、8473、9933）；不變量與冪等全過；修正後 1,270 件全回 healed。Opus 審：必修五項已改（兩階梯自動排除、一年規則凍結 first_seen、healed 改以 r 判斷、dtype 保持、型別正規化）。**退回原因**：每天重乘＝多餘（最終做母表鎖定＋官方底包）、修不了口徑差／早年雜訊／減資面額。仍可借用：接縫偵測 `selfhost_seam_check.py` 當每週核對工具。

## 8. 還沒做／可之後
- 母表官方口徑的工程：`PACK_SOURCE` 開關與自動退回（要顯示當前母表來源）、tw-swing 唯讀 PAT（`tw-hold-data`，daily 與 publish_bundle 兩個 workflow 都要；加進到期提醒）、`--pack-source selfhost`、`selfhost_datapack.yml`、略過 chips baseline、`stock_list`／產業別對新標的補空、`prices_raw_close`（FinMind 來源 vs 官方口徑，影響填息率）、`DAILY_RECENT` 重切、`--require-fresh` 判準、10/23 go/no-go。
- 櫃買預告表端點未找到；減資預告表 `TWTAVU` 端點未驗證。
- `docs/DATA_PERFECT_TOPICS.md`（已 push）記錄「讓數據完美」議題與決策；70 個 `adj_jump` flag、上櫃成交量口徑、現增 A/B 決策文件仍未查（承 HANDOFF_2026-10-06_pm §6）。
- 備查：是否查證交所資料商店（付費授權法人資料）價格與可否自動下載——使用者尚未決定。

## 9. 踩坑（新增）
- 用 `str.replace()` 寫含 `\n` 的 Python 字串時，經 heredoc／非 raw 字串會變成真的換行，造成 `SyntaxError: unterminated string literal`——改檔用精確 Edit，改完先跑測試。
- `data/selfhost/` 是 gitignore；方案 A 的暫存輸出在 session scratchpad，不在 repo。
- 對官方的探測請求要節制：今天只對 OpenAPI 發了少量請求（日線、融資、預告表、swagger 各 1–2 次）與 1 次 TWSE 預告表網站端點。
- 使用者容易被「選項 A／方案 A／A 方案」混淆：討論時用白話命名，別重複使用同一個字母。
