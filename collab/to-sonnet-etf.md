【tw-hold】ETF 分頁 階段 1（任務書 v1，2026-11-27）
專案路徑：D:\g\claude\tw-hold（直接在這個目錄工作，分支 main）

## 要讀的檔案（只准讀這些；大檔只讀指定行）
1. reference/etf_universe.py（全）—— 白名單、分割表、常數
2. scripts/etf_track.py（全）—— 收集框架，函式簽名與規格在 docstring
3. build_etf.py（全）—— 計算框架，JSON schema 在模組說明
4. app/etf_view.py（全）—— 呈現用純函式框架、文字常數
5. tests/test_etf.py（全）—— 驗收測試，預期值不准改
6. scripts/selfhost_raw_prices.py 第 63–205 行（_get、_num、_rows、fetch_twse、fetch_tpex、collect_day）
7. scripts/selfhost_events.py 第 140–218 行（_ex_rows、_roc、_f 的用法）
8. app/streamlit_app.py：第 150–160 行（_load）、2115–2160 行（_fmt_pct、_vtable）、3221–3240 行（_active_etf_page 開頭，看頁首寫法）、4205–4208 行（NAV）、4295–4325 行（路由）
9. .github/workflows/pcf_retry.yml 第 20–50、95–125 行（排程、setup、commit＋push 重試樣板）
10. TSD 樣本（只看前 3 行）：`D:/g/data_backup/tsd/_repo/data/universe/daily/2026-11-20.csv`、`.../early/daily/2014-12-31.csv`、`.../early/exright/2014-10-24.csv`
    已知欄位：daily＝`key,date,stock_id,name,market,open,high,low,close,volume,amount,change,limit,shares,transactions,price_basis,last_price`；
    exright＝`date,stock_id,pre_close,ref_price,value,kind,open_base,limit_up,limit_down,ex_div_ref`（同資料夾的 `_fetched.json` 跳過）。
    官方 TWT49U 的 detail['value'] 是字串如 `"0.400000"`。

