# 估值速覽升級指引（給工程師與 AI 實作者）

> 版本：2026-11-02 v2（晚：加 9-1／9-2 展開區、第 15 節全站名詞）。v1 Opus 定框架。人看的版本：`design.md`／網頁。規格來源：`design.md`、`detail_fixes.md`。
> repo：`d:/g/claude/tw-hold`（main `d19710b` 起算）。

## 0. 鐵則

| # | 規則 |
|---|---|
| 1 | **介面、資料 schema、常數名稱以本文件為準，實作者不得更改**；覺得有問題就停下回報 Opus |
| 2 | 本地可分階段；**上線一次到位**（第 7 節範圍全部完成、全套測試通過才 push） |
| 3 | 計算只在引擎層（`screener/`、`build_*.py`）；`app/` 只讀結果排版，不重算任何數字（`tests/test_consistency.py` 鎖） |
| 4 | 沒寫到的舊行為一律維持；只有維持會讓畫面數字矛盾時才停下回報 |
| 5 | 讀 CI 產出的 JSON／parquet 一律 `.get()`／欄位存在檢查（app 部署比資料快） |
| 6 | 改引擎後要重跑 `build_lists.py` 等產出，否則 app 看到舊資料 |
| 7 | 不准網路搜尋；產出檔只放 repo 或 `d:/g/claude/` 底下 |
| 8 | 畫面文字：中文白話、短、每個數字只出現一次；試算處標「規則未經驗證」 |

## 1. 模組地圖

| 動作 | 檔案 | 內容 |
|---|---|---|
| 新增 | `screener/growth.py` | 年增率共用模組（第 6 節） |
| 新增 | `screener/eps_windows.py` | 近 4 季／前瞻 4 季窗口與試算（取代 `eps_nowcast` 的窗口邏輯，第 3 節） |
| 新增 | `screener/multiples_self.py` | 自建歷史倍數（PE、PB、前瞻 PE）與有效月數（第 4 節） |
| 新增 | `build_multiples.py` | rebuild 時算全市場月度序列 → `data/derived/multiples_hist.parquet`、`eps_revision.parquet` |
| 新增 | `reference/share_basis.py` | 股數基準：事件倍數、面額推回、歷史股數（第 4-2 節） |
| 改寫 | `screener/val_card.py` | 分層 A～D、路由、三價、前瞻三價、購買區間（第 5 節） |
| 改寫 | `screener/detect.py` | 可信度分組（第 8 節）；`pb_events` 刪除；`shares_check` 改用 `share_basis` |
| 改 | `screener/eps_nowcast.py` | 保留試算公式函式供 `eps_windows` 呼叫；刪除 `_future`、`FUTURE_*`、`MAX_NC_K` 窗口邏輯、`TRIAL_BASIS="ttm"` 分支 |
| 改 | `screener/candidate_pool.py` | `c_eps_yoy`、`_support_oppose` 改用 `growth.py` |
| 改 | `build_classification.py`、`screener/classify.py` | 刪除永不觸發狀態（預估轉虧、前瞻擴張）與 `eps_nc`／`eps_f4` 輸入；遲滯後依最終大類重算子分類 |
| 改 | `app/streamlit_app.py` | 估值速覽卡片、展開區、怎麼算（第 9 節）；拿掉「開發中」只在上線那次；全站改名（第 15 節） |
| 改 | `app/checklist.py`、`app/stockcharts.py` | 季 EPS 年增改讀 `growth.py`；名詞照第 15 節；河流圖與體檢本益比改法見第 15-4 節（已定案） |
| 新增 | `tests/test_glossary.py` | 第 15-3 節：禁用寫法不得出現在畫面字串 |
| 改 | 自建上游收集（`selfhost_collect` 系列） | 每日收 `t187ap03_L`／`mopsfin_t187ap03_O` 快照 |
| 改 | tw-swing `publish_bundle` | bundle 加 `monthly_raw_close.parquet`（第 2 節） |
| 刪 | `val_card.FALLBACK_MULTS` 用於主三價、`REF_MARGIN`、`DIFF_WARN` 的位置判斷、`_finish` 的 block→severe 全轉 | 第 5、8 節 |

## 2. 資料

### 2-1 新增資料

| 檔案 | 產生 | 欄位 | 備註 |
|---|---|---|---|
| bundle `monthly_raw_close.parquet` | tw-swing publish（合併 `fundamentals/prices_raw.parquet` 2015 起＋每日原始收盤） | `ticker`(str 裸代號), `month`(YYYY-MM), `date`(該月最後交易日), `close`(float, 原始未還原) | 實測：tw-swing `prices_raw` 只有 500 檔、停在 2026-09-02；tw-hold `prices_raw_close` 1019 檔、2020-10 起。合併後 2015-01 起 426 檔，其餘從 2020-10 起（5 年窗夠，PB 全歷史不夠） |
| `data/reference/company_basic.parquet`（tw-hold-data） | 自建上游每日快照 | `ticker`, `asof`, `par_value`(float 元), `issued_shares`(int 股), `preferred_shares`(int), `paid_in_capital`(int 元) | 上市 `t187ap03_L`（欄名：普通股每股面額「新台幣 10.0000元」要解析數字、已發行普通股數或TDR原股發行股數、特別股、實收資本額）；上櫃 `mopsfin_t187ap03_O`（ParValueOfCommonStock、IssueShares、PreferredStock.shares、Paidin.Capital.NTDollars）。只有當天快照，**不可回填歷史** |
| `data/derived/multiples_hist.parquet` | `build_multiples.py` | 見 4-4 | rebuild 產出 |
| `data/derived/eps_revision.parquet` | `build_multiples.py` | `ticker`, `month`, `window`(如 "2026Q1-2026Q4"), `eps_fwd`, `n_est_q`, `event`("normal"/"roll"/"report") | 每月 10 號後一筆；上修判斷用 |

### 2-2 既有資料注意事項（實測 2026-11-02）

