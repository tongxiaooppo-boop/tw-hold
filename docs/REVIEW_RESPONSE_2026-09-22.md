# 審核回覆：資料更新管線的備援/自癒機制

> 對應 `docs/REVIEW_REQUEST_2026-09-22.md`。Opus 實際讀完 §2 表格全部檔案後
> 回覆：簽呈描述的六個改動屬實，**但簽呈自己沒發現的問題比 §4 列的六點更
> 嚴重**——尤其 push 重試迴圈本身有一個會靜默掉資料的 bug，比「要不要防按鈕
> 濫用」優先級高得多。全部 8 個新問題 + §4 六點的裁決都已經處理完，commit
> 見文末。

---

## 審核結論一句話

原本以為最需要挑戰的是「按鈕存取控制」（§4-1），結果 Opus 抓到的最大隱患
是**我自己寫的 push 重試迴圈邏輯有 bug**：`for i in 1 2 3; do git push && break; git pull --rebase; done` 這個寫法，如果三次 push 全失敗但最後一次
`pull --rebase` 成功，**迴圈的 exit code 是最後一條指令的、也就是那個成功
的 pull**——job 綠燈、`notify-failure` 不會觸發，但資料根本沒推上 main。
這正好是這一整輪想解決的「靜默失敗」問題的翻版，只是這次是我自己新寫的
代碼裡的。

---

## §4 六個挑戰點的裁決

| # | 挑戰點 | 裁決 | 處理 |
| :- | :--- | :--- | :--- |
| 1 | 按鈕存取控制 | **真隱患，但中等，不是第一優先**——爆炸半徑有限（公開 repo Actions 分鐘數不計費、兩條 workflow 冪等、無意義 commit 會被 `diff --quiet` 擋掉） | 行程級冷卻（`st.cache_resource`，15 分鐘）+ 觸發前查 GitHub Actions API 確認上一輪跑完沒，兩層都比原本的 `session_state` 冷卻更權威、繞不過 |
| 2 | push race：重試 vs 序列化 | **選重試，不要序列化**——GitHub concurrency group 每個 group 只保留一個 pending run，第三個進來時 pending 那個會被**直接取消**（不是排隊），三條共用一個 group 反而可能靜默丟掉 PCF 這種不可回復的資料，比現在的失敗模式更難察覺 | 維持三個獨立 group，把重試邏輯本身修對（見下） |
| 3 | 排程備援對系統性故障無效 | **認知正確，但不用做連續失敗計數器**——更符合「警報掛在程式註明新鮮度」的做法是把絕對落後天數畫到 app 上，使用者打開 app 就看得到，比 CI log 裡的計數器有用 | 做 A4（見下），跳過計數器 |
| 4 | 按鈕 fire-and-forget | **真的該修，但很小** | 成功訊息附 GitHub Actions 連結；順便用問題 1 的 runs API 查詢一併達成 |
| 5 | PCF 補跑只抓「有沒有抓」不抓「抓對了沒」 | **真隱患，比簽呈自己認為的嚴重**——壞資料會直接產出錯誤買賣旗標給使用者看，不是「設計上沒打算涵蓋」可以帶過的範圍 | 見 A3（兩層防守） |
| 6 | 三個機制互相耦合、製造雜訊 | **部分屬實，但方向要調整**——真正會遮蔽根本問題的不是雜訊 commit，是 push 靜默失敗（就是上面那個 bug）；修掉它 + 做 A4，PAT 過期時 app 上會直接表現成「資料日卡住不動」，比任何計數器都直覺 | 修 A1 即可，不需額外機制 |

---

## Opus 額外抓到、簽呈完全沒提到的 8 個問題（全部已處理）

