"""產 `data/derived/value_rank.json`（估值排行分頁「合理價以下排行」）。任務書 2026-11-19 v1。

市值前 500 每檔建估值卡，依 營收年增／EPS 暴增／分類 分「一般、循環、高成長」，
各取股價 ≤ 合理價、離合理價最遠的前 20 檔。

用法：python build_value_rank.py [--asof YYYY-MM-DD] [--limit N]
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from collections import Counter
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "app"))

OUT = REPO / "data" / "derived" / "value_rank.json"
DERIVED = REPO / "data" / "derived"


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(f) or f in (float("inf"), float("-inf")) else f


def main(argv: list[str] | None = None) -> int:
    from app import val_inputs
    from screener import val_card, value_rank as vr
    from scripts.val2_dryrun_cards import LocalBundle

    ap = argparse.ArgumentParser(description="產 data/derived/value_rank.json")
    ap.add_argument("--asof", default=None)
    ap.add_argument("--limit", type=int, default=None, help="只算前 N 檔（本機試跑，寫旁邊的檔）")
    args = ap.parse_args(argv)

    now = _dt.datetime.now(ZoneInfo("Asia/Taipei"))
    asof_s = args.asof or now.date().isoformat()
    asof = pd.Timestamp(asof_s)

    val_inputs.ensure_multiples()

    uni_path = REPO / "data" / "upstream" / "fundamentals" / "universe.parquet"
    if not uni_path.exists():
        print("錯誤：找不到 universe.parquet，中止且不覆寫舊 JSON。", file=sys.stderr)
        return 1
    uni = pd.read_parquet(uni_path)
    uni = uni[uni["in_mktcap500"] == True]  # noqa: E712
    uni_by = {str(r["ticker"]).split(".")[0]: r for r in uni.to_dict("records")}
    codes = list(uni_by)
    universe_n = len(codes)
    if args.limit:
        codes = codes[: args.limit]

    stocks = json.load(open(DERIVED / "stock_class.json", encoding="utf-8"))["stocks"]
    cls_by = {str(c.get("ticker")): c for c in stocks}

    bundle = LocalBundle()
    rows: list[dict] = []
    errors = 0
    for code in codes:
        try:
            cls = cls_by.get(code)
            kw = val_inputs.card_inputs(code, asof, cls, DERIVED, bundle)
            if "missing" in kw:
                errors += 1
                continue
            card = val_card.build_card(**kw)
            u = uni_by[code]
            prices = card.get("prices") or {}
            eps = card.get("eps") or {}
            qs = (eps.get("reported") or {}).get("quarters") or []
            typ = (cls or {}).get("type")
            eps_x = vr.eps_ratio(kw["qf"])
            rev_g = vr.revenue_growth(kw["qf"])
            group, why = vr.category(typ, eps_x, rev_g)
            y3, y12, rev_m = vr.rev_yoy(kw["rev"])
            mom = vr.rev_mom(kw["rev"], rev_m)
            rows.append(dict(
                ticker=code, name=u.get("stock_name"), industry=u.get("industry"), type=typ,
                display_type=card.get("display_type"), route=card.get("route"), tier=card.get("tier"),
                price=_num(card.get("price")), px_date=card.get("px_date"),
                cheap=_num(prices.get("cheap")), fair=_num(prices.get("fair")), dear=_num(prices.get("dear")),
                eps_last_q=qs[-1]["q"] if qs else None,
                eps_ttm=_num((eps.get("ttm") or {}).get("eps")),
                eps_x=eps_x, rev_g=rev_g, group=group, why=why,
                rev3m_yoy=y3, rev12m_yoy=y12, rev_month=rev_m, rev_flag=vr.rev_flag(group, y3, y12),
                rev_mom=mom, mom_warn=vr.mom_warn(mom, rev_m),
                **vr.rev_month_info(kw["rev"], rev_m),
            ))
        except Exception as exc:  # noqa: BLE001
            errors += 1
            print(f"{code} 建卡失敗：{type(exc).__name__}: {exc}", file=sys.stderr)

    common = Counter(r["eps_last_q"] for r in rows if r["eps_last_q"]).most_common(1)
    common_q = common[0][0] if common else None
    for r in rows:
        q = r["eps_last_q"]
        r["lag"] = (f"最新一季財報未公布，EPS 用到 {q}"
                    if common_q and q and str(q) < str(common_q) else "")

    carded_n = len(rows)
    if carded_n < 0.9 * len(codes):
        print(f"::error::建卡成功只有 {carded_n}/{len(codes)}，中止且不覆寫舊 JSON。", file=sys.stderr)
        return 1

    below = sum(1 for r in rows if r["price"] is not None and r["fair"] is not None
                and r["price"] <= r["fair"])
    rp = vr.rev_progress(rows, asof_s)
    doc = {
        "asof": asof_s,
        "built_at": now.replace(microsecond=0).isoformat(),
        "universe_n": universe_n,
        "carded_n": carded_n,
        "below_fair_n": below,
        "errors": errors,
        "thresholds": {"growth_rev": vr.GROWTH_REV, "spike_eps": vr.SPIKE_EPS, "top_n": vr.TOP_N,
                       "decel_pts": vr.DECEL_PTS,
                       "mom_warn": vr.MOM_WARN, "growth_top_n": vr.GROWTH_TOP_N},
        "rev_progress": rp,
        "growth": vr.growth_rank(rows, rp["month"]),
        "groups": vr.rank(rows),
    }
    out = OUT.with_name("value_rank.limit.json") if args.limit else OUT
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"已寫 {out}：universe {universe_n}、建卡 {carded_n}、合理價以下 {below}、錯誤 {errors}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
