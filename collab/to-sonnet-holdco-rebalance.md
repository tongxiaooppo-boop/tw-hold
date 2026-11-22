【tw-hold】換股日挪到金控期限＋1 天 — 任務書 v1（2026-11-22）

工作目錄：`D:\g\claude\tw-hold`（直接在主目錄做；禁 stash／reset／checkout；只 add 自己改的檔）。
暫存檔只准放在這個 repo 內並在結束前刪掉。不准改介面（函式簽名、常數值、測試預期值）；覺得有問題就停下回報。

## 背景（已拍板，不用討論）
季報換股日從 5/15、8/14、11/14 改成 6/1、9/1、12/1（金控法定期限＋1 天），3/31 不變；2026-12-01 起生效。
換股日後金控新季財報沒到齊就先不換，最多等 14 天，滿了照換並標出還是舊季的金控。框架與規則全寫在 `build_lists.py` 的 docstring。

## 要讀的檔案（只准讀這些）
- `build_lists.py` 第 1–150 行、第 290–330 行（`_build`）、第 330–445 行（`main`）
- `tests/test_rebalance_holdco.py`（全檔，預期值不准改）
- `build_factors.py` 第 311–330 行、第 395–419 行（`screen_all` 開頭與回傳 context）
- `build_classification.py` 第 185–200 行
- `app/streamlit_app.py` 第 170–185 行、第 1460–1480 行
- `tests/test_lists.py` 第 137–156 行

## 要做的事
1. **`build_lists.py`**：實作 `current_rebalance`、`target_quarter_end`、`holdco_missing`、`rebalance_status`（照 docstring，不改簽名）。檔頭 docstring 第 7 行「3/31、5/15、8/14、11/14」改「3/31、6/1、9/1、12/1（2026-12-01 起；之前 5/15、8/14、11/14）」。
2. **`build_factors.screen_all`**：context 加 `"holdco_latest"`：`{代號: ISO 日期或 None}`，只含 `build_lists.HOLDCO` 13 檔；值＝該檔在 `q`（`load_quarterly(live=True)` 的結果）中「`eps` 或 `net_income` 有限值」的最大 `period_end`。q 欄名不是這兩個就停下回報。避免循環 import：HOLDCO 用函式內 `from build_lists import HOLDCO`，或把 HOLDCO 搬到不 import build_lists 的地方——**不行就停下回報**，不要自己重構。
3. **`build_lists.main`／`_build`**：用 `rebalance_status(asof, None→讀檔, ctx.get("holdco_latest"))` 取代 `effective_rebalance(asof)`；`_build` 加參數接收 status（新參數放最後、給預設值，避免改壞既有呼叫）。value、deposit 兩份 `_meta` 加 `"holdco_waiting"`、`"holdco_stale"`（清單，空的也寫）。結尾 print：等待中印「金控新季未到齊（代號…），換股延後，最晚 YYYY-MM-DD」；stale 印「已滿 14 天照換，沿用舊季：代號…」。
4. **`build_classification.py`**：`REBALANCE_FOR_QUARTER` 改 `{3: (6, 1, 0), 6: (9, 1, 0), 9: (12, 1, 0), 12: (3, 31, 1)}`，第 190 行註解同步。
5. **`app/streamlit_app.py`**：177、180 行的「3/31、5/15、8/14、11/14」改「3/31、6/1、9/1、12/1」。1470 行附近顯示本期換股日處：`meta.get("holdco_waiting")` 非空 → 後面加「（金控 N 家新季財報未到，換股延後）」；`meta.get("holdco_stale")` 非空 → 加「（金控 代號… 沿用舊一季財報）」。一律 `.get()`。

## 不准做
- 不改 `REBALANCE_MD`／`HOLDCO`／`HOLDCO_WAIT_DAYS`／`SCHEDULE_SWITCH` 的值，不改 `tests/test_rebalance_holdco.py`。
- 不改 `reference/loader.py`、`screener/eps_windows.py`（那裡寫的是一般股法定期限，不是換股日）。
- 不跑 build、不 push、不動 data/。

## PROOF_CMD
```
cd D:\g\claude\tw-hold && PYTHONIOENCODING=utf-8 python -m pytest tests/test_rebalance_holdco.py tests/test_lists.py tests/test_build_classification.py -q
```
預期：全部 passed（test_rebalance_holdco 27 條）。之後再跑全套 `python -m pytest -q`，passed 數不能比改之前少、0 failed（改之前先跑一次記下數字）。

## 完成後
commit（訊息中文，結尾加 `Co-Authored-By: Claude Sonnet <noreply@anthropic.com>`），寫回報 `collab/from-sonnet-holdco-rebalance.md`：
- commit hash
- PROOF_CMD 輸出最後一行、全套前後 passed／failed 數
- 第 2 點 HOLDCO import 怎麼處理的（一句）
- 需要決定的事（沒有寫無）
不貼程式碼。