| 資料 | 注意 |
|---|---|
| `revenue.parquet` 的 `announced` | 2026 年才有值（88.9%），之前 0.1%；值的中位數是次月 17 號、69% 晚於 10 號 → **不是官方公告日**（疑為收集時間）。可見日一律用推定「次月 10 號」 |
| 股數事件 | 母體內 1,453 筆：ex_both 966、ex_rights 187、cap_reduction 280、par_change 20；**cap_reduction 有 177 筆 m=None**（不是少數） |
| 季報 | 近 12 季有斷季 12 檔；2026Q2 EPS 缺 34、歸母淨利缺 69、股本缺 24 |
| 面額 | 股本 ÷ 最新季隱含股數：中位 10.02；33 檔明顯不是 10 元（9 檔 <2 元）；股本含特別股（例：台泥特別股 2 億股） |
| `disclosure_date` | loader 一律期末 +45 天；年報法定 3/31，產品端用到的地方要改用 `reference.corporate_actions.report_deadline()` |

## 3. EPS 窗口（`screener/eps_windows.py`）

### 3-1 定義

| 名稱 | 規則 |
|---|---|
| 已公布季 | 有財報 EPS 且已過推定可見日 |
| 營收到齊季 | 三個月月營收都有、且推定可見（次月 10 號） |
| 近 4 季 | 末季＝最新已公布季的下一季若「營收到齊」則為它（試算），否則＝最新已公布季；往前取連續 4 季。**最多 1 個試算季** |
| 前瞻 4 季 | 末季＝近 4 季末季的下一季，若該季已有 ≥1 個月月營收；否則前瞻＝近 4 季。**最多 2 個試算季** |
| 財報延遲 | 若最新已公布季之後有 ≥2 季營收到齊 → 近 4 季＝最後連續 4 季財報，`status="report_late"`，前瞻不更新 |
| 連續性 | 四季必須相鄰不重複；有缺季 → 該窗口不可用（不得用 `tail(4)`） |

### 3-2 試算季公式

```
revenue  = 已公布月份實際 + Σ 缺月補值
op       = revenue × (gm_last − opex_last)          # 最新已公布季
pretax   = op + nonop_med8                           # 近 8 季業外中位數
ni_par   = pretax × (1 − tax8) × (1 − minority8)     # 近 8 季合計比率
eps      = ni_par ÷ shares_latest                     # 最新季 歸母淨利 ÷ EPS
```

| 參數 | 規則 | 不可用時 |
|---|---|---|
| `gm_last`、`opex_last` | 最新已公布季 | 不試算 |
| `nonop_med8` | 近 8 季（稅前 − 營業利益）中位數 | 近 8 季有效 <4 季 → 不試算 |
| `tax8` | 1 − Σ淨利 ÷ Σ稅前；超出 [0, 0.35] 用 0.20 並標示 | 抵銷比 <0.10 → 不試算 |
| `minority8` | 1 − Σ歸母淨利 ÷ Σ淨利 | 抵銷比 <0.10 或 >0.5 → 不試算 |
| `shares_latest` | 最新季 歸母淨利 ÷ EPS（|EPS| ≥ 0.05） | 推不出 → 不試算；不可退回四季中位數 |
| 抵銷比 | \|Σx\| ÷ Σ\|x\| | — |

### 3-3 缺月補值

| 情況 | 補法 |
|---|---|
| 一般 | 去年同月 × (1 + g_q)，g_q＝該季已公布月份合計 ÷ 去年同月份合計 − 1 |
| Q1 只有 1 月 | g_q 改用近 3 個月合計比；標 `method="q1_3m"` |
| 去年同月缺或 0 | 用該季已公布月份平均；標 `method="avg"` |
| 應公布未公布（已過 10 號仍缺） | 視為資料不足，不補、不試算 |
| 月營收與季報口徑不符（`detect.revenue_caliber` block） | 不試算 |
| 金融股 | 不試算 |

### 3-4 介面

```python
@dataclass(frozen=True)
class QuarterRow:
    q: str                 # "2026Q3"
    kind: str              # "actual" | "est"
    eps: float
    rev: float | None
    months_known: int      # est 季已公布月數（actual 為 3）
    fill_method: str | None  # None | "yoy_q" | "q1_3m" | "avg"
    params_from: str | None  # 參數來源季，如 "2026Q2"

@dataclass(frozen=True)
class EpsWindow:
    ok: bool
    status: str            # "ok" | "report_late" | "no_data" | "not_estimable"
    reason: str | None
    quarters: tuple[QuarterRow, ...]   # 連續 4 季，舊→新
    eps: float | None      # 四季合計
    n_est: int

def ttm_window(q: pd.DataFrame, monthly: pd.Series, asof: pd.Timestamp) -> EpsWindow:
    """近 4 季。q＝單季財報（含 period_end, revenue, gross_profit, op_income, pretax_income,
    net_income, ni_parent, eps）；monthly＝月營收（index＝月初）；asof＝評價日（推定可見日判斷用）。
    只用 asof 當下可見資料（歷史重建同一函式）。最多 1 個試算季。"""

def fwd_window(q: pd.DataFrame, monthly: pd.Series, asof: pd.Timestamp,
               base: EpsWindow | None = None) -> EpsWindow:
    """前瞻 4 季。新季 0 個月營收 → 回傳與近 4 季相同、status="ok"、n_est 同近 4 季。
    最多 2 個試算季；財報延遲 → status="report_late"。"""

def reported_window(q: pd.DataFrame, asof: pd.Timestamp) -> EpsWindow:
    """已公布 4 季（全 actual）。"""
```

## 4. 自建倍數（`reference/share_basis.py`、`screener/multiples_self.py`、`build_multiples.py`）

### 4-1 公式

| 倍數 | 每個月底 t |
|---|---|
| PE | `price_adj(t) ÷ ttm_window(asof=t).eps` |
| 前瞻 PE | `price_adj(t) ÷ fwd_window(asof=t).eps` |
| PB | `price_adj(t) ÷ bvps(t)`；bvps＝最近可見季歸母權益 ÷ 該季股數（換到最新基準） |

`price_adj(t)＝原始收盤(t) ÷ Π(t 之後的股數事件 m)`；**不做股利還原**。EPS 已由 loader 調到最新基準。

### 4-2 股數基準

