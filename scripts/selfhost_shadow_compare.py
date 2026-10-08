"""影子期每日比對：自建 zip（官方口徑）vs 上游 data_pack.zip，只看最近 N 個共同交易日。

不需要 tw-swing（跟 `selfhost_datapack_parity.py` 不同：那支用 tw-swing 匯入器比整段歷史，是 10/19 一次性的 B8 報告）。
兩包格式相同（data/{code}.TW|TWO.csv、data/institutional/*_inst.csv、data/margin/*_margin.csv），這裡直接讀 CSV。

為什麼只看最近幾天：最新一天的還原因子 F＝1（現價不動、被調整的是歷史），兩包最近幾天的收盤應等於官方收盤，
差異只會來自「漏抓／錯日／錯欄」——正是影子期要抓的。整段歷史的口徑差（約 1/3 還原價列差 >0.2%）已知，不在這裡報。

輸出 json：各項的共同代號數、只有一邊有的代號數、收盤相符率（相對差 ≤0.1%）、成交量比中位數、法人合計／融資餘額相符率；
加上兩包各自的最新日期。

    python scripts/selfhost_shadow_compare.py --selfhost data/selfhost/merged/data_pack_selfhost.zip --upstream data_pack.zip --json out.json
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import zipfile
from pathlib import Path

import pandas as pd

PRICE_RE = re.compile(r"^data/(\d{4})\.(TW|TWO)\.csv$")
INST_RE = re.compile(r"^data/institutional/(\d{4})_inst\.csv$")
MARGIN_RE = re.compile(r"^data/margin/(\d{4})_margin\.csv$")
CLOSE_TOL = 0.001


def _tail_csv(zf: zipfile.ZipFile, name: str, date_col: str, since: pd.Timestamp) -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(zf.read(name)), encoding="utf-8-sig", low_memory=False)
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    return df[df[date_col] >= since]


def read_recent(path: Path, days: int) -> dict[str, pd.DataFrame]:
    """讀最近 `days` 個日曆日×2 的列（先粗切，再由呼叫端取共同交易日）。"""
    out = {"price": [], "inst": [], "margin": []}
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        # 先用 0050（或第一個價格檔）定最新日，往前粗切
        px_names = [n for n in names if PRICE_RE.match(n)]
        probe = next((n for n in px_names if "/0050." in n), px_names[0] if px_names else None)
        if probe is None:
            return {k: pd.DataFrame() for k in out}
        last = pd.read_csv(io.BytesIO(zf.read(probe)), encoding="utf-8-sig")["Date"].max()
        since = pd.Timestamp(last) - pd.Timedelta(days=days * 2 + 7)
        for n in names:
            if m := PRICE_RE.match(n):
                df = _tail_csv(zf, n, "Date", since)
                out["price"].append(df.assign(code=m.group(1), market=m.group(2)))
            elif m := INST_RE.match(n):
                df = _tail_csv(zf, n, "date", since)
                out["inst"].append(df.assign(code=m.group(1)))
            elif m := MARGIN_RE.match(n):
                df = _tail_csv(zf, n, "date", since)
                out["margin"].append(df.assign(code=m.group(1)))
    res = {k: (pd.concat(v, ignore_index=True) if v else pd.DataFrame()) for k, v in out.items()}
    if len(res["price"]):
        res["price"] = res["price"].rename(columns={"Date": "date"})
    return res


def compare(a: dict[str, pd.DataFrame], b: dict[str, pd.DataFrame], days: int) -> dict:
    """a＝自建、b＝上游。"""
    rep: dict = {"latest": {"selfhost": str(a["price"]["date"].max().date()) if len(a["price"]) else None,
                            "upstream": str(b["price"]["date"].max().date()) if len(b["price"]) else None}}
    common_days = sorted(set(a["price"]["date"]) & set(b["price"]["date"]))[-days:] if len(a["price"]) and len(b["price"]) else []
    rep["days"] = [str(d.date()) for d in common_days]
    if not common_days:
        rep["error"] = "沒有共同交易日"
        return rep
    per_day = {}
    for d in common_days:
        pa = a["price"][a["price"]["date"] == d]
        pb = b["price"][b["price"]["date"] == d]
        m = pa.merge(pb, on="code", suffixes=("_s", "_u"))
        rel = (m["Close_s"] / m["Close_u"] - 1).abs()
        vr = (m["Volume_s"] / m["Volume_u"].where(m["Volume_u"] > 0)).dropna()
        r = {"common": len(m), "only_selfhost": len(set(pa["code"]) - set(pb["code"])),
             "only_upstream": len(set(pb["code"]) - set(pa["code"])),
             "close_match": round(float((rel <= CLOSE_TOL).mean()), 4) if len(m) else None,
             "close_mismatch_codes": m.loc[rel > CLOSE_TOL, "code"].head(15).tolist(),
             "volume_ratio_median": round(float(vr.median()), 4) if len(vr) else None}
        for kind, cols in (("inst", ["total_net"]), ("margin", ["margin_balance", "short_balance"])):
            ka, kb = a[kind], b[kind]
            if not len(ka) or not len(kb):
                r[kind] = None
                continue
            ma = ka[ka["date"] == d].merge(kb[kb["date"] == d], on="code", suffixes=("_s", "_u"))
            r[kind] = {"common": len(ma), **{f"{c}_match": round(float((ma[f"{c}_s"] == ma[f"{c}_u"]).mean()), 4) if len(ma) else None
                                             for c in cols if f"{c}_s" in ma.columns and f"{c}_u" in ma.columns}}
        per_day[str(d.date())] = r
    rep["per_day"] = per_day
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selfhost", required=True)
    ap.add_argument("--upstream", required=True)
    ap.add_argument("--days", type=int, default=5)
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    rep = compare(read_recent(Path(a.selfhost), a.days), read_recent(Path(a.upstream), a.days), a.days)
    text = json.dumps(rep, ensure_ascii=False, indent=1)
    if a.json:
        Path(a.json).write_text(text, encoding="utf-8")
    print(text)
    # 只對「最新共同日」發警告：較早的日子，之後有除權息／減資的檔，兩包的還原歷史本來就不同（口徑差，非錯誤）。
    # 最新一天 F＝1，兩包都應等於官方收盤；對不上多半是某一包預套了未來事件或漏還原（2026-10-08 實例：上游 3625 把
    # 10/19 減資因子乘到 10/7 收盤、上游 6108 沒還原 10/7 除息）——要人看是哪一包錯，不自動判。
    per_day = rep.get("per_day", {})
    if per_day:
        d, r = list(per_day.items())[-1]
        if r["close_match"] is not None and r["close_mismatch_codes"]:
            print(f"::warning::最新共同日 {d} 收盤有 {len(r['close_mismatch_codes'])} 檔對不上（相符率 {r['close_match']:.2%}）："
                  f"{r['close_mismatch_codes']}——查是哪一包錯", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
