# 簽呈：0050 卡片 fallback + 開盤前新鮮度守門 — 請 Opus 全檢

> **給接手審核的你**：這是一份自足的簽呈，你在全新對話、沒有上下文。
> 讀完這份就能開始審，不用先讀其他文件（除非下面某條你想深挖）。
> 環境：`d:\g\claude\tw-hold\`，commit `6a5e0e7`（已 push 到 `origin/main`）。
> 這是**純運維/UI 層**的一輪改動——沒有動任何選股規則、因子公式、verdict 邏輯，
> `PRD.md` 凍結範圍沒有變更。

---

## 0. 一分鐘現況

- commit `6a5e0e7`（本輪改動）+ `ec13aa2`（rebuild bot 自動 commit），已 push。
  跑過的測試：`test_app_smoke.py`（2 個相關 case）、`test_index_proxy.py`（4 個）、
  新增的 `test_promote_index_0050.py`（6 個）全過。**沒有跑過完整 `pytest -q`**——
  建議你審的時候先補跑一次全套，我只挑了受影響的測試檔跑，沒有排除掉「改動
  間接波及但我沒想到」的可能性。
- 觸發了一次 `rebuild.yml`（run `35045507623`，`workflow_dispatch`）驗證新流程
  在真環境能跑：**「上市代理 0050 快照」步驟成功、驗證通過、`data/reference/index_0050.parquet`
  已 commit（`ec13aa2`）**，實測 2848 筆、最後一筆 2026-09-15、收盤 106.25（前一天
  106.90，跌幅 -0.6%，在合理範圍），「0050 驗證沒過才告警」那步被跳過（正常，
  代表沒觸發拒絕分支）。**端到端跑通了一次，但只有一次**——§4 提到的長期/邊界
  情境（連續多天 reject、連假、並發）都沒有實測過，只有邏輯推演。

---

## 1. 背景：從一個問題牽出三個改動

使用者問「總經導航的 0050 卡片為什麼是舊資料，006201 走 FinMind，0050 來源是誰？」
查出兩層問題：

1. **0050 走 `bundle_data.prices("0050")`**，要拖一整包 tw-swing bundle
   （本機實測：`prices_adj.parquet` 25MB，加上完全用不到的財報/PER/籌碼/月營收
   共 ~89MB）才能顯示一張卡片；006201 是獨立向 FinMind 抓的小檔，兩者速度天差地遠。
2. **總經導航頁最前面有一道 `_ensure_bundle()` 硬性關卡**——bundle 抓失敗/抓慢
   會擋掉整頁，包括完全不需要 bundle 的 006201/國際指數/總經數字卡（那些都是
   純讀本地 CI 產出檔案，見 `reference/global_macro.py`、`tx_futures.py` 檔頭）。
3. 過程中使用者陸續要求：燈號改用既有 UI 元件風格（不要 emoji）、價值/定存排序
   統一用總經導航「族群動向」那款 `segmented_control`、開盤前要確保資料更新到
   前一天且要好診斷、**以及這次的重點——0050 改法要有備援，因為「前一日的資料
   錯誤不可原諒」**。

---

## 2. 改了什麼（照時間序）

| # | 改動 | 檔案:行號 |
| :- | :--- | :--- |
| 1 | `_ensure_bundle()` 加 `ttl=3600`——原本沒有 TTL，容器活多久就用第一次下載的 bundle 多久，跟上游更新脫節 | `app/streamlit_app.py:1267` |
| 2 | 價值/定存排序 `st.selectbox` → `st.segmented_control`，統一成「族群動向」同款 UI，欄寬比例 2:1 → 3:2 | `app/streamlit_app.py:957, 985` |
| 3 | 開盤前新鮮度守門：新增 `scripts/freshness_check.py`，比對「預期交易日」（今天往前找最近平日，連假留 2 天緩衝）| 新檔 |
| 4 | `heartbeat.yml` 從「每週一次、只看 `rebuilt_at` 有沒有變」改成「平日台北 08:30（開盤前 30 分）、直接查 `trading_date` 本身」，告警訊息附診斷指引（rebuilt_at 也舊→查 tw-swing；rebuilt_at 新但 trading_date 舊→bundle 本身舊；只有某一項 stale→那條獨立管線自己斷了）| `.github/workflows/heartbeat.yml` 整份重寫 |
| 5 | 表頭右側新鮮度徽章，燈號用既有 `.thc-pill`（good/warn 色點+底色），不用 emoji；只顯示 bundle trading_date | `app/streamlit_app.py:2377`（`_freshness_badge_html`）、`2412-2414`（表頭 columns） |
| 6 | **0050 卡片改讀小檔**：`reference/index_proxy.py` 新增 `load_0050()`，讀 `data/reference/index_0050.parquet`（committed）| `reference/index_proxy.py` |
| 7 | **CI 端驗證後才落地**：新增 `scripts/promote_index_0050.py`，把 `data/upstream/index_0050.parquet`（tw-swing bundle 本來就有附的小檔，CI 下載到暫存目錄）驗證後複製到 `data/reference/`。三道驗證：非空/欄位對、**新檔日期不能比舊檔倒退**、**單日漲跌幅不能超過 ±15%**——任一沒過就保留舊檔案不覆寫、exit 1 | 新檔 |
| 8 | `rebuild.yml` 加兩步：「上市代理 0050 快照（驗證後才覆寫）」（`continue-on-error: true`，不擋三清單主線）+「0050 驗證沒過才告警」（`if: steps.promote_0050.outcome == 'failure'`）| `.github/workflows/rebuild.yml` |
| 9 | `_macro_compass_page()`：**拿掉整頁最前面的 `_ensure_bundle()` 關卡**。改成 `_load_0050()`——先讀 `index_proxy.load_0050()`，空的才退回 `_bundle_close("0050")`（這時才真的呼叫 `_ensure_bundle()` + 拉整包 bundle）| `app/streamlit_app.py:2136-2160` |
| 10 | `freshness_check.py` 的檢查項目從「bundle trading_date + 006201」改成「bundle trading_date + **0050**（獨立新增）+ 006201」，因為 0050 不再跟 bundle 共用同一個時鐘 | `scripts/freshness_check.py` |
| 11 | 補測試：`test_index_proxy.py` +2、`test_promote_index_0050.py` 新增 6 個（涵蓋跳過/空檔/日期倒退/漲跌幅超標/正常覆寫/首次寫入）| `tests/` |

---

## 3. 關鍵設計決策（請逐一 sanity-check）

| | 決策 | 理由 |
| :- | :--- | :--- |
| **A** | 0050 的權威來源改成 tw-swing bundle 裡本來就有附的 `index_0050.parquet`（走現有 `fetch_bundle.py` 下載），**不是**另開一次獨立 FinMind API 呼叫（006201 是這樣做的）| 省一次 API 額度，且理論上跟 bundle 其他資料同源一致；代價是仍然依賴 tw-swing 那邊持續附這個檔（PIPELINE 標成 `u1b`，屬於「可選、缺了不擋主線」層級） |
| **B** | 驗證失敗時「保留舊檔案、不覆寫」而不是「用舊資料重試」或「用次要資料源 fallback」| 使用者原話「前一日的資料錯誤不可原諒，寧可暫時舊也不要覆蓋成錯的」——正確性優先於新鮮度 |
| **C** | app 端讀取失敗（`load_0050()` 回空）才退回吃整包 bundle，**不是**直接顯示「沒資料」| 讓 0050 卡片有兩層防呆：CI 端防止錯資料上線，app 端防止小檔缺失時卡片直接消失 |
| **D** | 拿掉總經導航頁最前面的 `_ensure_bundle()` 全頁關卡，改成只在 fallback 分支才觸發 | 頁面 90% 內容不需要 bundle，不該被它的下載延遲/失敗拖累 |

---

## 4. 我特別想要你挑戰的點（這才是重點，不要只覆核我列的清單）

1. **驗證門檻本身站不站得住腳**：`promote_index_0050.py` 只驗證「新檔最後一筆」——
   日期不倒退、漲跌幅 <15%。**沒有驗證中段資料是否被竄改**（例如上游重新回填
   歷史、修正過去某天的收盤價），也沒有驗證跟 bundle 其他來源（`prices_adj.parquet`
   裡的 0050，如果它也在裡面）是否一致。15% 這個數字是我憑感覺定的（0050 是
   ETF、正常不會跳這麼多），**不是回測/統計算出來的**，有沒有更嚴謹的做法？

2. **「保留舊檔案」會不會變成沒人發現的慢性問題**：如果 tw-swing 那邊 `index_0050.parquet`
   連續好幾天都不過驗證（例如上游資料格式悄悄變了，導致每天都觸發同一種
   reject），`_load_0050()` 會每次都退回 `_bundle_close`——**這時總經導航會悄悄
   變回原本的慢速+全頁依賴 bundle**，除非有人去看 webhook 告警，不然使用者只會
   覺得「這頁最近怎麼變慢了」，不會直接聯想到 0050 驗證的問題。告警機制（§2 
   的第 8 項）夠不夠？需不需要在 app 畫面上也留一個線索（例如 fallback 發生時
   在總經導航頁印一行 `st.caption` 講「0050 目前走備援路徑」）？

3. **006201 完全沒有同等級的驗證**：`fetch_index_proxy.py`（獨立 FinMind 抓取）
   沒有任何「日期倒退」「漲跌幅異常」檢查，直接覆寫。既然使用者的原則是
   「前一日資料錯誤不可原諒」，這個原則邏輯上該適用到 006201，不該只有 0050
   享受這層保護——這是我這輪的疏漏，還是有理由不對稱處理？

4. **表頭徽章的語意在 0050/006201 決耦後有沒有跟著更新**：徽章固定顯示
   「bundle trading_date」，理由是「涵蓋面最廣（三清單/個股查詢/0050）」——但
   這次改動後 0050 已經**不再**跟 bundle 共用時鐘了，這個理由半失效。使用者
   站在總經導航頁看到頭部徽章的日期，會不會誤以為那就是這頁 0050/006201 卡片
   的資料日期？要不要把徽章文案改成更明確地講「三清單／個股查詢」而不是暗示
   涵蓋全站？

5. **`_ensure_bundle()` 的 `st.cache_resource` 在多個並發 session 下的行為**：
   `cache_resource` 是 process 級共享（不是 per-session），TTL 到期後下一個
   進來的請求會觸發重新執行 `ensure_assets()`（打 GitHub API + 可能下載檔案）。
   如果同一時間有多個使用者的 session 一起打到這個容器、剛好都撞上 TTL 到期，
   會不會有多個 thread 同時跑 `ensure_assets()`、互相覆寫同一批本地檔案？
   `st.cache_resource` 本身有沒有做這層鎖，還是要我自己加？

6. **開盤前告警的連假誤報**：`freshness_check.py` 的 `SLACK_DAYS = 2` 只夠蓋
   一般三天連假，蓋不住農曆春節（可能到 9-10 天）。這段期間 `heartbeat.yml`
   每個平日開盤前都會告警，且三項檢查（bundle/0050/006201）會同時觸發——這算
   是可接受的「已知限制，人工判斷是假警報」，還是應該做行事曆感知（要嘛硬編碼
   台灣國定假日表，要嘛接外部行事曆 API）？

7. **`_bundle_close` fallback 失敗時的訊息品質下降**：原本整頁關卡失敗時會顯示
   `st.error` 附帶具體錯誤（PAT 找不到 / GitHub API 錯誤碼），現在 fallback 
   失敗只會讓 0050 併入 `tw_missing`、顯示籠統的「這次沒拿到：上市（0050）」
   （`app/streamlit_app.py:2192-2193`），失去原本的診斷細節。這個取捨——用
   「不擋頁」換「診斷資訊變粗」——划算嗎？

8. **`scripts/` 目錄現在被 app 執行期 import**（`_freshness_badge_html` 裡
   `from scripts.freshness_check import ...`）——這個目錄原本定位是 CI/CLI
   工具，沒有 `__init__.py`，靠 Python 3 namespace package 機制能被 import。
   這個新增的耦合（app 依賴 scripts/）合不合適，還是應該把 `_check_one`/
   `_meta_trading_date` 這種共用邏輯搬進 `reference/`（app 本來就會 import
   的目錄）比較乾淨？

---

## 5. 不用審的（已定案/範圍外）

- 選股規則、因子公式、verdict 邏輯——這輪完全沒碰。
- 三清單（價值/定存/長波段）本身的資料流——沒改，只有它們的排序 UI 元件換了。
- 是否要把「badge-only 顯示」升級成「硬性擋頁」——使用者已經明確裁決 badge-only，
  這題不用重審（除非你認為 §4 的新風險改變了這個判斷）。

---

## 6. 請你回答

1. **§4 的 8 個挑戰點**，哪些是真的隱患、哪些是我過慮？各自建議怎麼處理。
2. **驗證邏輯（§4-1）夠不夠嚴謹**——如果不夠，具體該加什麼檢查？
3. **006201 要不要補齊同等級的驗證（§4-3）**？
4. 有沒有我完全沒想到、但你掃過程式碼會擔心的地方（尤其並發/快取相關，§4-5）？
