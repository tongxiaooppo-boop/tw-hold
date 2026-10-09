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

## 休市日（B2 配套）
manifest 附 `closed_days`（證交所 holidaySchedule 的休市日，只留平日、排序的 ISO 日期）。tw-swing 的 `pack_source` 用它算
「落後幾個交易日」；沒附時 swing 只當週末休市，連假後會多算 1 天落後（偏向退回上游／最後一槍誤判紅燈）。
抓不到時 `closed_days` 是空陣列、`closed_days_source` 標 `unavailable`，不影響其他欄位（fail-open）。

## 事件因子（B6）
`corp_actions`＝週收集的事件表 ∪ 每日收集的官方事件結果表窗口（`openapi_events.parquet`，每班抓 [今天−5, 今天]）。
同鍵（代號、日期、類型、來源）值相同＝不動；**值不同＝官方事後更正，新者勝**（M1）：每日列的 `fetched_at`（該值第一次被看到的時間）
晚於週收集事件表的資產更新時間（`--weekly-corp-updated`；沒給就用週收集日線最後一天 21:00 UTC 當代理）→ 每日列勝，否則週收集勝；
同檔同日同類別但 type／source 不同（例：官方把「息」更正成「權息」）且兩邊都是官方來源（M2）→ 因子差 ≤0.5% 視為同一件（留週收集），
否則同樣新者勝、輸的那筆丟掉，免得 `resolve_events` 只依字母序挑一筆。衝突筆數與範例進 manifest（`events_daily_conflicts`），不靜默。
另掃「同檔同類別、14 天內、因子完全相同但日期不同」的官方事件對（M3，官方更正事件日時新舊兩筆都會留下、會套兩次），
只警告並記進 manifest（`events_possible_date_shift`），不自動刪。
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from selfhost_adjust import CLASS as EVENT_CLASS, CONFLICT_TOL, PRIORITY  # noqa: E402

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
CMP_COLS = ["prev_close", "ref_price", "factor"]
OFFICIAL_SOURCES = {src for src, pr in PRIORITY.items() if pr == 0}
DATE_SHIFT_DAYS = 14


def closed_days_for_manifest(fetch=None) -> tuple[list[str], str]:
    """證交所休市日 → (排序的 ISO 日期（只留平日）, 來源標記 'twse_holidaySchedule'|'unavailable')。
    `fetch` 預設用 last_trading_day_guard.fetch_closed（抓不到回 None＝fail-open）；測試可注入。"""
    try:
        if fetch is None:
            from last_trading_day_guard import fetch_closed as fetch  # noqa: PLC0415
        closed = fetch()
    except Exception as e:      # noqa: BLE001  休市表只是配套，任何失敗都不可擋資料包
        print(f"::warning::休市日表取得失敗，manifest 不附 closed_days：{str(e)[:100]}", file=sys.stderr)
        return [], "unavailable"
    if not closed:
        return [], "unavailable"
    days = sorted(str(d) for d in closed if getattr(d, "weekday", lambda: 5)() < 5)
    return days, "twse_holidaySchedule"


def _num_equal(a, b, rel: float = 1e-9) -> bool:
    if pd.isna(a) and pd.isna(b):
        return True
    if pd.isna(a) or pd.isna(b):
        return False
    return abs(float(a) - float(b)) <= rel * max(1.0, abs(float(a)), abs(float(b)))


def _same_event_values(a, b) -> bool:
    return all(_num_equal(a[c], b[c]) for c in CMP_COLS)


