# tw-hold（app 內顯示為「股市雷達」）

> 📘 [部署／使用說明書](guide.html)

`me`（`taiwan-stock-analyzer-v3`）的升級版。**v1 已上線**（2026-09-08 起）：
長波段候選池/價值/定存三清單 + 個股查詢，之後陸續加了短線清單（渲染 tw-swing 的
分享級輸出）、主動式 ETF PCF 認養旗標、總經導航（國際指數/VIX/台指期/Put-Call
Ratio）、多軌體檢（三清單通過條件檢核表）等分頁——目前 app 上的分頁是
「總經導航／短線／長波段／價值／定存／個股查詢／多軌體檢／主動式 ETF」
（見 `app/streamlit_app.py` 的 `NAV`）。
**核心宇宙（前 500 大）資料上游 = tw-swing**：tw-swing 抓 FinMind 財報/日線/估值、
整併成 data bundle 發佈到 **tw-swing 私有 repo 的 Release（tag `data-latest`）**；
tw-hold 用 PAT 拉 bundle、每日重算三清單、做 domain 與 UI。
執行期對 `twswing` package 零依賴（共用碼複製，`loader.py` 是搬移）。

- 產出：長波段候選池（**狀態型、不給 verdict、買賣由人決定**）/ 價值 / 定存
  （**規則化因子指數、季換股**）三清單
- 價值/定存：買入建議價 或「不推薦」＋原因；每期揭露「新進/移除 + 移除原因」= 出場訊號
- 個股查詢：不打分，數據 + plotly 圖表；不在前 500 大的即時補 FinMind（僅本地）
- 佈署：Streamlit Community Cloud（個股即時補抓為本地進階模式）。公開連結：
  https://tw-hold-jchm8ooiwp7ewqisfzmpoo.streamlit.app/

## 資料來源與授權

- 價量、籌碼、公司行為等原始資料來自 **臺灣證券交易所（TWSE）** 與 **財團法人中華民國證券櫃檯買賣中心（TPEx）** 的公開資訊；
  其中以 OpenAPI（`openapi.twse.com.tw` 等，政府資料開放授權條款－第 1 版）取得者，提供機關為各該機構，依該條款顯名標示。
- 兩機構網站另有使用條款（含禁止自動化程式下載、重製與散布網站內容，但已授權政府資料開放平臺者不在此限）。
  為此：**本 repo 的程式公開，自建上游收集到的資料不公開散布**（存放於私有 repo 的 Release），僅供個人研究使用。
- 本 repo 內建檔案的來源（顯名）：

  | 目錄 | 內容 | 來源 |
  | :-- | :-- | :-- |
  | `data/derived/` | 三清單、短線掃描、模擬單等 | **本專案自行計算的衍生結果**；輸入為 tw-swing bundle（FinMind、證交所、櫃買中心資料）與 `data/pcf/` |
  | `data/pcf/` | 主動式 ETF 每日申購買回清單（PCF）快照 | 統一投信（ezmoney.com.tw）、群益投信（capitalfund.com.tw）、復華投信（fhtrust.com.tw）官方網站，每日一次 |
  | `data/reference/global_macro*` | 國際指數、美股、匯率等收盤 | Yahoo Finance（yfinance），每日一次 |
  | `data/reference/tx_futures*`、`foreign_futures*` | 台指期收盤、外資台指期未平倉 | 臺灣期貨交易所 OpenAPI（`openapi.taifex.com.tw`，提供機關：金融監督管理委員會證券期貨局，政府資料開放授權條款－第 1 版）；外資未平倉部分另取自期交所網站下載頁 |
  | `data/reference/inst_flow*` | 三大法人買賣超金額 | 臺灣證券交易所（BFI82U） |
  | `data/reference/index_0050*`、`index_006201*` | 0050、006201 收盤序列 | 0050 取自 tw-swing bundle；006201 取自 FinMind |

- 本專案僅供個人研究與學習，**不構成投資建議**；資料可能有誤、延遲或缺漏，使用者自行負責。
- **授權**：本 repo 的程式碼以 [MIT 授權](LICENSE) 釋出（軟體按現狀提供、不附任何保證）。程式抓取資料的來源網站另有各自的使用條款（見上），**資料的取得與使用須由執行者自行遵守**；本 repo 不提供也不散布這些原始資料。
- 任何權利人認為本專案有不當之處，請來信或開 issue，將立即下架處理。

規格見 [PRD.md](PRD.md)（v1 範圍凍結，見 `docs/PLAN.md` 凍結條件）｜執行 checklist 見 [docs/PLAN.md](docs/PLAN.md)｜
**最新審核/交接 [docs/REVIEW_RESPONSE_2026-09-22.md](docs/REVIEW_RESPONSE_2026-09-22.md)**
（資料管線備援/自癒機制：push 靜默失敗 bug、PCF 假訊號雙層防守、國際總經絕對新鮮度偵測、
手動重整按鈕節流，對應 `docs/REVIEW_REQUEST_2026-09-22.md`）｜
AI 解說層設計 [docs/AI_LAYER.md](docs/AI_LAYER.md)（未實作）｜介面草模 `scratchpad/tw-hold-mock.html`。

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
| `app/` | Streamlit UI（`streamlit_app.py` 主程式、`stockcharts.py` plotly 圖表——沒有獨立 `charts/` 目錄，圖表函式就放在 `app/` 底下） |
| `reference/` | 從 tw-swing / me 複製進來的參考程式碼（FinMind client、price_adjuster、指標） |
| `tests/` | |

## 跟其他專案的關係

- **tw-swing**：上游資料源。發佈 bundle 到**自己私有 repo 的 Release**（tag `data-latest`；財報/日線/PER/月營收/universe），分 **U1a 週更 / U1b 日更**兩條管線（PRD §3.1.1）。tw-hold 用 PAT 拉，**不 import `twswing`、不讀 tw-swing 磁碟**。共用碼（regime/indicators/finmind client）複製進 `reference/`；`loader.py` 是**搬移**（tw-swing 端刪除）。
- **me (v3)**：參考程式碼來源，不 import、不執行依賴。
