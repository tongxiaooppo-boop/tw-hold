"""金融股估值卡 EPS 檢查：dump 全母體卡片關鍵欄位、compare 兩份 dump 的差異。

python scripts/check_fin_eps_cards.py dump --out <json> [--tickers 2812,2834]
python scripts/check_fin_eps_cards.py compare <base.json> <new.json>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import val_inputs  # noqa: E402
from screener import val_card  # noqa: E402
from scripts.val2_dryrun_cards import LocalBundle  # noqa: E402

ASOF = pd.Timestamp("2026-11-19")
KEYS = ("tier", "route", "reason", "prices", "roe", "growth", "nonop_hist", "nonop_median")


def _win(w):
    if w is None:
        return None
    return dict(ok=w.get("ok"), status=w.get("status"), eps=w.get("eps"),
                q=[(r["q"], r["kind"], r["eps"]) for r in w.get("quarters") or []])


def dump(out: str, tickers: list[str] | None) -> None:
    stocks = json.load(open(ROOT / "data/derived/stock_class.json", encoding="utf-8"))["stocks"]
    bundle = LocalBundle()
    result = {}
    for cls in stocks:
        code = str(cls.get("ticker"))
        if tickers and code not in tickers:
            continue
        try:
            kw = val_inputs.card_inputs(code, ASOF, cls, ROOT / "data/derived", bundle)
            if "missing" in kw:
                result[code] = {"error": str(kw["missing"]), "cls": cls}
                continue
            card = val_card.build_card(**kw)
        except Exception as exc:  # noqa: BLE001
            result[code] = {"error": f"{type(exc).__name__}: {exc}", "cls": cls}
            continue
        row = {k: card.get(k) for k in KEYS}
        row["eps"] = {k: _win((card.get("eps") or {}).get(k)) for k in ("reported", "ttm", "fwd")}
        row["cls"] = {"industry_group": cls.get("industry_group"), "type": cls.get("type")}
        result[code] = row
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, default=str, ensure_ascii=False, sort_keys=True)
    print(f"dump {len(result)} 檔 -> {out}")


def _fin(row: dict) -> bool:
    c = row.get("cls") or {}
    return c.get("industry_group") == "financial" or c.get("type") == "financial"


def _norm(x):
    return json.loads(json.dumps(x, default=str, sort_keys=True))


def compare(base: str, new: str) -> None:
    a = json.load(open(base, encoding="utf-8"))
    b = json.load(open(new, encoding="utf-8"))
    nonfin, fin_core, fin_eps = [], [], []
    for code in sorted(set(a) | set(b)):
        ra, rb = a.get(code, {}), b.get(code, {})
        fin = _fin(rb or ra)
        if not fin:
            diff = [k for k in sorted(set(ra) | set(rb)) if _norm(ra.get(k)) != _norm(rb.get(k))]
            if diff:
                nonfin.append((code, diff))
            continue
        diff = [k for k in ("tier", "route", "prices", "error") if _norm(ra.get(k)) != _norm(rb.get(k))]
        if diff:
            fin_core.append((code, diff))
        ea, eb = (ra.get("eps") or {}), (rb.get("eps") or {})
        if _norm(ea) != _norm(eb):
            wa, wb = (ea.get("reported") or {}), (eb.get("reported") or {})
            la = (wa.get("q") or [[None]])[-1]
            lb = (wb.get("q") or [[None]])[-1]
            fin_eps.append(f"{code} reported {la[0]}→{lb[0]} {wa.get('eps')}→{wb.get('eps')}")
    print(f"非金融變動 {len(nonfin)} 檔")
    for code, diff in nonfin[:20]:
        print(f"  {code}: {','.join(diff)}")
    print(f"金融 tier/route/prices 變動 {len(fin_core)} 檔")
    for code, diff in fin_core[:20]:
        print(f"  {code}: {','.join(diff)}")
    print(f"金融 EPS 變動 {len(fin_eps)} 檔")
    for line in fin_eps:
        print("  " + line)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dump")
    d.add_argument("--out", required=True)
    d.add_argument("--tickers")
    c = sub.add_parser("compare")
    c.add_argument("base")
    c.add_argument("new")
    args = ap.parse_args()
    if args.cmd == "dump":
        dump(args.out, args.tickers.split(",") if args.tickers else None)
    else:
        compare(args.base, args.new)


if __name__ == "__main__":
    main()
