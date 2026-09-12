"""本機開發用：一次把「上游 bundle 拉新 + 三清單 + 出場觀察表重算」都做完。

**只給本機/本地開發用**，不是給 CI 用（CI 走 `rebuild.yml`，那邊有自己的排程跟
`repository_dispatch`）。使用情境：本機的 `data/upstream/`（bundle，不進版控，
執行期才有）放久了會跟 GitHub 上的資料脫節——2026-09-12 就抓到本機 `trading_date`
停在 5 天前。這支腳本把「該手動跑哪幾支」串起來，不用每次都想。

**只碰不進版控的東西**：`data/upstream/`（bundle）+ `data/derived/*.json`（重算結果，
這個雖然進版控，但改完你要自己看 `git diff` 決定要不要 commit——本機重算可能因為
拉 bundle 的時間點跟 CI 不同秒，數字會有極小的重算漂移，不要無腦全部 commit，
只挑真的要的檔案）。**不碰** `data/pcf/`（主動式 ETF PCF 快照）——那是
`scripts/snapshot_pcf.py` 打投信官網即時資料，本來就該一天一次由 CI 跑，
本機隨便重跑等於多打一次外部網站，不必要。

用法：
    python refresh_local.py            # 拉 bundle + 重算三清單 + 出場觀察表
    python refresh_local.py --check    # 只驗 bundle schema/日期，不落地、不重算清單
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _run(*args: str) -> int:
    print(f"\n$ {' '.join(args)}", flush=True)
    return subprocess.call([sys.executable, *args], cwd=REPO)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="只驗 bundle schema/日期（傳給 fetch_bundle.py），不重算清單")
    args = ap.parse_args()

    rc = _run("fetch_bundle.py", *(["--check"] if args.check else []))
    if rc != 0:
        print("\n🔴 fetch_bundle.py 失敗（schema 對不上或拉不到）——沒有重算清單。")
        return rc
    if args.check:
        return 0

    rc = _run("build_lists.py")
    if rc != 0:
        print("\n🔴 build_lists.py 失敗——bundle 已經是新的，但清單沒重算成功。")
        return rc

    print("\n完成。`data/derived/*.json` 已用新 bundle 重算——"
         "跑 `git diff data/derived/` 自己看要不要 commit（本機重算可能有極小漂移，"
         "不用無腦全收）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
