"""自建營收指數、營收 beta、產業同步度（估值分類框架，2026-11-01 Opus 定介面）。

依據：`D:\\g\\claude\\估值定義定案草案.md` §1.2「自建營收指數」：
  每月取「當月與去年同月都有營收」的同樣本公司，加總算 TTM YoY（全市場一條、產業各一條，
  樣本 < 5 家不建）。beta＝個股對全市場；同步度＝個股與「排除自己的產業指數」相關。
  它是上市櫃樣本的營收景氣代理，不是 GDP beta；樣本只有現行上市櫃（存活者偏差，§8.7 第 4 點）。

純函式：不讀檔、不連網。

## 資料格式（介面，不准改）

monthly_rev（長表）：欄位 `ticker`(str)、`month`(月初 Timestamp，例 2024-06-01)、`revenue`(float，元)。
  - 呼叫端負責把 revenue.parquet 的 month 正規化成月初 Timestamp。
  - revenue ≤ 0 或 NaN 一律視為「該月無營收」。
  - 同 (ticker, month) 重複 → ValueError。

## 同樣本 TTM YoY 的算法（暫定，見回報「待決」1）

對月份 m：
  S_k＝月份 k 的同樣本＝在 k 與 k−12 個月都有營收的公司。
  num12(m)＝Σ_{k=m−11..m} Σ_{i∈S_k} rev_i(k)
  den12(m)＝Σ_{k=m−11..m} Σ_{i∈S_k} rev_i(k−12)
  n_min(m)＝min_{k=m−11..m} |S_k|
  ttm_yoy(m)＝num12/den12 − 1；若 n_min < min_members 或 den12 ≤ 0 → NaN。
（＝逐月同樣本、12 個月分子分母各自加總。新上市公司在滿 12 個月前不進樣本，
  所以不會造成假成長。）
"""
from __future__ import annotations

import pandas as pd

MIN_MEMBERS = 5                # 樣本 < 5 家不建（草案 §1.2）
REV_BETA_WINDOW = 120          # 【待決】beta／同步度用近幾個月；暫定 120（≈40 季，與 OROA 窗一致）
REV_BETA_MIN_OBS = 36          # 【待決】共同有效月數少於這個 → NaN

INDEX_COLS = ("num12", "den12", "n_min", "ttm_yoy")


def same_sample_components(monthly_rev: pd.DataFrame) -> pd.DataFrame:
    """逐月同樣本成分。

    輸出長表，欄位 `ticker, month, cur, prev`：
      每一列＝某公司在某月「當月 cur 與去年同月 prev 都 > 0」才出現（否則不出列）。
      依 (month, ticker) 遞增排序、index 0..n-1。
    錯誤：缺欄位 → KeyError；(ticker, month) 重複 → ValueError。
    """
    raise NotImplementedError


def build_market_index(monthly_rev: pd.DataFrame,
                       min_members: int = MIN_MEMBERS) -> pd.DataFrame:
    """全市場同樣本營收指數。

    輸出：index＝month（月初 Timestamp，遞增，涵蓋輸入出現過的最早到最晚月份、每月一列），
    欄位 INDEX_COLS：
      num12, den12（float）、n_min（int；12 個月內任一月沒有樣本＝0）、
      ttm_yoy（float；算法見檔頭；資料不夠 12 個月、n_min < min_members、den12 ≤ 0 → NaN）。
    錯誤：同 same_sample_components。
    """
    raise NotImplementedError


def build_industry_index(monthly_rev: pd.DataFrame, industry_map: dict[str, str],
                         min_members: int = MIN_MEMBERS) -> pd.DataFrame:
    """各產業同樣本營收指數。

    industry_map：ticker → 產業名（呼叫端先用 quarterly_prep.normalize_industry 正規化；
      值為 None 或 ticker 不在表內 → 該公司不進任何產業指數，但仍可進全市場指數）。
    輸出長表：欄位 `industry, month, num12, den12, n_min, ttm_yoy`，
      依 (industry, month) 遞增；每個產業的月份範圍＝輸入全體的最早到最晚月份。
      算法同 build_market_index，只是樣本限該產業。樣本不足的產業**仍出列**，ttm_yoy＝NaN。
    """
    raise NotImplementedError


def industry_index_excluding_self(industry_index: pd.DataFrame, monthly_rev: pd.DataFrame,
                                  ticker: str, industry: str,
                                  min_members: int = MIN_MEMBERS) -> pd.Series:
    """「排除自己」的產業指數 TTM YoY（同步度用）。

    從 build_industry_index 輸出中 industry 那一段，扣掉 ticker 自己的同樣本貢獻：
      num12' = num12 − Σ_{k=m−11..m, ticker∈S_k} rev_ticker(k)
      den12' = den12 − Σ_{k=m−11..m, ticker∈S_k} rev_ticker(k−12)
      n_min' = min_k (|S_k| − [ticker∈S_k])
      ttm_yoy' = num12'/den12' − 1；n_min' < min_members 或 den12' ≤ 0 → NaN。
    輸出：index＝month 的 float Series，name＝"ttm_yoy"。
    industry 不在 industry_index → 全 NaN 的空 Series（不丟例外）。
    """
    raise NotImplementedError


def stock_ttm_yoy(monthly: pd.Series) -> pd.Series:
    """單一個股的月頻 TTM 營收年增。

    monthly：index＝月初 Timestamp（遞增）、值＝營收；≤0 或 NaN 視為缺。
    輸出：同 index；位置 m ＝ Σ(m−11..m) ÷ Σ(m−23..m−12) − 1，
      這 24 個**曆月**都要有營收（>0），否則 NaN。
    錯誤：index 非 DatetimeIndex 或不嚴格遞增 → ValueError。
    """
    raise NotImplementedError


def revenue_beta(stock_ttm_yoy: pd.Series, market_ttm_yoy: pd.Series,
                 window: int = REV_BETA_WINDOW, min_obs: int = REV_BETA_MIN_OBS) -> float:
    """營收 beta＝個股 TTM YoY 對全市場 TTM YoY 的 OLS 斜率（含截距）。

    取兩序列 index 交集且兩者都非 NaN 的月份，再取其中最後 window 個月。
    斜率＝cov(s, m) / var(m)（樣本共變異／變異，ddof 一致即可）。
    有效月 < min_obs、或 market 在窗內變異數為 0 → NaN。不丟例外。
    """
    raise NotImplementedError


def industry_sync(stock_ttm_yoy: pd.Series, industry_index_excluding_self: pd.Series,
                  window: int = REV_BETA_WINDOW, min_obs: int = REV_BETA_MIN_OBS) -> float:
    """產業同步度＝個股 TTM YoY 與「排除自己的產業指數」TTM YoY 的 Pearson 相關係數。

    月份對齊、取窗、min_obs 規則同 revenue_beta；任一方窗內標準差為 0 → NaN。不丟例外。
    """
    raise NotImplementedError
