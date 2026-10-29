# 任務書：「月營收」分頁（2026-10-29，Opus 定框架）

> **狀態（2026-10-29 14:30）**：第 1、2 步已完成並 commit（Cline 寫、Opus 驗收）。**只剩第 3 步（UI）**，下個 session 派 Sonnet 子代理（worktree）。
> 第 1、2 步的檔案不准再讀或修改，除了第 3 步清單列的函式介面。

做完要讓 `pytest` 全綠、`python build_revenue_watch.py` 在本機跑得出 JSON、app 的「月營收」分頁可以正常顯示。
介面（函式簽名、JSON 格式、Row 欄位）已經 commit，**不准改**；覺得介面有問題就停下來，寫進 `collab/from-cline.md`。

## 要讀的檔案（只准讀這些）

| 檔案 | 範圍 |
|---|---|
| `screener/revenue_watch.py` | 全檔（框架＋JSON 格式，你要填實作） |
| `build_revenue_watch.py` | 全檔（框架＋步驟，你要填實作） |
| `app/valuation.py` | 第 1–40 行（說明）、`def estimate` 起到檔尾（回傳的 dict 長怎樣） |
| `app/bundle_data.py` | 第 18–125 行、第 153–172 行 |
| `reference/revenue_mops.py` | 全檔（MOPS 每期表的欄位：`COLUMNS`、`load_period`） |
| `scripts/pcf_fetchers.py` | `grep -n "def fetch_twse_closes" -A30` 那一段就好 |
| `app/streamlit_app.py` | ⚠️ 3700 多行，**不准整檔讀**。只讀：`_fmt_yi`／`_fmt_pct`／`_fmt_x`／`_vtable`（`grep -n "def _fmt_yi"` 起約 40 行）、`def _revenue_page`（佔位函式）、`def _disclaimer`（約 3 行） |
| `tests/test_app_smoke.py` | 全檔（照這個寫法加分頁測試） |

不准讀：`PRD.md`、`PLAN.md`、`docs/`、`research/`、`_archive_*`、`data/` 底下的大檔（parquet 只能用程式讀，不要印整張表）。

## 第 1 步：`screener/revenue_watch.py` 的實作＋測試

照每個函式的 docstring 實作。新增 `tests/test_revenue_watch.py`，**至少**包含以下測試，預期值照下面寫的（已手算）：

1. `test_periods_to_show`：2026-10-29 → `["2026-09","2026-08"]`；2026-11-03 → `["2026-10","2026-09"]`；2027-01-05 → `["2026-12","2026-11"]`（比 `str(p)`）。
2. `test_ratio`：`ratio(110,100)` ≈ 0.1；`ratio(90,100)` ≈ −0.1；`ratio(None,100)`、`ratio(1,None)`、`ratio(1,0)`、`ratio(1,-5)` 都是 None。
3. `test_yoy_streak`：歷史 2025-01～2025-12 每月 100；2026-01～2026-06 每月 90；2026-07～2026-09 每月 120。
   → 2026-09 的 streak＝3；2026-06 的 streak＝0。把 2025-08 那一列刪掉 → 2026-09 的 streak＝1（2026-08 找不到去年同月就停）。
4. `test_record_high`：2025-09～2026-08 共 12 個月每月 100，2026-09＝150 → True；2026-09＝99 → False；2026-09＝100（等於最大值）→ True；只留 2026-03～2026-09（更早月份只有 6 個）→ False。
5. `test_ma_status`：收盤價 1,2,…,60（60 筆）→ price 60、ma20＝50.5、ma60＝30.5、above_ma20／above_ma60 都 True；只給前 19 筆 → ma20 None、above_ma20 None、ma60 None；空表 → 全部 None。
6. `test_valuation_fields_not_ok`：`{"ok": False, "reason": "財報不足 4 季，不做試算。"}` → est_ok False、est_reason 是那段字、band_mid None、upside_mid None、warns `[]`。
7. `test_valuation_fields_ok`：est＝`{"ok":True,"reason":None,"band":{"low":80,"mid":100,"high":120},"growth_price":150,"eps":{"run_ex":5.0},"year":{"est":6.0},"cycle":{"pct":0.85},"warns":["a"],"infos":["b"]}`，price＝70 →
   upside_mid ≈ 0.428571、upside_growth ≈ 1.142857、at_valuation False、cyclical True、warns `["a","b"]`、run_eps 5.0、est_eps 6.0。
   同一份 est、price＝100 → at_valuation True。`band` 為 None、`year` 為 None、`cycle` 為 None → band_* None、upside_mid None、at_valuation None、est_eps None、cyclical False。
