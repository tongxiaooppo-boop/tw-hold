# D09 完成回報（2026-11-08）

## 完成項

- 已填實 `scripts/selfhost_tdcc.py` 全部 15 個未實作函式，並新增 `_prepare_tsd`、`_read_tsd_hist`、`_read_tsd_csv` 私有輔助函式。
- 支援官方 CSV 抓取／清理、TSD 歷史匯入、來源優先合併、逐週比對、恆等式與 ISO 缺週檢查、寫檔驗證及四種 CLI 模式。大量資料合併、比較與恆等式檢查皆採向量化處理。
- 官方覆蓋不同數值 TSD 時會警告並列出前 10 筆差異。匯入只補現有檔案缺少的主鍵。
- 以 AST 比對確認既有函式簽名、常數與 docstring 未變；未改測試、其他 selfhost 腳本、workflow、tw-swing 或 TSD 資料。
- 未接排程、閘門或下游；未上傳 Release、未 push。本次專案內測試暫存目錄已清除。

## Commit

`daa1908f4ba03b64c6f3afc0ec566341eefd0d1c`（main）

訊息：`D09：集保股權分散表收集＋TSD 歷史匯入`

本次 commit 僅含 `scripts/selfhost_tdcc.py`；`data/selfhost/tdcc.parquet` 未 commit。

## PROOF_CMD

六條皆已執行，最終 exit code 皆為 0。測試設定 `PYTEST_ADDOPTS` 將暫存目錄放在本專案內，並設定 `PYTHONIOENCODING=utf-8` 保留中文輸出。一般沙箱曾出現寫入腳本與 pytest 暫存目錄的 PermissionError，改以核准的執行權限完成，沒有跳過實際資料驗證。

### 1. 專用測試

```text
python -m pytest tests/test_selfhost_tdcc.py -q -p no:cacheprovider
.............................                                            [100%]
29 passed in 1.81s
```

### 2. 完整測試

```text
python -m pytest -q -p no:cacheprovider
........................................................................ [ 98%]
.................                                                        [100%]
1448 passed, 9 skipped in 204.65s (0:03:24)
```

實際總數 1457 與預期相同，但比任務書的 `1453 passed, 4 skipped` 多 5 項 skipped、少 5 項 passed；沒有 failed 或 error。未修改測試或跳過條件；本次 `-q` 輸出未列出跳過原因。

### 3. TSD 封存／CSV／官方核對

```text
python scripts/selfhost_tdcc.py --verify-tsd D:/g/claude/databook/tw-stock-data-main-1107/tw-stock-data-main
      date   n_a   n_b  n_both  n_equal  ratio
2026-09-04 55692 55692   55692    55692    1.0
2026-09-11 55709 55709   55709    55709    1.0
      date   n_a   n_b  n_both  n_equal  ratio
2026-11-06 56083 56083   56083    56083    1.0
```

### 4. 歷史匯入

```text
python scripts/selfhost_tdcc.py --import-tsd D:/g/claude/databook/tw-stock-data-main-1107/tw-stock-data-main
匯入新增 17,571,370 列｜累積 351 週｜最早 2020-01-03 最晚 2026-11-06
```

### 5. 官方最新週併入

```text
python scripts/selfhost_tdcc.py
資料日期 2026-11-06｜3,299 檔｜新增 0 列｜overridden 0｜累積 351 週
```

overridden 為 0，沒有需要列出的數值差異。

### 6. tw-swing 快照核對

```text
python scripts/selfhost_tdcc.py --verify-twswing D:/g/claude/tw-swing/data/tdcc
      date   n_a   n_b  n_both  n_equal  ratio
2026-09-11 55709 52432   52432    52432    1.0
2026-09-18 55726 52448   52448    52448    1.0
2026-09-24 55743 52464   52464    52464    1.0
2026-10-02 55760 52480   52480    52480    1.0
2026-10-08 55879 52592   52592    52592    1.0
2026-10-16 55998 52704   52704    52704    1.0
2026-10-22 56015 52720   52720    52720    1.0
2026-10-30 56032 52736   52736    52736    1.0
```

本機可比對的快照為上述 8 週，全部相符率 1.0。

## 資料檔大小

`data/selfhost/tdcc.parquet`：118,489,202 bytes（約 113.00 MiB）。

## 自行採用的小疑問

無。

## 需要 Opus 決定的事

無。
