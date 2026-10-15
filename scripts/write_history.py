"""寫推薦歷史快照 data/history/<asof>.json（模組說明見 reference/history.py）。

    python scripts/write_history.py                       # 每日：short／long（本 repo 檔）＋ swing（抓 tw-swing 分享 JSON）
    python scripts/write_history.py --backfill-git        # 本機完整歷史：從 git 撈 short／long 的歷史版本
    python scripts/write_history.py --backfill-swing DIR  # 用 tw-swing 的 data/daily/*.csv 回填 swing 線（DIR 本機才有）

git 回填的坑（交接單 §13.3）：①提交訊息日期是 UTC，**以檔案內容日期為準**；②同一交易日可有多筆內容不同的提交，
選「健康版本」（short：scanned ≥ 90% × 觀察到的最大值）中最後一筆；③當天沒變不會 commit → 該日撈不到（not_retained，不補值）。
CI 是淺層 clone，回填要在本機跑。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

from reference import history as H

SWING_SHARE_URL = "https://tw-swing.pages.dev/share-latest.json"
START = {"short": "2026-10-02", "long": "2026-09-07", "swing": "2026-08-26"}   # 追蹤開始日；之前一律 before


def refresh_holidays() -> None:
    try:
        import last_trading_day_guard as g
        closed = g.fetch_closed()
        if not closed:
            return
        p = H.HIST_DIR / "_holidays.json"
        cur = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        new = {**{d.isoformat(): "休市（證交所公告）" for d in closed}, **cur}
        if new != cur:
            H.HIST_DIR.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(dict(sorted(new.items())), ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] 休市日表更新失敗（沿用現有）：{e}")


def _load(rel: str) -> dict | None:
    p = ROOT / rel
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def live() -> int:
    refresh_holidays()
    d = ROOT / "data" / "derived"
    sc, sw = _load("data/derived/short_scan.json"), _load("data/derived/swing_list.json")
    if sc:
        a, ln = H.short_line(sc, "live")
        print("short", a, H.add_line(a, "short", ln))
    if sw:
        a, ln = H.long_line(sw, "live")
        print("long ", a, H.add_line(a, "long", ln))
    try:
        req = urllib.request.Request(SWING_SHARE_URL, headers={"User-Agent": "tw-hold"})
        share = json.loads(urllib.request.urlopen(req, timeout=20).read().decode("utf-8"))
        a, ln = H.swing_line(share["asof"], share.get("candidates") or [], "live", warnings=share.get("data_warnings") or [])
        print("swing", a, H.add_line(a, "swing", ln))
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] tw-swing 分享 JSON 抓不到，swing 線今天不記：{e}")
    return 0


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True).stdout


def backfill_git(force: bool = False) -> int:
    for key, rel, build, datekey in (("short", "data/derived/short_scan.json", H.short_line, None),
                                     ("long", "data/derived/swing_list.json", H.long_line, None)):
        shas = _git("log", "--reverse", "--format=%H", "--", rel).split()
        versions = []                                   # (content_date, doc)
        for sha in shas:
            try:
                doc = json.loads(_git("show", f"{sha}:{rel}"))
                versions.append((build(doc, "backfill-git")[0], sha, doc))
            except Exception:  # noqa: BLE001
                continue
        if key == "short":
            top = max((d["_meta"].get("scanned") or 0) for _, _, d in versions)
            healthy = lambda d: (d["_meta"].get("scanned") or 0) >= 0.9 * top  # noqa: E731
        else:
            healthy = lambda d: bool(d.get("candidates_pool") is not None)  # noqa: E731
        by_date: dict[str, list] = {}
        for date, sha, doc in versions:
            by_date.setdefault(date, []).append((sha, doc))
        for date, vs in sorted(by_date.items()):
            if date < START[key]:
                continue
            good = [v for v in vs if healthy(v[1])]
            sha, doc = (good or vs)[-1]
            a, ln = build(doc, "backfill-git")
            if not good:
                ln["status"], ln["note"] = "degraded", "該日只撈得到不健康版本（掃描檔數異常）"
            ln["n_versions"] = len(vs)
            sets = {tuple(sorted(c["t"] for c in build(v[1], "x")[1]["candidates"])) for v in vs}
            ln["conflict"] = len(sets) > 1
            print(key, a, H.add_line(a, key, ln, force=force), f"n={ln['n']} versions={len(vs)} conflict={ln['conflict']}")
    return 0


def backfill_swing(csv_dir: str, force: bool = False) -> int:
    for f in sorted(Path(csv_dir).glob("20??-??-??.csv")):
        asof = f.stem
        if asof < START["swing"]:
            continue
        df = pd.read_csv(f, encoding="utf-8-sig") if f.stat().st_size > 5 else pd.DataFrame()
        cands = [] if df.empty or "ticker" not in df.columns else [
            {"ticker": r.ticker, "name": r.name, "entry": r.entry, "stop": r.stop, "signal": r.rule_name}
            for r in df.itertuples()]
        a, ln = H.swing_line(asof, cands, "backfill-csv")
        print("swing", a, H.add_line(a, "swing", ln, force=force), f"n={ln['n']}")
    return 0


def backfill_rc(swing_repo: str) -> int:
    """把 tw-swing 的補算旁檔（Y4／W6 事故日重算）轉成本 repo 的 swing 線補算旁檔。
    只留分享級欄位：訊號用 rules.yaml 的規則『名稱』，不帶規則 ID（本 repo 公開）。"""
    import yaml
    root = Path(swing_repo)
    names = {r["id"]: r["name"] for r in yaml.safe_load((root / "rules.yaml").read_text(encoding="utf-8"))["rules"]}
    out_dir = H.HIST_DIR / "recomputed"
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in sorted((root / "data" / "history" / "recomputed").glob("20??-??-??.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        if not d["candidates"]:
            continue
        cands = [{"t": c["t"], "nm": c["nm"], "px": c["px"], "stop": c["stop"],
                  "sig": "、".join(names[r] for r in c["r"])} for c in d["candidates"]]
        tgt = out_dir / f.name
        doc = json.loads(tgt.read_text(encoding="utf-8")) if tgt.exists() else {"schema": 1, "asof": d["asof"], "lines": {}}
        doc["lines"]["swing"] = {"n": len(cands), "candidates": cands}      # 合併寫入，不蓋掉同日別條線的補算
        doc["method"] = d["method"]
        tgt.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        print("swing 補算", d["asof"], len(cands))
    return 0


def recompute_short(start: str, end: str) -> int:
    """用目前的 bundle（價量／法人／融資券）截到各日重掃 tw-hold 短線，存補算旁檔。
    限制：universe、主動 ETF 旗標用『現在』的（非當時）；價格是現在的還原序列（比率型條件不受影響）。
    這是『當時若有這支掃描會說什麼』的近似，不是當時系統的產出（短線掃描 10/02 才上線）。"""
    import build_short_scan as bs
    px = pd.read_parquet(ROOT / "data" / "upstream" / "prices_adj.parquet", columns=["date"])
    days = sorted(d for d in pd.to_datetime(px["date"]).unique() if pd.Timestamp(start) <= d <= pd.Timestamp(end))
    out_dir = H.HIST_DIR / "recomputed"
    out_dir.mkdir(parents=True, exist_ok=True)
    for d in days:
        k = pd.Timestamp(d).date().isoformat()
        doc = bs.build(cutoff=k)
        a, ln = H.short_line(doc, "recompute")
        if a != k:
            print(k, "資料最後一天是", a, "→ 略過"); continue
        f = out_dir / f"{k}.json"
        cur = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"schema": 1, "asof": k, "lines": {}}
        cur["lines"]["short"] = {"n": ln["n"], "scanned": ln.get("scanned"), "status": ln["status"], "note": ln["note"],
                                 "candidates": [{"t": c["t"], "nm": c["nm"], "px": c["px"]} for c in ln["candidates"]]}
        cur["method"] = "recompute-from-current-bundle"
        f.write_text(json.dumps(cur, ensure_ascii=False, indent=1), encoding="utf-8")
        print("short 補算", k, "scanned", ln.get("scanned"), "passed", ln["n"])
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill-git", action="store_true")
    ap.add_argument("--backfill-swing", metavar="CSV_DIR")
    ap.add_argument("--backfill-rc", metavar="SWING_REPO", help="讀 tw-swing 的 data/history/recomputed 產生 swing 線補算旁檔")
    ap.add_argument("--recompute-short", nargs=2, metavar=("FROM", "TO"), help="用目前 bundle 重掃 tw-hold 短線並存補算旁檔")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if a.recompute_short:
        return recompute_short(*a.recompute_short)
    if a.backfill_rc:
        return backfill_rc(a.backfill_rc)
    if a.backfill_git:
        return backfill_git(a.force)
    if a.backfill_swing:
        return backfill_swing(a.backfill_swing, a.force)
    return live()


if __name__ == "__main__":
    raise SystemExit(main())
