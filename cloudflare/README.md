# tw-hold 鬧鐘（Cloudflare Worker）

GitHub 的 `schedule` 實測會晚 5～9 小時，`workflow_dispatch` 不會。這個 Worker 只當鬧鐘：到點呼叫 GitHub API dispatch 指定 workflow。GitHub 原本的 cron 不動，留作備援（workflow 都是冪等的）。

## 時間表

見 `schedule.js`。

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
