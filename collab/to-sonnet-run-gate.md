# 【tw-hold】任務書：自動班開跑前先檢查資料新鮮度（run gate）＋國際總經漏抓沿用上一版

- 版本：2026-11-18 v1（Opus 寫）
- 專案路徑：`D:/g/claude/tw-hold`（直接在 main 工作，不開 worktree）
- 背景：Cloudflare Worker 準時 dispatch 各 workflow；GitHub 原 cron 留當備援（延遲 5–9 小時）。目前每一班都不管資料是否已抓好就整條重跑。國際總經每班整批重抓 19 檔並覆蓋 Release，Yahoo 偶爾整檔漏一檔（11/18 07:13 漏 ^TNX），把前一班的好資料蓋掉、該卡片從頁面消失。

## 要讀的檔案（只准讀這些）
- `scripts/fetch_global_macro.py`（全檔 303 行）
- `tests/test_fetch_global_macro.py`（看 monkeypatch 寫法）
- `.github/workflows/global_macro.yml`、`chip_flow_evening.yml`、`openapi_daily.yml`、`revenue_watch.yml`、`heartbeat.yml`
- `scripts/refdata_sync.py`（只看 CLI 用法，1–40 行）
- `tests/test_workflow_schedules.py`（只看它檢查什麼，不准讓它失敗）

## 禁止
- 不准改上面清單以外的既有檔案（新增檔案只限本書列出的）；不准動 `cloudflare/`（Opus 自己改與部署）、`app/`。
- 不准改 cron 時間、concurrency 群組。
- 不准 `git stash`／`reset`／`checkout`；只 `git add` 自己改的檔（工作目錄有別人的未追蹤檔，別碰）。不准 push。
- 暫存檔只放 `D:/g/claude/tw-hold/` 底下，結束前刪掉。
- 小疑問（欄名不同但意義明確）自行採用並在回報註明；會改變下面框架行為的才停下回報，最多停 2 次。

---

## 第 1 部分：國際總經漏抓沿用上一版（`scripts/fetch_global_macro.py`）

在 `main()` 裡 `df = fetch()` 之後、`_check_staleness` 之前加：

1. `missing = sorted(set(ALL_SYMBOLS) - set(df["symbol"]))`。有缺就印 `整檔沒抓到，單檔重抓：[...]`，呼叫既有 `_retry_stale(df, missing)`（單檔 10 天）。
2. 新函式 `_carry_forward(df: pd.DataFrame, old: pd.DataFrame | None, symbols: list[str]) -> tuple[pd.DataFrame, list[str]]`：
   - `old` 是執行前的 `OUT`（workflow 已先 `refdata pull` 還原上一版；檔不存在／讀失敗 → `None`）。**要在寫入 OUT 之前讀**。
   - 對 `symbols`（第 1 步的 missing）中每一檔：把 `old` 裡該檔的列併進 `df`，`drop_duplicates(["symbol","date"], keep="last")`，**新抓的列優先**（new 排在後面）。
   - 回傳的清單 `carried`＝第 1 步重抓後**仍完全沒有新列**、只靠舊資料補回的 symbol（重抓有拿到 10 天的不算 carried，但歷史一樣要從 old 補齊）。
   - old 也沒有的 symbol：維持缺，不報錯。
3. 之後照舊跑 `_check_staleness`（沿用的舊資料若落後超過門檻，自然會進 `stale`、卡片標 ⚠️）。
4. meta 加鍵 `"carried_forward": carried`（list[str]，沒有就 `[]`）；有沿用就印 `::warning::沿用上一版：[...]`。

測試（加在 `tests/test_fetch_global_macro.py`，monkeypatch `yf.download`，不打網路）：
- `test_carry_forward_整檔漏抓重抓也空_沿用舊資料`：新 df 沒 ^TNX、old 有 ^TNX 100 列 → 結果含那 100 列，carried == ["^TNX"]
- `test_carry_forward_重抓有10天_併舊歷史不算沿用`：old 有 ^TNX 100 列、df 只有重抓的最近 10 天（其中 2 天與 old 重疊、值不同）→ 重疊日取新值、總列數 108，carried == []
- `test_carry_forward_沒有舊檔_維持缺`：old=None → df 不含 ^TNX，carried == []

## 第 2 部分：run gate（新檔）

### 2a. 判斷本體 `reference/run_gate.py`（純函式，不做 IO）

