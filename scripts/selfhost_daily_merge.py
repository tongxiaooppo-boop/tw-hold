"""B4（方案 a）：每週官方收集（selfhost-data）＋每日收集（openapi-daily）→ 併成一份「到完整日為止」的 raw，給 adjust → to_datapack。

只讀不寫來源：輸出到 `--out-dir`（預設 data/selfhost/merged/），**不覆蓋** data/selfhost/ 的週收集檔
（單一寫入者：週收集檔只由 selfhost_collect.yml 寫；這支的產出只給當班 adjust／to_datapack 用）。

## 併入規則（B12）
- 以 (市場, 資料日) 為單位：週收集有的日子 → 用週收集（帶日期網站端點、含官方事後更正）；週收集沒有的日子 → 用每日表。
- 同一天兩邊都有 → 用週收集，並記差異（只有一邊有的代號數、數值不同的列數）到 manifest，不靜默。
- 每日表的額外欄位（src、last_modified、fetched_at、next_ref…）丟掉，欄位與型別對齊週收集。

## 完整日
六項（日線／法人／融資券 × 上市／上櫃）各自的最後資料日取最小值＝完整日。完整日之後的列**整批不進這一版**
（只發佈價、法人、融資都齊的日子；半新半舊不發佈），在 manifest 記為 pending。

## 事件因子（B6）
`corp_actions`＝週收集的事件表 ∪ 每日收集的官方事件結果表窗口（`openapi_events.parquet`，每班抓 [今天−5, 今天]）。
同鍵（代號、日期、類型、來源）**以週收集為準**（含官方事後更正、經過 build 驗證）；每日表只補週收集還沒有的事件。
manifest 的 `events_through`＝max(週收集日線最後一天, 每日事件最近一次成功抓取涵蓋到的日子)；
完整日晚於 `events_through` 時，`events_gap_days` 會講出來，不靜默。

    python scripts/selfhost_daily_merge.py                       # 讀 data/selfhost/{raw_prices,inst,margin,openapi_*}.parquet
    python scripts/selfhost_daily_merge.py --weekly-dir A --daily-dir B --out-dir C
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SH = ROOT / "data" / "selfhost"
TABLES = {  # 名稱: (週收集檔, 每日檔, 比對數值欄)
    "raw_prices": ("raw_prices.parquet", "openapi_prices.parquet", ["open", "high", "low", "close", "volume"]),
    "inst": ("inst.parquet", "openapi_inst.parquet", ["foreign_net", "trust_net", "dealer_net", "total_net"]),
    "margin": ("margin.parquet", "openapi_margin.parquet", ["margin_balance", "short_balance", "margin_buy", "short_sell"]),
}
MARKETS = ("TW", "TWO")
VAL_TOL = 1e-6
GAP_WINDOW_DAYS = 14            # 完整日往前幾個日曆日內，檢查有沒有「別的表有、這張表沒有」的交易日


def _norm(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).astype("datetime64[us]")
    for c in ("ticker", "market"):
        df[c] = df[c].astype(str)
    return df


def merge_table(weekly: pd.DataFrame, daily: pd.DataFrame | None, val_cols: list[str]) -> tuple[pd.DataFrame, dict]:
    """回 (併好的表, 報告)。週收集優先；只補週收集沒有的 (市場, 日)。"""
    weekly = _norm(weekly)
    rep = {"appended": {}, "overlap": {}}
    if daily is None or daily.empty:
        return weekly, rep
    daily = _norm(daily)
    cols = list(weekly.columns)
    missing = [c for c in cols if c not in daily.columns]
    if missing:
        raise ValueError(f"每日表缺欄位 {missing}")
    daily = daily[cols].astype(weekly.dtypes.to_dict())
    wk = set(zip(weekly["market"], weekly["date"]))
    dk = daily[["market", "date"]].drop_duplicates()
    add_parts = []
    for mk, d in dk.itertuples(index=False):
        day = daily[(daily["market"] == mk) & (daily["date"] == d)]
        key = f"{mk} {d.date()}"
        if (mk, d) in wk:
            w = weekly[(weekly["market"] == mk) & (weekly["date"] == d)]
            m = w.merge(day, on="ticker", suffixes=("_w", "_d"))
            diff = {c: int((~((m[f"{c}_w"] - m[f"{c}_d"]).abs() <= VAL_TOL)
                            & ~(m[f"{c}_w"].isna() & m[f"{c}_d"].isna())).sum()) for c in val_cols}
            rep["overlap"][key] = {"weekly": len(w), "daily": len(day), "only_weekly": len(set(w["ticker"]) - set(day["ticker"])),
                                   "only_daily": len(set(day["ticker"]) - set(w["ticker"])), "value_diff": diff}
        else:
            add_parts.append(day)
            rep["appended"][key] = len(day)
    out = pd.concat([weekly, *add_parts], ignore_index=True) if add_parts else weekly
    return out.sort_values(["date", "market", "ticker"]).reset_index(drop=True), rep


def last_dates(tables: dict[str, pd.DataFrame]) -> dict[str, str | None]:
    out = {}
    for name, df in tables.items():
        for mk in MARKETS:
            s = df.loc[df["market"] == mk, "date"]
            out[f"{name}.{mk}"] = str(s.max().date()) if len(s) else None
    return out


def complete_day(lasts: dict[str, str | None]) -> pd.Timestamp | None:
    if any(v is None for v in lasts.values()):
        return None
    return pd.Timestamp(min(lasts.values()))


def find_gaps(merged: dict[str, pd.DataFrame], cday: pd.Timestamp, window: int = GAP_WINDOW_DAYS) -> dict[str, list[str]]:
    """完整日往前 `window` 個日曆日內的中間缺日：以三張表兩市場的日期聯集當交易日，哪張表哪個市場少了就是洞。
    （只看最後日抓不到「中間漏一天」——例：上市 10/9 失敗但 10/12 已進來，完整日仍前進，zip 會悄悄缺一天。）
    整天所有表都沒有的日子無法靠聯集發現（要交易日曆），由 selfhost_openapi_daily 的缺日偵測與週收集補。"""
    lo = cday - pd.Timedelta(days=window)
    days: set[pd.Timestamp] = set()
    for df in merged.values():
        d = df.loc[(df["date"] >= lo) & (df["date"] <= cday), "date"]
        days |= set(d.unique())
    gaps: dict[str, list[str]] = {}
    for name, df in merged.items():
        for mk in MARKETS:
            have = set(df.loc[(df["market"] == mk) & (df["date"] >= lo) & (df["date"] <= cday), "date"].unique())
            miss = sorted(days - have)
            if miss:
                gaps[f"{name}.{mk}"] = [str(pd.Timestamp(d).date()) for d in miss]
    return gaps


def _read(p: Path) -> pd.DataFrame | None:
    return pd.read_parquet(p) if p.exists() else None


EVENT_KEY = ["ticker", "date", "type", "source"]


def merge_events(weekly: pd.DataFrame | None, daily: pd.DataFrame | None) -> tuple[pd.DataFrame | None, int]:
    """週收集事件表 ∪ 每日事件窗口。同鍵以週收集為準；欄位對齊週收集（每日表多的 fetched_at 丟掉、缺的欄補空）。
    回傳 (合併表, 由每日表補入的事件數)。兩邊都沒有回 (None, 0)。"""
    if daily is None or daily.empty:
        return weekly, 0
    d = daily.copy()
    d["date"] = pd.to_datetime(d["date"])
    if weekly is None or weekly.empty:
        return d.drop(columns=[c for c in ("fetched_at",) if c in d.columns]), len(d)
    w = weekly.copy()
    w["date"] = pd.to_datetime(w["date"])
    for c in w.columns:
        if c not in d.columns:
            d[c] = pd.NA
    d = d[list(w.columns)]
    wk = set(map(tuple, w[EVENT_KEY].astype(str).values))
    new = d[[tuple(r) not in wk for r in d[EVENT_KEY].astype(str).values]]
    if new.empty:
        return weekly, 0
    out = pd.concat([w, new.astype(w.dtypes.to_dict(), errors="ignore")], ignore_index=True)
    return out.sort_values(["ticker", "date", "type", "source"]).reset_index(drop=True), len(new)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weekly-dir", default=str(SH))
    ap.add_argument("--daily-dir", default=str(SH))
    ap.add_argument("--out-dir", default=str(SH / "merged"))
    a = ap.parse_args(argv)
    wdir, ddir, odir = Path(a.weekly_dir), Path(a.daily_dir), Path(a.out_dir)
    odir.mkdir(parents=True, exist_ok=True)

    merged, reports = {}, {}
    for name, (wf, df_, vals) in TABLES.items():
        w = _read(wdir / wf)
        if w is None or w.empty:
            print(f"::error::找不到週收集檔 {wdir / wf}", file=sys.stderr)
            return 1
        merged[name], reports[name] = merge_table(w, _read(ddir / df_), vals)
        for k, r in reports[name]["overlap"].items():
            if r["only_weekly"] or r["only_daily"] or any(r["value_diff"].values()):
                print(f"  {name} {k}：週收集與每日表不一致（以週收集為準）{r}")

    lasts = last_dates(merged)
    cday = complete_day(lasts)
    if cday is None:
        print(f"::error::有資料項完全沒有列，無法決定完整日：{lasts}", file=sys.stderr)
        return 1
    pending = {}
    for name, df in merged.items():
        late = df[df["date"] > cday]
        if len(late):
            pending[name] = {f"{mk} {d.date()}": int(n) for (mk, d), n in late.groupby(["market", "date"]).size().items()}
        merged[name] = df[df["date"] <= cday]
        merged[name].to_parquet(odir / f"{name}.parquet", index=False, compression="zstd")

    gaps = find_gaps(merged, cday)
    ev, ev_from_daily = merge_events(_read(wdir / "corp_actions.parquet"), _read(ddir / "openapi_events.parquet"))
    ev_through = None
    if ev is not None and len(ev):
        ev.to_parquet(odir / "corp_actions.parquet", index=False, compression="zstd")
    wraw = _read(wdir / TABLES["raw_prices"][0])
    if wraw is not None and len(wraw):
        ev_through = pd.to_datetime(wraw["date"]).max()           # 週收集日線最後一天＝週收集事件表涵蓋到的日子
    try:                                                          # 每日事件窗口最近一次成功抓取涵蓋到哪天（B6）
        dmeta = json.loads((ddir / "openapi_events_meta.json").read_text(encoding="utf-8"))
        dthrough = pd.Timestamp(dmeta["through"])
        ev_through = dthrough if ev_through is None else max(ev_through, dthrough)
    except (OSError, ValueError, KeyError, TypeError):
        dmeta = None
    cal = sorted(merged["raw_prices"]["date"].unique())
    gap_days = [str(pd.Timestamp(d).date()) for d in cal if ev_through is not None and pd.Timestamp(d) > ev_through]

    # 輸入雜湊：併好的四個檔內容一樣（完整日沒前進、舊日子沒被更正、週收集沒更新）→ workflow 不重做還原與 zip
    h = hashlib.sha256()
    for n in ("raw_prices", "inst", "margin", "corp_actions"):
        f = odir / f"{n}.parquet"
        if f.exists():
            h.update(n.encode())
            h.update(pd.util.hash_pandas_object(pd.read_parquet(f), index=False).values.tobytes())
    manifest = {"complete_day": str(cday.date()), "input_hash": h.hexdigest(), "last_dates": lasts, "pending_after_complete_day": pending,
                "events_through": str(ev_through.date()) if ev_through is not None else None,
                "events_gap_days": gap_days, "gaps": gaps,
                "events_from_daily": ev_from_daily, "events_daily_fetched_at": (dmeta or {}).get("fetched_at"),
                "appended_from_daily": {n: r["appended"] for n, r in reports.items()},
                "overlap_check": {n: r["overlap"] for n, r in reports.items()}}
    (odir / "merge_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[merge] 完整日 {cday.date()}；各項最後日 {lasts}")
    print(f"[merge] 由每日表補入：{ {n: list(r['appended']) for n, r in reports.items()} }")
    if pending:
        print(f"[merge] 完整日之後、這一版不收：{pending}")
    if gaps:
        print(f"::warning::完整日前 {GAP_WINDOW_DAYS} 天內有中間缺日（zip 會缺這些天，閘門會擋）：{gaps}", file=sys.stderr)
    if ev_from_daily:
        print(f"[merge] 由每日事件窗口補入週收集尚未有的事件：{ev_from_daily} 件")
    if gap_days:
        print(f"::warning::事件表只到 {ev_through.date()}，之後 {len(gap_days)} 個交易日 {gap_days} 的除權息／減資因子尚未進來（B6）——"
              "這幾天若有事件，該檔還原價在事件日會有假跳空", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