8. `test_make_row`：first_seen_at＝`Timestamp("2026-11-03 18:47")` → `"2026-11-03 18:47"`；note `"-"` → `""`；回傳的 key 順序與模組開頭 Row 表一致。
9. `test_rank`：四列 yoy＝0.5（low_base True）、0.4、None、0.3 → `rank(rows,"yoy")` 回 [0.5,0.4,0.3]；`exclude_low_base=True` → [0.4,0.3]；`n=1` → [0.5]；兩列 yoy 同分 → market_cap 大的在前；`require=("est_ok",)` 排除 est_ok False 的列。
10. `test_hold_signal`：above_ma60 False → "跌破季線"（就算 at_valuation True 也一樣）；above_ma20 False、above_ma60 True → "跌破月線"；兩條線都在上、at_valuation True → "已到估值"；全部 None → None。

## 第 2 步：`build_revenue_watch.py`

照檔案開頭的步驟 1–5 實作。注意：
- `_install_preloaded_reader()`：把原本的 `bundle_data._read` 存起來；新版第一次遇到某個 `name` 時整檔 `pd.read_parquet` 一次，再按 ticker 切片。`suffixed` 和 `columns` 的行為必須跟原本一模一樣。另外加一個測試 `tests/test_revenue_watch.py::test_preloaded_reader_matches_original`：用 `tmp_path` 寫一個小 parquet（兩個 ticker、含 `.TW`／`.TWO`），比對新舊 `_read` 的回傳相同（`monkeypatch` `bundle_data._dest` 指到 tmp）。
- 印出摘要：每一期的 source、n_published／n_universe、est_ok 的家數、耗時。
- 本機驗收：`python build_revenue_watch.py --limit 20`，接著跑完整的 `python build_revenue_watch.py`，把兩次的摘要和總耗時寫進報告。本機 bundle 在 `data/upstream/`，不用下載。

## 第 3 步：`app/streamlit_app.py::_revenue_page`

只改 `_revenue_page` 這個函式（要拆小函式可以，放在它正上方、名稱 `_rev_` 開頭）。其他函式、CSS、`NAV` 都不准動。排序和取前 30 名一律呼叫 `screener.revenue_watch.rank`／`hold_signal`，不要在 UI 自己重寫。表格一律用 `_vtable`（**不准用 st.dataframe**，手機上會截欄）。

- `data is None` → `st.info("還沒有月營收資料。")`，return。
- 開頭 `st.header("月營收")`，接著呼叫 `_disclaimer()`。
- **期別切換**：`st.segmented_control("期別", ..., key="_rev_period")`，標籤是 `"{pub_month 的月}月公布（{month 的月}月營收）"`，如果 `n_published < n_universe` 就加上 `" · 公布中 {n_published}/{n_universe}"`。預設選 periods[0]。
- caption：現價日期（price_date）、universe_note；`has_first_seen` 為 False 時加一句「這期沒有逐家公布時間（2026-10 營收起才開始收集）」。
- **檢視切換**：`st.segmented_control("檢視", ["公布清單","營收成長","估值價差","持有提示"], key="_rev_view")`，預設「公布清單」。

① **公布清單**
- `has_first_seen` 為 True：依 first_seen_at 新到舊排，同一時間再依 yoy 大到小。按日期分組，每組前面加 `st.markdown(f"**{日期}**　{家數} 家")`；最近 3 個日期直接顯示，更早的收進 `st.expander("更早公布")`。
- 為 False：一張表、依 yoy 大到小排，不放公布時間欄。
- 欄位：代號＋名稱、公布時間（只在 has_first_seen 時有，顯示 `MM/DD HH:MM`）、營收（`_fmt_yi`）、月增、年增、累計年增（`_fmt_pct`）、備註（超過 20 字截斷加「…」）。revised 為 True 的在名稱後面加「（更正）」。

