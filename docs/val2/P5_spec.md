# 估值 2.0 P5 規格：資料與上線（Opus 定，2026-11-03）

> 上位規格：`upgrade_guide.md`。本檔有寫的以本檔為準（§0 列出與 guide 不同的決定）。
> 介面（本檔的函式簽名、檔名、欄位、測試名稱與預期值）實作者不得改；覺得有問題停下回報。

## 0. Opus 的決定（與 guide／PHASES 不同處）

| # | 決定 | 理由 |
|---|---|---|
| D1 | `company_basic` **不在 tw-hold-data 另抓**，改由 tw-swing `build_universe.py` 已在抓的 `t187ap03_L`／`mopsfin_t187ap03_O` 多留 3 欄，寫進同一份 `official_shares.parquet`，bundle 另以 `company_basic.parquet` 名稱發佈 | 同一個端點不要兩邊各抓（guide 表 6 也這樣建議）；build_universe 每次 publish 都跑（每天），失敗有 30 天快照退路 |
| D2 | `monthly_raw_close` 來源＝自建官方未還原價**全歷史**（`selfhost-data/raw_prices.parquet` 2015-01 起 2,147 檔 ∪ `openapi-daily`），不是 guide 寫的 FinMind `prices_raw` | 實測自建 raw_prices 2015 起就有 2,147 檔；guide §13「PB 全歷史只從 2020-10 起」與 T-12「426 檔」**因此解除**，說明頁要照新事實寫 |
| D3 | 倍數檔上雲：兩個 parquet（`multiples_hist`、`eps_revision`）推 `derived-latest` release（同 factors）；`industry_pe.json`、`multiples_check.json` 隨 `data/derived/` commit | parquet 每天一顆 blob 不進 git；JSON 小、可 diff |
| D4 | app 端倍數檔：缺檔**或檔案超過 6 小時**就重抓（`.part` 再 replace）；抓不到但舊檔還在 → 用舊檔 | factors 現行「有檔就不抓」會讓長跑的容器一直用第一天的資料 |
| D5 | 使用說明＝`app/help_valuation.md`（單一來源），在估值速覽最下面一個展開區「📖 估值怎麼看」顯示；不另做網站 | 網友就是用這個 app；一份檔案、跟著程式一起上版 |
| D6 | A30 疑點結案：2330 2026Q2 業外 958 億是真的（營收、營業利益、淨利與官方 XBRL 完全一致；淨利÷稅前 82%） | Opus 11/3 對 TSD `fin_hist/2026Q2.csv` |

## 1. P5a：tw-swing（工作目錄：tw-swing clone）

### 1-1 `scripts/build_universe.py`

- `parse_official_shares(twse_rows, tpex_rows) -> pd.DataFrame`：**簽名不變**，回傳欄位改為
  `ticker, issued_shares, market, par_value, preferred_shares, paid_in_capital`（前三欄行為不變）。
  - 上市欄名：面額 `普通股每股面額`（值例 `"新台幣                 10.0000元"`）、特別股 `特別股`、實收資本額 `實收資本額`；
    上櫃：`ParValueOfCommonStock`（同格式）、`PreferredStock.shares`、`Paidin.Capital.NTDollars`。
  - 新增 `parse_par(text: str) -> float`：取字串裡第一個數字（可含小數點）；取不到、≤0 → NaN。
    例：`"新台幣                 10.0000元"`→10.0；`"新台幣 1.0000元"`→1.0；`"美金 0.0100元"`→**NaN**（非新台幣一律 NaN，避免 TDR 誤用）；`""`→NaN。
  - `preferred_shares`、`paid_in_capital`：去逗號轉數字，空字串／無法轉 → NaN；不因為這三欄缺值就丟掉該列（列只依 `issued_shares` 篩，維持原行為）。
- `load_official_shares`：快照退路讀舊檔時，**舊檔沒有新欄位要補 NaN**，不可 KeyError；回傳欄位同上。
- 寫檔照舊：`official_shares.parquet`（＋`asof`）。`market_cap()` 等既有使用處不動。

### 1-2 `scripts/build_u1b_bundle.py`

- `_selfhost_raw_close()` 拆成：
  - `_selfhost_raw_full() -> pd.DataFrame | None`：下載兩個 release 檔、合併去重（週收集優先）、只留 4 碼數字代號與 close>0、ticker 帶 `.TW`／`.TWO`，**不截年份**；同一 process 內只下載一次（`functools.lru_cache` 或模組變數）。失敗回 None（原行為）。
  - `_selfhost_raw_close()`：`_selfhost_raw_full()` 再截近 `RAW_YEARS` 年（＝原行為，輸出不變）。
