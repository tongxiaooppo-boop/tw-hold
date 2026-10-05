# 上游（tw-stock-scanner）實際做法稽核 ＋ 自建上游涵蓋表

> 2026-10-05。目的：自建上游（`PLAN_OWN_UPSTREAM.md`）必須**涵蓋上游的所有做法**，並檢討我們自己抓的部分資料。
> 依據：上游原始碼 `books/claude/tw-stock-scanner-main/`（updater.py、fetch_daily_official.py、fetch_institutional.py、fetch_margin.py、fetch_tdcc.py、fetch_fi_holding.py、download_all_tw_stocks.py、macro.py）
> ＋ workflow 副本 `tw-swing/docs/reference/upstream_datapack_workflow.yml` ＋ 今天對官方端點與 tw-swing 母表（asof 2026-10-02）的實測。
> 標記：✅＝今天實測／讀碼確認；🔶＝推論、未驗證；❓＝讀不出來。

---

## 0. 先更正我之前說錯／講太快的三件事

1. **「用 yfinance 當第二個裁判」不成立（循環論證）。** data_pack 的還原價**本來就是 yfinance `auto_adjust=True` 抓的**（updater.py:107-110、download_all_tw_stocks.py）。拿自建結果對 data_pack 再對 Yahoo，兩個基準同源，不是獨立驗證。
   → 真正獨立的基準是**官方除權息參考價**（TWSE `TWT49U`、TPEx `exDailyQ`）。yfinance 只能當「上游怎麼做」的參照，不是裁判。
2. **我曾猜「上游每天只重抓最近 7 天，舊歷史不會重新還原」，之後一度說被實測推翻——那個「推翻」是錯的。** 當時只量「除息前一天」，剛好在 7 天窗內。改量「除息前 25 個交易日 vs 前 1 天」後，216 個乾淨事件中 212 個（98%）有等於官方因子的階梯（**還原接縫**），位置在 ex 前 7–11 日曆日。**假設成立**；詳見 `tw-swing/docs/analysis/tw-stock-scanner-1005-analysis.md` §2。上游唯一的修復是手動重跑 `download_all_tw_stocks.py`（約 2026-06-01/02 做過一次，之前的事件已無接縫）。
3. 我說「上櫃日線一天沒抓就補不回來」——對 openapi 版成立，但 `www/zh-tw/afterTrading/dailyQuotes` 可帶日期回補到 2015（見 pitfalls §G）。上游用的正是**只回最新日的 openapi 版**（fetch_daily_official.py:75），這是上游的限制，不是官方的限制。

---

## 1. 上游做法清單 × 自建涵蓋狀態

### 1.1 價格

| # | 上游做法（出處） | 自建計畫怎麼涵蓋 | 狀態 |
| :-- | :-- | :-- | :-- |
| P1 | 歷史＝yfinance `auto_adjust=True`（OHLC 全還原、Volume）2015-01-01 起，`.TW`/`.TWO`（download_all:START_DATE、updater:107） | 自建：官方原始價（帶日期回補到 2015）＋官方除權息參考價自算還原。**口徑差異**：Yahoo 的還原是「股利／前收」比例，官方參考價因子也是「參考價／前收」，實測兩者在 95% 事件差 <0.2%（§2-A） | P2 |
| P2 | 每日增量：官方當天**未還原**收盤 append（fetch_daily_official），隔天 yfinance 重抓最近 7 天覆寫（updater.LOOKBACK=7）。程式註解自承「除權息日落差，屬短暫近似」 | 自建不會有這個「未還原接在還原後」的過渡期：每天原始價進來就用當時已知的因子重算整段（見 §3 設計） | P2 |
| P3 | 歷史列去重 `keep="last"`、`Close>0` 過濾（updater:116、131） | 需對齊：我們過濾 `close<=0`；停牌日是否補列？ | P1 對帳時逐欄比 |
| P4 | 單檔增量：最後日 ≥ 預期交易日就 SKIP（updater:91） | 自建以「缺哪天補哪天」取代，輸入是日期而非檔 | P1 |
| P5 | 宇宙＝**4 碼純數字**代號（fetch_daily_official:58、fetch_margin:175、save_by_ticker:215），來源 ISIN 上市清單＋TPEx 清單（download_all） | 官方 MI_INDEX 含 ETF／主動 ETF（`00400A`）等 1380 列；必須用同一條規則濾，否則檔數對不上 | P1 驗收 |
| P6 | 大盤 `^TWII`：官方 `MI_5MINS_HIST` 追加 OHLC＋前日差>15% 拒寫＋`clean_benchmark()` 清 <5000 或跳 40% 的列（fetch_daily_official:94-147）。**歷史上出過「0.62 之亂」（把漲跌%當收盤）** | 我們現行用 0050 代理大盤（`index_0050`），不用 `^TWII`。若自建要提供，須搬防呆 | 暫不需（確認 tw-hold 沒用 benchmark_TWII） |
| P7 | 分割／面額變更**沒處理**（workflow 檔頭「缺口」） | 已有 `reference/corporate_actions.py`＋`resolve_splits.py`；自建 P2 要把 TWT49U 的「權」「減資」事件納入 | P2 |
| P8 | 健檢：價格檔 <1500 中止上傳（workflow）；保底＝先下載現有包再增量，過檢才 `--clobber` | 自建要有等價閘門（檔數≥98% 上游、日期斷言） | P1/P3 |
| P9 | 三段 cron（15:10／17:00／22:30）＋`concurrency` | 影子收集：16:30／18:30 兩班，另「每次補近 N 天缺的日子」 | P1 |

