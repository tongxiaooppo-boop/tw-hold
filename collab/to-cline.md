# 任務書：B1 個股估值標籤（轉機股／景氣循環股／一般）＋全市場分類掃描（2026-10-30，Opus 定框架）

> 背景一句話：估值速覽的「成長價」＝預估 EPS × 目前本益比，會跟股價等比例變動；對「剛轉盈、近四季微利」和「景氣循環股」特別失真。之後要依標籤給不同的估值卡。**這一輪只做：標籤函式＋測試＋全市場分類報表。不改買進區間、不改 UI。**

做完要：`pytest` 全綠、分類報表產出、本機 `git commit`（不 push）、寫回報到 `collab/from-cline.md`（整檔覆蓋）。

**不准用網路搜尋、網頁抓取、瀏覽器工具。** 檔案只能建在本專案目錄內。

## 要讀的檔案（只准讀這些）

| 檔案 | 範圍 |
|---|---|
| `app/valuation.py` | 第 38–64 行（常數）、第 79–95 行（`_quarters`）、第 156–165 行（`_cycle_block`，寫法參考）、第 423–432 行與第 495–560 行（`estimate` 開頭與回傳） |
| `tests/test_valuation.py` | 第 1–12 行（import）、第 312–316 行（`test_estimate_有買進區間欄位`，寫法參考） |

不准讀其他檔案。`app/bundle_data.py`、`factors/factors.py` 不用讀，照第 3 步貼的程式呼叫即可。

## 第 1 步：`app/valuation.py` 新增常數與 `stock_label`（介面不准改）

常數放在現有常數區最後（`VP_NODE_RATIO` 下面）：

```python
TURN_GROWTH_X = 2.0             # 今年預估 EPS ≥ 近四季 × 這個 → 轉機股（基期太低）
CYCLE_OM_SPREAD = 0.20          # 近 24 季營益率 最高 − 最低 ≥ 20 個百分點 → 景氣循環股
CYCLE_EPS_DROP = 0.40           # 近 6 個完整年度裡，某年 EPS 比之前最高年少 ≥ 40% → 景氣循環股
LABEL_EPS_YEARS = 6
LABEL_MIN_EPS_YEARS = 3
```

函式放在 `buy_range` 前面，docstring 照抄：

```python
def stock_label(q: pd.DataFrame, est_eps: float | None) -> dict:
    """估值標籤（2026-10-30 使用者與 Opus 討論定案，門檻待全市場掃描後再調）：
    轉機股優先於景氣循環股，兩者都不符合＝一般。q 是 `_quarters()` 的輸出（用到 period_end、
    revenue、op_income、eps）。

    轉機股（turn_why，任一成立）：
      - 近四季 EPS 合計 ≤ 0
      - 近四季有任一季 EPS < 0（要連續 4 季獲利才脫離，等於自帶緩衝）
      - 近四季合計 > 0 且 今年預估 EPS ≥ 近四季合計 × TURN_GROWTH_X
      「近四季」＝q 最後 4 列，必須首尾相隔正好 3 季且 eps 都不是 NaN，否則 ttm_eps=None、
      這三條都不判。
    景氣循環股（cycle_why，任一成立）：
      - 近 CYCLE_QUARTERS 季（revenue > 0 的季，營益率＝op_income/revenue，去掉 NaN）
        至少 CYCLE_MIN_QUARTERS 季，且 最高 − 最低 ≥ CYCLE_OM_SPREAD
        （om_n＝實際季數；不足 CYCLE_MIN_QUARTERS 季 → om_min、om_max 都給 None、不判）
      - 完整年度（該年 4 季都在、eps 都不是 NaN）取最後 LABEL_EPS_YEARS 年，至少
        LABEL_MIN_EPS_YEARS 年；依年份排序，對第 2 年起每一年 i：之前各年最高 EPS > 0 時，
        跌幅＝1 − EPS_i ÷ 之前最高（EPS_i ≤ 0 時跌幅 ≥ 1，照公式算即可）；
        max_drop＝所有跌幅的最大值（都沒有可算的 → 0.0）；max_drop ≥ CYCLE_EPS_DROP 成立。
        年數不足 → max_drop=None、不判。

    回傳：
      {"label": "turnaround" | "cyclical" | "normal",
       "turn_why": list[str], "cycle_why": list[str],
       "ttm_eps": float | None,
       "om_min": float | None, "om_max": float | None, "om_n": int,
       "eps_years": [{"year": int, "eps": float}, ...],   # 最後 LABEL_EPS_YEARS 個完整年度（不足 3 年也照列），依年份
       "max_drop": float | None,
       "drop_from": int | None, "drop_to": int | None}    # 最大跌幅是哪一年（之前最高）→ 哪一年
    why 字串（給 UI 直接顯示，照這個格式）：
      "近四季 EPS 合計 {ttm:.2f} ≤ 0"
      "近四季有虧損季"
      "今年預估 EPS {est:.2f} ≥ 近四季 {ttm:.2f} 的 2 倍"
      "近 {n} 季營益率 {min:.0%}～{max:.0%}"
      "年 EPS 從 {drop_from} 年 {a:.2f} 掉到 {drop_to} 年 {b:.2f}"
    """
```

