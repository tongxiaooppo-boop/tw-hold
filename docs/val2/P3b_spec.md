# P3b 規格（Opus 定，2026-11-02；實作者不得改本檔與 `tests/test_val2_p3b.py` 的預期值）

範圍：分類刪死狀態＋遲滯後重算子分類＋金融業季數閘門、季更有效檔數金融規則、`coverage_mktcap_k`、loader 歸母淨利頂替集中、推薦卡季 EPS 年增改用 `growth`。
**`eps_nowcast` 本階段不動**：P3a 後已無引擎呼叫它（`eps_windows` 自成一體），只剩 `app/streamlit_app.py` 舊畫面 import 常數；P4 改寫畫面時連同 `tests/test_eps_nowcast.py`、`tests/test_bug4.py` 的 nowcast 測試整檔刪除。
沒寫到的舊行為一律維持。

## 1. `reference/loader.py::merge_statements`（歸母淨利頂替，A26 Q3 定案）
- 合併前先記下資產負債表**原始** `equity_parent`（沒有此欄＝全 NaN），再做既有的 `equity_parent.fillna(equity)`。
- 合併後：`ni_parent` 為 NaN 且 原始 `equity_parent` 為 NaN（含資產負債表沒有該季列）且 `net_income` 有限 → `ni_parent = net_income`。其餘維持 NaN。
- 暫存欄合併完要刪掉；輸出欄位與欄序跟現在完全一樣（不新增欄）。
- docstring 寫明規則與理由：「歸母權益也缺＝沒有非控制權益，合併淨利就是歸母淨利；歸母權益有值時不頂替（2015～2023 有 8 列兩者不同）」。
- 下游拿掉無條件頂替：`screener/multiples_self.py`（約 100 行 `ni = v.ni_parent if ... else v.net_income`）與 `screener/val_card.py`（約 461 行同樣寫法）改成只用 `ni_parent`，兩處 docstring（multiples_self 約 11 行、val_card 約 453 行）改成「ni_parent（loader 已依規則頂替）」。`reference/corporate_actions.py` 約 406 行**不動**（範圍外，影響只有那 8 列舊季）。
- 若 val2 測試的 fixture 依賴下游頂替（ni_parent NaN、net_income 有值）而失敗：只准把該 fixture 的 ni_parent 改成等於 net_income（模擬 loader 輸出），預期值不准改，回報列出。

## 2. `screener/classify.py`
### 2-1 刪死狀態
- 刪：`STATE_FWD_LOSS`、`STATE_FWD_EXPAND`、`FWD_EXPAND_MIN`、`UNSTABLE_EPSNC_REL`、`UNSTABLE_MEDIAN_Q`（確認只有這裡用）、`ClassInputs.eps_nc`、`ClassInputs.eps_f4` 與相關判斷；檔頭 docstring 的「預估轉虧」「前瞻擴張」兩條、「獲利不穩」後半條、ClassInputs docstring 的 eps_nc／eps_f4 說明一併刪。
- 「獲利不穩」只剩：最新 4 季任一 eps < 0。
- `RULE_VERSION = "class-v2-2026-11-02"`。
- 刪 `tests/test_classify.py` 的 `test_預估EPS_NC小於等於0_另列預估轉虧`、`test_前瞻擴張`、`test_前瞻擴張_F4低於NC_不成立`、`test_前瞻擴張_不到10趴_不成立`。

### 2-2 資料閘門（金融業不看營收）
- `industry_group == "financial"` → 季數＝`eps` 非 NaN 的列數；其他＝`revenue` 非 NaN 的列數（現狀）。`metrics["n_quarters"]` 與 why「單季財報僅 {n} 季（< 12 季），不分類」用這個數。檔頭第 0 步改寫。

### 2-3 `metrics["by_type"]`（遲滯後重算用）
- 候選類型為 `TYPE_CYCLICAL`／`TYPE_GROWTH`／`TYPE_NORMAL` 時：`metrics["by_type"]＝{t: {"subtags": [...], "state": [...], "reasons_degrade": [...]}}`，三個 t 都要有，內容＝「假設類型就是 t」時 classify 會輸出的 subtags／state／reasons_degrade（同一套程式碼、同樣順序與去重）。`by_type[c.type]` 必須與 c 本身三欄相等。
- 其他類型（資料不足／金融／特殊）：`metrics["by_type"] = {}`。
- 跟類型有關的部分（只列現有的，照現行規則）：循環的副標與降級（產業先驗、單一事件、未觀察完整、資產重／輕、結構衰退）、高成長的降級（5 年 CAGR 未檢查、上市未滿 20 季）、一般的副標（營運收縮、近5年曾虧損）、狀態名「谷底回升」（循環）／「轉機」（其他）、「疑似景氣高檔／低檔」（只有循環）。疑似循環副標與降級、高獲利區＋疑似循環的降級跟類型無關，三份都照現行條件。
- why 不分類型（維持候選類型的說明）。實作建議：把現在 `ctype` 決定之後的副標／降級／狀態段落抽成私有函式 `_decorate(t, ...)`，候選類型與三個 t 各呼叫一次。

