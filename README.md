# me2

`me`（`taiwan-stock-analyzer-v3`）的升級版。**完全獨立的專案**，與 tw-swing 無關。

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

- **tw-swing**：只是「可以參考的程式碼」，**零 runtime 依賴**。tw-swing 改東西不會弄壞 me2。
- **me (v3)**：參考程式碼來源，不 import、不執行依賴。