| 規則 | 內容 |
|---|---|
| 最新基準 | 所有每股數字換到今天的股數基準，用同一組事件 m |
| 歷史股數 | 當季股本 ÷ 當時面額；面額＝今日面額（`company_basic`）依 par_change 事件往回推；或用該季隱含股數（歸母淨利 ÷ EPS） |
| `company_basic` | 只用於「現在」與核對，不回填歷史 |
| 特別股 | 股本含特別股 → 普通股數＝(股本 − 特別股面額合計) ÷ 面額（有資料時） |
| 現金減資（m=None 的 cap_reduction） | 事件日到下一份可見財報之間，PE、前瞻 PE、PB 該段月份標 `excluded` |

```python
def share_factor_after(ticker: str, t: pd.Timestamp) -> float:
    """t 之後（不含 t）所有股數事件 m 的乘積；無事件 = 1.0。m=None 的事件不乘。"""

def par_value_at(ticker: str, t: pd.Timestamp, today_par: float | None) -> float | None:
    """t 當時面額：今日面額依 par_change 事件往回推；無今日資料 → None。"""

def excluded_months(ticker: str, q: pd.DataFrame) -> set[pd.Period]:
    """現金減資等無法調整的區間（月）。"""
```

### 4-3 有效月數

| 規則 | 值（起始值） |
|---|---|
| 窗口 | 近 60 個完整月（一般、循環輕）；高成長近 36 個月；PB 全部歷史（2015 起，有多少算多少） |
| 有效月 | 倍數 > 0、PE ≤ `MULT_MAX_PE`=100、EPS ≥ `EPS_MIN`=0.05、非缺值、非 excluded |
| A 層門檻 | 有效月 ≥ `VALID_MIN`=36（高成長 ≥ 30，沿用現行；PB ≥ 60，沿用現行）；已在 A 層者 <`VALID_EXIT`=33（高成長 27、PB 54）才退出 |
| 各自計算 | PE、前瞻 PE、PB 三套分開 |
| 分位 | 只用有效月取 P20／P50／P80；倍數上限（一般 30、例外 50、高成長 50）照舊截斷，原始分位保留 |

### 4-4 `multiples_hist.parquet` schema

| 欄位 | 型別 | 說明 |
|---|---|---|
| `ticker` | str | 裸代號 |
| `month` | str | YYYY-MM |
| `date` | date | 月底交易日 |
| `price_adj` | float | 原始收盤 ÷ 之後股數事件 |
| `eps_ttm`, `eps_fwd`, `bvps` | float | 當時可見 |
| `n_est_ttm`, `n_est_fwd` | int | 試算季數 |
| `pe`, `pe_fwd`, `pb` | float | 無效時 NaN |
| `valid_pe`, `valid_pe_fwd`, `valid_pb` | bool | 4-3 有效月 |
| `excluded` | bool | 現金減資等 |
| `pe_exchange` | float | 交易所 PER（核對用） |

### 4-5 核對

| 檢查 | 標準 |
|---|---|
| 自建 PE vs 交易所 PER | 只比 `n_est_ttm==0` 且前後 3 個月無股數事件的月份；中位差 >2% → 警示（不擋上線） |
| 純分割前後 | 自建 PE、PB 連續（事件前後月比值差 <5%） |

## 5. 分層、路由、三價、購買區間（`screener/val_card.py`）

### 5-1 決策順序

| 順序 | 條件 | 結果 |
|---|---|---|
| 1 | 不在分類母體／財報 <4 季 | D，原因 |
| 2 | 路線＝PB（金融、循環・資產重、營建） | PB 有效 → A（PB）；否則 D |
| 3 | 近 4 季 EPS ≤ 0 | C |
| 4 | 特殊（非營建）、資料不足 | D |
| 5 | PE 有效月數達標（含緩衝） | A（PE） |
| 6 | 其餘 | B |

### 5-2 各層輸出

| 層 | `prices` | `fwd_prices` | `buy_range` | 其他 |
|---|---|---|---|---|
| A-PE | 近 4 季 EPS × 自建 PE P20/P50/P80 | 前瞻 EPS × 自建前瞻 PE（前瞻有效月達標才給） | 5-3 | 循環：EPS＝min(近 4 季, 3 年平均)，名稱「較低獲利情境」，另給 `eps_5y_avg` |
| A-PB | 每股淨值 × 自建 PB 分位 | 無 | 便宜～合理（PB），無前瞻 | 金融附 `roe`＝近 4 季歸母淨利 ÷ 平均歸母權益 |
| B | 無 | 無 | 無 | `pe_now`、`industry_pct`、`eps_needed`＝現價 ÷ 產業中位 PE；同產業有效樣本 <8 → 只給 `pe_now` |
| C | 無 | 無 | 無 | `ps_position` 或 `pb_position`（自身歷史分位）；「虧損中，不用獲利估價」 |
| D | 無 | 無 | 無 | `reason` |

其他：P80÷P20 >4 只降級；P20 ≥ 上限 → 顯示原始倍數＋「歷史倍數高於上限」，`position="na"`。

### 5-3 購買區間

| 狀態 | 進入 | 上緣 |
|---|---|---|
| `normal` | 預設；連續 2 次下修；前瞻倍數失效 | 近 4 季合理價 |
| `fwd_up` | 連續 2 次上修，且前瞻合理價 > 近 4 季合理價 | 前瞻合理價 |

下緣＝近 4 季便宜價。上緣 < 下緣時不給。

### 5-4 上修判斷（讀 `eps_revision.parquet`）

| 規則 | 值 |
|---|---|
| 比較 | 同一 `window` 的 `eps_fwd`，本月 vs 上月 |
| 一次上修／下修 | ≥ +`REV_STEP`=2% ／ ≤ −2% |
| `event="roll"`（換季）或 `"report"`（財報替換） | 不比較；連續次數不變 |
| 連續 | 只數 normal 月；方向相反即歸零 |

```python
def build_card(qf, rev, px, cls: dict | None, mh: pd.DataFrame | None,
               rev_hist: pd.DataFrame | None, industry_pe: dict | None, asof: pd.Timestamp) -> dict:
    """mh＝該檔 multiples_hist；rev_hist＝該檔 eps_revision；industry_pe＝{產業: (中位 PE, 有效樣本數)}。
    回傳 dict 欄位見 5-5。不讀檔。"""
```