def merge_events(weekly: pd.DataFrame | None, daily: pd.DataFrame | None,
                 weekly_asof: pd.Timestamp | None = None) -> tuple[pd.DataFrame | None, dict]:
    """週收集事件表 ∪ 每日事件窗口（B6）。回傳 (合併表, stats)。
    stats：from_daily（由每日表補入的新事件數）、conflicts／daily_won／weekly_won、examples（最多 10 筆）。
    欄位對齊週收集（每日表多的 fetched_at 丟掉、缺的欄補空）。`weekly_asof` 是週收集事件表的時間（UTC、無時區）；
    沒給時每日列永遠不贏（＝週收集優先，舊行為）。"""
    stats = {"from_daily": 0, "conflicts": 0, "daily_won": 0, "weekly_won": 0, "examples": []}
    if daily is None or daily.empty:
        return weekly, stats
    d = daily.copy()
    d["date"] = pd.to_datetime(d["date"])
    d["fetched_at"] = pd.to_datetime(d["fetched_at"]) if "fetched_at" in d.columns else pd.NaT
    if weekly is None or weekly.empty:
        stats["from_daily"] = len(d)
        return d.drop(columns=["fetched_at"]), stats
    if any(c not in weekly.columns for c in ("ticker", "date", "type", "source", "factor")):
        print("::warning::週收集事件表缺必要欄位，每日事件窗口未併入", file=sys.stderr)
        return weekly, stats
    w = weekly.copy()
    w["date"] = pd.to_datetime(w["date"])
    cols = list(w.columns)
    for c in cols:
        if c not in d.columns:
            d[c] = pd.NA
    w["_cls"] = w["type"].map(EVENT_CLASS)
    d["_cls"] = d["type"].map(EVENT_CLASS)
    idx: dict[tuple, list] = {}
    for i, r in w.iterrows():
        idx.setdefault((r["ticker"], r["date"], r["_cls"] if pd.notna(r["_cls"]) else None), []).append(i)
    drop_w: set = set()
    add_d: list = []

    def daily_newer(row) -> bool:
        return bool(weekly_asof is not None and pd.notna(row["fetched_at"]) and row["fetched_at"] > weekly_asof)

    def note(kind: str, dr, wr, winner: str) -> None:
        stats["conflicts"] += 1
        stats["daily_won" if winner == "daily" else "weekly_won"] += 1
        if len(stats["examples"]) < 10:
            stats["examples"].append({"ticker": dr["ticker"], "date": str(dr["date"].date()), "kind": kind,
                                      "weekly": f"{wr['type']}/{wr['source']} f={float(wr['factor']):.6f}",
                                      "daily": f"{dr['type']}/{dr['source']} f={float(dr['factor']):.6f}", "winner": winner})

    for _, r in d.iterrows():
        cls = r["_cls"] if pd.notna(r["_cls"]) else None
        cand = idx.get((r["ticker"], r["date"], cls), [])
        exact = [i for i in cand if w.at[i, "type"] == r["type"] and w.at[i, "source"] == r["source"]]
        if exact:                                                     # 同鍵：值相同不動；值不同＝官方事後更正，新者勝（M1）
            wr = w.loc[exact[0]]
            if _same_event_values(wr, r):
                continue
            if daily_newer(r):
                note("same_key", r, wr, "daily")
                drop_w.update(exact)
                add_d.append(r)
            else:
                note("same_key", r, wr, "weekly")
            continue
        official_w = [i for i in cand if w.at[i, "source"] in OFFICIAL_SOURCES]
        if cand and r["source"] in OFFICIAL_SOURCES and official_w:   # 同檔同日同類別、type／source 不同（M2）
            wr = w.loc[official_w[0]]
            wf, df_ = float(wr["factor"]), float(r["factor"])
            if wf > 0 and abs(df_ / wf - 1) <= CONFLICT_TOL:
                continue                                              # 因子相近＝同一件事，留週收集
            if daily_newer(r):
                note("same_class", r, wr, "daily")
                drop_w.update(official_w)
                add_d.append(r)
            else:
                note("same_class", r, wr, "weekly")
            continue
        stats["from_daily"] += 1                                      # 週收集完全沒有（或只有 FinMind 列，官方優先由 resolve_events 處理）
        add_d.append(r)
    out = w.drop(index=list(drop_w)).drop(columns=["_cls"])
    if add_d:
        add = pd.DataFrame(add_d)[cols]
        out = pd.concat([out, add.astype(out.dtypes.to_dict(), errors="ignore")], ignore_index=True)
    return out.sort_values(["ticker", "date", "type", "source"]).reset_index(drop=True), stats