`estimate()` 只加一件事：回傳 dict 多一個鍵 `"label": stock_label(q, est_eps)`。**其他邏輯（buy_range、growth_price、risk）一行都不准動。**

## 第 2 步：`tests/test_valuation.py` 加測試（預期值照抄，不准拿程式輸出回填）

在檔案最後加一個建資料的 helper 和下列測試：

```python
def _lq(eps: list[float], om: list[float] | None = None, end: str = "2025-12-31") -> pd.DataFrame:
    """每季營收 10 億；eps 依序到 end 那一季；om 沒給＝每季 20%。"""
    pe = pd.date_range(end=end, periods=len(eps), freq="QE")
    om = om or [0.2] * len(eps)
    return pd.DataFrame({"period_end": pe, "revenue": 1e9, "op_income": [1e9 * m for m in om],
                         "eps": eps})
```

| 測試名 | 輸入 | 預期 |
|---|---|---|
| `test_標籤_穩定_一般` | `_lq([1.0]*24)`, est=4.0 | label=normal；om_min=om_max=0.2；max_drop=0.0；ttm_eps=4.0；eps_years 6 年 |
| `test_標籤_近四季虧損_轉機` | `_lq([1.0]*20 + [-0.5, -0.2, 0.1, 0.1])`, est=0.5 | label=turnaround；turn_why 含「近四季 EPS 合計 -0.50 ≤ 0」與「近四季有虧損季」 |
| `test_標籤_預估是近四季2倍_轉機_邊界含等號` | `_lq([1.0]*20 + [0.1]*4)`, est=0.8 | label=turnaround，turn_why 只有一條「今年預估 EPS 0.80 ≥ 近四季 0.40 的 2 倍」 |
| `test_標籤_預估不到2倍_不是轉機` | 同上，est=0.79 | turn_why == []（注意：這組年 EPS 從 4 掉到 0.4，cycle_why 會成立，label=cyclical） |
| `test_標籤_年EPS大跌_景氣循環` | 年 EPS [2,4,8,4,5,6]（每年 4 季平均分配，2020～2025），est=6.0 | label=cyclical；max_drop=0.5（pytest.approx）；drop_from=2022、drop_to=2023；cycle_why 只有一條「年 EPS 從 2022 年 8.00 掉到 2023 年 4.00」 |
| `test_標籤_成長股_年EPS只升不跌_一般` | 年 EPS [2,3,4,5,6,7]，est=7.0 | label=normal；max_drop=0.0 |
| `test_標籤_跌30%_不算景氣循環` | 年 EPS [4,6,8,5.6,6,7]，est=7.0 | label=normal；max_drop=0.3（approx） |
| `test_標籤_營益率起伏大_景氣循環` | `_lq([1.0]*24, om=[0.05, 0.30]*12)`, est=4.0 | label=cyclical；cycle_why 只有一條「近 24 季營益率 5%～30%」 |
| `test_標籤_循環又有虧損季_轉機優先` | 年 EPS [2,4,8,4,5,6] 但最後一季改成 -0.1，est=6.0 | label=turnaround；cycle_why 仍非空（兩邊都記，label 取轉機） |
| `test_標籤_資料太短_不判循環` | `_lq([1.0]*6)`, est=4.0 | label=normal；om_n=6、om_min=None；max_drop=None；eps_years 只有 1 年（2025） |
| `test_標籤_近四季漏一季_不判轉機` | `_lq([1.0]*20 + [-1.0]*4)` 再刪掉倒數第 2 列，est=-1.0 | ttm_eps=None；turn_why == [] |
| `test_estimate_有標籤欄位` | 照 `test_estimate_有買進區間欄位` 的寫法呼叫 `va.estimate(...)` | `r["label"]["label"] in {"turnaround", "cyclical", "normal"}` |