### 5-5 `build_card` 回傳欄位（app 只讀這些）

`ok, tier("A"|"B"|"C"|"D"), route("PE"|"PB"|None), reason, price, px_date, type, display_type, state, subtags, eps{reported, ttm, fwd: EpsWindow 轉 dict}, growth{見第 6 節}, prices{cheap, fair, dear, base, base_name, mults, raw_mults, n_valid, window}, position, fwd_prices{...同上} | None, buy_range{low, high, state, note} | None, revision{last_pct, streak, direction}, b_tier{pe_now, industry_pct, eps_needed, n_peers} | None, c_tier{...} | None, roe | None, eps_5y_avg | None, status{data, share_basis, comparability, estimate}, notes[], version`

## 6. 年增率（`screener/growth.py`）

```python
@dataclass(frozen=True)
class Growth:
    value: float | None    # 比例；不適用時 None
    label: str             # "pct" | "turn_profit" | "turn_loss" | "loss_wider" | "loss_narrower" | "base_zero" | "flat" | "na"
    low_base: bool
    text: str              # 畫面用短字，如 "+35%（基期低）"、"虧轉盈"

def yoy_eps(cur: float | None, prev: float | None) -> Growth: ...
def yoy_revenue(cur: float | None, prev: float | None) -> Growth: ...
```

| prev | cur | label | 百分比 |
|---|---|---|---|
| > 0 | > 0 | pct | cur/prev − 1；EPS：\|prev\| <1 元或 prev < cur/5 → low_base；營收：prev < cur/5 → low_base |
| ≤ 0（<0） | > 0 | turn_profit | 無 |
| > 0 | < 0 | turn_loss | 無 |
| < 0 | < 0 | loss_wider（\|cur\|>\|prev\|）／loss_narrower | 無 |
| = 0 | 任何 | base_zero | 無 |
| 任何 | = 0 | flat | 無 |
| None | 任何 | na | 無 |

| 指標 | 呼叫 | 用在 |
|---|---|---|
| 最新月營收年增 | yoy_revenue(本月, 去年同月) | 推薦卡 |
| 本季營收年增 | yoy_revenue(本季已公布月合計, 去年同月份合計) | 估值頁 |
| 近 4 季營收年增 | yoy_revenue(近 4 季營收, 一年前 4 季) | 估值頁 |
| 季 EPS 年增 | yoy_eps(最新季, 去年同季) | 推薦卡；`c_eps_yoy`＝label=="pct" 且 value > 0.25 |
| 近 4 季 EPS 年增 | yoy_eps(近 4 季, 一年前近 4 季) | 估值頁 |
| 前瞻 EPS 年增 | yoy_eps(前瞻 4 季, 一年前同窗口實際) | 估值頁 |
| 營收加速／減速 | 本月年增 vs 上月年增（兩者 label=="pct"） | 推薦卡 |

## 7. 上線範圍

| 項目 | 必備 |
|---|---|
| 第 1～6 節全部 | ✅ |
| 可信度分組（第 8 節） | ✅ |
| 循環改名＋5 年平均、金融 ROE、營建 PB | ✅ |
| 分類：刪死狀態、遲滯後重算子分類 | ✅ |
| 拿掉未來 4 季、購買參考價 1.10、補位主三價 | ✅ |
| 給網友的使用說明網頁 | ✅ |
| 全站名詞統一（第 15 節，含改版範圍外的純改名） | ✅ 同一次上線 |
| 河流圖、三軌體檢本益比改自建口徑（第 15-4 節） | ✅ |
| 說明文字寫錯的事實（第 15-5 節 F1～F5） | 改版前先修（只改字，獨立小批） |
| 月營收分頁 | ❌ 維持封印；2.0 上線後改讀 `build_card` 再解封 |
| 高成長近期動能 | 下一版 |

## 8. 可信度（`screener/detect.py`）

| 組 | 包含 | 作用範圍 |
|---|---|---|
| data | 財報缺季、月營收缺、分類過期 | 缺 → 停用受影響窗口 |
| share_basis | 股數對不上（用 `share_basis`）、特別股、現金減資區間 | 嚴重 → 停用 PE／PB 該段 |
| comparability | P80÷P20、倍數截斷、疑似循環、單一事件、剛換類 | 只提示 |
| estimate | 橋接（**改驗實際公式：零業外改業外中位數後的試算**）、業外閘門、高變動、稅率／少數股權 | 嚴重 → 停用試算季（近 4 季退回已公布 4 季、前瞻不給） |

| 規則 | 內容 |
|---|---|
| 狀態值 | 每組 `ok`／`warn`／`stop`／`unchecked`；`unchecked` ≠ `ok` |
| 刪除 | `_finish` 的 block→severe 全轉；`pb_events` |
| 高變動門檻 | 營收季增減 30% 改為「與去年同季相比的季增減差」≥ 30 個百分點（排除淡旺季）【起始值】 |
| 新增顯示 | 營業現金流 ÷ 淨利（近 4 季）、應計比率（(淨利 − 營業現金流) ÷ 平均總資產） |

## 9. 畫面（`app/streamlit_app.py`）

| 區塊 | 內容 |
|---|---|
| 股價卡 A 層 | 現價｜三價（相對自身歷史）便宜／合理／昂貴＋位置｜購買區間 X～Y（狀態）｜前瞻三價（相對自身前瞻倍數） |
| 股價卡 B／C／D | 依 5-2 |
| EPS 卡 | 近 4 季 EPS（年增）｜前瞻 4 季 EPS（年增｜比上月、連續上修）｜營收年增：本季（已公布 n 個月）／近 4 季 |
| 展開區 | 三個，內容見 9-1 |
| 怎麼算 | 用詞說明（便宜＝歷史上該倍數只有 20% 的月份比這更低，再換算成價格…）、歷史重建（近似）、規則未經驗證 |

### 9-1 三個展開區的內容（取代舊版；名稱照第 15 節）