### 2-4 `apply_hysteresis`
- 決定 final 之後：`final != new.type` 且 `final in new.metrics.get("by_type", {})` → `out.subtags`、`out.reasons_degrade` 換成 `by_type[final]` 的；狀態的過濾（立即狀態＋前一曆季候選也有）改以 `by_type[final]["state"]` 為底。`metrics["subtags_recomputed"] = True`；否則 False（沒有 by_type 時一切照舊，現有遲滯測試不變）。
- 狀態延續比對時，「轉機」與「谷底回升」視為同一個狀態（前一季候選是一般判的「轉機」，本季最終是循環的「谷底回升」，算延續）。
- docstring 補上這兩條。

## 3. `build_classification.py`
- `assemble_inputs` 拿掉 `eps_nc=None, eps_f4=None`；檔頭第 11 行說明刪。
- `_valid_tickers(q, period_end, financial: frozenset[str] | set[str] = frozenset()) -> set[str]`：`financial` 裡的 ticker 只要 `eps`、`ni_parent` 兩欄有值；其他照 `REQUIRED_COLS` 三欄。`new_quarter_ready` 與 `main` 的 `valid_count` 都要傳 financial＝universe 中 `qp.industry_group(industry) == "financial"` 的 ticker（`_t` 正規化；universe 沒有 industry 欄＝空集合）。新增私有 `_financial_set(universe) -> set[str]`。
- 新增 `coverage_mktcap_k(universe: pd.DataFrame, covered: set[str]) -> int | None`：沒有 `mktcap_rank` 欄 → None。丟掉 rank NaN、ticker 用 `_t` 正規化、同 ticker 留 rank 最小那列，依 rank 由小到大；K＝從第 1 個開始連續在 covered 裡的檔數（第 1 個就不在＝0）。
- `main` 的 payload 加 `"coverage_mktcap_k": coverage_mktcap_k(universe, {s["ticker"] for s in stocks})`（stocks 全部算，含資料不足）。

## 4. `screener/candidate_pool.py`（季 EPS 年增改用 `growth.yoy_eps`）
- `canslim_fundamental`：最新列 `g = growth.yoy_eps(eps, eps_base_q)`（NaN 當 None）。
  - `eps_yoy_q`＝`g.value`（None → NaN）；新增欄 `eps_yoy_label`＝`g.label`；`eps_yoy_low_base`＝`g.low_base`；`eps_yoy_base` 照舊。
  - `c_eps_yoy`＝`g.label == "pct" and g.value > EPS_YOY_MIN`。
  - `EPS_LOW_BASE_ABS` 若別處沒 import 就刪（改由 growth 決定）。
- `build_candidate_pool` 的 rec 加 `"eps_yoy_label": str`。
- `_invalidation` 的「季 EPS YoY 轉負」：已轉負 ⇔ `label == "turn_loss"` 或（`label == "pct"` 且 value < 0）或（`label == "flat"` 且 `eps_yoy_base` > 0）——跟舊行為一致（舊：去年 > 0 且今年較低）。rec 沒有 `eps_yoy_label`（舊 JSON）→ 退回舊判斷 `(eps_yoy_q or 0) < 0`。
- `_support_oppose` 文字不動（改名在 P4／§15）；`eps_low_base` 來源改成 growth 的（多了「去年不到今年 1/5」）。

## 5. 驗收（Opus）
- `tests/test_val2_p3b.py` 全過；全套不退步（基準：val2 `26a8819` 全套數字見 sol 回報）。
- 乾跑：`build_classification.py` 寫到 `_dryrun/stock_class.json`（不寫 data/derived）：金融股（industry_group financial）資料不足檔數＝0（或逐檔列原因）；新舊快照類型交叉表；`subtags_recomputed` True 的檔列出；`coverage_mktcap_k` 值。
- 推薦卡：新舊 `build_candidate_pool` 同一 asof 進池名單差異逐檔列（預期只有 low_base 標記差異，進池名單不變）。
