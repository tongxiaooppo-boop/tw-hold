"""季報前處理：現金流單季化、TTM、產業名正規化（估值分類框架，2026-11-01 Opus 定介面）。

依據：`D:\\g\\claude\\估值定義定案草案.md` §8.7（資料驗證結果）。
全部是純函式：不讀檔、不連網。讀檔在 `reference/loader.py::load_quarterly()`，
組裝在之後的 `build_classification.py`。

## 介面約定（不准改；覺得有問題停下回報）

- 季別一律用**季末 Timestamp**（3/31、6/30、9/30、12/31，時間 00:00），與 `load_quarterly()` 的
  `period_end` 相同。
- `income.*`、`eps` 已是單季（§8.7 第 1 點實測），**不用**差分。
- `cashflow` 的 `ocf`／`icf`／`ocf_net`／`capex` 是**年初累計**（台灣依法），必須先經
  `to_single_quarter_cashflow` 差分成單季才可加總或算 TTM。
- 會計年度一律視為**曆年**（Q1＝3 月季末）。非曆年制公司（少數 KY）不在本模組處理，見回報「待決」。
- 缺值一律 NaN，**不補值、不猜**。
"""
from __future__ import annotations

import pandas as pd

# 年初累計、要差分成單季的現金流欄位
CUMULATIVE_CF_COLS: tuple[str, ...] = ("ocf", "icf", "ocf_net", "capex")

# 差分前的原始累計值另存成 f"{col}{YTD_SUFFIX}"
YTD_SUFFIX = "_ytd"

# ── 產業分組（草案 §1.1 第 1、2 步、§8.7 第 2 點）──────────────────────────
# industry_group() 的四種輸出
GROUP_FINANCIAL = "financial"
GROUP_BIOTECH = "biotech"
GROUP_CONSTRUCTION = "construction"
GROUP_OTHER = "other"

# 對照表：universe.industry 原文（去頭尾空白後）→ 分組。表外一律 GROUP_OTHER。
# 只收草案 §8.7 第 2 點明列的名稱；實際資料若出現其他寫法（例「建材營造業」），
# 要由 Opus 決定後補進來，不要在實作時自行擴充。
# 2026-11-01 Opus 審後決定：「化學生技醫療」是櫃買把化學與生技混在一起的分類，化學股連續虧損
# 不該被當生技退出 → 不收進 biotech（落到 other；真生技仍由「生技醫療業」涵蓋）。
INDUSTRY_GROUP_MAP: dict[str, str] = {
    "金融保險": GROUP_FINANCIAL,
    "金融業": GROUP_FINANCIAL,
    "生技醫療業": GROUP_BIOTECH,
    "建材營造": GROUP_CONSTRUCTION,
}

# 重複寫法 → 統一名稱（產業營收指數 rev_index 分組用；§8.7 第 2 點）。
# 表外名稱原樣保留（只去頭尾空白）。
INDUSTRY_ALIASES: dict[str, str] = {
    "創新版股票": "創新板股票",
    "創新板股票": "創新板股票",
    "其他電子類": "其他電子業",
    "其他電子業": "其他電子業",
    "觀光事業": "觀光餐旅",
    "觀光餐旅": "觀光餐旅",
    "金融業": "金融保險",
    "金融保險": "金融保險",
}


def to_single_quarter_cashflow(q: pd.DataFrame,
                               cols: tuple[str, ...] = CUMULATIVE_CF_COLS) -> pd.DataFrame:
    """把年初累計的現金流欄位差分成單季值。

    輸入
      q：至少有 `ticker`、`period_end`（季末 Timestamp）兩欄，可含多檔、任意排序；
         其他欄位原樣帶出。
      cols：要差分的欄位；q 裡不存在的欄位**靜默略過**（不新增該欄）。

    輸出
      新 DataFrame（不改動輸入），依 (ticker, period_end) 遞增排序、index 重設為 0..n-1。
      對 cols 中每個存在的欄位 c：
        - 新增 f"{c}_ytd"＝原始累計值（原樣）。
        - c 改成單季值：
            Q1（period_end 月份＝3）：單季＝累計值本身（不差分）。
            Q2～Q4：單季＝本季累計 − **同 ticker、同曆年、前一季**的累計。
              前一季那一列不存在（缺季）、或兩者任一為 NaN → NaN。
              （不往前跳季找：缺 Q2 時 Q3 也是 NaN，Q4＝Q4 累計 − Q3 累計照算。）
      差分結果可為負（例如 capex 累計值修正），原樣保留。

    錯誤
      - 缺 `ticker` 或 `period_end` 欄 → KeyError。
      - 任何 period_end 不是季末（月份不在 3/6/9/12 或日不是該月最後一天）→ ValueError。
      - 同 (ticker, period_end) 重複 → ValueError（應先由 load_quarterly 去重）。
    """
    for need in ("ticker", "period_end"):
        if need not in q.columns:
            raise KeyError(need)
    pe = pd.to_datetime(q["period_end"])
    # 季末檢查：月份在 3/6/9/12 且為該月最後一天
    bad = ~(pe.dt.month.isin([3, 6, 9, 12]) & pe.dt.is_month_end)
    if bad.any():
        raise ValueError(f"period_end 不是季末：{pe[bad].iloc[0]}")
    if q.duplicated(["ticker", "period_end"]).any():
        raise ValueError("(ticker, period_end) 有重複")

    out = q.copy()
    out["period_end"] = pe
    out = out.sort_values(["ticker", "period_end"]).reset_index(drop=True)
    year = out["period_end"].dt.year
    is_q1 = out["period_end"].dt.month == 3
    key = pd.MultiIndex.from_arrays([out["ticker"], out["period_end"]])
    # 前一個季末（缺季不往前跳）；跨年（Q1 的前一季是去年 Q4）不用，Q1 直接取累計值
    prev_end = out["period_end"] - pd.offsets.QuarterEnd(1)
    prev_key = pd.MultiIndex.from_arrays([out["ticker"], prev_end])
    same_year = (prev_end.dt.year == year).to_numpy()
    for c in cols:
        if c not in out.columns:
            continue
        cum = out[c].astype(float)
        out[f"{c}{YTD_SUFFIX}"] = cum
        prev = pd.Series(cum.to_numpy(), index=key).reindex(prev_key).to_numpy()
        single = pd.Series(cum.to_numpy() - prev, index=out.index).where(same_year)
        out[c] = cum.where(is_q1, single)
    return out


