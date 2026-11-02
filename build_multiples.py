"""全市場自建倍數月度序列（估值 2.0，upgrade_guide §2-1、§4、§5-4）。

【框架由 Opus 定，實作者不得改 CLI、輸入、產出 schema、例外規則】P2 實作。
rebuild 時在 build_classification 之後、build_lists 之前跑（P5 才接 workflow）。

用法：python build_multiples.py [--asof YYYY-MM-DD] [--tickers 2330,2327] [--out-dir data/derived] [--workers N]
  --asof 預設今天（台北日期）；--tickers 只跑這些（仍寫產出，給除錯用）；--workers 預設 max(1, cpu−1)。

輸入（P2 先用本機檔，P5 換 bundle `monthly_raw_close`）：
- 母體／產業／金融：data/derived/stock_class.json 的 ["stocks"]（ticker、industry、industry_group；
  industry_group=="financial" → financial=True）
- 季報：reference.loader.load_quarterly(live=True) → reference.corporate_actions.adjust_eps(q)
- 月營收：data/upstream/revenue.parquet（ticker, month "YYYY-MM", revenue）→ index＝月初 Timestamp
- 原始收盤：data/upstream/prices_raw_close.parquet（ticker 帶 .TW/.TWO, date, close）→ multiples_self.monthly_closes
- 交易所 PER：data/upstream/per.parquet（ticker 裸, date, per）；先只留月底交易日再傳入，省記憶體

產出（--out-dir，全部先寫暫存檔、全部成功才一起取代舊檔）：
- multiples_hist.parquet：multiples_self.HIST_COLUMNS，全市場串接
- eps_revision.parquet：ticker, month "YYYY-MM", window(str|None), eps_fwd, n_est_q(int), event
  · 只做非金融股；月份＝last_complete_month(asof) 往前 24 個月起、到「11 日 ≤ asof」的最後一個月
  · 每月一筆，asof_m＝該月 11 日（月營收 10 日可見之後），fwd_window(live=False)
  · window＝f"{第一季}-{最後一季}"（例 "2026Q1-2026Q4"），窗口 ok=False → window=None、eps_fwd=NaN、n_est_q=0
  · event＝multiples_self.revision_event(上一列, 本列)，actual_qs＝窗口內 kind=="actual" 的季
- industry_pe.json：{"asof", "month", "industries": {產業: {"median_pe": float, "n": int}}}
  · 樣本＝非金融股、last_complete_month(asof) 那一列 valid_pe=True 的 pe（P3 再依分層篩）
- multiples_check.json（§4-5）：
  · {"asof", "n_tickers", "n_ok", "n_failed", "failed": [{ticker, error}], "no_price": [ticker…],
     "pe_vs_exchange": {"n_compared", "abs_median_p50", "abs_median_p90", "abs_median_max",
                        "warn": [{ticker, median_diff, n_months}]},
     "split_jumps": [{ticker, date, type, m, pe_before, pe_after, pb_before, pb_after}]}
  · 比對月份＝n_est_ttm==0、pe 與 pe_exchange 都有限、前後 3 個月內（月份差 ≤3）沒有任何股數事件；
    每檔 median_diff＝median(pe ÷ pe_exchange − 1)，比對月 ≥6 才算；|median_diff| > 0.02 進 warn（依絕對值大到小）
  · split_jumps：type ∈ {split, par_change} 且 m 有限 ≠1 的事件，比事件前一個月 vs 事件當月（或後一個月，
    事件當月月底在事件日之前時）的 pe、pb，任一比值偏離 1 超過 5% 才列
例外：任何一檔例外 → 記進 failed 並跳過；failed 檔數 > 母體 1% → 印出、exit 1、不覆寫任何舊檔。
share_basis.EventsUnavailable → 直接 exit 1（不可當成沒事件）。
"""
from __future__ import annotations


def main(argv: list[str] | None = None) -> int:
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
