"""自建 zip 發佈前的閘門（B11 起步版）：新的一包不可以比已發佈的那包差。

檢查（任一不過 → exit 1，不上傳；已發佈那包保持不動）：
  1. zip 打得開、內容完整（`testzip`）
  2. 完整日不早於已發佈那包（不可倒退）
  3. 日線檔數不比已發佈那包少超過 2%
  4. 錨點代號（0050、2330 上市；6488 上櫃）都在，且最後一列日期＝完整日、收盤＝官方未還原收盤（最新一天 F＝1）
  5. 法人、融資檔數 > 0

通過後把 zip 的 sha256、檔數、完整日寫進 manifest（下游 tw-swing 要比對 sha256 才用，避免讀到傳到一半的 zip）。

    python scripts/selfhost_zip_gate.py --zip merged/data_pack_selfhost.zip --manifest merged/merge_manifest.json \
        --raw merged/raw_prices.parquet [--published published_manifest.json]
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

import pandas as pd

ANCHORS = {"0050": "TW", "2330": "TW", "6488": "TWO"}
SHRINK_TOL = 0.02


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check(zip_path: Path, manifest: dict, raw: pd.DataFrame, published: dict | None) -> tuple[list[str], dict]:
    errs: list[str] = []
    cday = pd.Timestamp(manifest["complete_day"])
    stats: dict = {}
    with zipfile.ZipFile(zip_path) as zf:
        bad = zf.testzip()
        if bad:
            errs.append(f"zip 內容損壞：{bad}")
        names = zf.namelist()
        stats["price_files"] = sum(1 for n in names if n.startswith("data/") and n.count("/") == 1 and n.endswith((".TW.csv", ".TWO.csv")))
        stats["inst_files"] = sum(1 for n in names if n.startswith("data/institutional/"))
        stats["margin_files"] = sum(1 for n in names if n.startswith("data/margin/"))
        for code, mk in ANCHORS.items():
            n = f"data/{code}.{mk}.csv"
            if n not in names:
                errs.append(f"錨點 {n} 不在 zip 裡")
                continue
            df = pd.read_csv(io.BytesIO(zf.read(n)))
            last = df.iloc[-1]
            if pd.Timestamp(last["Date"]) != cday:
                errs.append(f"錨點 {code} 最後日 {last['Date']} ≠ 完整日 {cday.date()}")
                continue
            r = raw[(raw["ticker"] == code) & (pd.to_datetime(raw["date"]) == cday)]
            if r.empty or abs(float(last["Close"]) / float(r["close"].iloc[0]) - 1) > 1e-9:
                errs.append(f"錨點 {code} 最新收盤 {last['Close']} ≠ 官方未還原收盤 {None if r.empty else float(r['close'].iloc[0])}")
    if stats["inst_files"] == 0 or stats["margin_files"] == 0:
        errs.append(f"法人／融資檔數為 0：{stats}")
    if published:
        if cday < pd.Timestamp(published["complete_day"]):
            errs.append(f"完整日倒退：{cday.date()} < 已發佈 {published['complete_day']}")
        old = (published.get("zip") or {}).get("price_files")
        if old and stats["price_files"] < old * (1 - SHRINK_TOL):
            errs.append(f"日線檔數縮水：{stats['price_files']} < 已發佈 {old} × {1 - SHRINK_TOL}")
    return errs, stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--raw", required=True)
    ap.add_argument("--published")
    a = ap.parse_args(argv)
    zp, mp = Path(a.zip), Path(a.manifest)
    man = json.loads(mp.read_text(encoding="utf-8"))
    pub = json.loads(Path(a.published).read_text(encoding="utf-8")) if a.published and Path(a.published).exists() else None
    raw = pd.read_parquet(a.raw, columns=["ticker", "date", "close"])
    errs, stats = check(zp, man, raw, pub)
    if errs:
        for e in errs:
            print(f"::error::zip 閘門：{e}", file=sys.stderr)
        return 1
    man["zip"] = {"name": zp.name, "sha256": sha256(zp), "bytes": zp.stat().st_size, **stats}
    mp.write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[gate] 通過：完整日 {man['complete_day']}、{stats}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
