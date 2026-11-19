# 【tw-hold】任務書：金融股估值卡「已公布季」只看 EPS（銀行／保險／金控營收空）

- 版本：2026-11-19 v1（Opus 寫）
- 專案路徑：`D:/g/claude/tw-hold`（直接在 main 工作，不開 worktree）
- 背景（Opus 已用真實資料確認）：季財報 `revenue` 對銀行整欄 NaN（2801、2812、2834…15 檔）、保險 2026Q1 起 NaN（IFRS 17）、2886 的 2026Q3（XBRL）NaN。估值卡把「已公布季」定義成 eps 與 revenue 都有值 → 2812／2834 的已公布 4 季是空的，2816 停在 2025Q4，2886 停在 2026Q2。金融股合理價走 PB、不受影響，壞的是 EPS 區塊（reported／ttm／fwd、成長表、業外表）。

## 要讀的檔案（只准讀這些）
- `screener/eps_windows.py`（全檔 368 行）
- `screener/val_card.py` 1–130 行（模組說明）、195–300 行
- `tests/test_val2_eps_windows.py`（看 `make_q`／`make_monthly`／`qs` 寫法）
- `scripts/val2_dryrun_cards.py` 1–55 行（只為了 import `LocalBundle`）
- `app/val_inputs.py` 71–100 行（`card_inputs`）

## 禁止
- 只准改：`screener/eps_windows.py`、`screener/val_card.py`、`tests/test_val2_eps_windows.py`；只准新增：`tests/test_val_card_financial.py`、`scripts/check_fin_eps_cards.py`。其他檔一律不動（`river.py`、`detect.py`、`app/` 都不准改）。
- 不准改 `CARD_VERSION`、不准改任何既有測試的預期值。
- 不准 `git stash`／`reset`／`checkout`；只 `git add` 自己的檔（工作目錄有很多別人的未追蹤檔，別碰）。不准 push。
- 暫存檔（基準 JSON 等）只放 `D:/g/claude/tw-hold/_tmp_fin/`，結束前整個刪掉。
- 小疑問自行採用並在回報註明；會改變下面框架行為的才停下回報，最多停 2 次。

---

## 第 0 步（先做，改程式之前）：真實資料檢查腳本 `scripts/check_fin_eps_cards.py`

```
python scripts/check_fin_eps_cards.py dump --out <json> [--tickers 2812,2834]
python scripts/check_fin_eps_cards.py compare <base.json> <new.json>
```
- dump：`ASOF = pd.Timestamp("2026-11-19")`；母體＝`data/derived/stock_class.json` 的 `stocks`（cls 傳該筆）；`bundle = LocalBundle()`（從 `scripts.val2_dryrun_cards` import）；`kw = val_inputs.card_inputs(code, ASOF, cls, ROOT/"data/derived", bundle)`，有 `"missing"` 或例外 → 記 `{"error": 字串}`；否則 `card = val_card.build_card(**kw)`。每檔存：
  `tier, route, reason, prices, roe, eps`（eps 下 reported／ttm／fwd 各存 `ok, status, eps, [q 清單]`，None 照存）`, growth, nonop_hist, nonop_median`。`json.dump(..., default=str, ensure_ascii=False, sort_keys=True)`。
- compare：金融判定＝cls 的 `industry_group == "financial"` 或 `type == "financial"`。印：
  1. `非金融變動 N 檔`（逐欄完全相等比較；N>0 時列前 20 檔代號＋哪些欄不同）
  2. `金融 tier/route/prices 變動 N 檔`（同上）
  3. `金融 EPS 變動 N 檔`，逐檔一行：`代號 reported 舊最後季→新最後季 舊eps→新eps`
- 做完先在**未改程式**的狀態下跑 `dump --out _tmp_fin/base.json`（存基準），再進第 1 步。

## 第 1 步：`screener/eps_windows.py`

