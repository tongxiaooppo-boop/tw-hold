"""一次性回填 `data/derived/swing_history.json`。

用 `data/derived/swing_list.json` 的 git 歷史，逐版重放 `candidates_pool` 的
ticker 集合，套用跟 `build_lists.py::_update_swing_history` 同一套「連續天數」
邏輯，算出每檔目前的首次進榜日／連續天數，寫成 `_update_swing_history` 認得
的狀態格式（`_asof`/`_pool`/`_prev_pool`/`tickers`）。只需要跑一次；之後每次
`build_lists.py` 重算會自己維護、累加這份檔案。

2026-09-24 Opus 審核抓到兩個坑，這版已經修：
  1. 同一個 trading_date 可能有多筆 commit（CI 排程正常重算 vs 本機手動修
     bug 重跑）——只留最後一版會**優先選到本機修正 commit**，不一定是當天
     CI 真正產出的版本。這版改成優先挑 `rebuild:` 開頭的 CI commit（`rebuild.yml`
     固定用這個前綴），只有某天完全沒有 CI commit 才退回用非 CI 版本。
  2. 舊版直接把每一版 git log 都當一天算，這版維持照 trading_date 去重（避免
     同一天多筆 commit 被重複算進連續天數）。

用法：
    python scripts/backfill_swing_history.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TARGET = "data/derived/swing_list.json"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _git_revs() -> list[tuple[str, str, str]]:
    """回傳 (commit hash, ISO 時間, commit message 第一行)，由舊到新。"""
    out = subprocess.run(
        ["git", "log", "--follow", "--format=%H|%aI|%s", "--", TARGET],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8",
        errors="replace", check=True).stdout
    revs = [line.split("|", 2) for line in out.strip().splitlines() if line.strip()]
    return list(reversed(revs))  # 由舊到新


def _show(rev: str) -> dict | None:
    out = subprocess.run(["git", "show", f"{rev}:{TARGET}"], cwd=REPO,
                         capture_output=True, text=True, encoding="utf-8",
                         errors="replace")
    if out.returncode != 0:
        return None
    try:
        return json.loads(out.stdout)
    except Exception:
        return None


def main() -> int:
    revs = _git_revs()
    # 同一個 trading_date 可能有多筆 commit——優先留 `rebuild:` 開頭的 CI
    # commit（同一天多筆 CI commit 的話留最後一筆），完全沒有 CI commit
    # 才退回用非 CI 版本（同樣留最後一筆）。
    by_date_ci: dict[str, list] = {}
    by_date_any: dict[str, list] = {}
    for rev, iso_dt, msg in revs:
        payload = _show(rev)
        if not payload or "candidates_pool" not in payload:
            continue  # M0.5 前的舊格式，沒有候選池概念
        asof_s = payload.get("_meta", {}).get("trading_date") or iso_dt[:10]
        by_date_any[asof_s] = payload["candidates_pool"]
        if msg.startswith("rebuild:"):
            by_date_ci[asof_s] = payload["candidates_pool"]
    by_date = {**by_date_any, **by_date_ci}  # CI 版覆蓋非 CI 版

    hist: dict = {}
    prev_hist: dict = {}
    prev_pool: set[str] = set()
    prev_prev_pool: set[str] = set()
    for asof_s in sorted(by_date):
        cur_pool = {c["ticker"] for c in by_date[asof_s]}
        new_hist = {}
        for tk in cur_pool:
            ph = hist.get(tk)
            if tk in prev_pool and ph:
                streak = int(ph["streak_days"]) + 1
                first_seen = ph["first_seen"]
            else:
                streak = 1
                first_seen = asof_s
            new_hist[tk] = {"first_seen": first_seen, "streak_days": streak}
        prev_hist = hist
        hist = new_hist
        prev_prev_pool = prev_pool
        prev_pool = cur_pool

    state = {
        "_asof": max(by_date) if by_date else None,
        "_pool": sorted(prev_pool),
        "_prev_pool": sorted(prev_prev_pool),
        "_prev_tickers": prev_hist,
        "tickers": hist,
    }
    out_p = REPO / "data" / "derived" / "swing_history.json"
    out_p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"→ {out_p}　（回放 {len(by_date)} 個交易日，目前在榜 {len(hist)} 檔有紀錄，"
         f"asof={state['_asof']}）")
    for tk, h in sorted(hist.items(), key=lambda kv: -kv[1]["streak_days"])[:10]:
        print(f"   {tk}　首次進榜 {h['first_seen']}　連續 {h['streak_days']} 天")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
