# tw-hold 鬧鐘（Cloudflare Worker）

GitHub 的 `schedule` 實測會晚 5～9 小時，`workflow_dispatch` 不會。這個 Worker 只當鬧鐘：到點呼叫 GitHub API dispatch 指定 workflow。GitHub 原本的 cron 不動，留作備援（workflow 都是冪等的）。

## 時間表

見 `schedule.js`。

## 與 workflow 的 gate 搭配（2026-11-18）

- dispatch 一律帶 `inputs: {source: "alarm"}`；五條 workflow 的 `workflow_dispatch.inputs.source` 必須宣告（預設 `manual`），否則 GitHub 回 422、整班漏掉。新增 workflow 到時間表時要先在該 workflow 宣告 `source`、push，再部署 Worker。
- 各 workflow 第一個 job `gate`（`scripts/run_gate.py`，規則在 `reference/run_gate.py`）決定這班要不要真的跑：資料已新鮮或 Cloudflare 剛成功就跳過；手動與 Streamlit 按鈕（沒帶 source）一律跑；gate 出錯一律跑。

## 部署

1. `npx wrangler login`
2. `cd cloudflare`
3. `npx wrangler deploy`
4. `npx wrangler secret put GH_TOKEN`

或用網頁版 Workers：貼上 `schedule.js`、`worker.js`，在 Settings → Triggers 加 cron（同 `wrangler.toml`），在 Settings → Variables 加 secret `GH_TOKEN`。

## 維護

- 改時間表要同步改 `wrangler.toml` 的分鐘欄位（`node --test cloudflare/` 會擋）。
- 查 log：`npx wrangler tail`
- 停用：Dashboard 刪掉 cron trigger（GitHub cron 仍在當備援）。
