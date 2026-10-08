# tw-hold 交接 — 2026-10-08 下午（承 HANDOFF_2026-10-08.md；計畫書見 updatePRD-opus.md）

> 寫給下一個接手的 Sonnet（含新對話的我）。Windows；`cd /d/g/claude/tw-hold`；python 一律 `PYTHONIOENCODING=utf-8`。一律中文白話。
> ⚠ 使用者規則：Opus 審 → 問使用者 → 才 push；改 cron／程式後兩個 repo 全套測試先過再 push，指令鏈不得讓 `pytest | tail` 吞失敗碼；不在官方還沒公布時請求；不自行改頻率。

## 0. 先做這件事（使用者交代）

**動手前先 `git pull`（或 `git fetch && git status -sb`），不要再 push `91a0405`。**
- `91a0405`（「時段外整班跳過不算錯誤；文件同步…」）**已經在 GitHub `origin/main` 上**，不需要、也不可以再推一次。
- 之後有人（Opus）在同一份工作樹又加了 `d807169`（只改 `docs/updatePRD-opus.md` §7.3 一行）。
- 2026-10-08 11:40 實查：本機 `HEAD` ＝ `origin/main` ＝ `d807169`，無未提交改動；若你之後看到「落後 GitHub 一個 commit」，就是有人在別處又推了東西——先 pull 看是什麼，再動手。
- 使用者要求本次交接寫明這點，原因是它收到的訊息是「本機分支落後 GitHub 一個 commit」，容易誤以為要再推 `91a0405`。

## 1. 今天（10/8）已完成並在 origin/main 上

| commit | 內容 |
|---|---|
| `1d71251`（Opus） | 影子期整條線：`selfhost_daily_merge`／`selfhost_zip_gate`／`selfhost_shadow_compare`／`selfhost_datapack.yml`；上市日線官網 `MI_INDEX` 為主；日線取到就停；`drop_future` 逐檔；週快照改跟 guard |
| `59887b1` | 事後審查修正：取到就停不再讓 workflow 變紅；併入缺日偵測（`find_gaps`，2018 起 2130 個完整日回測 0 誤報）；閘門驗法人／融資最後日；`selfhost_freshness` 停滯紅燈（已發佈完整日落後 ≥2 交易日 → `selfhost_datapack` 變紅） |
| `91a0405` | 整班落在請求時段外（排程延遲，例：04:02 班延到 08:01）回傳 0；DATA_FLOW §3.1 自建上游線＋救援；data-all md／html 補階段 2；PRD.md、updataPRD.md 註明被 updatePRD-opus.md 取代；updatePRD-opus B8 清單重播、§7.3 切換前後清單逐檔對照 |
| `d807169`（Opus） | updatePRD-opus §7.3：`apply_chips_baseline` 略過標明**尚未實作**（B2）；`import_chips` 是否整份重建**未驗證** |

測試：tw-hold 全套 487 passed（`pytest` 於 repo 根，`tests/` 內 477）。tw-swing 834 passed（本日未動 tw-swing）。

## 2. 今晚起要看的（依序）

1. **10/8 23:58 週收集**（本週最後交易日＝週四）：確認 `selfhost_collect` 有跑（guard 通過、減資輪詢與 snap-* 週快照有做）→ 接著 `selfhost_datapack` 被 workflow_run 觸發、Release `datapack-selfhost` 的 `merge_manifest.json` 完整日更新；**停滯紅燈有沒有誤報**（10/9 國慶補假、10/10–11 週末，完整日停在 10/8 是正常——休市表有列才不會誤報；若紅了先看 `selfhost_freshness` 輸出的落後天數與休市表是否抓到）。
2. 10/9（補假）、10/12（一）起：`openapi_daily` 排程班次實況——10/7 晚 5 班只起 3 班；看 10/8 晚是否重現（**不自行改頻率**）。
3. 讀 Opus 重新量測的官方公布時間：`data/selfhost/_measure_20261008/poll_publish.py`（本機背景，到 10/9 01:00）。結果決定要不要重排 `openapi_daily` 班次與 B10（產完 zip 觸發 swing）設計——**重排要使用者同意**。

## 3. 還沒做（10/23 前）

B2（swing `PACK_SOURCE` 開關＋自動退回＋略過 `apply_chips_baseline`＋來源標示）、B10（dispatch 鏈）、B6（每日抓官方當日結果表）、B13（端到端乾跑＋退回演練）、B8（10/19 比對報告含清單重播）。
- 待使用者決策：閘門 `gaps` 一律擋整包的政策（影子期維持；B2 切換前決定「只有 raw_prices 的洞擋、inst／margin 洞只警告」或維持全擋）。
- 待驗：`import_chips` 是否也整份重建（d807169 標明）。
- 文件債：`PRD.md` 內文資料管線章節仍過期；`data-all` 階段 1「已上線」與手動腳本未區分；`updatePRD-opus.md` §10 以後是事後審查紀錄。

## 4. 踩坑（今天新增）

- **同一份工作樹有多個 Claude（我與 Opus）在寫**：`git status` 看到「檔案被改過」常是對方改的；動手前 pull、commit 前看 `git diff`，不要假設自己是唯一寫入者。
- **「取到就停」要把已存／尚未公布／整班時段外都算成功**，否則 `main()` 回傳 1 → workflow 變紅 → 還會連帶觸發 `selfhost_datapack`；停滯交給 `selfhost_freshness` 紅燈。
- **`pytest` 要在 repo 根跑**：根目錄收集 487 個，`tests/` 內只有 477（其餘在別的測試目錄）。
- 沒設 `ALERT_WEBHOOK`：workflow 變紅是唯一會被看到的訊號，所以「該紅的要紅、不該紅的不能紅」都要小心。
- Opus 子代理審查值得做：這次抓到停滯無紅燈、閘門錨點全缺會靜默通過。
