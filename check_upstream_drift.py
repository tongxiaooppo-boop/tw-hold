"""守門員 G5：偵測 tw-swing 的**上游來源檔**在複製之後有沒有被改。

**只提醒、不自動同步**（PLAN §M0.4 / §M0.5）。

判斷方式：`reference/` 裡的檔案是從 tw-swing 複製來、且**在 tw-hold 這邊有意
改過**（改 import、.env 路徑、精簡 docstring），所以不能拿兩份直接比 hash。
改比對「tw-swing 那份**現在**的 SHA-256」vs「複製當時記下的 baseline」——
不一樣 = 上游動過了，該回去看 diff、決定要不要把新改動 merge 進來。

baseline 在下面 `BASELINE`，跟著 `reference/UPSTREAM.md` 一起維護：
每次手動 merge 上游改動後，更新這裡的 hash + UPSTREAM.md 的 commit 欄。

⚠️ 只在本機、tw-swing 也 checkout 在旁邊（`../tw-swing`）時能跑；CI 沒有 →
   跳過回 0。永遠回 0（提醒不是門檻）。

用法：
    python check_upstream_drift.py
    python check_upstream_drift.py --tw-swing /path/to/tw-swing
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

REPO = Path(__file__).resolve().parent

#: tw-swing 來源檔（相對 repo 根） -> 複製當時的 SHA-256。
#: 更新時機：手動把上游改動 merge 進 reference/ 之後。
BASELINE = {
    "src/twswing/data/regime.py":
        "69747e90b973b9c4f4fecf412608990b5d741626de16715dd50552720791b942",
    "src/twswing/data/finmind.py":
        "fcd201e63262ec1be61dad00120614854ca9122244226d4775fae1fba70c617e",
    # M1/M4 複製進來後補：indicators/*, price_adjuster.py, fetcher.py
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tw-swing", default=str(REPO.parent / "tw-swing"))
    args = ap.parse_args()
    tws = Path(args.tw_swing)

    if not (tws / ".git").exists():
        print(f"[skip] 找不到 tw-swing working tree（{tws}）")
        return 0

    drift = 0
    for src, base in BASELINE.items():
        p = tws / src
        if not p.exists():
            print(f"[MOVED?] {src} 上游來源不見了——路徑可能改了")
            drift += 1
            continue
        cur = hashlib.sha256(p.read_bytes()).hexdigest()
        if cur == base:
            print(f"[ok]   {src}")
        else:
            print(f"[DRIFT] {src}")
            print(f"        baseline {base[:16]}...  現在 {cur[:16]}...")
            print(f"        看 diff： git -C {tws} log -p -- {src}")
            drift += 1

    print()
    if drift:
        print(f"{drift} 個上游來源檔動過了。**只提醒**——決定要不要 merge，"
              f"merge 完更新本檔 BASELINE + reference/UPSTREAM.md。")
    else:
        print("上游來源沒動。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
