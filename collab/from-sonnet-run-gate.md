# 回報：run gate＋國際總經沿用上一版（2026-11-18）

## 完成項
- 第 1 部分：scripts/fetch_global_macro.py 加 _carry_forward／_read_old，main 先讀舊 OUT、整檔漏抓先單檔重抓再沿用，meta 加 carried_forward，沿用時印 ::warning::；3 個測試。
- 2a：reference/run_gate.py（expected_us_date／expected_chip_date／macro_fresh／chip_fresh／decide），照框架。
- 2b：scripts/run_gate.py CLI（fail-open、寫 GITHUB_OUTPUT／STEP_SUMMARY）。
- 2c：五條 workflow 加 source input、gate job、主 job needs＋if；global_macro notify-failure 改 needs [gate, fetch]、if 為 gate 或 fetch result == failure。
- 2d：tests/test_run_gate.py（31 個測試含 parametrize）。

## commit
見 git log（單一 commit）。

## PROOF_CMD 最後一行
- 第一條：46 passed in 1.51s
- 全套：1506 passed, 4 skipped in 202.53s

## 自行採用的小決定
- macro_fresh 的 tx_meta["date"] 與 meta["reference_date"] 以字串前 10 碼轉 date 比較（沒讀 tx_futures_meta 實檔，依任務書欄名）。
- global_macro gate 另外安裝 yfinance（CLI import ALL_SYMBOLS）；另三條 gate 不裝套件（reference/run_gate 無第三方依賴）。
- gate 的 refdata pull 步驟加 continue-on-error，確保失敗仍走 fail-open。
- 單檔重抓的結果不納入 carried（有拿到新列就不算沿用），歷史照從 old 補齊。
- test_五條workflow 用 PyYAML，且排除 notify-failure job。
- 工作目錄有別人改的 cloudflare/*，未碰、未 add。

## 需要 Opus 決定的事
無
