# 【tw-hold】股本扣預收股本 r2：有預收股本那季改用掛牌股數（版本 2026-11-22 r2）

> 專案 tw-hold（`D:\g\claude\tw-hold`，main）。r1 已 commit `94594f6`（未 push），本輪在它上面加一個 commit。
> 禁止：stash／reset／checkout／push／改本文件沒列的檔。只 `git add` 自己改的檔。UTF-8 無 BOM，不用 PowerShell 寫檔，python 加 `PYTHONIOENCODING=utf-8`。暫存檔放 `D:\g\claude\` 底下、結束前刪。不上網。
> 介面照本文件不准改；有問題停下回報（最多 2 次），小疑問自行採用寫進回報。

## 為什麼改（使用者 2026-11-22 拍板）

有預收股本那季：錢已進權益、新股還沒發。r1「股數扣預收」讓每股淨值偏高 7～13%；舊「股本÷10」偏低。實測交易所掛牌股數（universe `listed_shares`）在新股掛牌後最接近實際（6533：舊 60.09／r1 89.61／掛牌 79.00）。
定案：
- 有預收股本（`advance_capital > 0`）那季：**live 且新股已掛牌**（掛牌股數 > 淨股本股數 × 1.005）→ 用掛牌股數；其餘（還沒掛牌、或非 live 歷史）→ 舊口徑 `capital_stock`（保守）。
- 沒預收股本 → `capital_net`（＝capital_stock，但近零錯值已是 NaN；NaN 不退回）。
- 「股數對不上」檢查（detect.py）維持 r1 的淨股本，不改。

## 要讀的檔案（只准讀這些）

`reference/share_basis.py` 第 60–140 行、`app/bundle_data.py` 第 205–225 行、`app/val_inputs.py` 第 140–165 行、`screener/screen.py` 第 60–75 行與 `_cap_basis`、`build_factors.py` 第 295–310 行、`tests/test_val2_share_basis.py`、`tests/test_screen_capital_net.py`

## 要改

1. `reference/share_basis.py` 新增（放 `common_shares` 前）：
   ```python
   LISTED_TOL = 0.005   # 掛牌股數 > 淨股本股數 × (1+此值) 才算新股已掛牌

   def capital_for_shares(row) -> float | None:
       """股數用的股本。advance_capital > 0 → capital_stock（舊口徑，預收按面額當股數，保守）；
       否則 row.get('capital_net', row.get('capital_stock'))。capital_net 是 NaN 時回 NaN、不退回。"""
   ```
   - `exchange_outstanding_ratio` 內 `cap = ...`（r1 改過那行）改成 `cap = capital_for_shares(row)`。
   - `common_shares`：`base = shares_today_basis(ticker, capital_for_shares(latest), ...)`（其餘參數不變）。接著：若 `live` 且 `latest` 的 `advance_capital > 0`，且 `basic.get('listed_shares')` 為有限正數，且 `listed > net_shares × (1 + LISTED_TOL)`（`net_shares = shares_today_basis(ticker, latest.get('capital_net'), ...)`，它是 None 就不比）→ `return float(listed), 'listed'`（不套庫藏比率）。docstring 補一句說明。
2. `app/bundle_data.py` `company_basic`、`app/val_inputs.py` 的 `company_basic`：回傳 dict 加 `listed_shares`，來源 universe.parquet 同代號的 `listed_shares`（bundle_data 用既有 `_read("universe.parquet", code, False)`；val_inputs 照該檔既有讀 universe 的方式，沒有就用同樣的讀法讀 bundle 的 universe）。缺檔／缺欄／無該檔 → `float("nan")`，不准讓 company_basic 因此回 None。
3. `screener/screen.py` `_cap_basis`、`build_factors.py` 退化估市值：改成「`advance_capital > 0` 的列用 `capital_stock`，其餘用 `capital_net`（無此欄退 capital_stock）」，逐列向量化，NaN 不退回。
4. 測試（新增，名稱照抄）：
   - `tests/test_val2_share_basis.py::test_capital_for_shares_rules`：adv>0 → capital_stock；adv NaN → capital_net；capital_net NaN → NaN。
   - `::test_common_shares_listed_when_advance_and_listed`：adv>0、live、listed 比淨股本股數多 10% → 回 (listed, 'listed')。
   - `::test_common_shares_advance_not_listed_uses_gross`：adv>0、live、listed ≈ 淨股本股數 → 用 capital_stock 股數，src 不是 'listed'。
   - `::test_common_shares_advance_history_uses_gross`：adv>0、live=False、有 listed → 用 capital_stock 股數。
   - 改 r1 的 `test_common_shares_uses_capital_net`／`test_market_cap_fallback_uses_capital_net` 若跟新規則衝突，只改預期值並在回報說明。
   - `tests/test_screen_capital_net.py::test_cap_basis_gross_when_advance`。

## PROOF_CMD

```
cd /d/g/claude/tw-hold && PYTHONIOENCODING=utf-8 python -m pytest -q -p no:cacheprovider 2>&1 | tail -2
```
預期：0 failed（約 1608 passed）。

## 回報（寫 `collab/from-sonnet-advance-capital-r2.md`，欄位照抄，不貼程式碼）
- 完成項：
- commit：
- 測試數字：
- 改了預期值的舊測試（哪條、為什麼）：
- 自行採用的小疑問：
- 需要決定的事：
