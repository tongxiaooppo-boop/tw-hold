# tw-hold v1 收尾交接 — 給下一輪

> **自足執行指令。你在全新對話、沒有上下文。** 讀完這份就能動工。
> 環境：Windows，`d:\g\claude\` 底下有 `tw-swing\`、`tw-hold\`、`books\`。
> ⚠️ **bash 工具的 cwd 是 `d:\g\claude`**——跑腳本先 `cd /d/g/claude/tw-hold` 或 `tw-swing`。
> ⚠️ 本機 console 是 cp950——**print 不要用 emoji**；跑 python 一律 `PYTHONIOENCODING=utf-8`。
>
> **本版建立**：2026-09-08（同日第二份，取代舊版）

---

## 0. 一分鐘現況

app：**https://tw-hold-jchm8ooiwp7ewqisfzmpoo.streamlit.app/**（Streamlit Community Cloud，
`tongxiaooppo-boop/tw-hold` main，main file `app/streamlit_app.py`，push main 即自動重佈）。

| | commit | 測試 |
| :-- | :-- | :-- |
| tw-hold `main` | `8450be1` | `pytest -q` → **66 passed** |
| tw-swing `master` | `8030d87` | 782 passed |

兩 repo clean + push。

**2026-09-08 下半天續做**（UI 收尾後）：
- UI：清單代號可點跳個股查詢（`st.tabs`→`st.radio` 導覽 + `?code=` 連結）、股利圖分次配息
  描邊、原始季度數據改千元+千分號。
- **股票分割還原**：`reference/corporate_actions.py`（`SPLITS` 5904/0052/4747/6949 +
  `IGNORE_JUMPS`）+ `build_factors.detect_unhandled_splits()` build 時自動偵測。5904 verdict
  資料不足→觀望。見記憶 `tw-hold-split-adjustment-gap`。
- **④ 月營收歷史**：bundle `revenue.parquet` 改長表（tw-swing `build_revenue_history.py` +
  版控 `revenue_history.parquet`）→ 個股頁月營收圖 + 候選池 `revenue_accel`。
  ⚠️ **需 `publish_bundle.yml` 跑一次**（每日 06:00 UTC 或手動 dispatch）新 schema 才生效。
  見記憶 `tw-hold-revenue-history`。

- **價值 / 定存清單**：各 15 檔，季表凍結（換股日 3/31、5/15、8/14、11/14）+ 候補變動 + 產業 ≤ 40% cap。
- **長波段候選池**：19 檔，CANSLIM + Minervini 8/8 全狀態，無 verdict / 無排名，支持/反對 + §5.3 風控。
- **個股查詢**：代號 → 7 類 plotly 圖（K線 / 季EPS / 三率 / 現金流 / 股利 / 本益比河流圖 / F-Score 9 分項）。

**開工前**：
```
cd /d/g/claude/tw-hold && git status && PYTHONIOENCODING=utf-8 python -m pytest -q
cd /d/g/claude/tw-swing && PYTHONIOENCODING=utf-8 python scripts/check_daily.py   # G-5 沒斷再動 tw-swing
```

---

## 1. 這一輪（2026-09-08 下半天）做了什麼

### ① 金控金融軌 ✅
定存清單原本一家金融都沒有——實際卡**四道**門檻不是一個。完整經過見記憶
`tw-hold-financial-track-design`。commit：tw-swing `0f3ec55`、tw-hold `c58fbd5`。
結果：富邦 2881 / 國泰 2882 / 永豐金 2890 / 元大金 2885 等 **12 檔金融過硬門檻**；
官股行庫（華南/兆豐/第一/合庫/玉山/中信）多因 §7.1 填息率 < 60% **正確**排除。
凍結季表下，候補 `likely_in` 已顯示 2820/2850/2890，**11/14 換股日**才會進 holdings。
⚠️ 殘餘不確定：金控 2026 起 FinMind 淨利改 YTD 口徑，`_deaccum_ytd` 用「2026+ 且年內
單調不減」啟發式還原單季——富邦看起來 YTD、兆豐看起來單季。兩種情況門檻都過、排序約略。
真出問題查 FinMind 原始 `origin_name`。

### ② 自動排程 ✅（採 (a) repository_dispatch）
tw-swing `publish_bundle.yml`（平日 06:00 UTC）發佈成功 → POST `repository_dispatch`
`bundle-published` → tw-hold `rebuild.yml` 重算三清單。端到端驗過。
PAT：tw-swing secret **`TWHOLD_DISPATCH_PAT`**（fine-grained / tw-hold / Contents:write，
**~2027-09-08 到期**）。`rebuild.yml` 加「三張 `*_list.json` 沒實質變動就不 commit」。
commit：tw-swing `32351a9`、tw-hold `9731273`。

### ⑤ UI（版型 B + 深色）— 主體做完，**使用者評審中**
使用者選**版型 B 判斷卡**、固定深色主題。commit `757ffe9` → `1a11d9b`。已做：
- `_card_b_html` / `_swing_b_html`：整張卡純 HTML 注入（class + inline style + `<details>`，
  `unsafe_allow_html` 支援，AppTest 驗過）。左色條 = verdict 嚴重度、放大決策數字、
  買入區間長條、chip、明細收 `<details>`。
- `.streamlit/config.toml`：固定 `base=dark` + 松綠 accent 地基色。`_inject_css()` 對齊
  `--thc-*` 色票。
- **兩欄卡片**：整季卡片 render 進一個 CSS grid（`.thc-grid`，桌面 2 欄 / <900px 1 欄 /
  `align-items:stretch` 同列等高）。
- **手機**：`st.columns` 在 <640px 直向堆疊（修個股圖表擠壓）。
- **個股查詢**：`st.form` + 「查詢」鈕；`st.segmented_control` 區間快捷
  （3月 / 今年至資料日期 / 1年 / 2年 / 全部，預設 1年）；均線依區間切
  （短 MA5/20/60、長 MA20/60/240，完整歷史算再裁 x 軸）；河流圖三段配色
  （P10–P30 綠 / P30–P70 灰 / P70–P90 琥珀）。
- **篩選 verdict**：`st.multiselect` → `st.pills`（multi）——多選下拉全選時會顯示
  「無選項」讓人困惑；pills 全亮＝不過濾、點暗某類就藏。分組按類別（推薦/觀望/資料不足），
  不按完整字串（定存 verdict 內嵌數字會炸成 12 個重疊選項）。
- **F-Score 9 分項**：`✓/✗` → `✅ 成立 / ⬜ 未達`。
- plotly 圖例移到**圖下方**（放上方跟標題重疊）。

測試：`tests/test_app_smoke.py`（AppTest 煙霧 + `_card_b_html` / `_verdict_cat` 單元）、
`tests/test_charts.py` 擴充（kline 帶區間、pe_river 帶區間）。

---

## 2. 待辦（優先序）

### A. ⑤ UI 收尾 🔵 —— **先把使用者評審剩下的意見收完**
使用者上一輪還在逐分頁看、邊看邊列意見（「先不改」＝先收集）。已知**還沒處理**：

| 項 | 說明 |
| :-- | :-- |
| ✅ 代號可點跳個股查詢 | `st.tabs` → `st.radio` session_state 導覽；代號變 `?code=XXXX` 連結，`_route()` 讀 query param 預填+切分頁+清 param。commit `84cd0ad`。 |
| ✅ 股利圖分次配息描邊 | 同年季配/半年配疊柱各段加淺色描邊、按 pay_date 排序。commit `a68b9e3`。 |
| 卡片右側留白 | 使用者說「先不改」，兩欄 grid 已解決大半。之後若還要處理 → 卡片給 `max-width` 讀起來像文件。 |
| 長波段卡「都是字」 | 已改成 B 語言（`_swing_b_html`），但使用者可能還想更緊湊 / 加視覺元素。等回饋。 |

⚠️ 改 app 一定本地 `PYTHONIOENCODING=utf-8 python -m pytest -q` + AppTest 過再 push
（`streamlit run` 本機無瀏覽器截不了圖，靠使用者看 Cloud）。

### ✅ A2. 分割待人工核 —— 2026-09-08 核完
使用者提供官方拆分日+比例。`SPLITS`：5904 / 0052 / 4747 / 6949。2327 / 4763 / 6781
data_pack 已還原。`IGNORE_JUMPS`：2380 / 4950 / 7772（疑減資缺比例）/ 5314（2026 事件待查）。
6949 日期在資料尾端、bundle 完整後回頭校。見記憶 `tw-hold-split-adjustment-gap`。

### ✅ B. ④ 月營收歷史 —— 2026-09-08 完成
見上方「續做」+ 記憶 `tw-hold-revenue-history`。**下一輪確認 `publish_bundle` 跑過、
tw-hold 個股頁月營收圖有出來**（舊 bundle 期間會顯示「只有 N 個月」）。

### C. ⑥ 小尾巴 🟢 —— **下一個做**

| 項 | 說明 |
| :-- | :-- |
| 實驗 B 報告過時 | **金融軌這輪改了 `cut5y` 語意 + 定存硬門檻通過數 55 → ~92**，`docs/reports/expectations_20260907.md` 的定存數字已不準。用完整填息率重跑 `research/backtest_rebalance.py`（研究文件，非產品）。 |
| `per.parquet` 不自動更新 | valuation 分位帶會慢慢舊。tw-swing 用 TWSE `BWIBBU_ALL` 每日整批刷 PER/PBR/殖利率、併進 U1b。 |
| 個股頁法人買賣超圖 | bundle 有 `chips.parquet`，`app/bundle_data.py` 加 reader + `stockcharts.py` 加圖。 |
| `price_adjuster.py` 移植 | 本地進階模式、500 大以外個股的還原股價（雲端唯讀不需要）。PRD §M4。 |
| PRD §8/§9〈已定〉過時 | 寫於 opus 審核前，講舊的 `tw-data` 公開 repo。現以 §3.1.1 / §10.1 為準，README 已標。 |
| `div_years` 全 = 12 | 股利資料從 2015 起，連續年數上限 ~12，定存排序時該分項飽和。要更長要補抓更早股利。 |

### D. ③ 產業逆風判定 🟢 —— **最後做**（PRD §6.5 / §7，PLAN 未打勾）
同產業近 N 個月動能中位數當代理，判斷某產業是不是集體走弱 → 清單明細標「產業逆風」旗標
（**只顯示，不進 verdict / 不剔除**——比照循環高峰旗標）。
資料：`prices_adj.parquet`（算動能）+ `universe.parquet` 的 `industry`（分組）。
放 `screener/pricing.py` 或新 `screener/industry.py`，價值 + 定存都掛。

### E. 未來項（使用者提過、還沒定案）
- **個股頁「三軌門檻檢視」**：把定存/價值/長波段的硬門檻套在單一檔上、只顯示 ✓/✗
  （描述不是建議）。PRD §4.1 明寫個股頁「不打分、不給買賣建議」——做之前**先定調措辭**
  + 記 PRD backlog。**2026-09-08 使用者再確認：先不做、列日後拓展**（階段一純讀清單 JSON
  顯示現有狀態即可，但仍要另開工，使用者選擇不節外生枝）。
- **tw-swing 短線訊號整合**（使用者 2026-09-08 定調）：**tw-swing 目前產出的訊號全部是短線**
  ——未來 tw-swing 每日短線清單打進 bundle → tw-hold 加一個**「短線」唯讀分頁**。
  於是 tw-hold 分頁會是：短線（tw-swing 來）/ 長波段 / 價值 / 定存 / 個股查詢——
  「短線」與 tw-hold 自有的「長波段候選池」是**不同軌**，別混。
  **合併 repo 不做**（分開是有原因的，tw-swing 在 G-5 時鐘上）；只走資料層，不碰 tw-swing pipeline。

---

## 3. 持續注意事項

- 🔴 **兩顆 PAT 到期**（記憶 `tw-hold-bundle-pat-expiry`）：
  ① `tw-hold-bundle-read`（拉 bundle）~2026-12-07 → **2026-11-30 起**提醒使用者換；
  ② `TWHOLD_DISPATCH_PAT`（觸發 rebuild）~2027-09-08 → 2027-08-25 起提醒。
- **11/14 換股日**：金融（新產 2850 / 華票 2820 / 永豐金 2890…）會實際進定存 holdings，
  換掉台積電 / 宏全 / 中興電等低殖利率股。屆時確認換股理由表正常。
- 金控 2026 淨利 YTD/單季啟發式（見 §1 ①）。

---

## 4. 入口點

| 要做 | 讀 |
| :-- | :-- |
| v1 全貌 / 里程碑 | `tw-hold/docs/PLAN.md`（§M1–§M4 已打勾） |
| 為什麼這樣設計 | `tw-hold/PRD.md`（§5 候選池、§6 價值、§7 定存、§10 失敗模式）**凍結** |
| 金融軌完整經過 | 記憶 `tw-hold-financial-track-design` |
| M1–M4 進度細節 | 記憶 `tw-hold-m1-progress` … `tw-hold-m4-progress` |
| 四個回測實驗 | `tw-hold/docs/BACKTEST_HANDOFF.md`、記憶 `tw-hold-backtest-experiments-outcome` |
| tw-swing 現況 | `tw-swing/docs/STATUS.md` |
| 產品碼 | `build_factors.py`（`screen_all` 主入口）、`build_lists.py`（季表 + 候補 + JSON）、`screener/{pricing,deposit_pricing,candidate_pool,gates,screen}.py`、`factors/factors.py`、`reference/loader.py`、`app/{streamlit_app,bundle_data,stockcharts}.py` |
| app UI | `app/streamlit_app.py`：`_inject_css`（`_CSS` 色票 + `.thc-*` 卡片 CSS）、`_card_list` → `_card_b_html`、`_swing_page` → `_swing_b_html`、`_stock_page`。深色地基在 `.streamlit/config.toml`。 |

### 個股查詢 Cloud crash（✅ 早修，教訓留著）
repo 根有 `charts/` `reference/` `screener/` `factors/` 頂層套件——**app 內模組不要跟它們同名**
（曾 `import charts` 撞到空套件 → `AttributeError`）。`requirements.txt` **釘死版本**
（`pandas==3.0.3 / pyarrow==24.0.0 / streamlit==1.60.0 / plotly==6.9.0`），改版本前一定
本地 pytest + streamlit run + AppTest 過。`_stock_page` 每張圖包 `_chart` try/except。

---

## 5. 紅線（一直有效）

- 🔴 **不改 tw-swing `daily.yml` / `rules.yaml` / portfolios / pipeline / 回測**（G-5 的 60 交易日時鐘上）。
  可動：`scripts/fetch_fundamentals.py`、`scripts/build_u1b_bundle.py`、`fundamentals.yml`、`publish_bundle.yml`。
- FinMind：token 600/hr、rate ≤ 450、**不 `Throttle.seed()`**、避開週六 `fundamentals.yml`（UTC 六 02:00）。
  補特定股用 `python scripts/fetch_fundamentals.py --tickers <純代號逗號串> --force --rate 450`。
- 定存 5% 殖利率硬底線不能自己放水到 4%——候選太少要回報使用者。
- tw-hold 是**公開 repo**：`positions.json` / token / `.env` 絕不進版控。
- **PRD 凍結**：不改因子設計 / 估值公式 / 分軌。要改記 backlog、v2 再說。
  （這輪 `cut5y` 語意修正是「修因子符合 PRD『假存股』原意」，使用者已裁決，屬例外。）
- 候選池措辭：「條件成立狀態」不叫「建議進場」；「候選池」不叫「推薦清單」；不給 verdict / 買價 / 排名。
