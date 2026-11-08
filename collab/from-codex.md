# D04 完成回報（2026-11-08）

## 完成項

1. `scripts/selfhost_shares.py`：填完全部框架函式，保留函式簽名、常數與 COLS；完成兩市場官方解析、重試與請求間隔、交易日曆、來源優先序合併、差異警告（附前 10 筆）、TSD 匯入、同日比對、asof 查詢及寫檔檢查。收集模式每 10 個交易日合併寫入，失敗日不寫、成功日保留；TSD 匯入僅補缺少主鍵。
2. `scripts/selfhost_gate.py`：僅將 shares 納入 DATASETS、DAILY 與 ABS_MIN（TW 900／TWO 700）。
3. `.github/workflows/selfhost_collect.yml`：下載與上傳清單加 shares.parquet，週快照清單加 shares，官方未還原日線步驟後加逐日發行股數步驟。

既有測試未修改；未改下游市值／排名、未改 tw-swing、未操作 Release、未 push。

## Commit

- 分支：main
- hash：`cfa54abe416992cd05fe96db5a64f10fa4808163`
- 訊息：`D04：官方逐日發行股數收集＋TSD 歷史匯入`
- commit 僅含上述三個指定檔案。

## PROOF_CMD

測試環境設定 `PYTHONUTF8=1`；透過 `PYTEST_ADDOPTS=--basetemp=.d04-pytest-target`／`.d04-pytest-full` 將本輪 pytest 暫存放在專案內，結束後刪除。一般沙箱無法寫測試暫存與 shares.parquet，網路有 WinError 10013；提升權限後五條均完成，以下為最終結果。

### 1. 指定測試（exit 0）

```text
python -m pytest tests/test_selfhost_shares.py -q
.............................                                            [100%]
29 passed in 1.05s
```

### 2. 完整測試（exit 0）

```text
python -m pytest -q -p no:cacheprovider
............... [ 95%]
............................................................             [100%]
1419 passed, 9 skipped in 194.16s (0:03:14)
```

實際為 1419 passed／9 skipped，與任務書預估的 1424 passed／4 skipped 有差異；兩者總數皆 1428，無 failed。依讀檔限制，未另外讀其他測試或設定檔調查跳過原因。

### 3. 六日期官方／TSD 比對（exit 0）

```text
python scripts/selfhost_shares.py --verify-tsd D:/g/claude/databook/tw-stock-data-main-1107/tw-stock-data-main --dates 2015-01-05,2016-08-25,2018-03-15,2021-02-26,2024-06-03,2026-11-06
      date market  n_official  n_tsd  n_both  n_equal  ratio
2015-01-05     TW         874    873     873      873    1.0
2015-01-05    TWO         680    682     680      680    1.0
2016-08-25     TW         898    896     896      896    1.0
2016-08-25    TWO         716    717     716      716    1.0
2018-03-15     TW         930    929     929      929    1.0
2018-03-15    TWO         748    749     748      748    1.0
2021-02-26     TW         961    959     959      959    1.0
2021-02-26    TWO         786    786     786      786    1.0
2024-06-03     TW        1025   1023    1023     1023    1.0
2024-06-03    TWO         819    819     819      819    1.0
2026-11-06     TW        1101   1099    1099     1099    1.0
2026-11-06    TWO         892    892     892      892    1.0
失敗日：[]
```

### 4. TSD 歷史匯入（exit 0）

```text
python scripts/selfhost_shares.py --import-tsd D:/g/claude/databook/tw-stock-data-main-1107/tw-stock-data-main
新增列數：5043467；總列數：5043467
```

匯入後核對：
```text
rows= 5043467 range= 2015-01-05 00:00:00 2026-11-06 00:00:00
market  src
TW      tw-stock-data    1099
TWO     tw-stock-data     892
duplicate_keys= 0
```

### 5. 官方區間收集（exit 0）

```text
python scripts/selfhost_shares.py --start 2026-09-01 --end 2026-10-05
2026-09-29：1987 列
2026-09-30：1985 列
2026-10-01：1984 列
2026-10-02：1985 列
2026-10-05：1985 列
抓了 23 天；失敗日：[]；overridden=0
```

最終 shares.parquet 為 5,043,541 列，含 official 45,642 列（23 天）、tw-stock-data 4,997,899 列。2026-11-06 仍為 TW 1,099／TWO 892，src 全為 tw-stock-data。

## 自行採用的小疑問

- TPEx 真實 JSON 的成功狀態為小寫 `stat="ok"`；成功狀態以大小寫等價判定，缺少 stat 仍依 parse_tpex 的 docstring 及測試按日期、表格與欄名驗證。TWSE 維持要求 `stat="OK"`。六日期驗證已確認全部相符。
- 股數只接受正整數（含 CSV 常見的整數小數寫法），非整數值視為無效，避免截斷股數。

## 需要 Opus 決定的事

無。
