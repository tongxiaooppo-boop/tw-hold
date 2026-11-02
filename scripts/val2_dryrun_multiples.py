"""讀取自建倍數產出，彙整全市場乾跑驗收報告。"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from screener import multiples_self as ms


def _table(frame: pd.DataFrame) -> str:
    def cell(value):
        if pd.isna(value):
            return "—"
        if isinstance(value, float):
            return f"{value:.6g}"
        return str(value).replace("|", "\\|")
    names = list(frame.columns)
    lines = ["| " + " | ".join(names) + " |", "| " + " | ".join("---" for _ in names) + " |"]
    lines.extend("| " + " | ".join(cell(v) for v in row) + " |" for row in frame.itertuples(index=False, name=None))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default="_dryrun")
    parser.add_argument("--build-log", default="_dryrun_build.log")
    parser.add_argument("--output", default="val2_mult_dryrun_out.md")
    args = parser.parse_args(argv)
    out = Path(args.out_dir)
    hist = pd.read_parquet(out / "multiples_hist.parquet")
    rev = pd.read_parquet(out / "eps_revision.parquet")
    check = json.loads((out / "multiples_check.json").read_text(encoding="utf-8"))
    industry = json.loads((out / "industry_pe.json").read_text(encoding="utf-8"))
    asof = pd.Timestamp(check["asof"])
    log = Path(args.build_log)
    elapsed = re.findall(r"(?:總耗時|\?{3})\s+([\d.]+)\s+(?:秒|\?)", (log.read_text(encoding="utf-16") if log.read_bytes().startswith((b"\xff\xfe", b"\xfe\xff")) else log.read_text(encoding="utf-8-sig")) if log.exists() else "")
    lines = ["# 自建倍數全市場乾跑", "", f"估值日：{check['asof']}；執行時間：{elapsed[-1] + ' 秒' if elapsed else '未提供建置紀錄'}。",
             f"母體 {check['n_tickers']} 檔；成功 {check['n_ok']}；failed {check['n_failed']}（{check['n_failed'] / max(1, check['n_tickers']):.2%}）；no_price {len(check['no_price'])} 檔。", "",
             "## 失敗與無價格", "", _table(pd.DataFrame(check["failed"], columns=["ticker", "error"])), "",
             "no_price：" + ("、".join(check["no_price"]) or "無"), "", "## 有效月數與 A 層門檻", ""]
    groups = dict(tuple(hist.groupby("ticker")))
    distributions = []
    # 失敗或無價格的母體個股以零個有效月列入分布。
    missing = check["n_tickers"] - len(groups)
    for kind, metric in (("normal", "pe"), ("growth", "pe"), ("pb", "pb"), ("normal", "pe_fwd")):
        counts = [ms.window_stats(mh, kind, metric, asof, cap=ms.MULT_CAP[kind])["n_valid"] for mh in groups.values()] + [0] * missing
        bins = Counter("0" if n == 0 else "1–29" if n < 30 else "30–35" if n < 36 else "36–59" if n < 60 else "60+" for n in counts)
        distributions.append(dict(kind=kind, metric=metric, **{key: bins[key] for key in ("0", "1–29", "30–35", "36–59", "60+")}, tier_a=sum(ms.is_valid_tier_a(n, kind, was_a=False) for n in counts)))
    lines += [_table(pd.DataFrame(distributions)), "", "## 與交易所 PE 核對", ""]
    comparison = check["pe_vs_exchange"]
    lines += [_table(pd.DataFrame([{k: v for k, v in comparison.items() if k != "warn"}])) , "", f"warn 共 {len(comparison['warn'])} 檔；以下為前 30 檔。", "", _table(pd.DataFrame(comparison["warn"][:30], columns=["ticker", "median_diff", "n_months"])), "", "### 分割與面額變更跳動（全列）", "", _table(pd.DataFrame(check["split_jumps"], columns=["ticker", "date", "type", "m", "pe_before", "pe_after", "pb_before", "pb_after"])), "", "## EPS 上修", ""]
    latest = rev["month"].max() if not rev.empty else "無"
    event_counts = rev.loc[rev["month"] == latest, "event"].value_counts()
    lines += [f"最新月份：{latest}", "", _table(pd.DataFrame([dict(event=event, n=int(event_counts.get(event, 0))) for event in ms.REV_EVENTS])), ""]
    streaks = pd.DataFrame([dict(ticker=ticker, **ms.revision_streak(rows)) for ticker, rows in rev.groupby("ticker")], columns=["ticker", "last_pct", "streak", "direction"])
    streaks["direction"] = streaks["direction"].fillna("None")
    distribution = streaks.groupby(["direction", "streak"], dropna=False).size().reset_index(name="n")
    lines += [_table(distribution), "", "連續上修至少 2 次，依次數遞減、代號遞增列前 20 檔：", "", _table(streaks[(streaks["direction"] == "up") & (streaks["streak"] >= 2)].sort_values(["streak", "ticker"], ascending=[False, True]).head(20)), "", "## 產業 PE", ""]
    industries = pd.DataFrame([dict(industry=name, **values) for name, values in industry["industries"].items()], columns=["industry", "median_pe", "n"])
    lines += [f"產業數 {len(industries)}；n<8 的產業數 {int((industries['n'] < 8).sum())}。", "", _table(industries.sort_values(["n", "industry"], ascending=[False, True]).head(10)), "", "## 指定個股最近 12 個月", ""]
    columns = ["month", "price_adj", "eps_ttm", "eps_fwd", "bvps", "pe", "pe_fwd", "pb", "pe_exchange", "valid_pe", "excluded"]
    for ticker in ("2330", "2327", "2881", "5289", "1815", "2454", "2412"):
        lines += [f"### {ticker}", "", _table(hist[hist["ticker"] == ticker].sort_values("month").tail(12)[columns]), ""]
    Path(args.output).write_text("\n".join(lines), encoding="utf-8")
    print(f"報告已寫入 {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
