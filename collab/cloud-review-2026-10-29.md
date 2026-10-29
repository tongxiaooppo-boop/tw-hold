你在審 tw-hold repo（Python／Streamlit 台股 app「股市雷達」）main 分支的一段改動。用繁體中文回報。只審、不改程式、不 commit、不 push。不准用網路搜尋或抓網頁，不准連 mopsov.twse.com.tw。

## 範圍
`git diff 76279b6^..aa207a9`，只看這些路徑：`screener/revenue_watch.py`、`build_revenue_watch.py`、`reference/revenue_mops.py`、`scripts/revenue_mops_collect.py`、`app/streamlit_app.py`（只看 `_rev_` 開頭的函式和 `_revenue_page`）、`.github/workflows/revenue_watch.yml`、`.github/workflows/rebuild.yml` 的相關變動、對應的 `tests/`。`data/` 底下的產物、文件、tw-swing 相關刪檔都跳過。需要背景時可以讀 `app/valuation.py`（估值試算 `estimate()`）和 `collab/to-cline.md`（規格）。

## 功能背景
朋友的做法：公司公布月營收當晚就估整季 EPS，估值價差 ≥40% 才買，沿月線／季線抱，到估值先賣一些、跌破線再全賣。這段程式：MOPS 每月 1～14 號一晚收 4 次，記錄每家第一次出現的時間（`first_seen_at`）→ 用 `app/valuation.estimate()` 算估值與價差 → 產 `data/derived/revenue_watch.json`（固定兩期：上個月、上上個月）→ app「月營收」分頁有四個檢視。

## 重點檢查（逐項給結論：沒問題／有問題＋檔案:行號＋具體觸發情境）
1. 估值／價差口徑：`upside_mid`、`upside_growth`、`at_valuation`、`cyclical`、`pe_wide`、`low_base` 的定義和計算有沒有算錯、分母為零、正負號、單位（元 vs 千元、% vs 小數）。
2. build 有沒有偷看未來：上一期的月營收歷史、財報季資料應該截到 ≤ 該月／該期可得的資料。（已知限制：上一期也用今天的現價比，這點不用報。）
3. 單檔失敗不能拖垮整批：build 和收集腳本裡，個股例外有沒有被吃掉後繼續；整批失敗時有沒有誤寫空檔蓋掉舊資料。
4. app 讀 JSON 一律用 `.get()`（雲端資料可能是舊 schema）；有沒有 `r["x"]` 這類可能 KeyError 的寫法；`None` 進格式化函式會不會炸。
5. `reference/revenue_mops.py` 的 `merge_seen`：保留第一次看到的數字、更正標 `revised`、`first_seen_at` 不被後面覆蓋；公布期外只抓不寫的防呆有沒有漏洞（時區用台北）。
6. workflow：`git add` 路徑不存在時的行為、cron 時間換算（UTC vs 台北）、併發兩班同時 commit 會不會衝突。

## 回報格式
- 每條發現：嚴重度（必修／建議／觀察）、檔案:行號、觸發情境（具體輸入 → 錯誤結果）、你多有把握。
- 沒把握的就寫「待確認」，不要硬判。不要貼大段程式碼。
- 最後一行總結：必修幾條、建議幾條。
