# tw-hold

`me`（`taiwan-stock-analyzer-v3`）的升級版。長波段/價值/定存推薦 + 個股查詢。
**資料層與 tw-swing 共用**（tw-swing 週抓財報、tw-hold 讀），domain 與 UI 是 tw-hold 自己的。
建議改名 `tw-hold`（跟 `tw-swing` 成對）。

- 產出：長波段（2–12 週+）/ 價值 / 定存 三種推薦清單
- 個股查詢：不打分，用數據展開常見圖表；不在市值前 500 大的即時補 FinMind
- 本地跑（暫訂 Streamlit）

計劃見 [PLAN.md](PLAN.md)。開發現況見 STATUS.md（尚未建立）。

## 目錄

| | |
| :--- | :--- |
| `data/` | 財報整併檔（版控）+ 快取 |
| `factors/` | 因子計算（F-Score、normalized PE、存股安全分…）——移植自 tw-swing `twswing.value` |
| `screener/` | 三清單的篩選邏輯 |
| `charts/` | plotly 圖表 |
| `app/` | Streamlit UI |
| `reference/` | 從 tw-swing / me 複製進來的參考程式碼（FinMind client、price_adjuster、指標） |
| `tests/` | |

## 跟其他專案的關係

- **tw-swing**：上游。tw-hold `import twswing.data.finmind` / `twswing.value.loader` / `twswing.data.fundamentals`（資料層），讀 `tw-swing/data/fundamentals/*.parquet`。domain 邏輯（factors/screen/screener/UI）是 tw-hold native。
- **me (v3)**：參考程式碼來源，不 import、不執行依賴。