### 1.2 籌碼

| # | 上游做法 | 自建涵蓋 | 狀態 |
| :-- | :-- | :-- | :-- |
| C1 | 上市法人 TWSE `T86` `selectType=ALL`，欄位按**名稱**映射（fetch_institutional:84-99）；數值清洗 `---`→0 | ✅ 端點可帶日期到 2015。2015～至少 2017-12 只有 16 欄（欄名「外資買賣超股數」，不拆外資自營商）、之後 19 欄 → 欄名映射比寫死 index 安全，沿用 | P1 |
| C2 | 上櫃法人：**舊版 `3itrade_hedge_result.php`**（d=民國斜線）取 24 欄表，index 4/13/16/19/23（:126-169）。**只取外資「不含自營」(idx4)，沒取外資自營商、外資合計** | 新 `insti/dailyTrade` 端點 **2018-03 起在 `tables[0]`（24 欄）、2018-01 以前在 `tables[1]`（16 欄，≥2017-06 實測有資料）**——先前寫「2018 前回空」是只看 `tables[0]` 的誤判（Opus 複查更正）。舊 `.php` 端點未再測。**✅ 2026-10-05 口徑結案**：tw-swing 母表 `inst.parquet` 的 `foreign_net` 在上市（T86 欄 4）與上櫃（舊 .php idx 4）**兩邊同為「外資及陸資不含外資自營商」**；`fi_prop_net`（外資自營商）只有上市有、上櫃為 NaN。`dealer_net` 上櫃也是 NaN（上游沒存）。自建 `selfhost_chips.py` 對齊同一口徑，並多存上櫃的 `dealer_net`（合計欄 idx 22）與 `total_net` | P1 前先測舊端點 |
| C3 | 缺口感知增量：**以 2330 的 `_inst.csv` 最後日為基準**，從 +1 天抓、最多回補 45 天（:237-261）。 | 🔶 **這是上游上櫃缺日的可能原因**：2330 是上市股，基準永遠是上市的進度；上櫃某天抓失敗，只要上市那天成功，基準前進，上櫃缺口永遠不會被補。與我們看到上游 `.TWO` 融資券缺 09-04、09-15～17（交接單 §1.1）相符，**未驗證**。自建必須**上市、上櫃各自記進度** | P1 設計要求 |
| C4 | 外資持股比例 `MI_QFIIS`（fetch_fi_holding） | 我們有用嗎？bundle 沒帶 fi_holding。❓ 需確認 tw-swing 是否消費 | 待確認 |
| C5 | 集保股權分散表 `getOD.ashx?id=1-5`，**只回最新一週**，歷史靠 FinMind（fetch_tdcc.py 檔頭） | tw-swing 已有 TDCC 週快照（09-19 起），與上游同樣「只能往後累積」 | 已涵蓋（自家） |

### 1.3 融資券

| # | 上游做法 | 自建涵蓋 | 狀態 |
| :-- | :-- | :-- | :-- |
| M1 | 上市 `MI_MARGN` `selectType=ALL`，**取欄位數==16 的那張表**而不是 `tables[1]`（fetch_margin:98-102） | ✅ 我實測 `tables[1]` 可行，但上游的「用欄數辨識」更耐改版，採用 | P1 |
| M2 | 上櫃：舊 `margin_bal_result.php`，20 欄表，index 映射（:132-141） | ✅ 新 `margin/balance` 端點到 2015 有資料、20 欄同欄名。欄位序要與舊表逐欄對 | P1 |
| M3 | 單位：張 | 上市 `MI_MARGN` 單位待對照（pitfalls 未驗） | P1 |
| M4 | 同 C3：以 2330 的 `_margin.csv` 為進度基準 | 同 C3 風險 | P1 |
| M5 | 「大盤融資維持率」彙整 `macro.build_market_margin_series`（`data/_market_margin.csv`，用個股融資餘額×收盤價×MA 推估成本，macro.py:49-79） | tw-hold 沒用（總經導航用的是 TAIFEX/BFI82U） | 不需要，列為「上游多做的」 |

### 1.4 資料包裡其他東西（上游多做、我們目前不消費）
news／research_articles／decision_journal／brief_mentions／conf_notes／groups／revenue_trend／fundamentals（FinMind JSON）。**bundle 只帶 `prices_adj`、`prices_raw_close`、`revenue`、`index_0050`、`chips`、`margin`**（build_u1b_bundle.py）。自建上游的範圍＝這六項裡的「官方可得」部分（價、法人、融資券）；財報／營收／估值已自抓、不在此計畫內。