def ttm(series: pd.Series, n: int = 4) -> pd.Series:
    """單季序列 → 近 n 季滾動加總（TTM）；只在「連續 n 季都有值」時給值。

    輸入
      series：單一檔股票的單季值，index 為季末 Timestamp（DatetimeIndex），須**嚴格遞增**。
      n：季數，預設 4（≥1 的整數）。

    輸出
      與輸入同 index、同 name 的 float Series。位置 t 的值＝t 往前（含 t）n 個**曆季**的加總，
      條件是：這 n 個曆季在 index 裡都存在，且值都不是 NaN；否則 NaN。
      例：index 缺 2024Q3 → 2024Q3..2025Q2 涵蓋到它的 4 個 TTM 都是 NaN
      （不是「往前取 4 列」，是「往前 4 個曆季」）。

    錯誤
      - index 不是 DatetimeIndex、不嚴格遞增（含重複）→ ValueError。
      - n < 1 → ValueError。
    """
    if n < 1:
        raise ValueError("n 必須 >= 1")
    if not isinstance(series.index, pd.DatetimeIndex):
        raise ValueError("index 必須是 DatetimeIndex")
    if not series.index.is_monotonic_increasing or not series.index.is_unique:
        raise ValueError("index 必須嚴格遞增")
    if len(series) == 0:
        return series.astype(float).copy()
    # 轉成曆季 Period、補齊缺季（NaN）後做 rolling，所以涵蓋缺季的窗都是 NaN
    per = series.index.to_period("Q")
    s = pd.Series(series.to_numpy(dtype=float), index=per)
    full = pd.period_range(per[0], per[-1], freq="Q")
    r = s.reindex(full).rolling(n, min_periods=n).sum()
    return pd.Series(r.reindex(per).to_numpy(), index=series.index, name=series.name)


def last_n_quarters(series: pd.Series, n: int) -> pd.Series | None:
    """最後 n 個連續曆季皆有值才回傳，保留原索引。"""
    ttm(series, n)
    tail = series.tail(n)
    if len(tail) < n or tail.isna().any():
        return None
    if n > 1 and not (tail.index.to_period("Q").asi8[1:] -
                      tail.index.to_period("Q").asi8[:-1] == 1).all():
        return None
    return tail


def panel_ttm(df: pd.DataFrame, col: str, n: int = 4,
              by: str = "ticker", date: str = "period_end") -> pd.Series:
    """逐檔依日期排序計算曆季 TTM，結果對齊輸入列。"""
    if n < 1:
        raise ValueError("n 必須 >= 1")
    if df.duplicated([by, date]).any():
        raise ValueError("(by, date) 有重複")
    out = pd.Series(float("nan"), index=range(len(df)), dtype=float)
    if col in df.columns:
        work = df.reset_index(drop=True)
        for _, g in work.groupby(by, sort=False):
            g = g.sort_values(date)
            series = pd.Series(g[col].to_numpy(), index=pd.DatetimeIndex(g[date]))
            out.iloc[g.index] = ttm(series, n).to_numpy()
    return pd.Series(out.to_numpy(), index=df.index, dtype=float)


def panel_lag(df: pd.DataFrame, col: str, k: int,
              by: str = "ticker", date: str = "period_end") -> pd.Series:
    """取同檔往前 k 個曆季的值，缺季保留 NaN。"""
    if k < 1:
        raise ValueError("k 必須 >= 1")
    if df.duplicated([by, date]).any():
        raise ValueError("(by, date) 有重複")
    out = pd.Series(float("nan"), index=range(len(df)), dtype=float)
    if col in df.columns:
        work = df.reset_index(drop=True)
        for _, g in work.groupby(by, sort=False):
            per = pd.DatetimeIndex(g[date]).to_period("Q")
            values = pd.Series(g[col].to_numpy(dtype=float), index=per)
            out.iloc[g.index] = values.reindex(per - k).to_numpy()
    return pd.Series(out.to_numpy(), index=df.index, dtype=float)


def industry_group(name: object) -> str:
    """產業名 → 分組：GROUP_FINANCIAL／GROUP_BIOTECH／GROUP_CONSTRUCTION／GROUP_OTHER。

    規則：str 先去頭尾空白後查 INDUSTRY_GROUP_MAP；查不到、None、NaN、非字串 → GROUP_OTHER。
    不做模糊比對（不用 `in`／startswith），避免「其他金融」之類誤收。
    不會丟例外。
    """
    if not isinstance(name, str):
        return GROUP_OTHER
    return INDUSTRY_GROUP_MAP.get(name.strip(), GROUP_OTHER)


def normalize_industry(name: object) -> str | None:
    """產業名正規化（產業營收指數分組用）：去頭尾空白後查 INDUSTRY_ALIASES，查不到原樣回傳
    （已去空白）。None、NaN、空字串、非字串 → None（呼叫端應排除這些股票，不建產業指數）。
    不會丟例外。
    """
    if not isinstance(name, str):
        return None
    s = name.strip()
    if not s:
        return None
    return INDUSTRY_ALIASES.get(s, s)
