"""以本機資料乾跑估值 2.0 三個 EPS 窗口，不接既有呼叫端。"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reference import corporate_actions, loader
from screener.eps_windows import windows


def _bare(ticker) -> str:
    return str(ticker).split(".")[0]


def _table(headers, rows) -> list[str]:
    return ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"] + [
        "| " + " | ".join(str(v).replace("|", "／") for v in row) + " |" for row in rows
    ] + [""]


def _number(value) -> str:
    return "—" if value is None else f"{value:,.6g}"


def _run(stocks, quarters, monthly, asof, live):
    counts = {name: {key: Counter() for key in ("status", "n_est", "reason", "fill_method")}
              for name in ("reported", "ttm", "fwd")}
    selected, errors = {}, []
    empty_q = pd.DataFrame()
    empty_m = pd.Series(dtype=float)
    for stock in stocks:
        ticker = _bare(stock["ticker"])
        try:
            result = windows(quarters.get(ticker, empty_q), monthly.get(ticker, empty_m),
                             asof=asof, live=live,
                             financial=stock.get("industry_group") == "financial")
        except Exception as exc:
            errors.append((ticker, f"{type(exc).__name__}: {exc}"))
            continue
        for name, window in result.items():
            counts[name]["status"][window.status] += 1
            counts[name]["n_est"][window.n_est] += 1
            if window.reason:
                counts[name]["reason"][window.reason] += 1
            for row in window.quarters:
                if row.kind == "est":
                    counts[name]["fill_method"][row.fill_method] += 1
        if ticker in {"2330", "2327", "2881", "5289", "1815", "2454"}:
            selected[ticker] = result
    return counts, selected, errors


def _distributions(counts, full):
    lines = []
    for name, stats in counts.items():
        lines += [f"### {name}", ""]
        for key in (("status", "n_est", "fill_method") if full else ("status", "n_est")):
            lines += [f"{key} 分布" , ""]
            lines += _table([key, "檔數" if key != "fill_method" else "試算季數"], stats[key].most_common())
        if full:
            lines += ["reason 前 15 名（每窗口按檔計數）", ""]
            lines += _table(["reason", "檔數"], stats["reason"].most_common(15))
    return lines


def main():
    q = loader.load_quarterly(live=True)
    q = corporate_actions.adjust_eps(q)
    m = pd.read_parquet(ROOT / "data/upstream/revenue.parquet")
    m["month"] = pd.to_datetime(m["month"]).dt.to_period("M").dt.to_timestamp()
    stocks = json.loads((ROOT / "data/derived/stock_class.json").read_text(encoding="utf-8"))["stocks"]
    quarters = {_bare(t): frame for t, frame in q.groupby("ticker", sort=False)}
    monthly = {_bare(t): frame.set_index("month")["revenue"]
               for t, frame in m.groupby("ticker", sort=False)}
    counts, selected, errors = _run(stocks, quarters, monthly, pd.Timestamp("2026-11-02"), True)
    lines = ["# 估值 2.0 EPS 窗口乾跑", "", "## 1. 即時口徑：2026-11-02，live=True", "",
             f"總檔數：{len(stocks)}；例外數：{len(errors)}。", ""]
    if errors:
        lines += _table(["ticker", "例外"], errors)
    lines += _distributions(counts, True)
    lines += ["### 指定個股推導", ""]
    for ticker in ("2330", "2327", "2881", "5289", "1815", "2454"):
        lines += [f"#### {ticker}", ""]
        for name, window in selected.get(ticker, {}).items():
            lines += [f"{name}：status={window.status}，n_est={window.n_est}，EPS={_number(window.eps)}，"
                      f"reason={window.reason or '—'}", ""]
            lines += _table(["q", "kind", "eps", "months_known", "fill_method"],
                            [(r.q, r.kind, _number(r.eps), r.months_known, r.fill_method) for r in window.quarters])
            for d in window.details:
                lines += [f"EstDetail {d.q}（金額與股數單位：元、股）", ""]
                fields = ("revenue", "gm_last", "opex_last", "op", "nonop", "tax", "minority",
                          "ni_parent", "shares", "eps")
                lines += _table(["參數", "數值"], [(f, _number(getattr(d, f))) for f in fields]
                                + [("shares_from", d.shares_from), ("flags", "；".join(d.flags) or "—")])
                lines += _table(["月", "營收", "來源"], [(month, _number(value), method)
                                                       for month, value, method in d.months])
    historical, _, historical_errors = _run(stocks, quarters, monthly, pd.Timestamp("2026-02-15"), False)
    lines += ["## 2. 歷史口徑：2026-02-15，live=False", ""]
    lines += _distributions(historical, False)
    # 有例外必須列出，避免分布總數不足卻無法追查。
    if historical_errors:
        lines += [f"歷史例外數：{len(historical_errors)}", ""]
        lines += _table(["ticker", "例外"], historical_errors)
    (ROOT / "val2_dryrun_out.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"即時：{len(stocks)} 檔，例外 {len(errors)}；歷史例外 {len(historical_errors)}")
    for label, result in (("即時", counts), ("歷史", historical)):
        for name, stats in result.items():
            print(label, name, "status", dict(stats["status"]), "n_est", dict(stats["n_est"]))
    return 1 if errors or historical_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