- 新增 `_monthly_raw_close() -> pd.DataFrame | None`：`_selfhost_raw_full()` 為 None → 印 `⚠️` 回 None（**不退回 FinMind 舊檔**）。否則每檔每月取**最後一個交易日那一列**（含當月未結束的月份；tw-hold 端會再丟掉）。欄位 `ticker`（**裸代號** str）、`month`（"YYYY-MM"）、`date`（datetime）、`close`（float），依 ticker、month 排序。
- `jobs` 加 `"monthly_raw_close.parquet": _monthly_raw_close()`。

### 1-3 bundle 發佈

- `scripts/make_bundle_meta.py` 的 `REL` 加 `"monthly_raw_close.parquet": "monthly_raw_close.parquet"`、`"company_basic.parquet": "company_basic.parquet"`。
- `.github/workflows/publish_bundle.yml` 發佈步驟：`build_universe.py` 之後 `cp data/fundamentals/official_shares.parquet data/bundle_out/company_basic.parquet`（檔案不在就跳過、不失敗）；兩個新檔加進 u1b 的 `make_bundle_meta` 參數與 `ASSETS`（缺檔照現有「只上傳存在的檔」邏輯）。
- 不改 cron、不改其他步驟。

### 1-4 測試（tw-swing，新增 `tests/test_bundle_val2.py`；既有 `test_build_universe_shares.py` 要繼續過）

| 測試名稱 | 預期 |
|---|---|
| `test_parse_par` | 上面四個例子 |
| `test_parse_official_shares_extra_cols` | 上市一列（面額 10、特別股 "200000000"、實收 "77231817420"）＋上櫃一列（面額 1.0、特別股 "0"）→ 6 欄；值分別 10.0／2e8／77231817420、1.0／0／…；特別股空字串 → NaN 且該列仍在 |
| `test_load_official_shares_old_snapshot` | 舊快照只有 ticker／issued_shares／market／asof、fetch 丟例外 → 回傳含 3 個新欄位（全 NaN），狀態 `snapshot …` |
| `test_monthly_raw_close` | 假的 full（2 檔、跨 3 個月、含當月）→ 每檔每月一列、取該月最後交易日、ticker 裸代號、含當月 |
| `test_monthly_raw_close_none` | `_selfhost_raw_full` 回 None → 回 None |

## 2. P5b：tw-hold（工作目錄：`val2_work/repo`）

### 2-1 bundle 接收

- `fetch_bundle.py` `PIPELINE` 加 `"monthly_raw_close.parquet": "u1b"`、`"company_basic.parquet": "u1b"`（缺檔＝既有 u1b 缺檔處理，只警告）。
- `app/bundle_data.py` `_ASSETS` 加 `"company_basic.parquet"`（不加 monthly_raw_close，app 用不到）。新增：

```python
def company_basic(code: str) -> dict | None:
    """company_basic.parquet 中該檔的 {par_value, issued_shares, preferred_shares, asof}；
    檔不存在、沒有該檔、讀檔失敗 → None。數值 NaN 照傳（float('nan')），asof 為 pd.Timestamp。"""
```

### 2-2 `build_multiples.py`（只改輸入，CLI／產出 schema 不動，更新模組說明的「輸入」段）

- 原始收盤：`closes = ms.monthly_closes(concat(monthly, daily), asof)`；monthly＝`data/upstream/monthly_raw_close.parquet` 的 ticker／date／close（存在才讀），daily＝`data/upstream/prices_raw_close.parquet`（原行為）。`monthly_closes` 本來就取每月最後一列，合併後同月會取到較晚的那天（兩者同源，結果一致）。
- monthly 檔不存在 → 印 `⚠️ 沒有 monthly_raw_close，原始收盤只從 prices_raw_close 起` 繼續。
- 交易所 PER：`data/upstream/fundamentals/per.parquet` 存在就用它，否則 `data/upstream/per.parquet`（CI 只有前者；本機兩者內容相同）。
- `multiples_check.json` 加一個鍵 `"closes_first_month"`：`{"p10": "YYYY-MM", "p50": …, "n_from_2015": int}`（各檔最早月份的分位數；`n_from_2015`＝最早月 ≤ 2015-03 的檔數）。

### 2-3 `screener/detect.py::share_checks`（**介面變更，Opus 定**）