② **營收成長**
- `st.toggle("含低基期（去年同月 < 1 億）", value=False, key="_rev_lowbase")`。
- `st.segmented_control("條件", ["全部","連續年增 ≥3 個月","創歷史新高"], key="_rev_cond")`：先篩條件（yoy_streak ≥ 3／record_high），再 `rank(rows,"yoy",exclude_low_base=not 開關)`。
- 欄位：代號＋名稱、年增、月增、累計年增、連續年增（「N 個月」）、創新高（✓ 或空白）、營收。

③ **估值價差**
- `st.segmented_control("估值口徑", ["合理價","合理成長價"], key="_rev_basis")` → key 用 `upside_mid` 或 `upside_growth`；`rank(rows, key, require=("est_ok",))`。
- 〔2026-10-29 Opus 追加〕`st.toggle("含景氣循環股／歷史本益比不穩定", value=False, key="_rev_cyc")`：關（預設）→ `rank(..., require=("est_ok",), exclude=("cyclical","pe_wide"))`；開 → 不帶 exclude。理由：9 月實測不排除時前 30 名有 23 檔景氣循環股（記憶體股價差 +500%～+1100%），那是「近 5 年平均本益比 × 高峰 EPS」的方法極限。開關下方 caption 寫這句理由。
- 欄位：代號＋名稱、現價、估值（band_mid 或 growth_price，`_fmt_x(v,1)`）、價差（`_fmt_pct`；≥ `UPSIDE_GOAL` 的在前面加「★ 」）、今年預估 EPS、年增、提醒（cyclical 或 warns 不空 → 「⚠」）。
- 表格下面加 `st.expander("怎麼估的")`，內容寫：近 3 個月營收 → 最新一季毛利率與費用率 → 稅後 → 股數 → 年化 EPS；今年預估 EPS＝已公布季＋未公布季×試算；合理價＝近 5 年各年平均本益比的中間值 × 今年預估 EPS；合理成長價＝目前本益比 × 今年預估 EPS。景氣循環股（⚠）在獲利高峰時估值會偏高。**試算不是預測、不是目標價。**
- 提醒欄：cyclical 或 pe_wide 為真、或 warns 不空 → 「⚠」。
- 「⚠」的原文：每一列可以收進 `st.expander(f"{代號} {名稱} 的提醒")`；只列前 30 名裡有 ⚠ 的。

④ **持有提示**
- 範圍：est_ok 為 True，且（upside_mid ≥ `UPSIDE_GOAL` 或 at_valuation 為 True）的列。
- 每一列用 `hold_signal`；None 顯示「續抱（線上）」。排序：跌破季線 → 跌破月線 → 已到估值 → 續抱，同類依 market_cap 大到小。
- 欄位：代號＋名稱、提示、現價、月線、季線、合理價、價差。
- 表格上面 caption：「app 不知道你持有什麼。這裡列出估值價差 ≥40% 或已到合理價的股票，給你對照手上的持股。口徑：到估值先賣一些、跌破月線／季線再全賣。不是建議。」

測試：在 `tests/test_app_smoke.py` 加 `test_月營收分頁_四個檢視都不炸`：切到「月營收」，逐一把 `_rev_view` 設成四個值，每次都 `assert not at.exception`。如果 `data/derived/revenue_watch.json` 不存在，就只檢查顯示了「還沒有月營收資料」。

## 驗收條件

- `python -m pytest -q` 全綠（現有測試一個都不能壞）。
- 第 2 步兩次本機執行的摘要。
- 報告寫在 `collab/from-cline.md`：commit 清單、測試數字、build 摘要與耗時、需要 Opus 決定的事。**不要貼程式碼。**

## 不准做的事

- 不准改：`screener/revenue_watch.py` 的函式簽名、模組開頭的 JSON／Row 格式、常數值；`.github/`、`.clinerules`、`collab/to-cline.md`、`reference/revenue_mops.py`、`scripts/revenue_mops_collect.py`、`app/valuation.py`、`app/bundle_data.py`。
- 不准 commit `data/derived/revenue_watch.json`（本機產物，由 CI 產生）。
- 不准連 MOPS（`mopsov.twse.com.tw`）：它短時間連打會封 IP。
- 不准用網路搜尋、網頁抓取、瀏覽器工具。
- 每一步做完就 `git commit`（訊息用中文，結尾加 `Co-Authored-By: Cline (DeepSeek V4 Pro)`），不准 push。