年 EPS 列表轉季：`[e / 4 for e in years for _ in range(4)]`。`stock_label` 直接吃 `va._quarters(...)` 不行（`_lq` 沒有其他欄），測試裡直接把 `_lq(...)` 傳給 `va.stock_label`。

## 第 3 步：全市場分類掃描 `research/valuation_labels_2026-10-30/classify_all.py`

（`.clinerules` 的「不准讀 research/」不影響這個新資料夾，你是建立它。）照下面骨架寫，執行時 `cd` 到專案根目錄、`PYTHONIOENCODING=utf-8`：

```python
import sys, warnings; warnings.filterwarnings("ignore")
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "app"))
import pandas as pd, pyarrow.parquet as pq, pyarrow.compute as pc
import bundle_data as bd, valuation as v
from factors.factors import quarterly_factors
tickers = sorted(set(pc.unique(pq.read_table(ROOT / "data/upstream/per.parquet", columns=["ticker"])["ticker"]).to_pylist()))
for t in tickers:
    try:
        fin = bd.financials(t)
        if fin.empty: continue
        r = v.estimate(quarterly_factors(fin), bd.revenue(t), bd.prices(t), bd.per_history(t))
        if not r.get("ok"): continue
        ...  # 收集欄位
    except Exception:
        continue   # 計數，最後印出失敗幾檔
```

每檔收集：`ticker, label, turn_why（用「；」接）, cycle_why（同）, ttm_eps, est（r["year"]["est"]，year 為 None 給 NaN）, om_min, om_max, max_drop, cur_pe（r["cur_pe"]["pe"]）, buy_state（r["buy"]["state"]，buy 為 None 給空字串）, growth_price, price（r["price"]）`。

產出（都放在 `research/valuation_labels_2026-10-30/`）：
1. `labels.csv`：上面的全部欄位。
2. `summary.md`（中文），內容依序：
   - 掃描檔數、失敗檔數。
   - 三類檔數與占比。
   - 各類 × buy_state 的交叉表（檔數）。
   - 特徵分布：全體的 `om_max − om_min` 與 `max_drop` 的 10/25/50/75/90 百分位；以及「如果 CYCLE_OM_SPREAD 改 0.15／0.20／0.25、CYCLE_EPS_DROP 改 0.3／0.4／0.5」各組合下 cyclical 會有幾檔（3×3 表；轉機優先的規則照舊，只重算非轉機的那群）。
   - 指定檔：`2330 2317 2454 2603 2609 2615 1802 2408 2002 3481 6669 6588 8422 1301 2412`，每檔一列：代號、label、turn_why、cycle_why、ttm_eps、est、max_drop、om 區間、buy_state。
   - 每一類用 `random_state=0` 抽 10 檔，同上欄位。
   表格用 markdown 表格，數字取 2 位小數、百分比取整數。

`labels.csv` 和 `summary.md` 要 commit（小檔）；不要 commit 其他產物。

## 第 4 步：驗證與 commit

- `python -m pytest -q -p no:cacheprovider` 全綠（原本 759 passed，加上新測試）。
- `git add app/valuation.py tests/test_valuation.py research/valuation_labels_2026-10-30/`，commit 訊息：`估值標籤：轉機股／景氣循環股／一般（stock_label）＋全市場分類掃描`，結尾加一行 `Co-Authored-By: Cline <noreply@cline.bot>`。
- 不准 push。

## 回報（覆寫 `collab/from-cline.md`，要精簡，不貼程式碼）

1. commit hash、pytest 數字。
2. 三類檔數。
3. 指定檔那張表（直接貼）。
4. 需要 Opus 決定的事（例如某條規則在實際資料上邊界不清）。

## 不准做的事

- 不准改 `buy_range`、`growth_price`、`risk_levels`、`hold_stop`、任何 UI（`app/streamlit_app.py` 不准碰）。
- 不准改上面定的常數值、函式簽名、why 字串格式；覺得有問題寫進「需要 Opus 決定」。
- 測試預期值照表，跑不過先檢查實作，不准改預期值；確定是任務書寫錯就停下回報。
