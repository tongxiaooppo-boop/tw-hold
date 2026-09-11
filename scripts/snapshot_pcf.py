"""每日拉規模前五大主動式 ETF 的 PCF → 落每日快照 `data/pcf/<code>/<date>.parquet`。

`rebuild.yml` 每天跑一次（`continue-on-error`）。PCF 各家只給「當天」、無歷史 →
自己存快照，`build_active_etf_flags.py` 再拿前後兩份做差分。

- 單一投信抓失敗不影響其他（`fetch_all` per-fund 接住）。
- 檔案已存在且內容一致 → 不重寫（不為沒變的東西留 commit）。
- 每檔只留最近 `KEEP` 份快照（差分只需 2 份，多留一點看趨勢；避免 repo 膨脹）。
- 永遠 exit 0——這支紅了不該擋每日重算。

用法：
    python scripts/snapshot_pcf.py            # 抓 + 落檔
    python scripts/snapshot_pcf.py --dry-run  # 只抓不寫
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import pandas as pd                                             # noqa: E402

from scripts.pcf_fetchers import FUNDS, fetch_all               # noqa: E402

PCF_DIR = REPO / "data" / "pcf"
INDEX = PCF_DIR / "_index.json"
KEEP = 15
_COLS = ["stock_code", "stock_name", "shares", "weight", "market_value", "price"]
# 基金層純量——每份快照常數，複製進每一列
_FUND_COLS = ["fund_nav", "fund_units", "fund_close", "fund_close_date", "data_date"]


def _frame(o: dict) -> pd.DataFrame:
    df = pd.DataFrame(o["holdings"], columns=_COLS)
    df["stock_code"] = df["stock_code"].astype(str)
    df = (df.dropna(subset=["stock_code", "shares"])
            .sort_values("stock_code", kind="stable")
            .reset_index(drop=True))
    df["fund_nav"] = o.get("nav")
    df["fund_units"] = o.get("units")
    df["fund_close"] = o.get("close")         # ETF 市價收盤（TWSE），算折溢價用
    # ↑ 那個收盤價是哪一天的。折溢價要「市價與淨值同一天」，盤後才跑就會差一天
    #   → build_active_etf_flags 用這欄擋掉跨日的折溢價（2026-09-11 修）。
    df["fund_close_date"] = o.get("close_date")
    df["data_date"] = o["data_date"]
    return df


def _same(path: Path, df: pd.DataFrame) -> bool:
    if not path.exists():
        return False
    try:
        old = pd.read_parquet(path)[_COLS].reset_index(drop=True)
    except Exception:
        return False
    return old.equals(df[_COLS].reset_index(drop=True))


def _prune(fund_dir: Path) -> None:
    snaps = sorted(fund_dir.glob("20*.parquet"))
    for p in snaps[:-KEEP]:
        p.unlink()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    ok, bad = fetch_all()
    PCF_DIR.mkdir(parents=True, exist_ok=True)
    idx: dict = {"updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "funds": {}, "missing": bad}
    wrote = 0

    for o in ok:
        code, dd = o["code"], o["data_date"]
        df = _frame(o)
        fund_dir = PCF_DIR / code
        path = fund_dir / f"{dd}.parquet"
        idx["funds"][code] = {
            "issuer": o["issuer"], "name": o["name"], "name_full": o.get("name_full", ""),
            "latest_date": dd, "post_date": o.get("post_date", dd), "nav": o.get("nav"),
            "holdings_n": int(len(df)), "fetched_at": o["fetched_at"],
        }
        if args.dry_run:
            print(f"[dry] {code} {dd} {len(df)} 檔")
            continue
        fund_dir.mkdir(parents=True, exist_ok=True)
        if _same(path, df):
            print(f"= {code} {dd} 內容未變，跳過")
        else:
            df.to_parquet(path, index=False)
            wrote += 1
            print(f"-> {path.relative_to(REPO)} （{len(df)} 檔）")
        _prune(fund_dir)

    for b in bad:
        print(f"::warning::主動式 ETF PCF 抓不到 {b['code']}（{b['issuer']}）：{b['error']}")

    if not args.dry_run:
        # 規模重排 sanity check：用各家自報 nav 排序，跟寫死的前 5 對一下
        idx["nav_rank"] = [
            {"code": c, "nav": v["nav"]}
            for c, v in sorted(idx["funds"].items(), key=lambda kv: -(kv[1].get("nav") or 0))
            if v.get("nav")]
        INDEX.write_text(json.dumps(idx, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n{len(ok)}/{len(FUNDS)} 檔成功，寫入 {wrote} 份新快照；index -> {INDEX.relative_to(REPO)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