| 展開 | 內容 | 不放 |
|---|---|---|
| 📊 估值定位細節 | 分層 A～D 與原因、路由（PE／PB）、類型與分類原因、可信度四組（正常／提醒／停用／未檢查＋停用了哪個窗口或方法）、有效月數與虧損月數（分開列）、ROE、現金流（營業現金流 ÷ 淨利、應計比率）、樣本說明 | 推導過程 |
| 📐 怎麼算 | 規則表：名詞定義、三價與購買區間的規則、歷史重建限制、已知限制（第 13 節）、「規則未經驗證」 | 這檔的數字（數字只出現在卡片與試算細節） |
| 🔍 試算細節 | ① 窗口表：**只列近 4 季、前瞻 4 季**各季的「實際／試算」與 EPS（使用者 11/2：估值只有這兩個基準；「已公布 4 季」不在估值卡與展開區出現，只用在河流圖圖例、推薦卡／體檢、試算停用時的退回） ② 每個試算季一張推導表 ③ 倍數窗表：PE／前瞻 PE／PB 的期間、有效月數、20／50／80 百分位倍數、三價＝基準 × 倍數 ④ 購買區間推導（下緣、上緣、是否前瞻上調、原因）⑤ B 層：反推 EPS 門檻的算式 ⑥ 近 8 季業外表（標題「近 8 季業外（中位數 X 億，用在試算）」）⑦ 停損與大量區表（算法不動，只改名稱） | 未來 4 季（已刪）、購買參考價（已刪） |

| 推導表的列（試算季） | 數值 | 來源／假設欄寫什麼 |
|---|---|---|
| 營收（逐月一列：X 月） | 金額 | 「實際」或補值方法：「去年同月 ×（1＋本季已公布月份累計年增）」／「農曆年：近 3 個月年增」／「已公布月份平均」 |
| ＝ 季營收 | 合計 | — |
| ×（毛利率 − 營業費用率） | 兩個比率 | 「YYYYQn 財報（最新一季）」 |
| ＝ 營業利益（試算） | 金額 | — |
| ＋ 業外 | 金額 | 「近 8 季業外中位數」 |
| ×（1−稅率）×（1−少數股權比） | 比率 | 「近 8 季合計；稅率超出 0～35% 用 20%」 |
| ＝ 歸母淨利（試算） | 金額 | — |
| ÷ 股數 | 億股 | 「YYYYQn 隱含股數」；T-19 例外時寫原因 |
| ＝ 試算 EPS | 元 | 「規則未經驗證」 |

- 同一個試算季同時屬於近 4 季與前瞻 4 季時，推導表只畫一次，標題寫「（近 4 季、前瞻 4 季共用）」。
- 窗口狀態要分開寫：「新季營收未出」「財報延遲」「試算停用（原因）」，不合併成「退回」。

### 9-2 表格樣式（全部估值展開區）

| 規則 | 內容 |
|---|---|
| 算出來的數字 | 一律三欄推導表「步驟｜數值｜來源／假設」（`_vtable`，手機把來源收到步驟下方，沿用現行做法） |
| 純規則、狀態 | 兩欄「項目｜內容」（`_kv_table`） |
| 不准 | 表格下方接灰色小字段落；說明併進「來源／假設」欄或規則表 |
| 字級 | `.thc-vt` 正常字級；改共用 CSS 要桌面＋手機截圖 |

### 9-3 卡片與展開區互相對照（使用者 11/2 傍晚指定）

| 規則 | 內容 |
|---|---|
| 說明文案表格化 | 展開區（含「📐 怎麼算」）的說明一律進表格（規則表兩欄、推導表三欄），不寫成段落 |
| 標記主卡片數字 | 展開區裡**就是主卡片上那個數字**的那一列，數值欄加標記「📌」，來源欄寫「＝卡片『XX』」（例：「＝卡片『合理價』」）；圖例在每個展開區第一行寫一次「📌＝主卡片上的數字」 |
| 卡片指向展開 | 主卡片每個數字旁可附極短的去處提示（例：「推導見 🔍 試算細節 ③」），只放卡片有、展開有推導的數字；手機不換行時可省略 |
| 同值同字 | 被標 📌 的值，在卡片與展開區的格式化結果必須字元相同（同一個格式化函式產生），測試 `test_glossary_同名同源` 擴充成逐一比對所有 📌 列 |
| 不重複 | 同一個數字在展開區只出現一次（📌 那列）；其他列要引用就寫「見上列」 |

## 10. 測試案例（名稱與預期，實作者不得改預期值）

| 測試 | 輸入 | 預期 |
|---|---|---|
| `test_近4季_營收到齊算入試算季` | 財報到 Q2、Q3 三個月營收齊、asof=10/15 | quarters=Q4..Q2 actual＋Q3 est；n_est=1 |
| `test_近4季_營收未齊不算入` | Q3 只有 7、8 月 | 4 季全 actual |
| `test_前瞻_新季0個月等於近4季` | asof=10/20，Q4 無月營收 | fwd.quarters == ttm.quarters |
| `test_前瞻_年報期兩個試算季` | 財報到 Q3、Q4 營收齊、1 月營收有、asof=2/15 | fwd＝Q2,Q3 actual＋Q4 est＋Q1 est；n_est=2 |
| `test_財報延遲` | 財報到 Q3、Q4 與 Q1 營收都齊、asof=4/15 | ttm.status="report_late"，4 季全 actual |
| `test_斷季窗口不可用` | 中間缺一季財報 | ok=False |
| `test_缺月補值_累計年增` | 10 月 +20%、去年 11 月 100 | 11 月補 120 |
| `test_缺月補值_Q1只有1月用3個月` | — | fill_method="q1_3m" |
| `test_抵銷比過小不試算` | 近 8 季稅前 +10,−9,… 合計接近 0 | status="not_estimable" |
| `test_股數推不出不試算` | 最新季 EPS=0 | not_estimable，不退回中位數 |
| `test_yoy_虧損擴大` | prev=−2, cur=−4 | label="loss_wider"，value=None |
| `test_yoy_虧轉盈` | prev=−1, cur=1 | "turn_profit" |
| `test_yoy_基期低` | prev=0.5, cur=3 | pct，low_base=True |
| `test_推薦卡_虧損擴大不過門檻` | eps −4、去年 −2 | c_eps_yoy=False |
| `test_自建PE_純分割連續` | 1 拆 4 事件 | 事件前後 PE 比值差 <5% |
| `test_自建PE_不含股利還原` | 高殖利率股 | 與交易所 PER 中位差 <2%（無事件期間） |
| `test_現金減資區間剔除` | m=None 減資 | 事件日到下份財報 excluded=True |
| `test_有效月數_微利月無效` | EPS 0.03 的月份 | valid_pe=False |
| `test_AB緩衝` | 前月 A、本月有效 34 | 仍 A；33 以下 → B |
| `test_上修_換季月不比較` | event="roll" | streak 不變 |
| `test_上修_同窗口2%` | 同窗口 +1.5% | 不算上修 |
| `test_購買區間_連續兩次上修切前瞻` | streak=2 且前瞻合理 > 近 4 季合理 | state="fwd_up"，high=前瞻合理 |
| `test_購買區間_前瞻合理較低不切` | 前瞻合理 < 近 4 季合理 | state="normal" |
| `test_購買區間_PB無前瞻` | 金融 | state="normal"，無 fwd |
| `test_營建PB有效為A` | 營建＋PB 有效月 ≥60 | tier="A"、route="PB" |
| `test_虧損優先C` | 一般股 近 4 季 EPS<0 | tier="C" |
| `test_B層產業樣本不足` | 同產業 5 檔 | 只有 pe_now |
| `test_畫面不自己算` | 掃 app | 無乘除運算估值數字（擴充現有測試含除法） |

