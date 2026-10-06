"""轉接層驗收：把 `selfhost_to_datapack.py` 產的 zip，用 **tw-swing 自己的匯入解析器** 解開，逐檔跟 tw-swing 現行 store 比。

不寫入任何 store：只呼叫 tw-swing 的 `import_data_pack.parse_one`、`twswing.data.chips.normalize_*`（純函式），
再跟 `data/store/{daily_full,inst,margin}.parquet` 比。

輸出：還原價相對差分佈（≤0.2% 的列佔比）、有差異的股票清單（供歸因）、法人／融資券逐欄相符率、只有一邊有的列數。

用法：
    python scripts/selfhost_datapack_parity.py --zip data/selfhost/data_pack_selfhost.zip --swing-root ../tw-swing [--json out.json]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

REL_TOL = 0.002


def _load_swing(swing_root: Path):
    sys.path.insert(0, str(swing_root / "src"))
    spec = importlib.util.spec_from_file_location("swing_import_data_pack", swing_root / "scripts" / "import_data_pack.py")
    idp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(idp)
    from twswing.data import chips  # noqa: PLC0415
    return idp, chips


def compare_prices(zf: zipfile.ZipFile, idp, store_daily: pd.DataFrame) -> dict:
    names = [n for n in zf.namelist() if idp.is_price_file(n)]
    frames, fails = [], 0
    for n in names:
        df, why = idp.parse_one(n, zf.read(n))
        if df is None:
            fails += 1
            continue
        frames.append(df)
    mine = pd.concat(frames, ignore_index=True)
    mine["ticker"] = mine["ticker"].astype(str)
    sd = store_daily[store_daily["ticker"].astype(str).isin(set(mine["ticker"]))].copy()
    sd["ticker"] = sd["ticker"].astype(str)
    sd = sd[(sd["date"] >= mine["date"].min()) & (sd["date"] <= mine["date"].max())]      # 只比 zip 涵蓋的期間
    m = mine.merge(sd[["ticker", "date", "open", "high", "low", "close", "volume"]], on=["ticker", "date"], how="outer",
                   suffixes=("", "_swing"), indicator=True)
    both = m[m["_merge"] == "both"].copy()
    rel = (both["close"] / both["close_swing"] - 1).abs()
    ok = rel <= REL_TOL
    vol_eq = (both["volume"] == both["volume_swing"])
    # 差異的形狀：上游「還原接縫」（只重抓最近 7 天，舊歷史停在尚未套用近期事件的水位）會讓兩邊的比值呈**階梯狀**（同一檔
    # 長時間維持同一個比值、只在事件日跳一下）；真正的資料不一致則是雜訊狀。逐檔數「比值變動點」分類。
    both = both.sort_values(["ticker", "date"])
    both["ratio"] = (both["close"] / both["close_swing"]).round(4)
    steps = both.groupby("ticker")["ratio"].apply(lambda r: int((r.diff().abs() > 1e-4).sum()))
    maxrel = rel.groupby(both["ticker"]).max()
    kind = pd.Series("相符（全程 ≤0.2%）", index=steps.index)
    kind[(maxrel > REL_TOL) & (steps <= 6)] = "階梯狀差異（疑似上游還原接縫）"
    kind[(maxrel > REL_TOL) & (steps > 6)] = "雜訊狀差異（需查）"
    bad = both[~ok].assign(rel=rel[~ok])
    by_t = bad.groupby("ticker").agg(n=("rel", "size"), max_rel=("rel", "max"), first=("date", "min"), last=("date", "max")) \
        .sort_values("n", ascending=False)
    return {
        "price_files_parsed": len(frames), "price_files_failed": fails, "rows_both": int(len(both)),
        "rows_only_selfhost": int((m["_merge"] == "left_only").sum()), "rows_only_swing_store": int((m["_merge"] == "right_only").sum()),
        "close_within_tol_pct": round(float(ok.mean()) * 100, 3), "volume_equal_pct": round(float(vol_eq.mean()) * 100, 3),
        "tickers_total": int(len(steps)), "ticker_kinds": kind.value_counts().to_dict(),
        "noisy_tickers": [t for t in kind[kind == "雜訊狀差異（需查）"].index][:30],
        "tickers_with_diff": int(len(by_t)), "worst_tickers": by_t.head(15).reset_index().astype({"first": str, "last": str}).to_dict("records"),
    }


def compare_chips(zf: zipfile.ZipFile, chips, store: pd.DataFrame, kind: str) -> dict:
    pat = re.compile(rf"^data/{'institutional' if kind == 'inst' else 'margin'}/([0-9A-Z]+)_{'inst' if kind == 'inst' else 'margin'}\.csv$")
    norm = chips.normalize_institutional if kind == "inst" else chips.normalize_margin
    cols = ["foreign_net", "fi_prop_net", "trust_net", "dealer_net", "total_net"] if kind == "inst" else \
        ["margin_balance", "margin_buy", "margin_sell", "margin_redeem", "short_balance", "short_buy", "short_sell", "short_redeem", "offset"]
    frames = []
    for n in zf.namelist():
        mm = pat.match(n)
        if not mm:
            continue
        raw = pd.read_csv(zf.open(n), encoding="utf-8-sig")
        df, _ = norm(raw, mm.group(1))
        frames.append(df)
    mine = pd.concat(frames, ignore_index=True)
    sd = store[store["code"].astype(str).isin(set(mine["code"]))]
    sd = sd[(sd["date"] >= mine["date"].min()) & (sd["date"] <= mine["date"].max())]      # 只比 zip 涵蓋的期間
    m = mine.merge(sd, on=["code", "date"], how="outer", suffixes=("", "_swing"), indicator=True)
    both = m[m["_merge"] == "both"]
    out = {"rows_both": int(len(both)), "rows_only_selfhost": int((m["_merge"] == "left_only").sum()),
           "rows_only_swing_store": int((m["_merge"] == "right_only").sum()), "cols": {}}
    for c in cols:
        a, b = pd.to_numeric(both[c], errors="coerce"), pd.to_numeric(both[c + "_swing"], errors="coerce")
        same = (a == b) | (a.isna() & b.isna())
        out["cols"][c] = round(float(same.mean()) * 100, 3)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", required=True)
    ap.add_argument("--swing-root", required=True)
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    root = Path(a.swing_root)
    idp, chips = _load_swing(root)
    store = root / "data" / "store"
    res = {}
    with zipfile.ZipFile(a.zip) as zf:
        res["prices"] = compare_prices(zf, idp, pd.read_parquet(store / "daily_full.parquet", columns=["ticker", "date", "open", "high", "low", "close", "volume"]))
        res["inst"] = compare_chips(zf, chips, pd.read_parquet(store / "inst.parquet"), "inst")
        res["margin"] = compare_chips(zf, chips, pd.read_parquet(store / "margin.parquet"), "margin")
    print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    if a.json:
        Path(a.json).write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
