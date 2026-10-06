# tw-hold 交接 — 自建上游：對帳收尾、防呆補齊、事件簿（2026-10-06 下午，承 HANDOFF_2026-10-06）

> **自足執行指令。你在全新對話、沒有上下文。** Windows；`d:\g\claude\` 下有 `tw-swing\`、`tw-hold\`、`books\`。
> ⚠ 跑腳本先 `cd /d/g/claude/tw-hold`；python 一律 `PYTHONIOENCODING=utf-8`。
> ⚠ **使用者規則：Opus 審 → 問使用者 → 才 push。** 本機有未 push 的 commit，pull 前先 `git status`／`git log origin/main..`。
> ⚠ **口徑結論先 grep 再寫**：`books/new-book6/tw-stock-data-main/CLAUDE.md`（120KB）與 `docs/READ_CONTRACT.md`（177KB）是別人踩坑的紀錄；我 2026-10-06 沒讀就下了錯的成交量口徑結論。彙整版：**`docs/data-fix.md`**（避坑指南＋「我們有沒有防」對照表）、`docs/data-qu.md`（外部 AI 查證題與核對結果）。
> ⚠ 外部 AI（Gemini／GPT）只做「查證事實」；回覆一律拿資料驗（它們錯過：Yahoo Close 含不含配股、6201 轉板、2026-04-09 是不是連假後、編造 2614 的預估參考價…）。

---

## 0. 現況

| | |
| :-- | :-- |
| tw-hold `main` | 本機領先 origin 12 個 commit（含今天的 `c4ff8c6` 與後續），**都沒 push** |
| 自建庫 | 全在本機 `data/selfhost/`（gitignored，約 500MB）：`raw_prices`（含 `chg`）、`inst`、`margin`（含 `margin_prev`／`short_prev`／`note`）、`notrade`、`refmark`、`stophalt`、`corp_actions`、`adj_prices`、`ledger`；2015-01-05～2026-10-05，2,864 天 |
| 沒接下游 | tw-hold／tw-swing 現行仍用上游 data_pack（接縫 1,576 件還在）；自建庫尚未被任何頁面消費 |
| GitHub | Release `selfhost-data` 沒建、`selfhost_collect.yml` 從沒在 Actions 跑過 |
| 測試 | `python -m pytest -q` → 338 passed |

## 1. 今天做完的（程式；細節看 commit 訊息與各檔檔頭）

**收集端**：近 3 日曆日重抓覆蓋（官方收盤後會更正，實測 10-05 投信 14 檔、成交量 17 檔）；排程加台北 23:59 第三班；休市複本守門（TPEx 融資券休市日回前一日複本）；跨市場同日重複去重（merge **與**每日路徑）；`margin_prev`／`short_prev`／`note`；`notrade` 旁表（有量無價列）；`refmark` 旁表（官方行情的漲跌標記：上市 X／上櫃 除息、除權）；`chg`（官方漲跌價差，close−chg＝官方參考價）；`selfhost_stophalt.py`（停止買賣每日快照，累積檔只增不減）；上櫃變更面額官方來源 `tpex_par`（pvChgRslt）。

**還原端**：同日減資＋除權息只套減資；事件日晚於最後實價日的事件不套用（今天抓到 6 件被套進 `adj_prices`，最新價≠未還原價）。

**閘門**：融資恆等式改看「逐日不符比例中位數」並升級為擋上傳；單日 >30% 只警告（官方隔日調帳）。

**分析／偵測**：`selfhost_recon.py`（自建還原價 vs 上游快照 `books\n`，近 250 日：1,762/1,969 檔相符，其餘歸因到上游缺陷）；`selfhost_ledger.py`（每檔事件簿 `ledger.parquet`＋flag 偵測；`--ticker 2614` 印時間軸）；`selfhost_monthly_review.py`（月初完整性＋官方事件對帳＋待 AI 查證清單）。

## 2. 今天查證出的重要事實（別重查）

1. **官方行情自己標事件日**：上市「漲跌(+/-)」欄 `X`、上櫃「漲跌」欄寫「除息／除權／除權息」。全史相鄰交易日標記日 16,967 個，事件表對上 16,941 個，**其餘 26 個全是轉板首日**（市場別改變）→ 事件表完整性有獨立證據。事件簿 `refmark_no_event` 就是這個偵測器（目前 0 筆）。
2. **價格跳動 flag 381 個全部能歸因**：三個來源收盤逐列一致（資料沒壞）、tw-stock-data 的 adj 事件我們一件沒漏；原因是無成交日後「官方參考價≠我們前一筆收盤」（官方 `close−漲跌價差` 才是參考價，官方漲跌幅都在限制內）。成因規則（無成交日參考價改變）**未驗證**。
3. 還原後仍跳的 `adj_jump` flag 剩 70 個（42 檔）：20 個在事件日（例 2429 2024-07-02 現增因子 0.749 但收盤 +46.7%、6225 2026-08-18 +62.5%）、50 個是官方標 X 但無事件的長缺日後復牌（例 6131 2019-04-10 −74.4%，缺 219 天）。**這 70 個是目前最可能的「真缺口」候選**，還沒逐一查。
4. 成交量／成交金額口徑：上市我們與 tw-stock-data 逐列相同（含零股）；**上櫃我們的量一律較大（0.7%～2%），兩個上櫃端點口徑不同，上櫃含不含零股未定論**（待用 TPEx 大盤統計加總驗證）。「2020-10-26 斷點」資料不支持。
5. 融資「前日餘額≠昨日今日餘額」是官方隔日調帳（2019-02-11、2026-04-09 約 54% 個股；全期 33 天超過 10%）；以前日餘額為準；`note` 講的是**次一營業日**。
6. FinMind 不能當備援（投信上櫃 2018–2020、補班週六自營是錯的）；Yahoo `Close` 含配股調整；FinMind／tw-stock-data 都是官方轉載，**沒有真正獨立的第二來源**。
7. 現增：官方除權息參考價 A（我們存這個）≠ 減除股利參考價 B（官方開盤／漲停基準）；2614（10-06 除權息，權息＋現增 38.2%@12.80）A=16.13、B=17.31；上游 Yahoo 在除權息日**前一晚**就套事件。**A/B 的決策文件還沒寫**（tw-stock-data 與我們用 A、tick-stock-panel 主張 B）。
8. 減資併現增：我們用 TWTAUU 的「除權參考價」，tw-stock-data 用「恢復買賣參考價」，差約 2%（3536 於 2015-03-20；3312 於 2018-04-10），其餘 238/240 件相同。

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

## 6. 還沒做／待決定

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