## 11. 驗收（Opus 親自）

| 項目 | 標準 |
|---|---|
| 全套 pytest | 全過（clone 缺資料的測試列清單） |
| 全市場重跑 | 1,018 檔 0 例外；分層 A／B／C／D 檔數、前瞻可用數、購買區間 fwd_up 數列表 |
| 翻轉清單 | 舊三價位置 vs 新：逐件抽 20 檔看 |
| 核對 | 自建 vs 交易所中位差分布；>2% 的檔逐一列 |
| 指定個股 | 2330、2327、2881、2882、3211、2408、5904、3661、1815、6477、一檔營建、一檔虧損 |
| 截圖 | 桌面＋手機（Playwright `D:\prog\pw-venv`） |

## 12. 參數表

| 常數 | 值 | 性質 |
|---|---|---|
| `VALID_MIN`／`VALID_EXIT` | 36／33（高成長 30／27、PB 60／54） | 起始值 |
| `MULT_MAX_PE` | 100 | 起始值 |
| `EPS_MIN` | 0.05 元 | 沿用 |
| `REV_STEP` | 0.02 | 起始值 |
| `REV_STREAK` | 2 | 定案 |
| `OFFSET_MIN` | 0.10（抵銷比） | 起始值 |
| `LOW_BASE_ABS`／`LOW_BASE_REL` | 1.0 元／0.2 | 定案 |
| `INDUSTRY_MIN_N` | 8 | 起始值 |
| `TAX_DEFAULT`／`TAX_MAX` | 0.20／0.35 | 沿用 |
| 推定可見 | 財報期末 +45 天、年報 3/31（`report_deadline`）；月營收次月 10 號 | 定案 |
| 倍數上限 | 一般 30（例外 50）、高成長 50、PB 無 | 沿用 |

## 13. 已知限制（寫進說明頁）

| 限制 | 說明 |
|---|---|
| 歷史重建是近似 | 用推定可見日與今天的更正版資料 |
| 前瞻未經驗證 | 規則沒有回測 |
| 存活者偏差 | 母體沒有下市股 |
| PB 全歷史 | 約 590 檔原始價只從 2020-10 起 |
| 試算排除一次性業外 | 用業外中位數，大額一次性損益不會反映 |

## 14. 實作陷阱（11/2 程式與資料掃描，詳見 `bugs_ledger.md`）

| # | 陷阱 | 要求 |
|---|---|---|
| T-1 | 缺季被 `tail(4)` 跨過（現行 `val_card._ttm_eps`、`_avg3_eps`、`detect.near_zero_eps`） | 一律先轉季度索引、檢查相鄰不重複 |
| T-2 | NaN 被 `sum()` 跳過、檢查遇缺值回 ok | 每個檢查回 `unchecked` 並記有效筆數 |
| T-3 | 正無限大被當成有效倍數 | 有效值＝`np.isfinite(x) and x > 0` |
| T-4 | 倍數窗口結束日取「最後一個正值日」 | 窗口以估值日錨定；缺值月留著算無效 |
| T-5 | 先刪無效值再取月底 | 先取完整月份月底觀測，再判有效；當月未結束不算 |
| T-6 | 每股淨值回找任意舊 PBR | 自建 bvps；最近可見季權益 |
| T-7 | `_monthly` 先刪 NaN | 保留月份與缺值，引擎判斷 |
| T-8 | 三個月營收都齊仍要求年增率 | 只在需要補值時才計算 g_q |
| T-9 | 金融股不建 `eps` 欄，畫面連已公布 EPS 都沒有 | `eps.reported` 對所有股票都填 |
| T-10 | 舊引擎 `va.estimate()` 在新卡片例外保護之前執行 | 兩引擎分開 try；改版後畫面不依賴舊引擎成功 |
| T-11 | `cap_reduction` 有 177 筆 m=None | 實作前先查清楚（現金減資／彌補虧損），能補 m 的補；補不了的按 4-2 剔除區間 |
| T-12 | 2015～2020 原始收盤只有約 426 檔 | PB 全歷史不足的股票照實用現有月份；要補請用 TWSE／TPEx 歷史月表另開工作 |
| T-13 | 業外占比用淨額，正負互抵變 0 | 閘門同時看絕對值占比（\|業外\| 合計 ÷ \|稅前\| 合計） |
| T-14 | 單位：月營收、財報、股數單位要一致（元／千元、股／千股） | 載入時統一成元、股，寫單元測試 |
| T-15 | 金融股累計轉單季用「年內單調不減」猜口徑，缺值會補成 Q1（`factors._deaccum_ytd`） | 依來源欄位明確判斷累計／單季；缺值維持 NaN；只有確定是 Q1 才保留原值 |
| T-16 | loader 權益欄可能誤用損益表歸母淨利 | 合併前把損益表欄改名 `ni_parent`；權益只從資產負債表取 |
| T-17 | 事件檔缺失／損壞靜默變成「沒有事件」 | 載入失敗要報錯並停用依賴事件的估值 |
| T-18 | 個股財報合併沒去重 | 各表依 (ticker, period_end) 去重、一對一合併驗證 |
| T-19 | 隱含股數單季跳動（607 季次）| 試算股數＝最新季隱含股數，但與前一季差 >10% 且無股數事件 → 改用前一季並標示；與股本 ÷ 面額差 >10% → 降級 |
| T-20 | 季報正負號錯、營收 ≤0、毛利 > 營收、月營收異常暴增 | 這些季／月標「不可用」，不進試算與年增率 |
| T-21 | 分類用未調整 EPS | `build_classification` 輸入先 `adjust_eps` |
| T-22 | 季更閘門只數資料列 | 涵蓋率改算必要欄位（EPS、營收、歸母淨利）有效的股票；成功率 <90% 不寫檔；允許同季重建（**11/14 前修**） |
| T-23 | 前瞻 EPS 遠高於近 4 季沒有偵測（B10，5289 前瞻 420 vs 近 4 季 183） | 沿用 `detect.forward_jump`（`FWD_JUMP_REL=1.5`，tw-hold `c5bffce`）：前瞻 EPS 用在購買區間上緣或前瞻三價時都要套；觸發就降可信度並寫原因。門檻 1.3／1.5／2.0 全市場觸發 122／67／24 檔 |