| # | 問題 | 嚴重度 | 修法 | commit |
| :- | :--- | :-- | :--- | :--- |
| A1 | push 重試迴圈最後一步是成功的 `pull` 時 exit code 會是 0，靜默掉資料 | 🔴 最優先 | 三份 workflow 都改用 `$pushed` 旗標明確判斷，5 次還沒成功就 `exit 1` | 三份 `.github/workflows/*.yml` |
| A2 | `rebuild.yml` 跟 `pcf_retry.yml` 常同一天各自 commit 到 `data/pcf/`/`active_etf_flags.json`（含時間戳一定不同），`pull --rebase` 幾乎必衝突且原本沒有解法 | 🔴 | 衝突時該批「產出檔」一律取自己這輪的版本（`git checkout --theirs` + `rebase --continue`），解不掉才 `rebase --abort` | 同上 |
| A3 | PCF holdings 抓回空/異常少但沒丟例外時，`snapshot_pcf.py` 照樣落地，下游差分會產出假的全體 consensus_sell（跟 memory `tw-hold-active-etf-flag` 那次假買訊號事故同類，方向相反） | 🔴 | 兩層防守：①`snapshot_pcf.py` 新增 `MIN_HOLDINGS=10`，異常少當抓失敗、記進 `missing`（順帶讓 `pcf_retry.yml` 自動接住）②`build_active_etf_flags.py` 新增 `MIN_SYNC_HOLDINGS=5`，今天筆數掉到前一份一半以下就當沒同步、不算差分（防不到「這次改動之前」就已落地的舊壞快照） | `scripts/snapshot_pcf.py`、`build_active_etf_flags.py` + 兩份新/改測試 |
| A4 | `_check_staleness()` 只比「這批自己最大日期」——整批一起卡住（連續沒跑成功）彼此沒有落差，偵測不到，app 上不會有任何 ⚠️ | 🔴 | `fetch_global_macro.py` 新增絕對新鮮度 `snapshot_lag_days`（跟營業日比，跳過週末）寫進 meta；`reference/global_macro.py` 新增 `load_snapshot_meta()`；app 在國際指數/波動度/美股個股整段前面加警示（>2 個營業日才顯示） | `scripts/fetch_global_macro.py`、`reference/global_macro.py`、`app/streamlit_app.py` |
| A5 | `pcf_retry.yml` 排在台北 10:00／12:00，比主排程（最晚 16:00）早，讀到的 `missing` 是前一天的，補跑邏輯上補不到當天要補的東西 | 🔴 | cron 改到 17:00／19:00（排在主排程之後）；判斷條件從單看 `missing` 擴大成「`missing` 非空 或 今天完全沒有任何一檔的日期」，順便涵蓋 rebuild.yml 整條掛掉、當天根本沒跑過 PCF 的情境 | `.github/workflows/pcf_retry.yml` |
| A6 | `pcf_retry.yml` 補抓步驟沒有 `continue-on-error`，一失敗 commit 步驟就不會跑，剛補到的不可回復資料被一起丟掉 | 🟠 | 補抓/重算兩步加 `continue-on-error: true`，commit 步驟改 `if: always() && need_retry=='1'` | 同上 |
| A7 | `heartbeat.yml` 的診斷文字說「rebuilt_at 也舊 → dispatch 沒送到」，但 `rebuild.yml` 資料沒變時本來就不 commit、`rebuilt_at` 本來就不會前進——會叫人去查一個沒壞的東西 | 🟡 | 改診斷文字（不是加新的「永遠 commit」機制——那樣會重新製造這輪一直在消除的雜訊 commit 問題），講清楚「rebuilt_at 舊也可能只是資料沒變，先去 Actions 看最近 run 時間」 | `.github/workflows/heartbeat.yml` |
| A8 | `STALE_THRESHOLD_DAYS=3` 對日經/恆生/KOSPI 這種有長國定連假的市場會連續誤報好幾天 | 🟡 | 這三檔門檻放寬到 7 天（`_ASIA_STALE_THRESHOLD_DAYS`），其餘維持 3 | `scripts/fetch_global_macro.py` |

---

## 這輪沒動、維持簽呈原判斷的部分

- §3 的六個設計決策（A–F）Opus 全部同意，沒有要推翻的。
- §5 列為範圍外的三項沒有翻案，包括「要不要設 `ALERT_WEBHOOK`」——上面所有
  修法都不依賴它。
- §4-2 沒有改成共用 `concurrency.group`（見上面裁決）。

---

## 驗證

- `pytest -q` 全套 **234 passed**（原本 224，這輪新增/改動的測試：
  `test_active_etf_flags.py` +1（`MIN_SYNC_HOLDINGS` 守門）、新增
  `tests/test_snapshot_pcf.py` 4 個（`MIN_HOLDINGS` 守門）、
  `test_fetch_global_macro.py` +2（亞股門檻放寬、`_business_days_since`）、
  `test_global_macro.py` +2（`load_snapshot_meta`)）。
- 三份 workflow YAML、`app/streamlit_app.py`、改動到的 Python 模組都過語法檢查。
- **沒有**在真環境重新觸發一次 `rebuild.yml`/`pcf_retry.yml` 去實測 push 衝突
  的 rebase-conflict 解法（A2）——本輪已經實測過一次「單純 push 被拒、rebase
  後直接成功」（沒衝突的情況），但「衝突時 `--theirs` 那段」只做過邏輯推演、
  沒有真的製造一次雙 workflow 同時 commit 到同一批檔案的情境去驗證。
  下次兩條真的撞在一起時，建議去 Actions log 確認那段有沒有跑對。

---

## commit

`aa9e373`（簽呈）→ 本輪修正一系列 commit（push 迴圈修正、PCF 健檢雙層、
global_macro 絕對新鮮度、pcf_retry 排程調整、heartbeat 文字修正、亞股門檻、
按鈕行程級節流 + runs API 查詢、對應測試）。
