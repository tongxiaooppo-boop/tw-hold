# 【tw-hold】Cloudflare 鬧鐘任務書：準時觸發 GitHub workflow＋期交所夜盤查詢日修正（版本 2026-11-14 v1）

> **專案：tw-hold（`D:\g\claude\tw-hold`，main 分支）。不是 tw-swing。** 下面相對路徑都以 `D:\g\claude\tw-hold` 為根；指令都先 `cd D:\g\claude\tw-hold` 再跑。回報寫到 `D:\g\claude\tw-hold\collab\from-codex.md`（覆蓋舊檔）。
> 檔案一律 **UTF-8 無 BOM**，不要用 PowerShell 寫檔。不要上網查資料、不要 `npm install`、不要部署、不要 `wrangler login`、不要設任何 secret。

## 背景（一段就好）
GitHub 的 `schedule` 在這兩個 repo 實測晚 5～9 小時，但 `workflow_dispatch` 不會延遲。做法：Cloudflare Worker 只當鬧鐘，到點呼叫 GitHub API dispatch 指定 workflow。GitHub 原本的 cron **一行都不改**（留作備援，workflow 都是冪等的）。

## 要讀的檔案（只准讀這些）
- `scripts/fetch_tx_futures.py`（全檔，約 200 行內）
- `tests/test_fetch_tx_futures.py`（全檔，照它的 monkeypatch 寫法）
- `scripts/fetch_foreign_futures.py` 第 85～110 行（只參考「結束日超過最新資料日會回錯誤頁」的註解與退讓寫法）

## 任務一：新增 `cloudflare/`（4 個檔，純 ES module，零相依）

### 1. `cloudflare/schedule.js`（介面寫死，不准改名稱與簽名）
```js
export const REPO = "tongxiaooppo-boop/tw-hold";
export const REF = "main";
// 時間一律台北時間 "HH:MM"；weekdays 用 JS getUTCDay 編號（0=週日…6=週六），null=不限；days＝每月幾號，null=不限
export const SCHEDULE = [
  { workflow: "global_macro.yml",      times: ["05:17", "06:17", "07:13"],          weekdays: [2,3,4,5,6], days: null },
  { workflow: "chip_flow_evening.yml", times: ["15:23", "16:43"],                   weekdays: [1,2,3,4,5], days: null },
  { workflow: "openapi_daily.yml",     times: ["16:07", "18:07", "20:07", "23:07"], weekdays: [1,2,3,4,5], days: null },
  { workflow: "openapi_daily.yml",     times: ["04:07"],                            weekdays: [2,3,4,5,6], days: null },
  { workflow: "heartbeat.yml",         times: ["08:23"],                            weekdays: [1,2,3,4,5], days: null },
  { workflow: "revenue_watch.yml",     times: ["18:47", "21:43", "23:23"],          weekdays: null, days: range(1, 17) },
  { workflow: "revenue_watch.yml",     times: ["07:47"],                            weekdays: null, days: range(2, 18) },
];
// range(a,b) 自己寫成小函式（含頭含尾），或直接列陣列，二選一

// 把 UTC 的 Date 轉成台北（固定 +8，台灣沒有夏令時間）：
export function taipeiParts(date) { /* 回 { hhmm: "HH:MM", weekday: 0-6, day: 1-31 }，用 date.getTime()+8h 後取 getUTC* */ }

// 該時刻（只看到分鐘）要 dispatch 的 workflow 檔名，依 SCHEDULE 順序、去重
export function dueWorkflows(date) { /* string[] */ }

// SCHEDULE 裡出現過的所有分鐘值，去重、由小到大（台北與 UTC 分鐘相同，因為時差是整小時）
export function cronMinutes() { /* number[] */ }
```

