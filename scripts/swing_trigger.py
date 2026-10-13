"""自建資料包發佈後，通知 tw-swing 跑每日掃描（事件接力）：不吃 GitHub 排程延遲。

判斷與呼叫從 `selfhost_datapack.yml` 的 shell 搬進來（YAML 沒有真 runner 可測；這裡的判斷邏輯有 pytest）。

## 什麼時候觸發（`should_trigger`）
資料包的「完整日」（日線／法人／融資券三項最小的最後日）是「當日地基完成」的明確訊號。**一個完整日只觸發一次**：
- 新的完整日**前進**了（跟已發佈的 manifest 比；已發佈沒有就當前進），而且
- **事件涵蓋到完整日**（`events_gap_days` 為空）。除息／減資事件還沒進來時，該日還原價會有假跳空，
  tw-swing 當日清單**產出後不可修改**，提早觸發等於把清單凍結在錯的資料上（2026-10-13 Opus 審核）。
- 若上一次因為事件缺口而沒觸發（已發佈的 manifest 帶著缺口），事件補齊後**補觸發一次**——否則那一天永遠不會接力。
同一天內容更正的重發（完整日沒前進、也沒有缺口轉好）**不觸發**，避免空跑；那種情況 tw-swing 的備援排程與 bundle 閘門（sha256）會接住。

## 失敗怎麼辦
任何失敗只印警告、結束碼 0：資料包已經發佈完成，不能因為通知失敗而變紅；tw-swing 有自己的排程備援（不要把它的 cron 全砍）。
手動重發（`force=true`）同一天不會觸發，符合上面的「一個完整日一次」。

## 用法
    python scripts/swing_trigger.py --new M/merge_manifest.json --old P/merge_manifest.json            # 只印決定（預設，不呼叫）
    SWING_PAT=… python scripts/swing_trigger.py --new … --old … --dispatch                              # 真的呼叫 workflow_dispatch
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

SWING_REPO = "tongxiaooppo-boop/tw-swing"
SWING_WORKFLOW = "daily.yml"
FALLBACK_BRANCH = "master"          # tw-swing 的預設分支是 master（2026-10-09 寫死 main 被 GitHub 拒絕、靜默不觸發）
_API = "https://api.github.com"


def should_trigger(new: dict, old: dict | None) -> tuple[bool, str]:
    """純函式：回 (要不要觸發, 理由)。`new`＝這次要發佈的 manifest；`old`＝已發佈的 manifest（沒有＝None）。"""
    new_day = str(new.get("complete_day") or "")
    if not new_day:
        return False, "新 manifest 沒有 complete_day，不觸發"
    gaps = new.get("events_gap_days") or []
    if gaps:
        return False, f"事件還沒涵蓋到完整日 {new_day}（缺口：{', '.join(map(str, gaps))}）——不觸發，避免把當日清單凍結在假跳空的還原價上"
    old_day = str((old or {}).get("complete_day") or "")
    if not old_day:
        return True, f"已發佈版本沒有完整日，視為前進：{new_day}"
    if new_day > old_day:
        return True, f"完整日前進 {old_day} → {new_day}"
    if new_day == old_day and (old or {}).get("events_gap_days"):
        return True, f"完整日 {new_day} 先前因事件缺口沒觸發，現在事件已補齊——補觸發"
    return False, f"完整日沒有前進（{old_day} → {new_day}），不觸發"


def _request(url: str, pat: str, method: str = "GET", data: bytes | None = None):
    req = urllib.request.Request(url, method=method, data=data, headers={
        "Authorization": f"Bearer {pat}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", **({"Content-Type": "application/json"} if data else {})})
    return urllib.request.urlopen(req, timeout=20)


def default_branch(pat: str, opener=_request) -> str:
    """問 API 取 tw-swing 預設分支；問不到退回 master。"""
    try:
        with opener(f"{_API}/repos/{SWING_REPO}", pat) as r:
            return json.loads(r.read().decode("utf-8")).get("default_branch") or FALLBACK_BRANCH
    except Exception:                                    # noqa: BLE001
        return FALLBACK_BRANCH


def dispatch(pat: str, opener=_request) -> tuple[bool, str]:
    """呼叫 tw-swing 的 workflow_dispatch。回 (成功與否, 訊息)；**不拋例外**。"""
    branch = default_branch(pat, opener)
    url = f"{_API}/repos/{SWING_REPO}/actions/workflows/{SWING_WORKFLOW}/dispatches"
    try:
        with opener(url, pat, "POST", json.dumps({"ref": branch}).encode("utf-8")) as r:
            return (r.status == 204), f"HTTP {r.status}（分支 {branch}）"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}：{e.read().decode('utf-8', errors='replace')[:200]}"
    except Exception as e:                               # noqa: BLE001
        return False, f"{type(e).__name__}：{str(e)[:200]}"


def _load(p: str | None) -> dict | None:
    if not p:
        return None
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--new", required=True, help="這次要發佈的 merge_manifest.json")
    ap.add_argument("--old", help="已發佈的 merge_manifest.json（沒有就視為第一次）")
    ap.add_argument("--dispatch", action="store_true", help="真的呼叫 workflow_dispatch（預設只印決定）")
    a = ap.parse_args(argv)
    new = _load(a.new)
    if new is None:
        print(f"::warning::讀不到新 manifest（{a.new}），不觸發 tw-swing")
        return 0
    go, why = should_trigger(new, _load(a.old))
    print(f"[swing_trigger] {'觸發' if go else '不觸發'}：{why}")
    if not go or not a.dispatch:
        return 0
    pat = (os.environ.get("SWING_PAT") or "").strip()
    if not pat:
        print("::warning::TWSWING_DISPATCH_PAT 沒設，無法觸發 tw-swing")
        return 0
    ok, msg = dispatch(pat)
    print(f"[swing_trigger] 已觸發 tw-swing {SWING_WORKFLOW}（完整日 {new['complete_day']}）：{msg}" if ok
          else f"::warning::觸發 tw-swing 失敗：{msg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