## 規則
- **框架檔的函式簽名、欄名、JSON schema、文字常數、測試預期值都不准改**；覺得有錯 → 停下，在回報寫「問題一句＋2～3 選項＋建議」，最多停 2 次。
- 欄名不同但意義明確這類小疑問自行採用，回報註明。
- 你在本機不准 stash／reset／checkout／rebase（CI workflow 裡照樣板寫 rebase 重試沒關係）；只 `git add` 自己改的檔。commit email 用 git 全域設定（不要帶 --author）。
- 暫存檔、一次性腳本只准放 `D:\g\claude\tw-hold\collab\tmp_etf\`，結束前刪掉。
- 不上網查資料；程式本身抓官方網站（twse.com.tw）可以。不改其他檔案。

## 步驟 1：收集（commit 一次）
a. `scripts/selfhost_raw_prices.py`：新增 `def _is_stock4(code: str) -> bool`（4 碼純數字）；`_rows`、`fetch_twse`、`fetch_tpex` 加最後一個參數 `keep: Callable[[str], bool] = _is_stock4`，用 `keep(code)` 取代原本的 4 碼判斷；`collect_day` 不動。預設行為必須完全不變。
b. 實作 `scripts/etf_track.py` 全部函式與三個子指令（規格在 docstring）。backfill 的官方除權息從 2015-01 按月切到本月。
c. 本機跑：
   `python scripts/etf_track.py backfill --tsd D:/g/data_backup/tsd/_repo/data`
   `python scripts/etf_track.py daily --days 10`
   `python scripts/etf_track.py verify --tsd D:/g/data_backup/tsd/_repo/data --dates 2016-06-01,2020-03-02,2025-06-18,2026-11-20`
   verify 要 exit 0。記下 prices／events 列數、每檔第一筆日期。
d. commit：`scripts/selfhost_raw_prices.py scripts/etf_track.py data/etf/prices.parquet data/etf/events.parquet`

## 步驟 2：計算（commit 一次）
a. 實作 `build_etf.py` 全部函式。
b. `python build_etf.py` 要 exit 0、產出 `data/derived/etf.json`。若 check_jumps 擋下 → **不准改 JUMP_LIMIT、不准自己加分割**，把訊息原文寫進回報停下。
c. commit：`build_etf.py data/derived/etf.json`

## 步驟 3：頁面＋排程（commit 一次）
a. 實作 `app/etf_view.py` 全部函式。
b. `app/streamlit_app.py`：
   - import 改成 `from app import etf_view, refresh_window, val_inputs, val_view`
   - NAV 在 "主動式 ETF" 前插入 "ETF"；路由加 `elif nav == "ETF": _etf_page(_load("etf.json"))`
   - 新函式 `_etf_page(data: dict | None) -> None`，放在 `_active_etf_page` 前面：
     1. data 為 None → `st.info("ETF 資料還沒產生")` 後 return。
     2. 標題 `st.subheader("ETF")`，`st.caption(f"資料日 {data['asof']}")`。
     3. 依 GROUPS 順序（cap、div、lev）每組：`st.markdown(f"#### {組名}")`；lev 組下面 `st.caption(etf_view.LEV_NOTE)`；
        排序 `st.segmented_control("排序", list(etf_view.SORTS[g]), default="代號", key=f"_etf_sort_{g}")`（回 None 時當 "代號"）；
        div 組再加分頁 `st.segmented_control("頁", [str(i) for i in range(1, page_count+1)], default="1", key="_etf_page_div")`（只有 1 頁就不顯示）；
        `_vtable(etf_view.HEAD[g], etf_view.table_rows(rows, g), num=etf_view.NUM_COLS, src=etf_view.SRC_COLS)`。
     4. 三個 expander（預設收合）：「這些數字怎麼算」→ `st.markdown(etf_view.EXPLAIN)`；
        「高股息：每年實際配息率」→ caption YEARLY_NOTE ＋ `_vtable(head, body, num=set(range(1, len(head))), wide=True)`；
        「定期定額回測」→ caption `DCA_NOTE.format(amount=DCA_AMOUNT)` ＋ `_vtable(etf_view.DCA_HEAD, body, num=set(range(2, 10)), wide=True)`。
     5. data["missing"] 非空 → `st.caption("沒有資料：" + "、".join(...))`。
     6. 最後 `_disclaimer()`。
c. 新增 `.github/workflows/etf_daily.yml`：週一～五 cron `"23 9 * * 1-5"`（台北 17:23）＋ workflow_dispatch；
   permissions contents: write；concurrency group `etf-daily`；python 3.12＋`pip install -r requirements.txt`；
   步驟：`python scripts/etf_track.py daily --days 10` → `python build_etf.py` → commit `data/etf data/derived/etf.json`（沒變就跳過；push 被拒 rebase 重試照抄 pcf_retry.yml 的迴圈，衝突時 `--theirs` 換成這兩個路徑）。
d. commit：`app/etf_view.py app/streamlit_app.py .github/workflows/etf_daily.yml`

## PROOF_CMD（三步都做完才跑；Opus 會自己重跑）
```
cd D:/g/claude/tw-hold && python -m pytest tests/test_etf.py -q && python -m pytest -q -p no:cacheprovider && python build_etf.py && python -c "import json;d=json.load(open('data/derived/etf.json',encoding='utf-8'));print(d['asof'],len(d['rows']),d['missing'],sum(1 for x in d['dca'].values() if x['reinvest']))"
```
預期：test_etf 31 passed；全套 0 failed；最後一行印出 asof ≥ 2026-11-26、rows 31、missing []、第四個數字 ≥ 20。

## 回報（寫進 collab/from-sonnet-etf.md，欄位固定，不貼程式碼）
- 完成項：步驟 1／2／3 各一行
- commit：hash＋訊息
- 測試：test_etf 數字；全套 passed／failed 數字
- 資料：prices 列數、events 列數（div／split 各幾筆）、verify 結果、每檔第一筆日期（一行一檔）
- PROOF_CMD 最後一行輸出原文
- 需要決定的事：沒有寫「無」
