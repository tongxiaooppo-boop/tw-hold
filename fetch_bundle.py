"""從 tw-swing 私有 repo 的 Release（移動 tag `data-latest`）拉上游 bundle
→ 解到 `data/upstream/`，並跑守門員（PRD §3.2、PLAN §M0.5）。

  G1  schema assert：`_meta.json` 的 `schema_version` + 每檔 `columns` / `sha256`
      對不上 → **大聲失敗**（兩個 repo 之間唯一的正式介面，不「盡力而為」）
  G3  `_meta.json.trading_date` vs 今天——不符**不失敗**，回報給清單頁標記
  ⚠️  只有 U1a 資產（財報 / per）時要能正常收工——缺 U1b 的日線檔就在結果裡
      標「日線類不可用」，**不是拋錯**（M0a 才跑得起來）

PAT（fine-grained、`tongxiaooppo-boop/tw-swing` 的 `contents: read`）：
  - 本地：`.env` 的 `TWSWING_BUNDLE_PAT`
  - GitHub Actions：`secrets.TWSWING_BUNDLE_PAT`（env 帶進來）
  - Streamlit Community Cloud：`st.secrets["TWSWING_BUNDLE_PAT"]`

用法：
    python fetch_bundle.py            # 拉最新 → data/upstream/
    python fetch_bundle.py --check    # 只驗 schema / 日期，不覆寫檔案
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent
UPSTREAM = REPO / "data" / "upstream"

BUNDLE_REPO = "tongxiaooppo-boop/tw-swing"   # 私有 repo，bundle 走其 Release
RELEASE_TAG = "data-latest"
SCHEMA_VERSION = 1                            # G1：與 tw-swing make_bundle_meta.py 對齊
GH_API = "https://api.github.com"

#: 哪些 bundle 檔屬於哪條上游管線。缺 u1b 的 → 「日線類不可用」不是錯。
PIPELINE = {
    "fundamentals/income.parquet": "u1a",
    "fundamentals/balance.parquet": "u1a",
    "fundamentals/cashflow.parquet": "u1a",
    "fundamentals/dividend.parquet": "u1a",
    "fundamentals/per.parquet": "u1a",
    "_meta.json": "u1a",
    "fundamentals/universe.parquet": "u1b",
    "prices_adj.parquet": "u1b",
    "prices_raw_close.parquet": "u1b",
    "revenue.parquet": "u1b",
    "index_0050.parquet": "u1b",
    "chips.parquet": "u1b",
}


class BundleError(RuntimeError):
    """G1 / 下載失敗——要大聲。"""


def _read_pat() -> str | None:
    tok = os.environ.get("TWSWING_BUNDLE_PAT")
    if tok:
        return tok.strip()
    env = REPO / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            if k.strip() == "TWSWING_BUNDLE_PAT" and v.strip():
                return v.strip().strip('"').strip("'")
    try:
        import streamlit as st  # noqa: PLC0415
        return st.secrets.get("TWSWING_BUNDLE_PAT")
    except Exception:
        return None


def _api(url: str, pat: str, accept: str = "application/vnd.github+json") -> bytes:
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {pat}",
        "Accept": accept,
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "tw-hold-fetch-bundle",
    })
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise BundleError(f"GitHub API {e.code} {url}\n{detail}") from e


def _release_assets(pat: str) -> list[dict]:
    url = f"{GH_API}/repos/{BUNDLE_REPO}/releases/tags/{RELEASE_TAG}"
    rel = json.loads(_api(url, pat))
    return rel.get("assets", [])


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _rel_for_basename(name: str) -> str | None:
    for rel in PIPELINE:
        if Path(rel).name == name:
            return rel
    return None


def fetch(check_only: bool = False) -> dict:
    """回傳結果 dict：`{trading_date, date_stale, u1b_available, files:[...], warnings:[...]}`。
    G1 失敗會 raise BundleError。"""
    pat = _read_pat()
    if not pat:
        raise BundleError(
            "找不到 TWSWING_BUNDLE_PAT（.env / 環境變數 / st.secrets）——"
            "tw-swing 是私有 repo，拉 Release 資產需要 PAT")

    assets = _release_assets(pat)
    if not assets:
        raise BundleError(f"Release `{RELEASE_TAG}` 沒有任何資產——tw-swing 還沒發佈過？")
    by_name = {a["name"]: a for a in assets}

    if "_meta.json" not in by_name:
        raise BundleError("Release 缺 `_meta.json`——這是唯一的正式介面，不能沒有")

    UPSTREAM.mkdir(parents=True, exist_ok=True)
    (UPSTREAM / "fundamentals").mkdir(exist_ok=True)

    meta_raw = _api(by_name["_meta.json"]["url"], pat, accept="application/octet-stream")
    meta = json.loads(meta_raw)
    if meta.get("schema_version") != SCHEMA_VERSION:
        raise BundleError(
            f"G1: schema_version {meta.get('schema_version')} ≠ 預期 {SCHEMA_VERSION}"
            "——上游改了 schema，tw-hold 要跟上（改 SCHEMA_VERSION + 對應讀取碼）")
    if not check_only:
        (UPSTREAM / "_meta.json").write_bytes(meta_raw)

    warnings: list[str] = []
    got: list[str] = []
    for rel, spec in meta.get("files", {}).items():
        base = Path(rel).name
        if base == "_meta.json":
            continue
        asset = by_name.get(base)
        if asset is None:
            msg = f"Release 缺 {base}（_meta.json 說有）"
            if PIPELINE.get(rel) == "u1b":
                warnings.append(msg)
                continue
            raise BundleError(f"G1: {msg}")

        dest = UPSTREAM / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not check_only:
            data = _api(asset["url"], pat, accept="application/octet-stream")
            dest.write_bytes(data)
            digest = hashlib.sha256(data).hexdigest()
        else:
            digest = _sha256(dest) if dest.exists() else None

        if spec.get("sha256") and digest and digest != spec["sha256"]:
            raise BundleError(
                f"G1: {base} sha256 對不上（下載 {digest[:12]}… ≠ meta {spec['sha256'][:12]}…）")
        got.append(rel)

    # G1 欄位檢查（要 pandas；check_only 且檔案不在就跳過）
    try:
        import pandas as pd  # noqa: PLC0415
        for rel in got:
            dest = UPSTREAM / rel
            if not dest.exists():
                continue
            cols = sorted(pd.read_parquet(dest, columns=None).columns.tolist()) \
                if dest.suffix == ".parquet" else None
            want = meta["files"][rel].get("columns")
            if cols is not None and want and cols != sorted(want):
                raise BundleError(
                    f"G1: {rel} 欄位對不上\n  bundle: {cols}\n  meta  : {sorted(want)}")
    except ImportError:
        warnings.append("沒有 pandas，跳過欄位檢查（只驗了 sha256）")

    # G3 交易日新鮮度（不失敗）
    td = meta.get("trading_date")
    stale = None
    if td:
        try:
            days = (date.today() - datetime.fromisoformat(td).date()).days
            stale = days
            if days > 5:
                warnings.append(f"G3: bundle trading_date {td} 距今 {days} 天（可能上游斷了）")
        except ValueError:
            warnings.append(f"G3: trading_date 格式怪：{td!r}")

    u1b = all(
        (UPSTREAM / rel).exists()
        for rel, p in PIPELINE.items() if p == "u1b" and rel != "chips.parquet"
    ) and not check_only

    result = {
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "trading_date": td,
        "date_stale_days": stale,
        "u1b_available": u1b,
        "files": got,
        "warnings": warnings,
    }
    if not check_only:
        (UPSTREAM / "_fetch_result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只驗 schema/日期，不覆寫檔案")
    args = ap.parse_args()
    try:
        r = fetch(check_only=args.check)
    except BundleError as e:
        print(f"[FAIL] {e}", file=sys.stderr)
        return 1
    print(f"trading_date {r['trading_date']}　"
          f"(距今 {r['date_stale_days']} 天)　"
          f"U1b {'可用' if r['u1b_available'] else '不可用（只有 U1a）'}")
    print(f"檔案 {len(r['files'])}：" + ", ".join(r["files"]))
    for w in r["warnings"]:
        print(f"  ⚠️ {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
