"""自動解析未還原的分割 / 面額變更 / 減資 → `reference/corporate_actions_resolved.json`。

`me` 被 2327 國巨的減資逼出 `price_adjuster.py`（跨事件日的回測圖崩掉）。這支把它接進
tw-hold 的偵測器後面，關鍵修正：**FinMind 給 factor、偵測器給日期**（FinMind 事件日、
TWSE 官方新股日、bundle 實際跳空日三者常差幾天，還原邊界要用 bundle 跳空日）。

流程：
1. `build_factors.scan_price_jumps()` → bundle `prices_adj` 近期的異常單日跳空
   `[{ticker, date, ratio}]`（已排除 SPLITS / IGNORE_JUMPS / 資料雜訊）。
2. 每檔抓 FinMind `TaiwanStockSplitPrice` + `TaiwanStockCapitalReductionReferencePrice`
   （免費、匿名可取；有 `FINMIND_TOKEN` 更好）。
3. 跳空比例對得上某事件的 before/after → 寫進 resolved.json（date = 跳空日，factor = FinMind）。
   對不上 → 留在「待人工」清單（不自動塞 IGNORE_JUMPS——可能只是 FinMind 還沒發佈）。
4. `--write` 才落檔；否則只印。永遠 exit 0（CI 不因這支變紅）。

用法：
    python scripts/resolve_splits.py              # 只看
    python scripts/resolve_splits.py --write      # 落檔（rebuild.yml 用這個）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for _p in (str(REPO), str(REPO / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from build_factors import scan_price_jumps                         # noqa: E402
from reference import corporate_actions as ca                      # noqa: E402
from reference.finmind_client import Client, read_token            # noqa: E402

RESOLVED = REPO / "reference" / "corporate_actions_resolved.json"
MATCH_TOL = 0.06          # factor 與跳空比例的相對容差


def _events(cli: Client, ticker: str) -> list[dict]:
    """兩張事件表合一 → `[{date, factor}]`（factor = before/after）。"""
    out = []
    for ds in ("TaiwanStockSplitPrice", "TaiwanStockCapitalReductionReferencePrice"):
        try:
            rows = cli.get(ds, data_id=ticker, start_date="2000-01-01")
        except Exception as e:
            print(f"  ! {ticker} {ds}: {type(e).__name__}: {e}")
            continue
        for r in rows or []:
            bp, ap = float(r.get("before_price") or 0), float(r.get("after_price") or 0)
            if bp > 0 and ap > 0:
                out.append({"date": r["date"], "factor": bp / ap})
    return out


def _nice(f: float) -> float:
    """7.001 → 7、2.0 → 2、0.5003 → 0.5：靠整數/簡分數 1% 內就吸附。"""
    for cand in (round(f), round(f * 2) / 2):
        if cand and abs(f / cand - 1) < 0.005:
            return cand
    return round(f, 4)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    jumps = scan_price_jumps()
    if not jumps:
        print("偵測器沒有新的未還原跳空。")
        return 0

    tok = read_token()
    print(f"FinMind：{'有 token' if tok else '匿名層 300/hr'}　·　待解 {len(jumps)} 筆跳空")
    cli = Client(token=tok)

    existing = {}
    if RESOLVED.exists():
        existing = json.loads(RESOLVED.read_text(encoding="utf-8")).get("splits", {})

    resolved = {tk: list(evs) for tk, evs in existing.items()}
    added, unresolved = [], []
    ev_cache: dict[str, list[dict]] = {}

    for j in jumps:
        tk, jdate, ratio = j["ticker"], j["date"], j["ratio"]
        target = 1.0 / ratio if ratio < 1 else ratio        # 分割/面額變更 vs 減資
        evs = ev_cache.setdefault(tk, _events(cli, tk))
        hit = next((e for e in evs if abs(e["factor"] / target - 1) < MATCH_TOL), None)
        if hit is None:
            unresolved.append(j)
            print(f"  ? {tk} {jdate} ×{ratio}　FinMind 無對應事件（factor≈{target:.2f}）→ 待人工")
            continue
        if any(e["date"] == jdate for e in resolved.get(tk, [])):
            continue                                         # 已解過
        factor = _nice(hit["factor"])
        resolved.setdefault(tk, []).append({"date": jdate, "factor": factor})
        added.append((tk, jdate, factor, hit["date"]))
        print(f"  + {tk} {jdate}　factor {factor}（FinMind 事件日 {hit['date']}，比例吻合）")

    if added and args.write:
        for tk in resolved:
            resolved[tk] = sorted(resolved[tk], key=lambda e: e["date"])
        RESOLVED.write_text(
            json.dumps({"splits": resolved,
                        "_note": "scripts/resolve_splits.py 自動產出——手動改請改 "
                                 "reference/corporate_actions.py 的 _MANUAL（會覆寫這裡）"},
                       ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        ca.reload()
        print(f"\n→ 寫入 {RESOLVED.relative_to(REPO)}（新增 {len(added)} 筆）")
    elif added:
        print(f"\n（--write 才落檔；{len(added)} 筆待寫）")

    if unresolved:
        print(f"\n⚠️ {len(unresolved)} 筆自動解不了——若是真事件請等 FinMind 發佈或手動加 "
              "reference/corporate_actions.py（_MANUAL / IGNORE_JUMPS）：")
        for j in unresolved:
            print(f"    {j['ticker']} {j['date']} ×{j['ratio']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