```python
def share_checks(ticker: str, q: pd.DataFrame, asof: pd.Timestamp, basic: dict | None = None) -> list[Check]:
```

- `today_par` 參數**移除**，改吃 `basic`（`bundle_data.company_basic` 的回傳）。「可用的 basic」＝不是 None、`par_value` 有限 >0、`asof` 與估值日差 ≤ `BASIC_MAX_AGE_DAYS = 30`。
- 規則 1、2 不變。
- 規則 3「股數對不上」：par＝可用 basic 的 `par_value`，否則 `PAR_DEFAULT`；`pref`＝可用 basic 的 `preferred_shares`（NaN → 0）；C＝`capital_stock ÷ par − pref`（股本含特別股，要扣掉）；其餘不變。
- 規則 4「面額與特別股」：
  - basic 不可用 → `unchecked`，why＝"面額與特別股資料缺或過期，假設面額 10 元"；
  - `pref > 0` → `warn`，value＝pref，why＝f"有特別股 {pref/1e8:.2f} 億股，每股淨值含特別股權益、股價淨值比可能偏低"；
  - 否則 `ok`。
- `screener/val_card.py::build_card` 加關鍵字參數 `basic: dict | None = None`（放最後，預設 None 讓舊呼叫不壞），原封傳給 `share_checks`。
- `app/val_inputs.py::card_inputs` 回傳 dict 加 `basic`：`bundle.company_basic(code)`（bundle 物件沒有這個方法 → None）；`_AppBundle` 轉接 `module.company_basic`。乾跑腳本的轉接物件也要有 `company_basic`（讀 `data/upstream/company_basic.parquet`，沒有就回 None）。

### 2-4 rebuild.yml 接 build_multiples（只加步驟，不改 cron、不動其他步驟）

- 位置：「估值分型季更」之後、「主動式 ETF PCF 快照」之前（build_lists 不讀倍數檔，所以不必在它前面）。
  ```yaml
  - name: 估值倍數（multiples_hist／eps_revision／industry_pe）
    continue-on-error: true
    timeout-minutes: 45
    run: python build_multiples.py --workers 2
  ```
- 「因子表 → derived-latest release」的 upload 加 `data/derived/multiples_hist.parquet data/derived/eps_revision.parquet`；兩檔不存在（上一步失敗）時**只上傳存在的檔**，不能讓 factors 也傳不上去。
- `industry_pe.json`、`multiples_check.json` 由既有 `git add data/derived/` 帶進 commit（確認 .gitignore 沒擋 JSON）。
- `continue-on-error: true` → 失敗不擋清單；release 上會留前一天的檔。

### 2-5 app 端下載倍數檔（`app/val_inputs.py`）

```python
DERIVED_RELEASE = "https://github.com/tongxiaooppo-boop/tw-hold/releases/download/derived-latest"
REFRESH_HOURS = 6

def ensure_multiples(derived: Path = DERIVED, now: float | None = None, fetch=None) -> None:
    """MH_FILE、REV_FILE 缺檔或 mtime 超過 REFRESH_HOURS → 從 DERIVED_RELEASE 下載到 .part 再 replace；
    下載失敗：刪 .part、舊檔保留、不丟例外。IND_FILE 不下載（隨 git 上版）。
    fetch(url, path) 預設 urllib.request.urlretrieve（測試注入）；now 預設 time.time()。"""
```

- streamlit 端：`_valuation_block` 呼叫 `card_inputs` 前呼叫一個 `@st.cache_data(ttl=3600)` 包起來的 `ensure_multiples()`（一小時最多檢查一次）。本機開發（`data/derived` 已有新檔）不會被覆蓋——mtime 新就不抓。

### 2-6 畫面收尾（`app/streamlit_app.py`）

- 刪「（開發中）」與「🚧 開發中…」caption（2157–2158 行附近）：標題改「#### 💰 估值速覽」。
- 估值速覽最後（`full=True` 才顯示）加 `st.expander("📖 估值怎麼看")`，內容＝讀 `app/help_valuation.md` 原文 `st.markdown`；檔案讀不到就不顯示該展開區。
- 1815「反推 EPS 門檻 5.08 元」的「元」被擠到下一行（A30 低優先）：數字與單位之間改不換行（`&nbsp;` 或 `white-space:nowrap`），只改這處的組字。

### 2-7 `app/help_valuation.md`（使用說明，給網友看）