def date_shift_suspects(ev: pd.DataFrame | None, limit: int = 20) -> list[dict]:
    """M3：同檔、同類別、官方來源、14 天內、因子完全相同但日期不同的事件對。官方更正事件日時，每日表只增不刪，
    新舊兩筆都會留下並被套兩次。只回報，不刪。"""
    if ev is None or ev.empty or any(c not in ev.columns for c in ("ticker", "date", "type", "source", "factor")):
        return []
    e = ev[ev["source"].isin(OFFICIAL_SOURCES)].copy()
    e["_cls"] = e["type"].map(EVENT_CLASS)
    e = e[e["_cls"].notna()].sort_values(["ticker", "_cls", "date"])
    out = []
    for (t, c), g in e.groupby(["ticker", "_cls"], sort=False):
        rows = g.to_dict("records")
        for a, b in zip(rows, rows[1:]):
            gap = (pd.Timestamp(b["date"]) - pd.Timestamp(a["date"])).days
            if 0 < gap <= DATE_SHIFT_DAYS and _num_equal(a["factor"], b["factor"]):
                out.append({"ticker": t, "class": c, "dates": [str(pd.Timestamp(a["date"]).date()), str(pd.Timestamp(b["date"]).date())],
                            "factor": float(a["factor"])})
                if len(out) >= limit:
                    return out
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weekly-dir", default=str(SH))
    ap.add_argument("--daily-dir", default=str(SH))
    ap.add_argument("--out-dir", default=str(SH / "merged"))
    ap.add_argument("--weekly-corp-updated", default="", help="週收集事件表（corp_actions.parquet）的資產更新時間 ISO（UTC）；"
                    "用來判斷每日事件列與週收集誰較新。沒給就用週收集日線最後一天 21:00 UTC 當代理")
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
    wraw = _read(wdir / TABLES["raw_prices"][0])
    ev_through = None
    if wraw is not None and len(wraw):
        ev_through = pd.to_datetime(wraw["date"]).max()           # 週收集日線最後一天＝週收集事件表涵蓋到的日子
    weekly_asof, asof_src = None, None
    if a.weekly_corp_updated:
        try:
            weekly_asof = pd.Timestamp(a.weekly_corp_updated)
            weekly_asof = weekly_asof.tz_convert("UTC").tz_localize(None) if weekly_asof.tzinfo else weekly_asof
            asof_src = "asset"
        except (ValueError, TypeError):
            weekly_asof = None
    if weekly_asof is None and ev_through is not None:
        weekly_asof, asof_src = ev_through.normalize() + pd.Timedelta(hours=21), "proxy"   # 週收集約在最後交易日 21:00 UTC（台北隔日 05:00）
    ev, ev_stats = merge_events(_read(wdir / "corp_actions.parquet"), _read(ddir / "openapi_events.parquet"), weekly_asof)
    ev_from_daily = ev_stats["from_daily"]
    if ev is not None and len(ev):
        ev.to_parquet(odir / "corp_actions.parquet", index=False, compression="zstd")
    shifts = date_shift_suspects(ev)
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
    closed_days, closed_src = closed_days_for_manifest()
    manifest = {"complete_day": str(cday.date()), "closed_days": closed_days, "closed_days_source": closed_src, "input_hash": h.hexdigest(), "last_dates": lasts, "pending_after_complete_day": pending,
                "events_through": str(ev_through.date()) if ev_through is not None else None,
                "events_gap_days": gap_days, "gaps": gaps,
                "events_from_daily": ev_from_daily,
                "events_daily_conflicts": {k: v for k, v in ev_stats.items() if k != "from_daily"},
                "events_possible_date_shift": shifts,
                "events_weekly_asof": {"value": str(weekly_asof) if weekly_asof is not None else None, "source": asof_src}, "events_daily_fetched_at": (dmeta or {}).get("fetched_at"),
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
    if ev_stats["conflicts"]:
        print(f"::warning::每日事件窗口與週收集有 {ev_stats['conflicts']} 筆同事件但值不同（每日較新勝 {ev_stats['daily_won']}、週收集勝 "
              f"{ev_stats['weekly_won']}）：{ev_stats['examples'][:3]}", file=sys.stderr)
    if shifts:
        print(f"::warning::疑似官方更正事件日、新舊兩筆都留下（同檔同類別 {DATE_SHIFT_DAYS} 天內因子完全相同）：{shifts[:3]}"
              f"（共 {len(shifts)}）——還原會套兩次，請人工檢視", file=sys.stderr)
    if gap_days:
        print(f"::warning::事件表只到 {ev_through.date()}，之後 {len(gap_days)} 個交易日 {gap_days} 的除權息／減資因子尚未進來（B6）——"
              "這幾天若有事件，該檔還原價在事件日會有假跳空", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