1. `_actuals(q, asof, live, financial: bool = False)`：financial=True 時條件只剩 `_finite(eps)`（可見性判斷照舊）；False 時完全照舊（eps 與 revenue 都有限）。
2. `reported_window(q, asof, live=False, financial: bool = False)` 把 financial 傳給 `_actuals`。
3. `ttm_window`、`fwd_window` 內呼叫 `_actuals` 處都傳 `financial`；`windows()` 呼叫 `reported_window` 時傳 `financial`。
4. 其他邏輯（financial 早退、前瞻試算）一行都不動。模組說明「可見性」段加一句：金融股（financial=True）已公布季只看 eps。

## 第 2 步：`screener/val_card.py`

1. `nonop_rows(q, financial: bool = False)`：203 行篩選改成 financial 時只看 `eps.notna()`。
2. `build_card` 在建 `result` 之前算 `financial`（cls 為 None → False；否則同 260 行公式），240 行 `actual` 篩選同上規則，249 行 `nonop_rows(q, financial)`。260 行改成沿用這個變數（不要算兩次）。
3. 其餘不動。

## 第 3 步：測試

`tests/test_val2_eps_windows.py` 新增（用既有 `make_q`；「營收全空」＝每季 `{"revenue": float("nan")}`）：

| 測試名 | 預期 |
|---|---|
| `test_金融營收全空_reported有4季` | make_q("2026Q3") 營收全 NaN，`reported_window(q, asof=2026-11-19, live=True, financial=True)` → ok、`qs` 最後季 "2026Q3"、4 季、eps≈3.84 |
| `test_非金融營收全空_維持no_data` | 同資料 financial=False → status "no_data"（現行行為） |
| `test_金融營收全空_ttm等於reported` | `ttm_window(..., financial=True)` 的 quarters == reported 的 quarters、n_est == 0 |
| `test_金融營收全空_fwd不試算` | `fwd_window(..., financial=True)` 不含任何非 actual 季 |
| `test_保險近3季營收空` | make_q("2026Q3") 但 2026Q1–Q3 營收 NaN：financial=True 最後季 "2026Q3"；financial=False 最後季 "2025Q4" |

新檔 `tests/test_val_card_financial.py`：

| 測試名 | 預期 |
|---|---|
| `test_nonop_rows_金融營收空有資料` | 營收全 NaN 12 季，`nonop_rows(q, financial=True)` 長度 == `ew.NONOP_QUARTERS` |
| `test_nonop_rows_非金融營收空為空` | 同資料 financial=False → `[]` |

## PROOF_CMD（Opus 會自己重跑，以這個為準）

```
cd D:/g/claude/tw-hold && PYTHONIOENCODING=utf-8 python -m pytest tests/test_val2_eps_windows.py tests/test_val_card_financial.py -q
cd D:/g/claude/tw-hold && PYTHONIOENCODING=utf-8 python scripts/check_fin_eps_cards.py dump --out _tmp_fin/new.json && PYTHONIOENCODING=utf-8 python scripts/check_fin_eps_cards.py compare _tmp_fin/base.json _tmp_fin/new.json
cd D:/g/claude/tw-hold && PYTHONIOENCODING=utf-8 python -m pytest -q
```
預期：
- 第一條全過、新增 7 個測試。
- compare：`非金融變動 0 檔`、`金融 tier/route/prices 變動 0 檔`；`金融 EPS 變動` 至少包含 2812、2834（空→最後季 2026Q3）、2816（2025Q4→2026Q3）、2886（2026Q2→2026Q3）；2880 不在變動清單（它還沒有 Q3 資料）。
- 全套 0 failed（基準 1506 passed、4 skipped，只會多）。

## Commit
- 兩個 commit：①「金融股估值卡檢查腳本」（第 0 步）②「金融股已公布季只看 EPS」（第 1–3 步）；訊息中文，結尾加
  `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`
- commit 前確認 `git config user.email` 是 `300864627+tongxiaooppo-boop@users.noreply.github.com`，不是就停下回報。不准 push。

## 回報格式（寫到 `collab/from-sonnet-fin-eps.md`，不貼程式碼）
- 完成項（第 0／1／2／3 步各一行）
- commit hash 清單
- PROOF_CMD 三條的輸出最後幾行（compare 那條貼完整三段統計＋金融 EPS 變動清單）
- 自行採用的小決定（每條一行）
- 需要 Opus 決定的事（沒有就寫「無」）