- 讀者：一般網友，會看股價、不熟估值術語。白話、短；**總長 ≤ 90 行**；名詞照 upgrade_guide §15（同一個東西同一個名字，和卡片字面一致）。
- 章節（照順序）：①這張卡在回答什麼（拿這檔自己過去的本益比當尺，不是預測股價）②三價：便宜／合理／昂貴怎麼來（近 5 年月底本益比 20%／50%／80% 位置 × EPS；高成長 3 年；上限）③購買區間與「可買」的意思 ④前瞻三價（試算季怎麼補、最多 2 季）⑤為什麼有的股票沒有價（A／B／C／D 四層，各一句白話）⑥可信度與降級原因怎麼看 ⑦已知限制（照 guide §13，但「PB 全歷史只從 2020-10」**改成**「原始股價 2015 年起；更早沒有」；其餘照寫）⑧不是買賣建議（一句）。
- 不放公式符號（P20、NC、F4、k…），不放程式名稱、檔名。
- 每個數字常數（5 年、3 年、30、50、1.10、2 季…）要和程式常數一致；實作者寫完列出「說明頁常數 ↔ 程式常數位置」對照表在回報裡。

### 2-8 測試（tw-hold）

改 `tests/test_val2_detect.py:100`（`today_par=10.0` → `basic=`），新增 `tests/test_val2_p5.py`：

| 測試名稱 | 預期 |
|---|---|
| `test_share_checks_basic_none` | basic=None → 「面額與特別股」unchecked、why 含「假設面額 10 元」 |
| `test_share_checks_basic_ok` | basic={par 10, pref 0, asof=ASOF} → ok |
| `test_share_checks_basic_stale` | asof＝ASOF−31 天 → unchecked |
| `test_share_checks_preferred_warn` | pref=2e8 → warn、value=2e8、why 含「2.00 億股」 |
| `test_share_checks_preferred_capital` | 最新季 capital_stock=1.2e10、ni_parent=1e9、eps=1.0（S=1e9）、par 10、pref 2e8 → C=1e9、「股數對不上」ok（dev≈0）；同資料 basic=None → C=1.2e9、dev≈0.167 → warn |
| `test_share_checks_par_1` | par 1.0、capital_stock=1e9、S=1e9 → ok（用 basic 面額，不是 10） |
| `test_build_card_passes_basic` | build_card(..., basic=含特別股) 的可信度裡有「面額與特別股」warn（用既有 test_val2_* 的最小卡片 fixture） |
| `test_card_inputs_basic` | 假 bundle 有 `company_basic` → 回傳 dict 的 basic 原樣；假 bundle 沒有此方法 → basic=None |
| `test_ensure_multiples_missing` | 缺檔 → fetch 被呼叫 2 次、檔案出現、沒有 .part |
| `test_ensure_multiples_fresh` | 兩檔 mtime＝now−1h → 不呼叫 fetch |
| `test_ensure_multiples_stale_fail` | mtime＝now−7h、fetch 丟例外 → 舊檔內容不變、沒有 .part、不丟例外 |
| `test_build_multiples_closes_union` | monthly（2015-01～2020-09 月底）＋ daily（2020-10 起日線）→ `monthly_closes` 結果從 2015-01 起連續、無重複月；monthly 檔不存在 → 從 2020-10 起（直接測組合用的小函式，實作者自取名 `_load_closes(asof, upstream: Path)`） |
| `test_help_valuation_exists` | `app/help_valuation.md` 存在、≤ 90 行、不含 `P20`／`NC`／`F4`／`TTM`／`YoY`／`.py` |

## 3. P5c：上線（Opus 親自，不派）

1. guide §11 全項（全市場重跑、分層數、翻轉抽 20、核對、指定 12 檔、桌面＋手機截圖），乾跑腳本照 P3／P4。
2. 順序：tw-swing 先 push（新檔是加法，tw-hold main 不讀）→ 手動 dispatch `publish_bundle.yml` → 確認 release 有兩個新檔、`company_basic` 面額分布（中位 10、<2 元約 9 檔）→ tw-hold `val2` merge 進 main（main 只多 bot 資料 commit）→ 全套 pytest → push → 手動 dispatch `rebuild.yml` → 確認 derived-latest 有兩個倍數檔、`multiples_check.json` 的 `closes_first_month` → Streamlit Reboot → 截圖抽 2330／2881／1815／1101。
3. 更新 guide §2-1（company_basic 與 monthly_raw_close 的實際來源）、§13、T-12；HANDOFF。
