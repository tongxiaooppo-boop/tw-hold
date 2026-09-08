# tw-hold v1 收尾交接 — 給下一輪

> **自足執行指令。你在全新對話、沒有上下文。** 讀完這份就能動工。
> 環境：Windows，`d:\g\claude\` 底下有 `tw-swing\`、`tw-hold\`、`books\`。
> ⚠️ **bash 工具的 cwd 是 `d:\g\claude`**，跑腳本要 `cd /d/g/claude/tw-hold` 或 `tw-swing`。
> ⚠️ 本機 console 是 cp950——**print 不要用 emoji**（`⚠️` 會 UnicodeEncodeError）；跑 python 用 `PYTHONIOENCODING=utf-8`。
>
> **建立**：2026-09-08 ｜ **前面做完**：M0b + M1 + M2 + M3 + M4（一天內全做完）

---

## 0. 一分鐘現況

**v1 五個里程碑（M0b/M1/M2/M3/M4）主體都完成了。** app 跑在
**https://tw-hold-jchm8ooiwp7ewqisfzmpoo.streamlit.app/**（Streamlit Community Cloud，
`tongxiaooppo-boop/tw-hold` main，main file `app/streamlit_app.py`）。

- **價值清單**：15 檔，季表凍結（換股日 3/31、5/15、8/14、11/14）+ 候補變動 + 產業 ≤ 40% cap。
  每檔有便宜門檻 / 估值上緣 / 空間% / verdict（推薦 / 觀望 / 資料不足）/ 買入區間。
- **定存清單**：15 檔。§7.1 兩道新硬門檻（填息率 ≥ 60%、近 3 年含息報酬 ≥ 0）+ §7.3 殖利率法買價。
  🔴 **見 §1「金控股全被踢出」——這是定存線目前最大的洞。**
- **長波段候選池**：19 檔。CANSLIM + Minervini 8/8 全狀態，無 verdict / 無總分 / 無排名，
  支持/反對並列 + §5.3 風控（停損位 / 可買上限）+ 失效條件檢查表。
- **個股查詢**：輸入代號 → 7 類 plotly 圖（K線 / 季EPS / 三率 / 現金流 / 股利 / 本益比河流圖 / F-Score 9 分項）。
- **警語**：每個分頁頂部 + 底部都有；長波段另加「無回測支撐」。

**commit 位置**：tw-hold `main` @ `d955267`、tw-swing `master` @ `1c0155c`。**兩 repo clean + push。**
tests：tw-hold 全套 **43 passed**。個股查詢分頁 Cloud crash 已修（見 §5b，真因是 `import charts` 撞到 repo 根的空套件）。

**進度細節**（權威）：記憶 `tw-hold-m1-progress` / `tw-hold-m2-progress` / `tw-hold-m3-progress` / `tw-hold-m4-progress`。
PLAN §M1–§M4 已打勾。**PRD 凍結，不 re-litigate。**

---

## 1. 🔴 金控股全被踢出定存清單（這一輪第一件事）

**現況**：華南金 2880、富邦金 2881、國泰金 2882、玉山金 2884、兆豐金 2886、
中信金 2891、第一金 2892、合庫金 5880——**8 家全部**被 `reject_reason = "eps 近4季非全正"` 刷掉。
（`cd /d/g/claude/tw-hold && PYTHONIOENCODING=utf-8 python -c "import build_factors as bf; d=bf.screen_all()['deposit']; print(d[d.ticker.isin(['2881','2882','2891','2886'])][['ticker','name','passes','reject_reason']])"` 可複現。）

**根因**：FinMind `TaiwanStockFinancialStatements` 對金融業用不同 XBRL type，
`EPS` / `IncomeAfterTaxes` 這些 key 對金控是 **NaN**（金融業損益表科目不一樣）。
所以 tw-swing `data/fundamentals/income.parquet` 裡金控的 `eps` / `net_income` 是空的
→ `screen_deposit` 的「近 4 季 EPS 每季為正」門檻擋掉。

**為什麼該修**：定存線的定位就是「接手美元收益部位」，金控/官股銀行是台股存股的核心標的。
現在定存 15 檔一家金融都沒有。實驗 B 早就標了「定存線是壞的」，這是其中一半原因
（另一半 universe 已在 M0b 修好）。

**怎麼修**（在 tw-swing）：
1. **先調查**：`cd /d/g/claude/tw-swing`，用 FinMind 抓 `2881` 的
   `TaiwanStockFinancialStatements`，看它的 `type` 欄有哪些值、EPS / 稅後淨利
   對金控是掛在哪個 type 下（可能是 `EPS`（元）本身有值但被別的 type 洗掉，或
   要用 `BasicEarningsPerShare` 之類）。FinMind token 在 tw-swing `.env`。
2. `scripts/fetch_fundamentals.py` 第 66 行 `INCOME_FIELDS`：加金融業對映的 key。
   金融業的 `revenue`（淨收益）/ `net_income` / `eps` 對映清楚後補進去。
3. 重抓金融股 income：`python scripts/fetch_fundamentals.py`（**只補金融股，別全量**——
   FinMind 600/hr、rate ≤ 450、不 seed；避開週六 `fundamentals.yml` 排程 UTC 六 02:00）。
4. `git add data/fundamentals/income.parquet && git commit && git push`。
5. `gh workflow run publish_bundle.yml --repo tongxiaooppo-boop/tw-swing`（U1b 會把新的
   income 重傳 + 更新 `_meta.json`）。等綠。
6. 回 tw-hold：`gh workflow run rebuild.yml --repo tongxiaooppo-boop/tw-hold`，
   確認定存清單這次有金控。
7. ⚠️ 也順手看一下 tw-swing 的 pool1 / 價值因子有沒有因為金融股 income 變動而移位
   （不該——金融股本來就不在那些 pool，但確認一下）。

⚠️ **紅線**：不改 tw-swing `daily.yml` / `rules.yaml` / portfolios / pipeline / 回測。
`fetch_fundamentals.py` / `fundamentals.yml` / `publish_bundle.yml` 可動。

---

## 2. 自動排程開關（使用者要決定，但你把選項備好）

**現況**：`rebuild.yml`（tw-hold）已接線可跑，但**排程刻意沒開**（PLAN 原則「先手動跑幾天」）。
`heartbeat.yml` 每週一 UTC 01:00 醒來檢查 `data/derived/_meta.json.rebuilt_at` 新鮮度——
**再過幾天它就會一直告警**（因為 rebuild 沒自動跑）。

兩條路，`rebuild.yml` 開頭註解寫了：
- **(a) 建議**：tw-swing `publish_bundle.yml` 末尾加 `curl` 發 `repository_dispatch`
  `bundle-published` → tw-hold `rebuild.yml`。需要 tw-hold 產一顆 fine-grained PAT
  （`tongxiaooppo-boop/tw-hold` 的 `contents: write` 或 metadata + actions），
  設成 **tw-swing 的 secret `TWHOLD_DISPATCH_PAT`**。好處：只有真的有新 bundle 才重算。
- **(b)**：`rebuild.yml` 的 `on:` 加 `schedule: - cron: "30 7 * * 1-5"`
  （publish_bundle 06:00 UTC 之後）。壞處：bundle 沒更新的日子也空跑 + 產生只有
  `rebuilt_at` 變的 commit。

**先問使用者要 (a) 還是 (b)**，再動手。(a) 要使用者去 GitHub 產 PAT + 設 secret。

---

## 3. 產業逆風判定（PRD §6.5 / §7，PLAN 未打勾）

同產業近 N 個月動能中位數當代理，判斷某產業是不是集體走弱 → 清單明細標「產業逆風」旗標
（**只顯示，不進 verdict / 不剔除**——比照循環高峰旗標）。
資料：`prices_adj.parquet`（算個股動能）+ `universe.parquet` 的 `industry` 欄（分組）。
放在 `screener/pricing.py` 或新 `screener/industry.py`。價值 + 定存都掛。優先度中等。

---

## 4. 月營收歷史（要動 bundle）

**現況**：`app/charts.py` 的月營收圖是 `st.info` placeholder；M1 候選池的 `revenue_accel`
「加速」判定也略過了（只用 `revenue_yoy > 0`）。兩者同一個根因——bundle 的
`revenue.parquet` 只有**單月快照**（1975 列 = 每檔 1 筆）。

**修法**（tw-swing `scripts/build_u1b_bundle.py`）：把 `data/revenue/` 的逐月快照
（tw-swing `fundamentals.yml` 已在抓）疊成一張歷史表打進 bundle，或改用 TWSE 整批檔。
補完：
- `app/charts.py` 加 `monthly_revenue()` 圖（YoY / MoM 柱狀）
- `screener/candidate_pool.py` 的 `revenue_yoy()` → 加回 `revenue_accel`（本月 YoY > 上月 YoY）

---

## 5. UI 正式設計一輪（使用者說「等真的做 UI 那一輪」）

三清單卡片 + 長波段卡片目前「能用、資訊完整」但沒做設計——偏高偏空、視覺層次陽春。
使用者要的方向（2026-09-08 討論）：**大代號 + 股名、臉上只放幾個關鍵值、其餘收展開**。
這個已經做了骨架（`_card_list` / `_swing_page` in `app/streamlit_app.py`），
剩「正式設計」：間距、風險 badge 上色、支持/反對排版、可能把明細表移出 expander。
**動手前先問使用者要不要一起連個股頁的排版做。**

---

## 5b. 個股查詢分頁 Cloud crash（✅ 已修，留紀錄）

三次才修對：
- `ModuleNotFoundError`（`from app import charts`）→ `streamlit_app.py` 頂端把 repo 根 + `app/`
  塞進 `sys.path`、內部改 bare import。commit `b8b0712`。
- **真因**：加了 repo 根到 `sys.path` 後，`import charts` 撞到 **`tw-hold/charts/`**——
  M0.2 留下的一個空 `__init__.py` 套件（在 repo 根），不是 `app/charts.py` → `ch.kline`
  不存在 → `AttributeError`。→ 刪掉空 `charts/`、`app/charts.py` 改名 **`app/stockcharts.py`**。
  commit `d955267`。
- 附帶硬化（留著）：`requirements.txt` 釘死版本（`pandas==3.0.3 / pyarrow==24.0.0 /
  streamlit==1.60.0 / plotly==6.9.0`）；`_stock_page` 每張圖包 try/except（`_chart` helper，
  單張爆掉就地顯示 `type(e).__name__: e`、不整頁掛）。
- ⚠️ **教訓**：repo 根有 `charts/` `reference/` `screener/` `factors/` 這些頂層套件——
  app 內的模組**不要跟它們同名**。改依賴版本前一定本地 `pytest -q` + `streamlit run` + AppTest 過。

---

## 6. 其他小尾巴（低優先）

| 項 | 說明 |
| :-- | :-- |
| `per.parquet` 不自動更新 | valuation 分位帶 max_date 2026-08-28，會慢慢舊。tw-swing 用 TWSE `BWIBBU_ALL` 每日整批刷 PER/PBR/殖利率，併進 U1b |
| 個股頁法人買賣超圖 | bundle 有 `chips.parquet`，`app/bundle_data.py` 加 reader + `charts.py` 加圖 |
| `price_adjuster.py` 移植 | 本地進階模式、500 大以外個股的還原股價（雲端唯讀模式不需要）。PRD §M4 |
| 實驗 B 報告更新 | `research/backtest_rebalance.py` 用完整填息率重跑 → 更新 `docs/reports/expectations_20260907.md`（研究文件，非產品） |
| PRD §8/§9〈已定〉過時 | 寫於 opus 審核前，講 `tw-data` 公開 repo。現行以 §3.1.1 / §10.1 為準——README 已標，有空校準 |
| `div_years` 全 = 12 | 股利資料從 2015 起，連續年數上限 ~12。定存排序時該分項飽和。要更長要補抓更早股利 |

---

## 7. 入口點

| 要做 | 讀 |
| :-- | :-- |
| v1 全貌 / 里程碑 | `tw-hold/docs/PLAN.md`（§M1–§M4 已打勾） |
| 為什麼這樣設計 | `tw-hold/PRD.md`（§5 候選池、§6 價值、§7 定存、§10 失敗模式）**凍結** |
| M1/M2/M3/M4 進度細節 | 記憶 `tw-hold-m1-progress` … `tw-hold-m4-progress` |
| 四個回測實驗 | `tw-hold/docs/BACKTEST_HANDOFF.md` |
| tw-swing 現況 | `tw-swing/docs/STATUS.md`、記憶 `tw-hold-m0-progress`〈上游交付〉 |
| 產品碼 | `build_factors.py`（screen_all 主入口）、`build_lists.py`（季表 + 候補 + JSON）、`screener/{pricing,deposit_pricing,candidate_pool,gates,screen}.py`、`app/{streamlit_app,bundle_data,stockcharts}.py` |

⚠️ **開工前**：`cd /d/g/claude/tw-hold && git status`（應乾淨）+ `python -m pytest -q`（43 passed）。
tw-swing 開工前先 `cd /d/g/claude/tw-swing && python scripts/check_daily.py`（G-5 沒斷再動）。

---

## 8. 紅線（一直有效）

- 🔴 **不改 tw-swing `daily.yml` / `rules.yaml` / portfolios / pipeline / 回測**（G-5 的 60 交易日時鐘上）
- FinMind：token 600/hr、rate ≤ 450、**不 `Throttle.seed()`**（會死等 1 小時）、避開週六 `fundamentals.yml` 排程（UTC 六 02:00）
- 定存 5% 殖利率硬底線不能自己放水到 4%——候選太少要回報使用者
- tw-hold 是**公開 repo**：`positions.json` / token / `.env` 絕不進版控
- **PRD 凍結**：不改因子設計、不改估值公式、不改分軌。要改記 backlog、v2 再說
- 候選池措辭：「條件成立狀態」不叫「建議進場」；「候選池」不叫「推薦清單」；不給 verdict / 買價 / 排名
- tw-hold bundle PAT ~2026-12-07 到期（記憶 `tw-hold-bundle-pat-expiry`）——約 11-30 起提醒使用者換
