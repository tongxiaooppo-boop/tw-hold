"""私有參考資料同步 CLI（見 reference/refdata.py 檔頭）。

    python scripts/refdata_sync.py pull [--only ref|pcf|all]
    python scripts/refdata_sync.py push data/reference/global_macro.parquet data/pcf ...

CI：job 開頭 pull、抓完 push 自己動過的檔。token：環境變數 DATA_REPO_PAT（寫）／DATA_READ_PAT（讀）。
pull 沒 token／沒 Release 時結束碼 0（本機開發不受影響）；push 失敗結束碼 1（寫入端要大聲）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reference import refdata  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("pull")
    p1.add_argument("--only", choices=["all", "ref", "pcf"], default="all")
    p2 = sub.add_parser("push")
    p2.add_argument("paths", nargs="+")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "pull":
            r = refdata.pull(a.only)
            bad = {k: v for k, v in r.items() if isinstance(v, str) and v.startswith("失敗")}
            print(f"[refdata] pull {a.only}：{len(r)} 項", {k: v for k, v in list(r.items())[:12]})
            for k, v in bad.items():
                print(f"::warning::refdata pull {k} {v}", file=sys.stderr)
            return 0
        r = refdata.push([Path(p) for p in a.paths])
        print("[refdata] push", r)
        skipped = [k for k, v in r.items() if isinstance(v, str)]
        if skipped:
            print(f"::warning::refdata push 略過：{skipped}", file=sys.stderr)
        return 0
    except refdata.RefdataError as e:
        print(f"::error::refdata {a.cmd} 失敗：{e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