### 2. `cloudflare/worker.js`
```js
import { REPO, REF, dueWorkflows } from "./schedule.js";

export async function dispatch(workflow, token, fetchImpl = fetch) { /* 回 { workflow, status, ok } */ }

export default {
  async scheduled(event, env, ctx) { /* ... */ },
};
```
- `scheduled`：`const when = new Date(event.scheduledTime)`（用排定時間，不用 `Date.now()`）→ `dueWorkflows(when)`；空陣列就直接結束（不呼叫 fetch）。每個依序 `await dispatch(w, env.GH_TOKEN)`。
- `dispatch`：`POST https://api.github.com/repos/${REPO}/actions/workflows/${workflow}/dispatches`，headers：`Authorization: Bearer <token>`、`Accept: application/vnd.github+json`、`X-GitHub-Api-Version: 2022-11-28`、`User-Agent: tw-hold-alarm`、`Content-Type: application/json`；body `JSON.stringify({ ref: REF })`。成功＝status 204。失敗（非 204 或 throw）**重試 1 次**；兩次都失敗 `console.error` 印 workflow、status、回應前 200 字，不 throw（讓同一輪其他 workflow 照跑）。成功 `console.log`。
- **不寫 `fetch` handler**（不開放網址觸發）。token 只從 `env.GH_TOKEN` 讀，任何地方都不准印出 token。

### 3. `cloudflare/wrangler.toml`
```toml
name = "tw-hold-alarm"
main = "worker.js"
compatibility_date = "2026-11-01"

[triggers]
crons = ["7,13,17,23,43,47 * * * *"]
```

### 4. `cloudflare/schedule.test.mjs`（用 `node --test`，不准裝套件）
測試名稱與預期值照抄（UTC 時刻 → 預期回傳）：
| 測試名 | UTC 輸入 | 台北 | 預期 `dueWorkflows` |
|---|---|---|---|
| global_macro_週二0517 | 2026-11-16T21:17:00Z | 11/17(二) 05:17 | `["global_macro.yml"]` |
| global_macro_週一0517不跑 | 2026-11-15T21:17:00Z | 11/16(一) 05:17 | `[]` |
| openapi_週六0407 | 2026-11-13T20:07:00Z | 11/14(六) 04:07 | `["openapi_daily.yml"]` |
| openapi_週一0407不跑 | 2026-11-15T20:07:00Z | 11/16(一) 04:07 | `[]` |
| openapi_週一1607 | 2026-11-16T08:07:00Z | 11/16(一) 16:07 | `["openapi_daily.yml"]` |
| openapi_週六1607不跑 | 2026-11-14T08:07:00Z | 11/14(六) 16:07 | `[]` |
| heartbeat_週一0823 | 2026-11-16T00:23:00Z | 11/16(一) 08:23 | `["heartbeat.yml"]` |
| chip_週一1523 | 2026-11-16T07:23:00Z | 11/16(一) 15:23 | `["chip_flow_evening.yml"]` |
| revenue_17號1847 | 2026-11-17T10:47:00Z | 11/17 18:47 | `["revenue_watch.yml"]` |
| revenue_18號1847不跑 | 2026-11-18T10:47:00Z | 11/18 18:47 | `[]` |
| revenue_18號0747 | 2026-11-17T23:47:00Z | 11/18 07:47 | `["revenue_watch.yml"]` |
| revenue_19號0747不跑 | 2026-11-18T23:47:00Z | 11/19 07:47 | `[]` |
| revenue_1號0747不跑 | 2026-11-30T23:47:00Z | 12/1 07:47 | `[]` |
| 非表定分鐘 | 2026-11-16T08:13:00Z | 11/16(一) 16:13 | `[]` |
| 秒數不影響 | 2026-11-16T08:07:42Z | 11/16(一) 16:07:42 | `["openapi_daily.yml"]` |

另外三個測試：
- `cron分鐘與wrangler一致`：讀 `wrangler.toml`，取 `crons` 第一條的分鐘欄位，拆成數字排序後 **deepEqual** `cronMinutes()`；並確認只有 1 條 cron。
- `避開整點半點`：`cronMinutes()` 每個值都不在 57–59、0–3、27–33。
- `worker_命中時dispatch`：mock `globalThis.fetch` 回 `{status:204, text:async()=>""}`，呼叫 `worker.default.scheduled({scheduledTime: Date.parse("2026-11-16T08:07:00Z")}, {GH_TOKEN:"t"}, {})` → fetch 被呼叫 1 次，URL 結尾 `/actions/workflows/openapi_daily.yml/dispatches`、method POST、body `{"ref":"main"}`、Authorization `Bearer t`。
- `worker_不命中不呼叫`：同上但 `2026-11-16T08:13:00Z` → fetch 0 次。
- `dispatch_失敗重試一次`：fetch 第一次回 500、第二次 204 → 呼叫 2 次、回 `ok: true`。

