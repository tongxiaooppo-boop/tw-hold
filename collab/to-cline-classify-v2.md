# 任務書：分類規則 v2（Cline／DeepSeek 執行）— 2026-11-01

你在 `D:\g\claude\tw-hold`（git repo，main）。請依下列 7 項修改 `screener/classify.py` 與 `tests/test_classify.py`。規則已由 Opus／Claude 決定，**你只實作，不重新設計**。

## 紀律（違反＝失敗）
- **只准讀**：`screener/classify.py`（全檔）、`tests/test_classify.py`（全檔）、本任務書、`research/classify_calib_2026-11-01/report.md`。**不准瀏覽其他目錄、不准讀 PRD／HANDOFF／其他程式。**
- **只准改**：`screener/classify.py`、`tests/test_classify.py`。要動 `ClassInputs`／`Classification` 的欄位、函式簽名、既有常數名稱，或測試預期值與任務書衝突 → **停下回報，不要自行決定**。
- 不要用網路搜尋、網頁抓取、瀏覽器工具。暫存檔只放 `D:\g\claude\tw-hold\_tmp_cline\`，結束前刪掉。
- **每完成一項（T1…T7）就跑測試並 commit 一次**（只 add 上述兩個檔；訊息「分類v2 Tn：…」；結尾加一行 `Co-Authored-By: Cline <noreply@cline.bot>`）。**不要 push。**
- 測試指令：`cd D:\g\claude\tw-hold && PYTHONIOENCODING=utf-8 python -m pytest tests/test_classify.py tests/test_build_classification.py tests/test_quarterly_prep.py tests/test_rev_index.py tests/test_rev_momentum.py -q`。基準：目前 205 個全過；每項做完仍須全過（你新增或依任務書調整的測試除外）。
- 新增測試用中文白話名稱，合成資料，預期值註解說明怎麼算。門檻常數放檔頭，標【經驗】。Python 3.14：識別字不要用 ①② 這類字元。

## T1 疑似循環不改類型（Q1=B）
現況：必要①②成立但輔助（beta≥1.5 或同步度≥0.6）都不成立 → 類型判 cyclical、副標「疑似循環」、降級。
改為：**類型維持非循環（落到原本會判成的 growth／normal）**，副標加「疑似循環」，`reasons_degrade` 加「營收型態疑似循環（輔助條件未過）」，`metrics["candidate_type"]` 維持 `cyclical`（已有就沿用）。若同時狀態含「歷史高獲利區」→ `reasons_degrade` 再加「疑似循環且處歷史高獲利區（避免用高峰 EPS 判便宜）」。確認循環（輔助成立）行為不變。
測試：`test_必要兩條成立但輔助未過_類型不是循環_副標疑似循環`、`test_疑似循環且歷史高獲利區_多一條降級原因`；既有釘住「疑似仍判循環」的測試改成新語意（只改預期，註解說明）。

## T2 傳統循環產業先驗路徑（Q2；調查證實振幅改相對尺度救不到 2605／2612）
新常數 `CYCLE_PRIOR_INDUSTRIES = ("航運業", "鋼鐵工業", "塑膠工業", "水泥工業", "造紙工業", "玻璃陶瓷", "橡膠工業", "化學工業")`【經驗】。`ClassInputs.industry_group` 只有 financial／biotech／construction／other，**沒有原始產業名**：此項**需要原始產業名**，請**停下回報**需要新增 `ClassInputs.industry_name: str = ""`（選用欄位，預設空字串；`build_classification.assemble_inputs` 要傳入 `normalize_industry(name)`）。**我（主對話）若在任務書後面註明「已核准」，你才實作；否則跳過 T2 並回報。**
（核准後的規則：必要①不成立、必要②成立，且 `industry_name` 在 `CYCLE_PRIOR_INDUSTRIES` → 類型 cyclical、副標「產業先驗循環」、降級原因「靠產業先驗，振幅未過前 30%」；①已成立者行為不變；與 T1 的疑似路徑不互相覆蓋。）
> 【主對話核准】：**已核准**（使用者 2026-11-01 授權主對話決定）。請新增 `industry_name` 欄位並改 `build_classification.py` 的 `assemble_inputs` 傳入（這是本任務書唯一允許改 `build_classification.py` 與 `tests/test_build_classification.py` 的地方，僅限傳入該欄與一個斷言）。
測試：`test_傳統循環產業_必要②成立但振幅未過_判循環_副標產業先驗`、`test_非傳統循環產業_振幅未過_不判循環`、`test_傳統循環產業_必要②不成立_不判循環`（1101 台泥型：有回撤但營收沒收縮）。

## T3 轉機顯示（Q3=B）
`display_type()`：非循環類型（normal／growth）**只有 `state` 含「轉機」（四條件全「且」的既有狀態）才顯示「轉機」**；只有「虧損」而無「轉機」狀態者顯示「虧損中」（新顯示字串，常數 `DISPLAY_LOSS`）。循環類不被覆蓋（維持）。金融／特殊／資料不足不變。
測試：`test_非循環只有虧損_顯示虧損中`、`test_非循環有轉機狀態_顯示轉機`；既有釘住「虧損→轉機」者改預期。

## T4 疑似景氣高檔／低檔須確認循環（規格對齊 #14，以草案為準）
「疑似景氣高檔／低檔」狀態：只有 **類型為 cyclical 且不是疑似（非「疑似循環」副標）且「循環未觀察完整」副標不存在**，且產業方向一致，才可產生；否則只留「歷史高／低獲利區」。
測試：`test_疑似循環不產生疑似景氣高檔`（3443 型）、`test_確認循環且已觀察完整_才可疑似景氣高檔`。

## T5 單一景氣事件標記（Q5①）
循環類（含確認循環與 T2 路徑）若必要②只在**單一 2 年窗**內成立（做法：把 TTM 營收 YoY 與 TTM 營業利益在任一個連續 24 個月窗內設 NaN 後，必要②不成立；窗滑動掃描 2015～今，任一窗使之不成立即算）→ 副標「僅單一景氣事件」＋降級原因，**不改類型**。新函式 `single_event_dependent(...)` 放 `classify.py`，純函式，簽名與 docstring 自訂（寫清楚），單元測試必備。
測試：`test_必要②只靠單一兩年窗_標僅單一景氣事件`、`test_必要②有兩段不同年份回撤_不標`。

## T6 循環退出門檻（Q5②）
`apply_hysteresis`：現況循環類沿用進入門檻、沒有退出門檻。改為：已是 cyclical 的 ticker，**只有當必要①（振幅全體分位 `oroa_amp_pct`）跌到 < `CYCLE_EXIT_AMP_PCT`(0.60)【經驗】連續 4 個曆季，或必要②連續 4 季不成立**，才允許離開循環；離開後同樣套「切換後鎖 4 季」。history 欄位 `HISTORY_COLS` 若需新增「連續失效季數」之類欄位 → 停下回報（不要自行改欄位）；可改用 history 內既有各列的 `metrics`/分位值回算。
測試：`test_循環分位跌到0點55只一季_不退出`、`test_循環分位連4季低於0點60_退出並鎖4季`、`test_循環必要條件連4季不成立_退出`。

## T7 副標「獲利不穩」改名
副標「獲利不穩」（近 5 個完整曆年有虧損年）與狀態「獲利不穩」（近 4 季有虧損季）同名不同義。**副標改名為「近5年曾虧損」**；狀態名稱不變。同步 why／測試字串。
測試：既有釘住副標字串者改名；新增 `test_副標與狀態不同名`。

## 完成回報（精簡，不貼程式碼）
每項 commit hash、測試通過數、停下回報的事項（若有）、你自行決定處（一行一個）。最後跑：`PYTHONIOENCODING=utf-8 python build_classification.py --out D:\g\claude\tw-hold\_tmp_cline\sc.json --no-history`，回報類型／顯示類型／狀態／副標分布，與 2605 2612 2618 2603 2609 2002 1301 1101 3443 3008 2454 2330 的類型／副標。
