"""全市場自建倍數月度序列（估值 2.0，upgrade_guide §2-1、§4、§5-4）。

【框架由 Opus 定，實作者不得改 CLI、輸入、產出 schema、例外規則】P2 實作。
rebuild 時在 build_classification 之後、build_lists 之前跑（P5 才接 workflow）。

用法：python build_multiples.py [--asof YYYY-MM-DD] [--tickers 2330,2327] [--out-dir data/derived] [--workers N]
  --asof 預設今天（台北日期）；--tickers 只跑這些（仍寫產出，給除錯用）；--workers 預設 max(1, cpu−1)。

輸入（bundle 月收盤全歷史與近期日線合併）：
- 母體／產業／金融：data/derived/stock_class.json 的 ["stocks"]（ticker、industry、industry_group；
  industry_group=="financial" → financial=True）
- 季報：reference.loader.load_quarterly(live=True) → reference.corporate_actions.adjust_eps(q)
- 月營收：data/upstream/revenue.parquet（ticker, month "YYYY-MM", revenue）→ index＝月初 Timestamp
- 原始收盤：data/upstream/monthly_raw_close.parquet（存在才讀）∪ prices_raw_close.parquet
  （ticker, date, close）→ multiples_self.monthly_closes，取完整月份最後交易列
- 交易所 PER：data/upstream/fundamentals/per.parquet 優先，否則 data/upstream/per.parquet；
  ticker 裸, date, per；先只留月底交易日再傳入，省記憶體

產出（--out-dir，全部先寫暫存檔、全部成功才一起取代舊檔）：
- multiples_hist.parquet：multiples_self.HIST_COLUMNS，全市場串接
- eps_revision.parquet：ticker, month "YYYY-MM", window(str|None), eps_fwd, n_est_q(int), event
  · 只做非金融股；月份＝last_complete_month(asof) 往前 24 個月起、到「11 日 ≤ asof」的最後一個月
  · 每月一筆，asof_m＝該月 11 日（月營收 10 日可見之後），fwd_window(live=False)
  · window＝f"{第一季}-{最後一季}"（例 "2026Q1-2026Q4"），窗口 ok=False → window=None、eps_fwd=NaN、n_est_q=0
  · event＝multiples_self.revision_event(上一列, 本列)，actual_qs＝窗口內 kind=="actual" 的季
- industry_pe.json：{"asof", "month", "industries": {產業: {"median_pe": float, "n": int, "values": [float…]}}}
  · 樣本＝非金融股、last_complete_month(asof) 那一列 valid_pe=True 的 pe（P3 定：不再依分層篩）
  · values＝樣本 pe 由小到大、round 4（P3 新增：B 層產業百分位用）
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


import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import os
from pathlib import Path
import time

import numpy as np
import pandas as pd

from reference import corporate_actions as ca
from reference import loader
from reference import share_basis as sb
from screener import eps_windows as ew
from screener import multiples_self as ms


def _load_closes(asof, upstream: Path) -> pd.DataFrame:
    columns = ["ticker", "date", "close"]
    frames = []
    monthly = upstream / "monthly_raw_close.parquet"
    if monthly.exists():
        frames.append(pd.read_parquet(monthly, columns=columns))
    else:
        print("⚠️ 沒有 monthly_raw_close，原始收盤只從 prices_raw_close 起", flush=True)
    frames.append(pd.read_parquet(upstream / "prices_raw_close.parquet", columns=columns))
    return ms.monthly_closes(pd.concat(frames, ignore_index=True), pd.Timestamp(asof))


def _init_worker(asof: str, tickers: list[str]) -> None:
    global _DATA
    sb.events("")
    wanted = set(tickers)
    q = ca.adjust_eps(loader.load_quarterly(live=True))
    q["ticker"] = q["ticker"].astype(str)
    q = q[q["ticker"].isin(wanted)]
    rev = pd.read_parquet("data/upstream/revenue.parquet", columns=["ticker", "month", "revenue"])
    rev["ticker"] = rev["ticker"].astype(str)
    rev = rev[rev["ticker"].isin(wanted)].copy()
    rev["month"] = pd.to_datetime(rev["month"])
    closes = _load_closes(pd.Timestamp(asof), Path("data/upstream"))
    closes = closes[closes["ticker"].isin(wanted)]
    per_path = Path("data/upstream/fundamentals/per.parquet")
    if not per_path.exists():
        per_path = Path("data/upstream/per.parquet")
    per = pd.read_parquet(per_path, columns=["ticker", "date", "per"])
    per["ticker"] = per["ticker"].astype(str)
    per["date"] = pd.to_datetime(per["date"])
    per = per.merge(closes[["ticker", "date"]], on=["ticker", "date"], how="inner")
    _DATA = (dict(tuple(q.groupby("ticker"))),
             {t: r.set_index("month")["revenue"].sort_index() for t, r in rev.groupby("ticker")},
             dict(tuple(closes.groupby("ticker"))), dict(tuple(per.groupby("ticker"))), q.iloc[:0], closes.iloc[:0])


def _build_one(stock: dict, asof: str) -> tuple:
    ticker = str(stock["ticker"])
    try:
        qs, revenues, prices, pers, empty_q, empty_prices = _DATA
        q = qs.get(ticker, empty_q)
        monthly = revenues.get(ticker, pd.Series(dtype=float, index=pd.DatetimeIndex([])))
        closes = prices.get(ticker, empty_prices)
        financial = stock.get("industry_group") == "financial"
        mh = ms.build_history(ticker, q, monthly, closes, pers.get(ticker), financial=financial)
        revisions = []
        if not financial:
            end = ms.last_complete_month(pd.Timestamp(asof))
            last = pd.Timestamp(asof).to_period("M")
            if pd.Timestamp(asof).day < 11:
                last -= 1
            previous = None
            for month in pd.period_range(end - 24, last, freq="M"):
                date = month.start_time + pd.Timedelta(days=10)
                base = ew.ttm_window(q, monthly, asof=date, live=False)
                w = ew.fwd_window(q, monthly, asof=date, base=base, live=False)
                current = dict(window=f"{w.quarters[0].q}-{w.quarters[-1].q}" if w.ok else None,
                               actual_qs=tuple(r.q for r in w.quarters if r.kind == "actual") if w.ok else ())
                revisions.append(dict(ticker=ticker, month=str(month), window=current["window"],
                                      eps_fwd=w.eps if w.ok else np.nan, n_est_q=w.n_est if w.ok else 0,
                                      event=ms.revision_event(previous, current)))
                previous = current
        comparison, jumps = _check_one(ticker, mh)
        return ticker, mh, revisions, comparison, jumps, None
    except sb.EventsUnavailable:
        raise
    except Exception as exc:
        return ticker, None, [], None, [], f"{type(exc).__name__}: {exc}"


def _check_one(ticker: str, mh: pd.DataFrame) -> tuple:
    events = sb.events(ticker)
    if mh.empty:
        return None, []
    periods = pd.PeriodIndex(mh["month"], freq="M")
    eligible = (mh["n_est_ttm"] == 0) & np.isfinite(mh["pe"]) & np.isfinite(mh["pe_exchange"])
    for event in events:
        eligible &= np.abs(periods.asi8 - event["date"].to_period("M").ordinal) > 3
    rows = mh[eligible]
    comparison = dict(ticker=ticker, median_diff=float((rows["pe"] / rows["pe_exchange"] - 1).median()), n_months=len(rows)) if len(rows) >= 6 else None
    indexed = mh.set_index("month")
    jumps = []
    for event in events:
        m = event.get("m")
        if event.get("type") not in {"split", "par_change"} or m is None or not np.isfinite(m) or m == 1:
            continue
        month = event["date"].to_period("M")
        before_key, after_key = str(month - 1), str(month)
        if after_key in indexed.index and indexed.loc[after_key, "date"] < event["date"]:
            after_key = str(month + 1)
        if before_key not in indexed.index or after_key not in indexed.index:
            continue
        before, after = indexed.loc[before_key], indexed.loc[after_key]
        if any(ms._positive(before[k]) and ms._positive(after[k]) and abs(after[k] / before[k] - 1) > .05 for k in ("pe", "pb")):
            jumps.append(dict(ticker=ticker, date=event["date"].strftime("%Y-%m-%d"), type=event["type"], m=float(m),
                              **{f"{k}_{side}": float(row[k]) if np.isfinite(row[k]) else None
                                 for k in ("pe", "pb") for side, row in (("before", before), ("after", after))}))
    return comparison, jumps


def _publish_outputs(out: Path, outputs: dict) -> None:
    originals = {name: (out / name).read_bytes() if (out / name).exists() else None for name in outputs}
    replaced = []
    try:
        for name, value in outputs.items():
            temporary = out / (name + ".tmp")
            if name.endswith(".parquet"):
                value.to_parquet(temporary, index=False)
            else:
                temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        for name in outputs:
            os.replace(out / (name + ".tmp"), out / name)
            replaced.append(name)
    except Exception:
        # 取代途中失敗時，還原已取代的檔案，避免留下混合版本。
        for name in reversed(replaced):
            original = originals[name]
            if original is None:
                (out / name).unlink(missing_ok=True)
            else:
                temporary = out / (name + ".tmp")
                temporary.write_bytes(original)
                os.replace(temporary, out / name)
        raise
    finally:
        for name in outputs:
            (out / (name + ".tmp")).unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asof", default=pd.Timestamp.now(tz="Asia/Taipei").strftime("%Y-%m-%d"))
    parser.add_argument("--tickers")
    parser.add_argument("--out-dir", default="data/derived")
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 1) - 1))
    args = parser.parse_args(argv)
    asof = pd.Timestamp(args.asof).strftime("%Y-%m-%d")
    if args.workers < 1:
        parser.error("--workers 必須至少為 1")
    started = time.perf_counter()
    stocks = json.loads(Path("data/derived/stock_class.json").read_text(encoding="utf-8"))["stocks"]
    if args.tickers:
        wanted = set(args.tickers.split(","))
        stocks = [s for s in stocks if str(s["ticker"]) in wanted]
    tickers = [str(s["ticker"]) for s in stocks]
    histories, revisions, comparisons, jumps, failed, no_price = [], [], [], [], [], []
    try:
        sb.events("")
        with ProcessPoolExecutor(max_workers=args.workers, initializer=_init_worker, initargs=(asof, tickers)) as pool:
            futures = [pool.submit(_build_one, stock, asof) for stock in stocks]
            for count, future in enumerate(as_completed(futures), 1):
                ticker, mh, rev, comparison, split_jumps, error = future.result()
                if error:
                    failed.append(dict(ticker=ticker, error=error))
                else:
                    histories.append(mh)
                    revisions.extend(rev)
                    if mh.empty:
                        no_price.append(ticker)
                    if comparison is not None:
                        comparisons.append(comparison)
                    jumps.extend(split_jumps)
                if count % 50 == 0 or count == len(stocks):
                    print(f"完成 {count}/{len(stocks)}，失敗 {len(failed)}，耗時 {time.perf_counter() - started:.1f} 秒", flush=True)
    except Exception as exc:
        print(f"建置或寫檔失敗：{type(exc).__name__}: {exc}", flush=True)
        return 1
    failed.sort(key=lambda r: r["ticker"])
    if len(failed) > len(stocks) * .01:
        print(json.dumps(failed, ensure_ascii=False), flush=True)
        return 1
    hist = pd.concat(histories, ignore_index=True) if histories else pd.DataFrame(columns=ms.HIST_COLUMNS)
    hist = hist.sort_values(["ticker", "month"]).reset_index(drop=True)
    rev = pd.DataFrame(revisions, columns=["ticker", "month", "window", "eps_fwd", "n_est_q", "event"]).sort_values(["ticker", "month"])
    end = str(ms.last_complete_month(pd.Timestamp(asof)))
    industries = {}
    metadata = {str(s["ticker"]): s for s in stocks}
    sample = hist[(hist["month"] == end) & hist["valid_pe"].astype(bool)].copy()
    sample["industry"] = sample["ticker"].map(lambda t: metadata[t].get("industry", ""))
    sample = sample[sample["ticker"].map(lambda t: metadata[t].get("industry_group") != "financial")]
    for name, group in sample.groupby("industry"):
        industries[name] = dict(median_pe=float(group["pe"].median()), n=len(group),
                                values=[round(float(v), 4) for v in sorted(group["pe"])])
    diffs = np.array([abs(r["median_diff"]) for r in comparisons])
    closes = _load_closes(pd.Timestamp(asof), Path("data/upstream"))
    first = closes[closes["ticker"].isin(tickers)].groupby("ticker")["month"].min()
    first_dates = pd.to_datetime(first)
    first_month = {"p10": first_dates.quantile(.1).strftime("%Y-%m") if len(first) else None,
                   "p50": first_dates.quantile(.5).strftime("%Y-%m") if len(first) else None,
                   "n_from_2015": int((first <= "2015-03").sum())}
    checks = dict(asof=asof, n_tickers=len(stocks), n_ok=len(stocks) - len(failed), n_failed=len(failed),
                  closes_first_month=first_month,
                  failed=failed, no_price=sorted(no_price),
                  pe_vs_exchange=dict(n_compared=len(comparisons),
                      abs_median_p50=float(np.quantile(diffs, .5)) if len(diffs) else None,
                      abs_median_p90=float(np.quantile(diffs, .9)) if len(diffs) else None,
                      abs_median_max=float(diffs.max()) if len(diffs) else None,
                      warn=sorted([r for r in comparisons if abs(r["median_diff"]) > .02], key=lambda r: -abs(r["median_diff"]))),
                  split_jumps=sorted(jumps, key=lambda r: (r["ticker"], r["date"])))
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    outputs = {"multiples_hist.parquet": hist, "eps_revision.parquet": rev,
               "industry_pe.json": dict(asof=asof, month=end, industries=industries), "multiples_check.json": checks}
    try:
        _publish_outputs(out, outputs)
    except Exception as exc:
        print(f"寫檔失敗：{type(exc).__name__}: {exc}", flush=True)
        return 1
    print(f"總耗時 {time.perf_counter() - started:.3f} 秒", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