---

## 2. 今天的實測證據

### A. 資料包還原價 vs 官方除權息參考價 ✅（⚠️ 2026-10-05 更正）
- **只量「除息前一天」**：資料包收盤與官方因子吻合（519 件單一事件，中位數差 0.0000，95% <0.2%）——**這個窗口恰好在上游 7 天重抓範圍內，只證明窗內是對的**。
- **量「除息前 25 個交易日 vs 前 1 天」**（用 `adj/raw` 比值，500 檔、單一事件 216 件）：**212 件（98%）有等於官方因子的階梯 = 還原接縫**；2025 年舊事件已修好（0/22、1/40），2026-06 之後的全有接縫。詳見分析報告 §2。
- **結論**：(1) 官方參考價因子與資料包「窗內」一致，P2 用它自算還原的方向仍正確；(2) 但 **data_pack 在近期事件 ex 前 ~8 天以上的列是錯的（舊基準）**，P3 對帳不能當真值，須把窗外列另列為已知上游缺陷；(3) 離群檔（6225、8112、3149、7610、9955…）仍是減資／增資／分割／同日多事件案例，待逐檔看。

### B. 官方端點 ✅（詳見 `tw-swing/docs/reference/twse_tpex_pitfalls.md` §G）
日線／法人／融資券全部可帶日期、回應日期可斷言；TPEx 法人 2018-03 前格式不同（`tables[1]`、16 欄），不是回空。

---

## 3. 自建設計要補上的上游缺陷（由上面推出）
1. **上市／上櫃各自記進度、各自補洞**（C3/M4）。上游用 2330 當唯一進度基準。
2. **每天用全部已知事件重算整段還原序列**，不要「未還原接在還原後、等隔天覆寫」，也不要像上游只重抓 7 天（P2）。這同時消除上游的還原接縫。
3. **不依賴宇宙 4 碼規則以外的東西**：先對齊 P5，再談擴充。
4. **端點用「欄位數／欄名」辨識，不用固定 index**（M1、C1）；回應日期斷言（pitfalls 檔頭）。
5. **對帳排除窗外列**：與 data_pack 比對時，近期除權息事件 ex 前 ~8 天以上的列是上游已知缺陷，不計入自建誤差，另列清單。
6. 驗收除了檔數 ≥98%，加「事件覆蓋」：TWT49U／exDailyQ 每筆除權息事件，自算還原後的前後比要落在官方因子 ±0.2%（資料包本身 95% 做得到，目標 ≥ 資料包的水準，並列出離群檔）。

---

## 4. 檢討：我們自己抓的資料（抽查）

| 項目 | 發現 | 影響 | 建議 |
| :-- | :-- | :-- | :-- |
| ✅ `data/fundamentals/prices_raw.parquet`（未還原收盤，`prices_raw_close` 的來源，FinMind） | **只有 500 檔、最後日 2026-09-02**（還原日線 1969 檔、到 10-02）。build_u1b_bundle.py 註解也自承「每日增量尚未接」 | 填息率只對 500 檔、且 09-02 之後除息的檔算不出（落後一個月）。1469 檔完全沒有 | P1 完成後改由官方 `MI_INDEX`／`dailyQuotes` 的原始收盤供應，**這是 P1 的第一個實際回報** |
| 🔶 上游 `.TWO` 融資券缺日（09-04、09-15～17）我們靠 `_thin_latest` 守衛偵測 | 守衛是**事後偵測**，沒補洞；缺的日子在我們的 margin.parquet 永遠是洞 | 融資「10 日未增加」已改按交易日曆對齊（避免誤算），但缺日當天仍是「待確認」 | P1 自建上櫃融資券（可帶日期補洞）後，缺日可由自建補上 |
| ✅ 外資在上櫃的口徑（C2，2026-10-05 結案） | 母表 `foreign_net` 兩市場同口徑（皆不含外資自營商）；只是上櫃沒有 `fi_prop_net`／`dealer_net` | 無系統性偏差；但上櫃缺外資自營商、自營商，下游若要用「完整外資」或「自營商」只有上市可算 | 自建上櫃補存 `dealer_net`／`total_net` |

> 「抽查」＝今天只驗了表中標 ✅ 的一項。標 🔶／❓ 的是從讀碼推出、尚未用資料回算，**不要當結論**。

---

## 5. 待辦（依序）
1. 測舊 `3itrade_hedge_result.php`／`margin_bal_result.php` 對 2015～2019 是否有上櫃法人／融資券（決定 2020 前缺口能否補）。
2. 查 tw-swing `chips.parquet` 的上市／上櫃外資口徑（C2）。
3. 官方 `MI_INDEX` 全量對 data_pack 宇宙：4 碼規則濾完後檔數與代號差集（P5）。
4. 才開始寫 P1 collector。
