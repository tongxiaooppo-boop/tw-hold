# 簽呈：09-23 回測整合/連環 bug 修正 + 09-24 市值排序/連續推薦天數 — 請 Opus 全檢

> ## ✅ 已結案（2026-09-24）
>
> **審核抓到三個 09-24 新邏輯的真漏洞（跟簽呈自己猜的方向不同）+ 一個
> 09-23 已 commit 的實質性計算 bug（三個分頁六張表的 0050 逐年報酬基準
> 日不一致）。** 全部處理完，回覆見 `docs/REVIEW_RESPONSE_2026-09-24.md`；
> `pytest -q` 240 passed。
>
> 最需要記住的一點：簽呈 §6 寫「已用 git checkout 清乾淨本機測試污染的
> derived 檔案」——這句話當時其實是錯的，`swing_history.json` 那時還沒
> 進 git，checkout 救不到它，實際上已經被污染。教訓：清理污染資料時，
> 沒進版控的新檔案要單獨確認，不能只信「跑過 git checkout 就沒事」。
>
> 未採納：§9（「修正前」0050 數字 +21.9% vs +21.4% 的敘事混用）——已知
> 但判定不在這輪範圍，留到之後真的有人追問再處理。

---

> **給接手審核的你**：這是一份自足的簽呈，你在全新對話、沒有上下文。
> 讀完這份就能開始審，不用先讀其他文件（除非下面某條你想深挖）。
> 環境：Windows，`d:\g\claude\tw-hold\`（git repo，跟同層的 `tw-swing\` 各自獨立）。
> **請實際讀程式碼驗證，不要只信任這份文件的敘述**——尤其 §3、§5 的挑戰點，
> 每一條都去對應檔案確認，不要只憑我的文字描述下判斷。這個使用者對回測數字
> 跟資料正確性非常較真，會針對具體年份/具體數字追問到底，審核也請用同樣
> 標準——找到問題比找不到問題更有價值。

---

## 0. 一分鐘現況

兩天份的工作：
- **09-23（commit `b80e35c` → `f7e4fe4`，已全部 commit）**：把三份獨立回測報告
  （tw-swing bench.html 逐規則排行榜、tw-swing tearsheet 權益曲線、tw-hold
  資金天花板跨方法論驗證）整合進 tw-hold app 既有的短線/長波段/價值三個分頁；
  過程中使用者追問數字查出兩個實質性 bug（候選池資料死區、CAGR 年化計算
  被死區拖低），修正後長波段「打不過 0050」的結論**翻案**成「小贏 0050」。
- **09-24（尚未 commit，改動見 §4 表格）**：①修正一句已經過期的免責聲明
  （長波段候選池「沒有回測支撐」——09-23 已經補了回測，這句話沒跟著更新）；
  ②市值排序選項（三清單通用，預設市值，其他排序保留可選）；③長波段候選池
  「首次進榜 / 連續入選天數」——用 `swing_list.json` 既有的 git 歷史回填、
  之後每次重算自動累加。

`pytest -q` 目前背景執行中，完整結果補在 §6（審核時請自己重跑一次確認，
不要只信任這裡貼的數字）。

---

## 1. 09-23：回測整合定案與做法

使用者要把三份回測報告整合，中途糾正過一次方向：**不是另開新頁**（我一開始
做錯），是塞進既有短線/長波段/價值三個分頁各自的 `BACKTEST_NOTES[...]["backtest"]`
（`app/streamlit_app.py`，`_strategy_backtest_expander()` 消費），因為多軌體檢頁
是查單一股票，跟查策略歷史績效性質不同。

內容規範（使用者陸續糾正出來）：
- 回測數字一律用 markdown 表格，**逐年報酬 + 年末帳戶價值都要列**，不能只寫
  全期年化摘要。
- 同一策略如果有多套方法論（bench.html 逐規則篩選 vs 資金天花板連續複利 vs
  每年歸零重跑），中間畫 `---` 實體分隔線區分，不能讓人誤以為是同一套算出來的。
- 三套方法論的關係要講清楚：bench.html 逐規則篩選（決定「這條規則有沒有
  edge」）／資金天花板（決定「用真實資金上限交易年化/回撤長怎樣」）／
  tw-swing 風險%配置 tearsheet（它自己實際下單邏輯的權益曲線），互相不能
  替代或加總。

對應 commit：`b80e35c`（三分頁補資金天花板數字）、`54a416b`（H2-trailatr2/Y4
每年歸零回測+短線分頁）、`cc51142`（短線回測分隔線）、`c25540b`（逐年表格）、
`f420780`（長波段/價值每年歸零重跑表格）。

---

## 2. 09-23：整合過程中查出的兩個實質性 bug

**① 候選池資料死區（非策略問題，commit `ae801fd`）**：使用者質疑「連續 3 年
無訊號不合理」。查證：CANSLIM 候選池的 `c_eps_3y_growth`（近 3 年 TTM EPS
要成長）需要 12 季前財報，但 `load_quarterly()` 只從 2015-Q1 起算，往回推第一個
候選池非空的週落在 **2019-02-15**。2016-01～2019-02 這段所有長波段報告都是
資料地基死區，不是策略沒機會進場。已在多份報告文件加註說明。

**② CAGR annualize 被死區拖低的實質性 bug（commit `cff1f03`）**：
`research/backtest_longswing.py`（實驗 E）的 `stats()` 拿全部 2016-2026（10.65 年）
當年化分母，把候選池死區的近 3 年「0% 報酬」也算進去，把每個口徑的年化都
拖低了近 10 個百分點——**這個直接影響「打不打得過 0050」的結論**。修正：
新增 `EVAL_START=2019-01-01` + `eval_window_stats()` 重算。修正前顯示 +21.9%
輸給 0050 +24.0%，**修正後其實是 +31.0% 小贏 0050 修正後的 +29.7%**——結論從
「打不過大盤」翻案成「小贏大盤」。回撤/勝率不受死區影響，不用改。順手修掉
一個連帶發現的既有 bug：`regime_at()` 回傳的 index 是輸入 Series 的 index
（0..N-1）不是日期，導致限縮評估窗後「分市況」區塊算出空白。

**③ 買得到口徑命名衝突，全 repo 統一（commit `6a52da7`、`f7e4fe4`）**：
`backtest_longswing.py` 內部曾把 `limit_at_close`（訊號收盤掛限價、3 日內沒
成交放棄）誤標成「買得到口徑」，跟 `backtest_scenario_b.py`／
`backtest_top17_buyable.py`（資金天花板/四本帳整套，也是短線 H2-trailatr2/
Y4/W6 跟價值線引用的定義）矛盾——那邊「買得到口徑」明確 = 次日開盤
（`next_open`）。使用者確認 tw-swing 之前實測過限價三日版本已經打槍，
**買得到原則全 repo 唯一定義是次日開盤**。裁決後把 `limit_at_close` 整個從
`backtest_longswing.py` 的 RUNS/RUN_LABELS 矩陣移除（不是改名保留，是刪除，
矩陣縮回 7 格），刪掉 3 個不再產生的 CSV，`PRD.md` §5.2.4 加了明確定義段落
防止以後再搞混。

**⚠️ 想被挑戰的點（09-23）**：
- `EVAL_START=2019-01-01` 這個日期是不是真的對應死區結束、有沒有 off-by-one
  （比如 2019-02-15 才是第一個非空候選池週，用 01-01 當窗口起點會不會混進
  1、2 月還是死區的資料）？
- `regime_at()` index bug 修好之後，「分市況」區塊的數字是不是真的正確了，
  還是只是「不再空白」但內容仍有問題？
- 三份報告檔案裡標注「已被取代」的舊版（`backtest_longswing_20260912.md`/
  `_20260914.md`）有沒有被任何地方（app、其他報告）誤連結，忘了改指向新版
  `backtest_longswing_20260923.md`？

---

## 3. 09-23 相關檔案

| 檔案 | 變動 |
| :--- | :--- |
| `research/backtest_longswing.py` | `EVAL_START`/`eval_window_stats()`、刪 `limit_at_close`、修 `regime_at()` index bug |
| `app/streamlit_app.py` | 三分頁 `BACKTEST_NOTES` 補回測內容（逐年表格+分隔線） |
| `PRD.md` §5.2.4 | 補「買得到口徑」明確定義 |
| `docs/reports/backtest_longswing_20260923.md` | 新報告，取代 09-12/09-14 版 |

---

## 4. 09-24：今天改的東西（尚未 commit）

使用者提出兩個功能需求，中途插了一句糾正：

> 「長波段及價值已經過回測，剛剛看還是有沒回測的訊息」

查出 `SWING_DISCLAIMER`（`app/streamlit_app.py`）跟 `build_lists.py` 裡
`_write("swing", ...)` 的 `_meta.disclaimer` 都還寫著「長波段候選池沒有回測
支撐」——這句話是 09-11 左右寫的，09-22/09-23 資金天花板+逐規則回測做完後
沒回頭更新，變成跟頁面下方自己列的回測表格互相矛盾。

| # | 改動 | 檔案 |
| :- | :--- | :--- |
| 1 | 更新過期免責聲明——區分「候選池篩選規則本身已有回測驗證」vs「停損位/可買上限的風控算術仍不是驗證過的買點」，不再整包打成沒回測 | `app/streamlit_app.py`（`SWING_DISCLAIMER`）、`build_lists.py`（swing `_meta.disclaimer`）、`guide.html` |
| 2 | 三清單（價值/定存/長波段）的 universe/candidates 資料加 `market_cap` 欄位（來自 `universe.parquet`，經 `fin_mktcap` map 進 `screen_all()` 回傳的 val/dep dataframe 跟候選池 pool 逐筆） | `build_factors.py::screen_all()` |
| 3 | 市值排序選項——`SORT_KEYS` 三個 kind（value/deposit/swing）都加「市值」當**第一個選項（= 預設）**，其他排序依據（價值分數/安全分/現價/…）保留可選；長波段候選池頁原本完全沒有排序 UI，這次新增 | `app/streamlit_app.py`（`SORT_KEYS`、`_card_list()` 沿用既有邏輯、`_swing_page()` 新增排序 UI） |
| 4 | 市值顯示格式化（元 → 億元整數）+ `LABELS`/`_fmt()` 補 `market_cap` | `app/streamlit_app.py` |
| 5 | 長波段候選池「首次進榜 / 連續入選天數」——見 §5 詳細設計 | `build_lists.py`（新函式 `_update_swing_history()`）、新檔 `data/derived/swing_history.json`、新腳本 `scripts/backfill_swing_history.py` |
| 6 | 長波段候選卡片顯示市值 + 連續天數徽章（`🆕 今日新進榜` / `連續入選 N 天（首次 YYYY-MM-DD）`） | `app/streamlit_app.py`（`_swing_b_html()` 的 `ctx` 行） |

---

## 5. 09-24：長波段「連續入選天數」設計細節（請重點審這節）

**動機**：使用者問「有沒有地基」——之前用 agent 查證過，`data/derived/swing_list.json`
**有進 git 版控**（不是只推 Release，`rebuild.yml` 平日排程跑完會 commit），
從 2026-09-07 起約 12 個「內容有實質變動」的交易日有歷史紀錄，回填成本低。
**只做了長波段（`swing_list.json`，CANSLIM+Minervini 候選池，每日全重算）**，
沒有做價值/定存——那兩條是季度凍結（換股日才變動），「連續天數」對它們語意
會是「連續幾季在成分股」而不是「連續幾天」，這次沒做（範圍邊界，不是漏做）。

**資料結構**：`data/derived/swing_history.json`——`{ticker: {first_seen, last_seen,
streak_days}}`，只保留**目前還在候選池**的 ticker（退出後就從檔案移除，不是
標記成歷史）。

**連續性判斷邏輯**（`build_lists.py::_update_swing_history()`）：用「上一版
`candidates_pool`（呼叫端既有的 `pool_prev` 變數，來自 `_load_prev("swing")`）
有沒有這檔」判斷連續，**不是比對日期字串**——這樣如果某檔曾經退出候選池、
之後重新進榜，會正確從 `streak_days=1` 重算，不會被舊紀錄誤接續。

```python
if tk in pool_prev and ph and ph.get("last_seen") != asof_s:
    streak = int(ph["streak_days"]) + 1
    first_seen = ph["first_seen"]