```python
from datetime import date, datetime

WORKFLOWS = ("global_macro", "chip_flow_evening", "openapi_daily", "revenue_watch", "heartbeat")
BACKUP_WINDOW_HOURS = {"openapi_daily": 8, "revenue_watch": 8, "heartbeat": 2}
HEARTBEAT_LAST_HOUR = 9          # 台北 09:00 後的 heartbeat 備援班直接跳過（開盤前檢查已無意義）
CHIP_READY_HOUR = 15             # 台北 15:00 後才期待「今天」的籌碼

def expected_us_date(now_utc: datetime) -> date:
    """台北今天之前最近的一個平日（週一～五）。美股假日不處理（→ 判不新鮮 → 照跑，退回現況）。"""

def expected_chip_date(now_utc: datetime) -> date:
    """台北時間 ≥15:00 且今天是平日 → 台北今天；否則 → 台北今天之前最近的平日。"""

def macro_fresh(meta: dict | None, symbols: set[str] | None, tx_meta: dict | None,
                all_symbols: set[str], now_utc: datetime) -> tuple[bool, str]:
    """全部成立才 True：meta 非 None；meta["reference_date"] >= expected_us_date；meta.get("stale") 為空；
    meta.get("carried_forward", []) 為空；symbols 包含 all_symbols 全部；tx_meta 非 None、
    tx_meta.get("missing_night") 不是 True、tx_meta["date"] >= 台北今天。
    第二個回傳值＝中文理由（不新鮮時寫是哪一條沒過）。meta 的 estimated 不列入判斷。"""

def chip_fresh(dates: dict[str, date | None], now_utc: datetime) -> tuple[bool, str]:
    """dates = {"foreign_futures": 最大日期, "inst_flow": 最大日期}；兩個都 >= expected_chip_date 才 True。"""

def decide(workflow: str, event: str, source: str | None, now_utc: datetime, *,
           fresh: tuple[bool, str] | None = None,
           last_dispatch_success_utc: datetime | None = None) -> tuple[bool, str]:
    """回傳 (要不要跑, 中文理由)。規則依序：
    1. event == "workflow_dispatch" 且 source != "alarm"（手動、Streamlit 按鈕，source 預設 "manual"）→ 跑
    2. workflow 是 global_macro／chip_flow_evening（event 是 schedule 或 alarm dispatch）：
       fresh 是 (True, _) → 不跑；否則 → 跑
    3. event == "workflow_dispatch" 且 source == "alarm"，其他三條 → 跑（各班有各自用途：官方分時段公布、月營收陸續申報）
    4. event == "schedule"（GitHub 備援）：
       - heartbeat 且台北時間 >= HEARTBEAT_LAST_HOUR → 不跑
       - last_dispatch_success_utc 不是 None 且 now - 它 <= BACKUP_WINDOW_HOURS[workflow] 小時 → 不跑（Cloudflare 有在跑）
       - 否則 → 跑
    5. 其他未知 event → 跑
    workflow 不在 WORKFLOWS → raise ValueError。"""
```

### 2b. CLI `scripts/run_gate.py --workflow <名稱>`

- 讀環境變數 `GITHUB_EVENT_NAME`、`GATE_SOURCE`（workflow 傳 `inputs.source`，schedule 時是空字串）。
- 依需要做 IO 再呼叫 `decide`：
  - global_macro：讀 `data/reference/global_macro_meta.json`、`global_macro.parquet`（symbol 集合）、`tx_futures_meta.json` → `macro_fresh`；`all_symbols` 用 `from scripts.fetch_global_macro import ALL_SYMBOLS`（若 import yfinance 有問題就改成在 gate job 也裝 yfinance，回報註明）。
  - chip_flow_evening：讀 `data/reference/foreign_futures.parquet`、`inst_flow.parquet` 的 `date` 欄最大值 → `chip_fresh`。
  - 其他三條且 event == schedule：`gh run list --workflow <檔名>.yml --event workflow_dispatch --status success --limit 1 --json createdAt`（`GH_TOKEN=${{ github.token }}`）取 createdAt。
- **任何例外 → 跑（fail-open）**，理由寫「gate 出錯，照跑：<例外訊息>」。gate 只能讓班「少跑」，不能害它「不跑」。
- 輸出：`run=true|false` 寫入 `$GITHUB_OUTPUT`；理由印到 stdout 並附加到 `$GITHUB_STEP_SUMMARY`（例：「⏭ 跳過：國際總經已是 2026-11-17 收盤、19 檔齊、夜盤到齊」）。

### 2c. 五條 workflow 改法（只加不刪）

- `on.workflow_dispatch` 加 `inputs: source: {type: string, default: "manual", required: false}`（**五條都要加**，Cloudflare 之後會帶 `source=alarm`，沒宣告會被 GitHub 拒）。
- 新增第一個 job `gate`：`runs-on: ubuntu-latest`、`permissions: {contents: read, actions: read}`、`outputs: run: ${{ steps.g.outputs.run }}`；步驟：checkout → setup-python 3.12 → 安裝最少套件 → （僅 global_macro、chip_flow_evening）`python scripts/refdata_sync.py pull --only ref`（**不帶 --strict**，失敗就讓 gate fail-open）→ `python scripts/run_gate.py --workflow <名稱>`（env：`GATE_SOURCE: ${{ inputs.source }}`、`GH_TOKEN: ${{ github.token }}`、refdata 用的 `DATA_REPO_PAT`／`DATA_REPO` 照原 workflow 寫法）。
- 原本的主 job 加 `needs: gate` 與 `if: needs.gate.outputs.run == 'true'`。原本已有 `if:` 的要用 `&&` 合併。
- global_macro 的 `notify-failure`（`needs: fetch`、`if: failure()`）：確認 fetch 被 skip 時**不會**發失敗通知（skipped 不算 failure；若需要改成 `needs.fetch.result == 'failure'` 就改，回報註明）。gate job 本身失敗時照樣要通知（把 gate 也列進 needs）。
- workflow 若有 job 層 `permissions` 衝突，以「主 job 權限不變、gate 只給 read」為準。

