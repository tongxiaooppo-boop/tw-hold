# 簽呈：資料更新管線的備援/自癒機制 — 請 Opus 全檢

> ## ✅ 已結案（2026-09-22）
>
> **審核結論：六個改動本身沒問題，但抓到 8 個簽呈自己沒發現的坑，其中一個
> 是最優先等級。** 回覆見 `docs/REVIEW_RESPONSE_2026-09-22.md`；修正後已
> commit、`pytest -q` 234 passed。
>
> 最關鍵的抓漏：push 重試迴圈 `for...; do git push && break; git pull --rebase; done`
> 這個寫法，三次 push 全失敗但最後一次 pull 成功時，**exit code 是那個成功
> 的 pull，job 會綠燈、notify-failure 不會觸發，但資料根本沒推上 main**——
> 這輪想解決的「靜默失敗」問題，結果自己新寫的代碼裡就有一個。§4 的六個
> 挑戰點逐一有裁決，其中 §4-2（重試 vs 序列化）判定「重試對、序列化錯」——
> GitHub concurrency group 第三個 run 進來時會直接取消 pending 那個，不是
> 排隊，共用 group 反而可能靜默丟掉 PCF 這種不可回復的資料。
>
> 未採納：無（§4 六點全部處理，§3 六個設計決策 Opus 全部同意）。

---

