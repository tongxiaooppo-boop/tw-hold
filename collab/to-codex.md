# 【tw-hold】D09 任務書：集保股權分散表收集＋TSD 歷史匯入（版本 2026-11-08 v2：不接排程／閘門、從 2020 起匯）

> **專案：tw-hold（`D:\g\claude\tw-hold`，main 分支）。不是 tw-swing。** 下面所有相對路徑都以 `D:\g\claude\tw-hold` 為根；所有指令都先 `cd D:\g\claude\tw-hold` 再跑。`D:\g\claude\tw-swing\collab\to-codex.md` 是另一個專案的舊任務（D04b，已完成），不要讀、不要照做。回報寫到 `D:\g\claude\tw-hold\collab\from-codex.md`。

## 要讀的檔案（只准讀這些，皆在 tw-hold）
- `scripts/selfhost_tdcc.py`（全檔；**框架，照檔頭與各函式 docstring 填實作**）
- `tests/test_selfhost_tdcc.py`（全檔；**規格，不准改**）
- `scripts/selfhost_shares.py` 第 69–80 行（`_get`）、第 160–181 行（`merge_rows`）、第 233–244 行（`write`）、第 309–319 行（`_typed`）當樣板

不准讀其他檔、不准上網查資料（PROOF_CMD 第 3 條的官方端點除外）、不准改 tw-swing 與 TSD 目錄。直接在本專案目錄（D:\g\claude\tw-hold，main 分支）做，不要複製 repo。暫存檔、一次性腳本只放本專案內，結束前刪掉。

## 背景（一句話）
集保官方只給最新一週、一年後就查不到，沒收的週永久失去；本輪寫好收集程式（逐週長表），並把 TSD 2020-01-03 起的 351 週歷史匯入本機。**這是備用程式：不接排程、不接閘門、不上 Release、下游不接**（平常每週下載 TSD 到本地就好，TSD 出事才啟用）。

## 要改的檔案
1. `scripts/selfhost_tdcc.py`：把每個 `raise NotImplementedError` 換成實作。**不改函式簽名、常數名與值、`COLS`、docstring 寫的行為**；可加 `_` 開頭的私有輔助函式（`main` 的 docstring 指定要有 `_read_tsd_hist`、`_read_tsd_csv`）。
2. 不新增其他檔；**不改 `selfhost_gate.py`、`.github/workflows/`**。

## 實作重點（docstring 已寫，這裡只列容易錯的）
- 官方 CSV 帶 BOM、CRLF，股數有千分位逗號要先去掉；代號要 strip（TSD 封存是定寬 6 碼，含空白）。
- TSD 封存 parquet 的 `date`、`stock_id` 是 category，先轉 str 再處理。
- 資料量：匯入約 1,757 萬列 → 不要逐列 Python 迴圈；`merge_rows`、`compare`、`identity_bad` 一律用向量化寫法（concat＋sort＋drop_duplicates、merge、groupby／pivot）。
- `compare` 比對時，兩邊任一為空的欄位不參與相等判斷（tw-swing 快照 1–15 級沒有股數、17 級沒有 pct）。
- `--import-tsd`：TSD 不得蓋掉任何現有列（只補缺的主鍵）。
- `write` 的檢查失敗要 raise，不能靜默修正。

## 不准做
- 不改測試檔、不改其他 selfhost 腳本、不改 tw-swing、不動 Release（不准 `gh release upload`）、不 push。
- 不用任何新資料源；不改 `SRC_PRIORITY`、`VERIFY_MIN`、`KNOWN_GAPS`、`HIST_START`、`MIN_TICKERS`。
- 規格看起來有矛盾（含測試寫錯）→ 停下寫進 from-codex.md「需要 Opus 決定的事」（格式：問題一句＋2–3 選項＋你的建議），不要自己改框架或測試。意義明確的小疑問自行採用並在回報註明。

## PROOF_CMD（照跑、照貼最後幾行）
```
python -m pytest tests/test_selfhost_tdcc.py -q -p no:cacheprovider
python -m pytest -q -p no:cacheprovider
python scripts/selfhost_tdcc.py --verify-tsd D:/g/claude/databook/tw-stock-data-main-1107/tw-stock-data-main
python scripts/selfhost_tdcc.py --import-tsd D:/g/claude/databook/tw-stock-data-main-1107/tw-stock-data-main
python scripts/selfhost_tdcc.py
python scripts/selfhost_tdcc.py --verify-twswing D:/g/claude/tw-swing/data/tdcc
```
預期：
1. `29 passed`。
2. `1453 passed, 4 skipped`、0 failed（基準 1424＋新 29）。
3. (a) 表 2 列：2026-09-04、2026-09-11，`ratio` 都是 1.0（Opus 已手算逐格 100% 相同）；(b) 官方最新週（應為 2026-11-06，若官方已換成 11-13 會印「TSD 沒有，略過」）`ratio` ≥ 0.999。exit 0。
4. 印「匯入新增 17,571,370 列｜累積 351 週｜最早 2020-01-03 最晚 2026-11-06」（Opus 用同樣規則手算：封存 2020-01-03 起 17,124,134 列＋csv 09-18～11-06 八週 447,236 列）。
5. 官方 2026-11-06 那週蓋掉 TSD 同週，**overridden 應為 0**；印「累積 351 週」（若官方已換成 11-13 則為 352 週）。不是 0 就貼前 10 筆差異（date、ticker、level、兩邊值），不要改程式去壓。exit 0。
6. 表約 9 列（2026-09-11～11-06，依 tw-swing 本機快照數），每列 `ratio` 1.0。exit 0。

若沙箱讀不到 TSD／tw-swing 目錄或不能連網，第 3～6 條跳過，在回報寫明「哪條、錯誤原文」，Opus 會自己跑。

## 回報格式（寫進 collab/from-codex.md，不貼程式碼）
- 完成項（對應「要改的檔案」1）
- commit hash（在 main commit，不 push；訊息「D09：集保股權分散表收集＋TSD 歷史匯入」；**`data/selfhost/tdcc.parquet` 不要 commit**）
- PROOF_CMD 六條的最後幾行輸出（第 3、6 條貼整張表）
- `data/selfhost/tdcc.parquet` 檔案大小
- 自行採用的小疑問（沒有就寫「無」）
- 需要 Opus 決定的事（沒有就寫「無」）
