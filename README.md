# tw-hold

`me`（`taiwan-stock-analyzer-v3`）的升級版。長波段/價值/定存推薦 + 個股查詢。
**核心宇宙（前 500 大）資料上游 = tw-swing**：tw-swing 抓 FinMind 財報/日線/估值、
整併成 data bundle 發佈到 **tw-swing 私有 repo 的 Release（tag `data-latest`）**；
tw-hold 用 PAT 拉 bundle、每日重算三清單、做 domain 與 UI。
執行期對 `twswing` package 零依賴（共用碼複製，`loader.py` 是搬移）。

- 產出：長波段（2–12 週+，**主動擇時**）/ 價值 / 定存（**規則化因子指數、季換股**）三清單
- 每清單：買入建議價 或「不推薦」＋原因；每期揭露「新進/移除 + 移除原因」= 出場訊號
- 個股查詢：不打分，數據 + plotly 圖表；不在前 500 大的即時補 FinMind（僅本地）
- 佈署：Streamlit Community Cloud（個股即時補抓為本地進階模式）

規格見 [PRD.md](PRD.md)（凍結）｜執行 checklist 見 [docs/PLAN.md](docs/PLAN.md)｜進度 [docs/M0_HANDOFF.md](docs/M0_HANDOFF.md)｜介面草模 `scratchpad/tw-hold-mock.html`。

> ⚠️ **PRD §8/§9〈已定〉區塊部分過時**（寫於 opus 審核前）：提到的「`tw-data` 公開 repo 唯一抓取者 / 匿名零 token / tw-hold 私有」已被 §10.1 取代——**現行：tw-hold public、bundle 走 tw-swing 私有 Release + fine-grained PAT、不建 `tw-data`**。以 §3.1.1 / §10.1 / `docs/M0_HANDOFF.md` 為準。

## 跑

```bash
pip install -r requirements.txt
python build_factors.py          # 算因子 + 兩清單 → data/derived/（需先有 bundle 的財報四表；缺日線類則該欄留 NaN）
streamlit run app/streamlit_app.py
pytest -q
```

FinMind token（個股即時補抓，僅本地）：`.env` 放 `FINMIND_TOKEN=...`。
bundle PAT：`.env` 放 `TWSWING_BUNDLE_PAT=...`（雲端走 `st.secrets`）。

## 目錄

| | |
| :--- | :--- |
| `data/` | `upstream/` 拉下來的 bundle（**不版控**）、`derived/` 重算產出（**版控**）、`cache/` 個股即時查快取（不版控） |
| `factors/` | 因子計算（F-Score、normalized PE、存股安全分…）——移植自 tw-swing `twswing.value` |
| `screener/` | 三清單的篩選邏輯 |
| `charts/` | plotly 圖表 |
| `app/` | Streamlit UI |
| `reference/` | 從 tw-swing / me 複製進來的參考程式碼（FinMind client、price_adjuster、指標） |
| `tests/` | |

## 跟其他專案的關係

- **tw-swing**：上游資料源。發佈 bundle 到**自己私有 repo 的 Release**（tag `data-latest`；財報/日線/PER/月營收/universe），分 **U1a 週更 / U1b 日更**兩條管線（PRD §3.1.1）。tw-hold 用 PAT 拉，**不 import `twswing`、不讀 tw-swing 磁碟**。共用碼（regime/indicators/finmind client）複製進 `reference/`；`loader.py` 是**搬移**（tw-swing 端刪除）。
- **me (v3)**：參考程式碼來源，不 import、不執行依賴。