> **給接手審核的你**：這是一份自足的簽呈，你在全新對話、沒有上下文。
> 讀完這份就能開始審，不用先讀其他文件（除非下面某條你想深挖）。
> 環境：`d:\g\claude\tw-hold\`，commit `69d22a7`（本輪最後一個手動 commit，
> 之後的 `187607b`/`a2cc86b` 是機器人自動 commit，資料內容變動，不是這輪要審的邏輯）。
> **請實際讀程式碼驗證，不要只信任這份文件的敘述**——尤其 §4 的挑戰點，
> 每一條都去對應檔案確認，不要只憑我的文字描述下判斷。

---

## 0. 一分鐘現況

今天（2026-09-22）從一個使用者回報「hold 資料沒更新」開始，牽出一連串管線韌性
問題，陸續修了 6 個獨立但相關的改動（commit `f10f8d4`→`69d22a7`，見 §2 表格）。
全部已 push 到 `origin/main`，其中「手動重整按鈕」跟「PCF 補跑」兩個新機制
今天都**實測跑過**（按鈕觸發過一次真的雲端重跑、PCF 補跑手動跑過一次）。
測試：`pytest tests/test_app_smoke.py tests/test_global_macro.py` 全過；
沒有跑過完整 `pytest -q`（上次全套跑是這輪最一開始，之後只跑了受影響的測試檔）。

---

## 1. 背景：從「資料沒更新」查到「告警系統從沒接上」

使用者問「hold 資料沒更新」，查出當天有兩個獨立問題：

1. `fetch_global_macro.py`（國際指數/美股個股/VIX/殖利率的每日快照）整條 crash——
   對過期 symbol 單獨重試時，`yf.download` 對單一 ticker 仍回傳 MultiIndex 欄位
   （`('Close','AAPL')` 這種 tuple），沒拉平就跟主批次單層的 `symbol` 欄位
   `pd.concat`，整批變 NaN，`sorted()` 比較 float/str 直接 `TypeError`。
2. 三清單 rebuild 卡在幾天前——查下去發現這其實是排程跨 UTC 午夜的正常抖動，
   不是真故障（見 §5，這個誤判後來自己更正了）。

過程中查到一個更根本的問題：`gh secret list` 顯示這個 repo **從沒設過
`ALERT_WEBHOOK`**——`rebuild.yml`/`heartbeat.yml`/`global_macro.yml` 裡寫好的
所有告警邏輯，這段時間都只是命中 `[ -z "$WEBHOOK" ] && echo "::warning::"`
這個分支，從沒真的通知到使用者。問使用者要不要現在設，**使用者明確回絕**：
「我不要告警，要的是備援+處理，警報掛在程式註明資料新鮮度就好」。
這份簽呈要審的六個改動，都是照這個方向做的：**自動重試/自癒優先於通知**。

---

## 2. 改了什麼（照時間序）

| # | 改動 | 檔案 | commit |
| :- | :--- | :--- | :--- |
| 1 | 修 `fetch_global_macro.py::_retry_stale()` 崩潰：單檔 `yf.download` 回傳的 MultiIndex 欄位 `raw.columns = raw.columns.get_level_values(0)` 拉平後再 concat | `scripts/fetch_global_macro.py` | `f10f8d4` |
| 2 | 總經導航卡片加「⚠️ 資料落後 N 天」標記——`fetch_global_macro.py` 本來就有寫的 `global_macro_meta.json.stale` 清單，之前只留在 CI log，現在接進 `_gz_card()`/`_mc_card()` | `reference/global_macro.py`（新增 `load_stale_map()`）、`app/streamlit_app.py` | `15b737d` |
| 3 | `global_macro.yml` 補 `notify-failure` job——原本三個告警步驟都要 fetch 先跑到寫出 `meta.json` 才有東西比對，整條 crash（像 #1 那次）會命中舊 meta、算出過期數 0、直接靜默。跟 `rebuild.yml::notify-failure` 同款式，抓「job 本身失敗」 | `.github/workflows/global_macro.yml` | `4beed20` |
| 4 | `rebuild.yml` 加排程備援——原本只靠 tw-swing `repository_dispatch` 單點觸發，dispatch 沒送到就永遠不會自己重跑。加平日 UTC 08:00（台北 16:00）`schedule` 觸發，bundle 沒變的日子靠既有 `diff --cached --quiet` 跳過 commit | `.github/workflows/rebuild.yml` | `c1e9c56` |
| 5 | 總經導航頁尾「手動重整」按鈕（打 GitHub REST `workflow_dispatch` API，`urllib.request` 標準庫，不加 `requests` 依賴）+ 新增 `.github/workflows/pcf_retry.yml`（PCF 沒有歷史回補 API，平日台北 10:00/12:00 檢查 `_index.json.missing`，非空才真的重抓，避免平白多打投信官網） | `app/streamlit_app.py`（`_macro_refresh_button`/`_trigger_workflow`）、`.github/workflows/pcf_retry.yml` | `894549c` |
| 6 | 三條會 commit 回 `main` 的 workflow（`rebuild.yml`/`global_macro.yml`/`pcf_retry.yml`）的 `git push` 都加 `pull --rebase` 重試（最多 3 次）——上線後**當天實測真的撞過一次**：手動重整按鈕同時觸發 `rebuild.yml` + `global_macro.yml`，`global_macro.yml` 先 push 成功，`rebuild.yml` 那邊基於舊 `main` 的 push 被 non-fast-forward 拒絕，整個 job 失敗（`notify-failure` 正確接住並觸發，證實 #3 的保護有用） | 三份 workflow 檔 | `69d22a7` |

---

## 3. 關鍵設計決策（請逐一 sanity-check）

| | 決策 | 理由 |
| :- | :--- | :--- |
| **A** | 修 bug 優先於加備援資料源——`fetch_global_macro.py` 的崩潰是程式邏輯錯，不是 yfinance 被擋（直接打 Yahoo raw chart API 驗證過：AAPL 09-21 的 close 本身在 Yahoo 端就是 `null`），换 Finnhub/Alpha Vantage 這類第三方 API 解決不了「Yahoo 自己沒資料」 | 對症下藥；備援門檻另外記在 memory，等真的連續多天過期才做 |
| **B** | 排程備援選「加 `schedule` 觸發」而不是「加告警叫人手動重跑」 | 使用者明確要備援不要告警（見 §1） |
| **C** | PCF 補跑做成獨立輕量 workflow（`pcf_retry.yml`），不是重跑整條 `rebuild.yml` | PCF 只是五檔投信官網的抓取，不需要為了補這個重新拉一次 25MB bundle、重算三清單 |
| **D** | PCF 補跑用 `_index.json.missing` 欄位門檻，不是無條件每次都重抓 | 避免對投信官網一天多打好幾次增加被反爬擋的風險（首週體檢時這是真的觀察點） |
| **E** | 手動重整按鈕用標準庫 `urllib.request` 打 GitHub API，不加 `requests` 套件 | `requirements.txt` 檔頭明講「刻意控依賴」（pandas/pyarrow/streamlit/plotly 之外不加），跟 `fetch_bundle.py`/`pcf_fetchers.py` 既有慣例一致 |
| **F** | 按鈕需要的 PAT（`GH_DISPATCH_PAT`）只給 `Actions: read/write` + `Contents: read-only`（觸發 workflow_dispatch API 實測需要這兩項，缺 Contents 會 403），刻意不給 `contents: write` | 最小權限——這顆 token 只需要「叫 CI 跑」，不需要能改 repo 內容 |

---

## 4. 我特別想要你挑戰的點（這才是重點，不要只覆核我列的清單）

1. **手動重整按鈕的存取控制**：這個 Streamlit app 目前是公開連結
   （`tw-hold-jchm8ooiwp7ewqisfzmpoo.streamlit.app`，使用者說過要讓朋友測），
   而按鈕本身**沒有任何身份驗證**——`_macro_refresh_button()` 只要
   `st.secrets["GH_DISPATCH_PAT"]` 存在就顯示按鈕，任何拿到連結的人都能按。
   冷卻機制是 `st.session_state["_macro_refresh_cooldown"]`（60 秒），但
   `session_state` 是**per-browser-session**，不同訪客（或同一人清 cookie/
   開無痕）各自有自己的 session state，等於冷卻形同虛設，理論上可以被
   重複觸發、消耗 GitHub Actions 分鐘數（雖然是公開 repo、分鐘數理論上無限，
   但仍是資源濫用向量，且會讓 commit 歷史被灌水）。這個風險大不大？
   需不需要加一層更強的節流（例如比對 `data/derived/_meta.json` 的
   `rebuilt_at`，如果離現在不到 N 分鐘就直接拒絕，不管 session 是誰）？

2. **push race 用「重試」而非「序列化」解決，夠不夠**：`rebuild.yml`/
   `global_macro.yml`/`pcf_retry.yml` 各自有獨立的 `concurrency.group`
   （`rebuild`/`global-macro`/`pcf-retry`），彼此不互斥，靠事後 `pull --rebase`
   重試 3 次來化解 push 衝突。今天實測撞過一次、重試邏輯還沒被那次撞車
   實際驗證過（那次是我手動重跑 `rebuild.yml` 單獨成功，不是重試邏輯生效）。
   如果之後三條真的更頻繁同時觸發（例如按鈕 + 排程 + dispatch 三個一起），
   3 次重試夠嗎？要不要乾脆讓三條共用同一個 `concurrency.group`（強制序列化，
   徹底避免 race，代價是彼此會排隊等）比較根本？

3. **排程備援對「系統性故障」沒有效果**：`rebuild.yml` 新增的 `schedule`
   備援（平日 UTC 08:00）能解決「dispatch 這次剛好沒送到」這種瞬時/隨機
   失敗，但如果是系統性故障（例如 `TWSWING_BUNDLE_PAT` 過期、tw-swing
   repo 本身停止發布），這個備援每天一樣會失敗，只是白跑一次 CI，不會真的
   讓資料變新。這個認知有沒有問題？要不要在 `notify-failure` 的訊息裡
   區分「這是偶發重試」還是「已經連續 N 天靠備援也救不回來，該人工查了」？
   （目前完全沒有連續失敗計數的機制。）

4. **手動重整按鈕是 fire-and-forget，使用者拿不到真實結果**：按下去只確認
   `workflow_dispatch` API 回 204（「已排入佇列」），不代表 workflow 真的會
   成功。使用者按完看到綠色「已觸發」，但如果那次 CI 跑到一半又失敗（像
   §2 的 race 那樣），使用者不會知道，只會在幾分鐘後重新整理頁面發現
   「怎麼還是舊的」。要不要在成功訊息裡附上 Actions 頁面連結，讓使用者
   自己能去確認執行狀態，而不是只能猜？

5. **PCF 補跑的 `missing` 判定只抓「抓取失敗」，抓不到「資料品質異常」**：
   `pcf_retry.yml` 的補跑條件是 `_index.json.missing` 非空（`fetch_all()`
   對哪個 fund 丟了 exception），如果五檔都成功抓到、但抓回來的內容本身
   有問題（例如某投信網站改版、回傳的 holdings 是空陣列或格式跑掉但沒
   丟例外），`missing` 會是空的，補跑機制完全不會觸發，因為它判斷的是
   「有沒有抓」不是「抓對了沒」。這算是這個機制設計上就沒打算涵蓋的範圍，
   還是該補一層基本的資料健檢（例如 `holdings` 筆數 < 某個門檻就當作
   可疑）？

6. **今天新增的三個告警/自癒機制彼此之間有沒有隱藏的耦合**：`notify-failure`
   （#3）、排程備援（#4）、PCF 補跑（#5）三個是分開加的，但它們共同的
   前提都是「這個 repo 的 GitHub Actions 額度/權限持續正常」。如果
   `TWSWING_BUNDLE_PAT` 或 `GH_DISPATCH_PAT` 真的過期了（memory 裡有記到
   期日提醒），這些備援機制會不會反而製造出一堆看起來像「系統在努力
   運作」但其實每次都注定失敗的雜訊 commit/run 記錄，讓人更難注意到
   根本問題（PAT 過期）？

---

## 5. 不用審的（已定案/範圍外）

- 選股規則、因子公式、verdict 邏輯——這輪完全沒碰。
- 「要不要設 `ALERT_WEBHOOK`」——使用者已經明確回絕，這題不用重審
  （除非你認為 §4 的新風險大到必須推翻這個決定，那請直接說明理由）。
- 「09-21 tw-swing 是不是真的跳過發布」——事後查證是排程正常跨日抖動，
  不是故障，這題當天已經釐清，不用重查。

---

## 6. 請你回答

1. **§4 的 6 個挑戰點**，哪些是真的隱患、哪些是我過慮？各自建議怎麼處理，
   越具體越好（例如：要改就給出改法，不是只說「這裡有風險」）。
2. **§4-1（按鈕存取控制）**如果你判定是真隱患，這是這次會議最該優先處理
   的一項還是可以緩一緩？
3. **§4-2（race 用重試 vs 序列化）**你會選哪個，為什麼？
4. 有沒有我完全沒想到、但你掃過程式碼會擔心的地方？