## 15. 全站名詞對照（11/2 晚定；來源 `terms/p2_sol_out.md`，Opus 縮短名稱）

> 原則：一個名詞＝一個定義＝一個引擎欄位。不同算法刻意並存時，名稱必須分開；只改畫面文字，**不改改版範圍外的算法與 schema 欄名**。

### 15-1 估值與獲利

| 概念 | 統一寫法 | 來源 | 禁用（畫面） |
|---|---|---|---|
| 最近連續 4 季、可含 1 季試算 | 近 4 季 EPS | `eps.ttm.eps` | TTM EPS、過去 4 季、近四季 |
| 4 季全是已公布財報 | 已公布 4 季 EPS | `eps.reported.eps`（候選池、體檢的舊 TTM 數字也叫這個） | TTM EPS、4 季實際 |
| 往前推一季的 4 季 | 前瞻 4 季 EPS | `eps.fwd.eps` | 前瞻 EPS（不帶 4 季）、未來 4 季、EPS_NC |
| 季的類別 | 實際／試算 | `QuarterRow.kind` | 推算、預測、成長預測、沿用前瞻 |
| 循環股三價的基準 | 較低獲利（近 4 季與 3 年平均取低） | `prices.base_name` | 直接叫近 4 季 EPS |
| 主三價 | 三價（相對自身歷史）：便宜價／合理價／昂貴價 | `prices` | 類型參考三價、補位價 |
| 位置 | 便宜區／合理區／昂貴區 | `position` | 其他模組用「便宜區」 |
| 前瞻三價 | 前瞻便宜價／前瞻合理價／前瞻昂貴價 | `fwd_prices` | 成長價、情境價 |
| 購買區間 | 購買區間 X～Y | `buy_range` | 購買參考價、買進區間、買入區間 |
| 倍數百分位 | 歷史 20%／50%／80% 位置的本益比（或股價淨值比） | `prices.mults` | P20／P50／P80、「歷史股價 20%」 |
| 有效月數／虧損月數 | 分開兩個詞 | `prices.n_valid`；虧損月另算 | 用虧損月數代稱無效月 |
| B 層門檻 | 反推 EPS 門檻 | `b_tier.eps_needed` | 合理 EPS |
| B 層產業比較 | 同產業本益比排名（百分位，n 家） | `b_tier.industry_pct`、`n_peers` | — |
| 本益比 | 本益比（自建）；現價本益比；前瞻本益比；交易所本益比（核對用） | `multiples_hist`、`pe_now`、`pe_fwd`、`pe_exchange` | PE、PER、per（使用者文字） |
| 股價淨值比 | 股價淨值比；每股淨值 | `multiples_hist.pb`、`bvps` | PB、PBR（使用者文字） |
| 營業費用率 | 營業費用率 | `opex_last` | 費損率、費用率 |
| 可信度四組 | 資料／股數基準／歷史可比性／試算；狀態：正常／提醒／停用／未檢查 | `status.*` | 高／中／低可信度、降級 |
| 上修 | 前瞻上修／前瞻下修（比上月 ±x%，連續 n 個月） | `revision` | 換季寫「窗口更換，本月不比較」；財報替換寫「改用財報，本月不比較」，不顯示 0% |

### 15-2 成長、價格、風控（含改版範圍外，只改名）