### 2d. 測試 `tests/test_run_gate.py`（全部用固定 `now_utc`，不打網路）

時間點：`T_WED_0517 = 2026-11-17 21:17 UTC`（台北 11/18 週三 05:17）；`T_WED_1630 = 2026-11-18 08:30 UTC`（台北週三 16:30）；`T_WED_1300 = 2026-11-18 05:00 UTC`（台北 13:00）。

| 測試名 | 預期 |
|---|---|
| `test_expected_us_date_週三早上是週二` | T_WED_0517 → 2026-11-17 |
| `test_expected_us_date_週一早上是上週五` | 台北 2026-11-16 05:17 → 2026-11-13 |
| `test_expected_chip_date_15點後是今天` | T_WED_1630 → 2026-11-18 |
| `test_expected_chip_date_15點前是前一平日` | T_WED_1300 → 2026-11-17 |
| `test_macro_fresh_全齊` | ref 2026-11-17、stale []、carried []、19 檔、tx date 2026-11-18 missing_night False → True |
| `test_macro_fresh_少一檔不新鮮` | symbols 缺 ^TNX → False，理由含 "^TNX" |
| `test_macro_fresh_stale非空不新鮮` | → False |
| `test_macro_fresh_有沿用不新鮮` | carried_forward ["^TNX"] → False |
| `test_macro_fresh_日期舊不新鮮` | ref 2026-11-14 → False |
| `test_macro_fresh_夜盤缺不新鮮` | missing_night True → False |
| `test_macro_fresh_meta不存在` | meta None → False |
| `test_chip_fresh_兩檔都到` / `test_chip_fresh_一檔落後` | True / False |
| `test_decide_手動一律跑` | workflow_dispatch + source "manual"（及 None）→ 五條全 True |
| `test_decide_alarm_總經新鮮跳過` | global_macro, workflow_dispatch, "alarm", fresh (True,..) → False |
| `test_decide_alarm_總經不新鮮跑` | fresh (False,..) → True |
| `test_decide_alarm_openapi月營收heartbeat照跑` | → True |
| `test_decide_備援_總經新鮮跳過` | schedule + fresh True → False |
| `test_decide_備援_openapi近8小時有成功跳過` | last success = now − 3h → False |
| `test_decide_備援_openapi超過8小時跑` | now − 9h → True |
| `test_decide_備援_沒有成功紀錄跑` | None → True |
| `test_decide_備援_heartbeat九點後跳過` | 台北 16:16 → False |
| `test_decide_備援_heartbeat開盤前看2小時` | 台北 08:40、last success 08:23 → False；last success 昨天 → True |
| `test_decide_未知workflow報錯` | ValueError |
| `test_cli_出錯一律跑` | 用 subprocess 或直接呼叫 CLI 的 main，讓讀檔丟例外 → 輸出 run=true |
| `test_五條workflow都有gate與source輸入` | 用 yaml 讀五個檔：`workflow_dispatch.inputs.source` 存在、有 `gate` job、主 job `needs` 含 gate 且 `if` 含 `needs.gate.outputs.run == 'true'` |

---

## PROOF_CMD（Opus 會自己重跑，以這個為準）

```
cd D:/g/claude/tw-hold && PYTHONIOENCODING=utf-8 python -m pytest tests/test_run_gate.py tests/test_fetch_global_macro.py tests/test_workflow_schedules.py -q
```
預期：全部 passed，新增 ≥ 27 個測試、0 failed。再跑全套：
```
cd D:/g/claude/tw-hold && PYTHONIOENCODING=utf-8 python -m pytest -q
```
預期：0 failed（11/17 基準 1476 passed，加新測試後只會多）。

## Commit
- 一個 commit 或分「第 1 部分」「第 2 部分」兩個都可；訊息中文，結尾加
  `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`
- commit 前確認 `git config user.email` 是 `300864627+tongxiaooppo-boop@users.noreply.github.com`，不是就停下回報。不准 push。

## 回報格式（寫到 `collab/from-sonnet-run-gate.md`，不貼程式碼）
- 完成項（第 1／2a／2b／2c／2d 各一行）
- commit hash 清單
- PROOF_CMD 兩條的輸出最後一行
- 自行採用的小決定（每條一行）
- 需要 Opus 決定的事（沒有就寫「無」）
