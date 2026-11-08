# D04 任務書：官方逐日發行股數收集＋TSD 歷史匯入（版本 2026-11-08 v2：分支更正為 main）

## 要讀的檔案（只准讀這些）
- `scripts/selfhost_shares.py`（全檔 151 行；**框架，照檔頭與各函式 docstring 填實作**）
- `tests/test_selfhost_shares.py`（全檔 281 行；**規格，不准改**）
- `scripts/selfhost_raw_prices.py` 第 1–75 行、第 140–205 行（`_get`、`fetch_twse`／`fetch_tpex`、`collect_day` 的寫法當樣板）
- `scripts/selfhost_gate.py` 第 28–40 行（`DATASETS`、`DAILY`、`ABS_MIN`）
- `.github/workflows/selfhost_collect.yml` 第 70–112 行、第 153–170 行

不准讀其他檔、不准上網查資料（下面 PROOF_CMD 第 3、4 條的兩個官方端點除外）、不准改 tw-swing。直接在本專案目錄（D:\g\claude\tw-hold，master）做，不要複製 repo。暫存檔、一次性腳本只放本專案內，結束前刪掉。

## 背景（一句話）
市值用的股數現在只有 ap03 一天快照（且有 10% 檔數跟交易所當日發行股數不同）。交易所兩個端點可帶歷史日期回發行股數，tw-stock-data（TSD）本機已有 2015 起的同源歷史；本輪做「收集＋匯入＋驗證」，**下游（市值、排名）改用本輪不做**。

## 要改的檔案
1. `scripts/selfhost_shares.py`：把每個 `raise NotImplementedError` 換成實作。**不改函式簽名、常數名與值、`COLS`、docstring 寫的行為**；可加 `_` 開頭的私有輔助函式。
2. `scripts/selfhost_gate.py`：`DATASETS` 加 `"shares": "shares.parquet"`；`DAILY` 加 `"shares"`；`ABS_MIN` 加 `"shares": {"TW": 900, "TWO": 700}`。其他不動。
3. `.github/workflows/selfhost_collect.yml`：
   - 「下載上一版」與「上傳 Release」兩個 `for f in ...` 清單都加 `shares.parquet`；當週快照那行 `for f in raw_prices inst margin corp_actions` 加 `shares`。
   - 在「官方未還原日線」步驟（第 97–100 行）**後面**加一步，格式照抄它：
     ```yaml
           - name: 官方逐日發行股數（上市 MI_QFIIS＋上櫃 dailyQuotes）
             if: steps.guard.outputs.run == 'true'
             continue-on-error: true
             run: python scripts/selfhost_shares.py
     ```
   - 其他步驟不動。
4. 不新增其他檔。

## 實作重點（docstring 已寫，這裡只列容易錯的）
- MI_QFIIS 回應是**頂層** `fields`／`data`，不是 `tables`；代號欄要避開「國際證券編碼」（用「結尾是代號且不含 ISIN」判定）。
- dailyQuotes 2018 與 2026 欄位數不同，股數欄位置不同 → 只能用欄名「發行股數」定位。
- `main` 收集模式：日期清單來自 `trading_days(RAW_PRICES, ...)`，跳過「檔案裡該日已有任何 src=official 列」的日子；每 10 天 merge＋write 一次。
- `--import-tsd`：TSD 不得蓋掉任何現有列（只補缺的主鍵）。
- `write` 的檢查失敗要 raise，不能靜默修正。

## 不准做
- 不改測試檔、不改其他 selfhost 腳本、不改 tw-swing、不動 Release（不准 `gh release upload`）、不 push。
- 不用 FinMind 或任何新資料源；不改 `SRC_PRIORITY`、`VERIFY_MIN`、`REFRESH_DAYS`。
- 規格看起來有矛盾 → 停下寫進 from-codex.md「需要 Opus 決定的事」（格式：問題一句＋2–3 選項＋你的建議），不要自己改框架。欄名小差異這類意義明確的小疑問自行採用並在回報註明。

## PROOF_CMD（照跑、照貼最後幾行）
```
python -m pytest tests/test_selfhost_shares.py -q
python -m pytest -q -p no:cacheprovider
python scripts/selfhost_shares.py --verify-tsd D:/g/claude/databook/tw-stock-data-main-1107/tw-stock-data-main --dates 2015-01-05,2016-08-25,2018-03-15,2021-02-26,2024-06-03,2026-11-06
python scripts/selfhost_shares.py --import-tsd D:/g/claude/databook/tw-stock-data-main-1107/tw-stock-data-main
python scripts/selfhost_shares.py --start 2026-09-01 --end 2026-10-05
```
預期：
1. `29 passed`。
2. `1424 passed, 4 skipped`、0 failed（基準 1395＋新 29）。
3. 6 天 × 2 市場共 12 列，每列 `ratio` ≥ 0.999（Opus 已手算 2018-03-15、2026-11-06 兩天兩市場都是 1.0）；2026-11-06 的 `n_official` 約 TW 1,101、TWO 892。exit 0。
4. 印出新增列數（數百萬列，2015-01-05～2026-11-06）；之後 `data/selfhost/shares.parquet` 2026-11-06 當天 TW ≥ 1,090 檔、TWO ≥ 880 檔，src 全是 `tw-stock-data`。
5. 抓 2026-09-01～10-05 的交易日（本機 raw_prices 只到 10-05），**overridden 應為 0**（TSD 與官方同源）；不是 0 就貼前 10 筆差異（ticker、date、兩個值），不要改程式去壓。exit 0。

若沙箱讀不到 TSD 目錄或不能連網，第 3～5 條跳過，在回報寫明「哪條、錯誤原文」，Opus 會自己跑。

## 回報格式（寫進 collab/from-codex.md，不貼程式碼）
- 完成項（對應「要改的檔案」1～3）
- commit hash（在 main commit，不 push；訊息「D04：官方逐日發行股數收集＋TSD 歷史匯入」）
- PROOF_CMD 五條的最後幾行輸出（第 3 條貼整張 12 列表）
- 自行採用的小疑問（沒有就寫「無」）
- 需要 Opus 決定的事（沒有就寫「無」）