### 5. `cloudflare/README.md`（中文，短）
內容只要：用途一段；時間表（直接說「見 schedule.js」）；部署步驟（`npx wrangler login` → `cd cloudflare` → `npx wrangler deploy` → `npx wrangler secret put GH_TOKEN`；或網頁版 Workers 貼上兩支 js 並在 Settings→Triggers 加 cron、Settings→Variables 加 secret）；改時間表要同步改 `wrangler.toml` 的分鐘（測試會擋）；查 log：`npx wrangler tail`；停用＝Dashboard 刪掉 cron trigger（GitHub cron 仍在當備援）。

## 任務二：`scripts/fetch_tx_futures.py` 夜盤查詢結束日
問題：`fetch_csv_records` 的 `queryEndDate` 只到台北今天，但期交所把週五夜盤記在**下一交易日**（11/14 實測：查到 11/14 沒有週五夜盤，查到 11/16 才出現 `2026/11/16 盤後`）。週末首頁因此缺週五夜盤。
修法（框架定死）：
- 結束日依序試 `today + 7天`、`today + 3天`、`today`（加常數 `END_AHEAD_DAYS = (7, 3, 0)`），每個結束日照現行「最多 2 次」下載＋`parse_csv`；**第一個 `parse_csv` 回非空就回傳**。三個都空或都失敗 → 印現有那行 `::warning::` 並回 `[]`（退回 OpenAPI 的行為不變）。
- 理由（寫成註解）：結束日超過最新資料日時，TAIFEX 有的端點會回錯誤頁（見 fetch_foreign_futures.py 註解），錯誤頁 `parse_csv` 會回 `[]`，所以往回退。
- 不改 `parse_csv`、`_to_record`、其他函式與常數。
- 新增測試（加在 `tests/test_fetch_tx_futures.py`，照現有 monkeypatch urlopen 寫法，從 request body 解析 `queryEndDate`）：
  - `test_csv結束日先試未來七天`：第一次請求的 queryEndDate＝今天＋7 天（用 monkeypatch 固定「今天」或在測試內用同一公式算）。
  - `test_未來日回錯誤頁退到今天`：+7、+3 回 HTML 錯誤頁（`<html>error</html>`）、今天回合法 CSV → 回非空，且共試到 today。
  - `test_三個結束日都空回空陣列`：全部回錯誤頁 → 回 `[]`。

## 不准做
- 不改 `.github/workflows/` 任何檔、不改任何 cron。
- 不改 `cloudflare/` 與 `scripts/fetch_tx_futures.py`、`tests/test_fetch_tx_futures.py` 以外的檔（`collab/from-codex.md` 除外）。
- 不建 `package.json`、`node_modules`；不部署。暫存檔放 `D:\g\claude\tw-hold` 內並在結束前刪掉。
- 介面（上面寫死的 export 名稱、簽名、SCHEDULE 內容、cron 字串）有問題就停下寫進回報，不要自己改。小疑問自行採用並在回報註明。

## PROOF_CMD（全部要過）
```
cd D:\g\claude\tw-hold
node --test cloudflare/
PYTHONIOENCODING=utf-8 python -m pytest tests/test_fetch_tx_futures.py -q
PYTHONIOENCODING=utf-8 python -m pytest -q
```
預期：`node --test` 顯示 20 個測試 pass、0 fail；`test_fetch_tx_futures.py` 全過（原有＋新 3 個）；全套 pytest 0 failed。

## 完成後
- 一個 commit：`feat: Cloudflare 鬧鐘準時 dispatch workflow＋夜盤查詢結束日往後`（用 repo 既有的 git 設定，不要改 user.email；**不要 push**）。
- 回報 `collab/from-codex.md` 欄位（不貼程式碼）：
  - 完成項（逐條對應任務一 1–5、任務二）
  - commit hash
  - PROOF_CMD 三行各自的實際輸出最後一行
  - 自行採用的小疑問
  - 需要 Opus 決定的事（沒有寫「無」）