elif ph and ph.get("last_seen") == asof_s:
    streak, first_seen = int(ph["streak_days"]), ph["first_seen"]  # 同日重跑
else:
    streak, first_seen = 1, asof_s
```

**回填**（`scripts/backfill_swing_history.py`，已手動跑過一次、產出已在
`data/derived/swing_history.json`）：用 `git log --follow` 抓 `swing_list.json`
每一版的 commit，`git show <rev>:<path>` 拿內容，按 `_meta.trading_date`
**去重**（同一天可能有多筆 commit——格式調整/重跑——只留最後一版，避免
同一天被重複算進連續天數），照上面同一套邏輯逐日重放。跑完結果：12 個
交易日、目前在榜 18 檔，最長連續 13 天（2026-09-07 進榜、一路留到最新一版）。

**⚠️ 想被挑戰的點（09-24，這節最需要獨立驗證）**：
- 「用 `pool_prev` 判斷連續」這個邏輯，如果 CI 一天內因為某種原因（重跑/
  workflow 重複觸發）產生兩次 commit、且兩次的候選池內容**剛好不同**
  （不是同日重跑完全相同的情況），會不會把同一天誤算成連續 2 天？
  `elif ph and ph.get("last_seen") == asof_s` 這條只防「完全同日重跑」，
  沒有防「同日兩次 commit 但內容不同」——這個情境在正式邏輯裡有沒有漏洞，
  回填腳本已經用「同日取最後一版」防住了，但正式增量邏輯（`_update_swing_history`）
  沒有這層防護，因為它一次只處理「當下這次重算」，不會回頭看同一天有沒有
  更早的 commit。
- 回填腳本用 `trading_date` 去重、保留「最後一版」，但如果最後一版剛好是
  一次資料錯誤的重跑（比如某天因為 bug 重算出錯誤的候選池，之後又修正重跑），
  去重邏輯會不會把錯誤版本的候選池當成那天的正式紀錄？
- `market_cap` 的資料來源是**今天的** `universe.parquet` 快照（不是點時的
  歷史市值）——候選池顯示的市值會隨每天重算變動，這對「排序依據」而言
  沒問題（本來就是看當下），但如果使用者以為這是「進場當天市值」會不會
  誤解？要不要在卡片上或說明文字裡講清楚這是「目前市值」？
- `screen_all()` 裡 `fin_mktcap` 這個 Series 的 index 是 ticker 字串，
  `.get(rec["ticker"])` 對不存在的 ticker 回傳 `None`——但如果 `fin_mktcap`
  本身是空 Series（`universe.parquet` 缺欄位的退化情況，見 `_universe_financials()`
  docstring「缺 universe.parquet → 全空」），這條路徑有沒有實際測過不會炸？

---

## 6. 測試

`pytest -q` 背景執行中，跑完會補這裡的結果——**審核時請自己重新跑一次**
（`cd d:\g\claude\tw-hold && python -m pytest -q`），不要只信任這份文件貼的數字。

本機另外手動跑過一次 `python build_lists.py`（用本機現有的舊 bundle 快照，
`trading_date` 停在 2026-09-21，不是今天）確認新邏輯不會炸、`market_cap`/
`first_seen`/`streak_days` 欄位有正確寫進 `swing_list.json`/`value_list.json`——
跑完之後**特意用 `git checkout` 把這次測試跑出來的 `data/derived/*.json`
還原掉**（因為那是舊 bundle 算出來的過期資料，不該留在 repo 裡跟 CI 之後
用新 bundle 算出來的正式資料混在一起）；只留下 `swing_history.json`（來自
獨立的 git 歷史回填腳本，不依賴那次本機重算）跟程式碼改動。

---

## 7. 不用做的事（範圍邊界）

- **短線（swing tab，來自 tw-swing 的 `share-latest.json`）沒有加市值排序**——
  那份資料來自另一個 repo（tw-swing）的每日分享級輸出，不是 tw-hold 自己的
  `data/derived/*`，要加市值欄位得改 tw-swing 那邊的產出格式，這次沒有動，
  使用者也沒有明確要求短線也要有這個功能。
- **價值/定存沒有做「連續推薦天數」**——理由見 §5 開頭，季度凍結的語意跟
  逐日連續天數不吻合，先不做。
- **沒有重新驗證 09-23 回測翻案的數字本身**（+31.0% vs 0050 +29.7% 那組）——
  09-23 那輪已經是使用者自己盯著數字追問查出來的，這次沒有理由再重查一次，
  除非審核發現新的疑點。