| 概念 | 統一寫法 | 來源 | 禁用（畫面） |
|---|---|---|---|
| 單月營收 | 最新月營收年增；月營收月增 | `growth.yoy_revenue`；`mom` | 月營收 YoY、裸稱「年增」「月增」 |
| 當季已公布月份 | 本季營收年增（已公布 n 個月） | `growth.yoy_revenue` | 近 3 月年增（指本季時） |
| 年初至今 | 今年累計營收年增 | `cum_yoy`（11/2 核對：曆年 1 月至當月 ÷ 去年同期，MOPS 與自算同窗口） | 裸稱「累計年增」 |
| EPS 年增 | 季 EPS 年增／近 4 季 EPS 年增／前瞻 EPS 年增；例外詞照第 6 節 | `growth.yoy_eps` | 季 EPS YoY；虧損擴大顯示正百分比 |
| CAGR | 「近 5 年 EPS 年複合成長」等，期間＋指標都寫 | 既有模組 | 裸稱 CAGR、成長率 |
| 現價 | 現價（日期） | 同一個價格快照 | 不帶日期的「股價」「收」混用 |
| 價值清單買價 | 價值買價（＝ normalized EPS × 歷史 30% 本益比） | `cheap_threshold`，算法不動（11/2 核對：價值清單沒有 `est_buy_price`，app 的「買價」就讀這欄，`streamlit_app.py:1193`） | 便宜門檻、估值買價、便宜區 |
| 價值上緣 | 價值上緣（＝ 已公布 4 季 EPS × 歷史 70% 本益比） | `valuation_ceiling` | 估值上緣 |
| 定存清單買價 | 定存買價 | `est_buy_price`（定存），算法不動 | 估值買價、買價 |
| 清單上下界 | 價值買價上下限／定存買價上下限 | `buy_low`／`buy_high` | 買入區間 |
| 候選池停損 | 進場停損（候選池）；移動停損（候選池） | `risk_stop`；`swing_stops.stop` | 停損參考位、裸稱停損 |
| 個股頁停損 | 週線進場停損；週線持股停損 | `rk.stop`；`hd.line` | 停損參考、持股停損（不帶週線） |
| 短線停損 | 訊號停損 | tw-swing `stop` | 裸稱停損 |
| 停損模擬統計 | 每段統計前寫是哪一種停損 | — | 兩種停損共用一句「半年模擬」 |
| 支撐 | 50 日線支撐；大量區支撐／大量區壓力 | `dist_50ma`；`sup_px`／`res_px` | 裸稱支撐、壓力 |
| 均線 | 年線（240 日）；200 日線 | 各圖表常數 | 200 日也叫年線 |
| 市況 | 週線市況：多頭／震盪／空頭（候選池）；均線位置：偏多／貼近／偏空（總經） | `regime`；`market_status` | 兩套共用多頭／空頭 |
| 殖利率 | 現金殖利率；美債殖利率（天期） | 既有 | 裸稱殖利率 |
| 配息率 | 近 4 季配息率 | `payout_ratio_ttm` | 配息率 TTM |
| 法人 | 法人近 20 日淨買超（張） | `inst_net20`（顯示換算張） | 股、金額混用 |
| 趨勢模板 | 趨勢模板 8 項（候選池）；趨勢模板 7 項（體檢，不含相對強弱） | 既有 | 兩處都叫 Minervini 趨勢模板 |

### 15-3 測試

| 測試 | 內容 |
|---|---|
| `test_glossary_禁用寫法` | 掃 `app/`、`screener/`、`build_*.py` 的非 docstring 中文字串（同 `terms/ui_strings.txt` 抽法），15-1／15-2 禁用寫法不得出現；白名單只放程式內部訊息 |
| `test_glossary_同名同源` | 估值卡、展開區、匯出（複製給 AI）的「近 4 季 EPS」「合理價」「購買區間」數值相同 |

### 15-4 河流圖與三軌體檢的本益比（G1，使用者 11/2 晚定案，列入上線範圍）

現況問題（`app/stockcharts.py:246–278`、`app/checklist.py:392`）：EPS＝含息還原收盤（`bundle_data.prices` 讀 `prices_adj`）÷ 交易所 per 反推 → 越早期 EPS 越低、河道下偏（同 2881 −11% 問題）；河道用 10／30／50／70／90 分位、期間＝圖上可見範圍，與估值卡不同。

| 項目 | 改法 |
|---|---|
| EPS | 財報「已公布 4 季 EPS」逐季階梯（`eps.reported` 同源；歷史各月底取當時已可見的 4 季，可見日照第 4 節），**不用試算、不反推** |
| 股價 | 原始收盤＋只做股數調整（不含息），與第 4 節自建倍數同一個 `share_basis` |
| 河道倍數 | 讀 `build_card` 的 `prices.mults` 與倍數窗（20／50／80，期間同估值卡）；PB 路線改畫股價淨值比河道（每股淨值 × 倍數） |
| 圖例 | 「已公布 4 季 EPS × 歷史 20%／50%／80% 本益比」；估值卡三價用近 4 季 EPS，兩者差異寫在圖下來源欄一行 |
| 無倍數窗（B／C／D 層） | 只畫股價與 EPS，不畫河道，寫原因 |
| 三軌體檢 PE 分位 | 改讀 `multiples_hist` 的自建本益比分位；名稱「本益比歷史位置（自建）」 |
| 交易所 per | 只留在核對（第 4-5 節），畫面不再用 |

| 測試 | 預期 |
|---|---|
| `test_river_用原始價` | 有除息的合成股，除息前河道不因還原下偏（EPS 序列＝財報值） |
| `test_river_倍數同估值卡` | 河道三條線的倍數 == `build_card().prices.mults` |
| `test_checklist_pe分位_自建` | 體檢 PE 分位讀 `multiples_hist`，不讀 per |

### 15-5 說明文字寫錯的事實（改版前獨立小批，只改字）

| # | 問題 | 位置 | 改法 |
|---|---|---|---|
| F1 | 體檢說「門檻與定存清單一致」，但體檢用連配 ≥7 年、負債比 ≤45%，清單是 ≥5 年、≤75% | `app/checklist.py:232,260`、`screener/screen.py:126`、`build_factors.py:469`、`app/streamlit_app.py:3051` | 11/2 已查：清單＝連續配息 ≥5 年、負債比 ≤75%（金融業產業中位數 ×1.1，`screen.py:112–130`）。體檢門檻不動、刪「一致」，改寫「體檢比清單嚴（7 年、45%），是參考檢核」 |
| F2 | 價值清單說明兩套換股日期（3／6／9／12 月 vs 3/31、5/15、8/14、11/14） | `app/streamlit_app.py:174,177` | 以實際換股日為準 |
| F3 | 96%（持股停損）與 45%（固定停損）兩段統計沒寫是哪一種 | `app/streamlit_app.py:2097,2487` | 各自標明 |
| F4 | 美股個股：「抓取當下最新成交價」vs 舊文「常規盤收盤」 | `app/streamlit_app.py:4071,4094` | 刪舊文（10/23 已改抓取當下價） |
| F5 | 法人淨買超單位：欄名「股」、卡片「張」、說明「金額」 | `app/streamlit_app.py:89,306`、`screener/candidate_pool.py:241` | 11/2 已修（tw-hold `2f4c5a6`）：值本來就是股數，「複製給 AI」欄名「（股）」正確不動；卡片換算張正確；只改說明「金額」→「股數（畫面換算成張）」。F1～F4 同 commit 已修 |
