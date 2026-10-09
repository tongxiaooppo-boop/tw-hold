# tw-hold 交接 — 2026-10-09 傍晚（承 HANDOFF_2026-10-09.md）

> Windows；`cd /d/g/claude/tw-hold`；python 一律 `PYTHONIOENCODING=utf-8`。一律中文白話。
> 使用者規則不變：不自行改 cron／頻率；不在官方還沒公布時請求；兩 repo 全套測試過才 push。
> **新規則（使用者 10/9）**：要使用者回答的事，**先附我的建議並預設照做**，不要丟一串待答問題；簡單的工作交給 Sonnet。

## 0. 本次做了什麼

Opus 審核 `updatePRD-opus.md` §0.5 全表，並審核自建上游、切換開關、退回機制。審核全文在 **`updatePRD-opus.md` §11**（R1–R10、B13 演練清單 §11.3）。使用者回「照建議」，以下全部已 push：

| repo | commit | 內容 |
|---|---|---|
| tw-swing | `f19a2ba` | **R1**：自建包下載驗證都過、但匯入失敗或籌碼守門觸發 → 整包退回上游重匯（`update_data.py`），+4 測試；**R6**：`daily.yml` 每班把 `_pack_source.json` 追加到 `data/daily/_pack_source.jsonl` |
| tw-hold | `2ea0733` | B2+ manifest 附 `closed_days`（先前未 push，這次一起推） |
| tw-hold | `9148b51` | **R2** 自癒：`last_trading_day_guard` 讀已發佈 manifest，有 `gaps` 或完整日落後 → 當晚 23:58 那班照收（沒加排程）；**R4** 閘門通過寫 `published_at`；**R6** 頁尾顯示資料來源（`reference/freshness.py`，全 `.get()`） |
| tw-hold | `3885786` | 文件：§11 處理欄、§0.5.3 完整回滾步驟、§7.3／§10／§2.6 更正、DATA_FLOW 自癒說明 |

測試：**tw-swing 865 passed、tw-hold 556 passed**（全套）。沒改 cron、沒設 repo 變數、沒 dispatch。

## 1. 使用者已拍板（照 Opus 建議）
- **R4**：最後一槍遇自建落後 1 日的規則不改（照用＋紅燈）；影子期用 `published_at` 統計每個完整日的發佈時間，10/23 再決定。
- **R5**：接受 B10 打開後短線掃描在融資券第一次抓到就算當天（早於 00:00）。依據：10/8 的 23:24 版＝01:18 重抓版＝週收集版（0 差異）。影子期每天看 manifest `overlap_check.margin`，出現差異再把 `MARGN_TODAY_AFTER_HOUR` 改 24。
- **§7.3 第 0 步**（切換前後清單逐檔對照）：保留，10/24 當天做一次。

## 2. 還沒在真 runner 跑過（只有單元測試）
R1 退回重匯、R2 guard 自癒、R6 daily 來源紀錄。第一次真實驗證＝B13 演練（`updatePRD-opus.md` §11.3）。

## 3. 下次回來先看
1. `git pull`（兩 repo）。
2. **B6 第一次線上跑**：`openapi-daily` Release 有沒有 `openapi_events.parquet`／`openapi_events_meta.json`、fetch log 有 `endpoint: events`。
3. **下一版 `datapack-selfhost` manifest**：要有 `closed_days`（`closed_days_source=twse_holidaySchedule`）、`published_at`、`events_*` 欄位。
4. `selfhost_collect` 下一班 log：新的「下載已發佈 manifest」步驟有沒有成功、guard 理由是否正常。
5. tw-swing 下一班 `daily.yml`：`data/daily/_pack_source.jsonl` 有沒有新增一行（`used=upstream`）。

## 4. 待辦（時程照 `updatePRD-opus.md` §0.2）
- **10/12 起影子期**：每天看完整日發佈時間（R4）、`overlap_check.margin`（R5）、`shadow_history.jsonl`。
- **10/16 前**做一次累積檢查（使用者 10/17–18 外出）。
- **10/19** B8 正式報告。
- **10/23** go/no-go＋B13 演練（§11.3 六步：真 dispatch、分支 selfhost 真跑、四種退回＋格式壞 zip、融資券落後一天、回滾）。
- **10/24** 切換：tw-swing 設 `DATA_REPO`、`PACK_SOURCE=selfhost`；tw-hold 設 `TRIGGER_SWING=true`；回滾步驟見 §0.5.3。
- 10/24 後：提醒使用者記憶 `tw-hold-after-1024-deferred` 的三件事。
- 未決小項：B6 的 L4、L5；B11「當日事件因子缺」警告（不擋切換）；全套測試偶發失敗查不出是哪項，下次出現存 `-rf` 輸出。
