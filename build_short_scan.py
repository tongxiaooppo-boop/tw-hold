"""短線條件掃描 → `data/derived/short_scan.json`（Streamlit「短線」頁第四個名單，app 只讀這裡）。

## 這是什麼

用多軌體檢「⚡ 短線」檢核表（`app/checklist.py::short_checks`）每天掃 universe，
**沒有任何 ❌ 未達的全部列出**。判定口徑跟檢核表頁是同一套（`summarize(...)["缺口"] == []`），
不另寫一份規則。

「掃描不選」：不排名、不打分、不截斷成固定檔數。「待確認」（資料不足）不算缺口但要帶出來；
「風險命中」（⚠️）不能因為全過就藏掉。

⚠️ **跟 tw-swing 三個推薦是不同來源、不同判準**——tw-swing 有回測、做過 G1–G5；
這份只是條件狀態掃描，**零回測、零驗證**，不給訊號、不給買賣點。

## 效能

整張表一次讀、記憶體內 groupby（不像 app 一檔一檔 filter 讀 parquet）。

用法：
    python build_short_scan.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "app"))

import checklist as cl  # noqa: E402

UPSTREAM = REPO / "data" / "upstream"
DERIVED = REPO / "data" / "derived"
OUT = DERIVED / "short_scan.json"
SCHEMA = 1

PX_DAYS, CHIPS_DAYS, MARGIN_DAYS = 160, 40, 120   # 檢核只用最近 ~60 日價量 / 5 日法人 / 11 日融資券


def _code(t) -> str:
    return str(t).strip().split(".")[0]


def _tail_days(df: pd.DataFrame, days: int) -> pd.DataFrame:
    df["date"] = pd.to_datetime(df["date"])
    return df[df["date"] >= df["date"].max() - pd.Timedelta(days=days)]


def _by_code(df: pd.DataFrame) -> dict:
    df = df.assign(_c=df["ticker"].map(_code))
    return {k: g.drop(columns="_c").reset_index(drop=True) for k, g in df.groupby("_c")}


def _read(name: str, columns: list[str]) -> pd.DataFrame | None:
    p = UPSTREAM / name
    if not p.exists():
        return None
    return pd.read_parquet(p, columns=columns)


def _active_flags() -> dict:
    """同 app `_active_flags`：schema 壞或 anchor 落後 > 4 天 → {}（當「沒有」）。"""
    p = DERIVED / "active_etf_flags.json"
    if not p.exists():
        return {}
    d = json.loads(p.read_text(encoding="utf-8"))
    m = d.get("_meta") or {}
    if not m.get("schema_ok"):
        return {}
    ad = m.get("anchor_date")
    try:
        if ad and (pd.Timestamp.now(tz="Asia/Taipei").tz_localize(None).normalize()
                   - pd.Timestamp(ad)).days > 4:
            return {}
    except Exception:  # noqa: BLE001
        pass
    return d


def _track_entry(stocks: list[dict], asof: str, prev_file: dict | None) -> tuple[dict, list[dict]]:
    """進榜日期／連續天數／昨日掉出。給每檔寫入 `first_seen`、`streak_days`。

    基準 = 「上一個交易日的名單」，存在 `_prev`（`{ticker: {first_seen, streak_days, name}}`）：
      - 新的 asof 晚於檔案裡的 asof → 前進一天：基準 = 檔案裡目前的 stocks，並把它存成新的 `_prev`；
      - 同一天重跑 → 基準沿用檔案裡的 `_prev`（不被這次重跑的結果污染）；
      - asof 早於檔案 → 不倒退，回 (None, [])，呼叫端保留原檔。
    連續性：昨天在名單、今天也在 → streak+1；掉出再回來 → 重算為 1（同長波段 swing_history 語意）。
    回傳 (新的 `_prev` 基準, 昨日掉出名單)。
    """
    base: dict = {}
    prev_asof = (prev_file or {}).get("_meta", {}).get("asof")
    if prev_file:
        if prev_asof is not None and asof < prev_asof:
            return None, []
        if prev_asof == asof:
            base = prev_file.get("_prev") or {}
        else:
            base = {x["ticker"]: {"first_seen": x.get("first_seen") or prev_asof,
                                  "streak_days": x.get("streak_days") or 1,
                                  "name": x.get("name")}
                    for x in prev_file.get("stocks", [])}
    for x in stocks:
        h = base.get(x["ticker"])
        if h:
            x["first_seen"], x["streak_days"] = h["first_seen"], int(h["streak_days"]) + 1
        else:
            x["first_seen"], x["streak_days"] = asof, 1
    today = {x["ticker"] for x in stocks}
    dropped = [{"ticker": t, "name": h.get("name")} for t, h in sorted(base.items())
               if t not in today]
    return base, dropped


def build() -> dict:
    from reference.corporate_actions import adjust_per_share

    uni = pd.read_parquet(UPSTREAM / "fundamentals" / "universe.parquet",
                          columns=["ticker", "stock_name", "industry", "in_universe"])
    uni = uni[uni["in_universe"].fillna(False)]
    uni["code"] = uni["ticker"].map(_code)

    px = _read("prices_adj.parquet", ["date", "ticker", "open", "high", "low", "close", "volume"])
    if px is None:
        raise SystemExit("bundle 沒有 prices_adj.parquet——無法掃描")
    px = adjust_per_share(_tail_days(px, PX_DAYS),
                          ["open", "high", "low", "close"])
    chips = _read("chips.parquet", ["date", "ticker", "foreign_net", "trust_net", "dealer_net"])
    margin = _read("margin.parquet", ["date", "ticker", "margin_balance", "short_balance"])

    px_g = _by_code(px)
    chips_g = _by_code(_tail_days(chips, CHIPS_DAYS)) if chips is not None else {}
    margin_g = _by_code(_tail_days(margin, MARGIN_DAYS)) if margin is not None else {}

    flags = _active_flags()
    asof = str(px["date"].max().date())

    passed, scanned = [], 0
    for r in uni.itertuples(index=False):
        p = px_g.get(r.code)
        if p is None or p.empty:
            continue
        # 停牌／下市：最後一根不是最新交易日 → 不掃（檢核表會拿舊價判斷）
        if str(pd.to_datetime(p["date"]).max().date()) != asof:
            continue
        scanned += 1
        c = chips_g.get(r.code)
        if c is not None and not c.empty:
            c = c.rename(columns={"foreign_net": "foreign", "trust_net": "trust",
                                  "dealer_net": "dealer"})
            for k in ("foreign", "trust", "dealer"):
                c[k] = pd.to_numeric(c[k], errors="coerce") / 1000.0
        m = margin_g.get(r.code)
        d = {"px": p.sort_values("date"), "chips": c, "margin": m}
        aef = ((flags.get("flags") or {}).get(r.code) or {}) if flags else None
        rows = cl.short_checks(d, active_etf=aef)
        s = cl.summarize(rows)
        if s["缺口"]:
            continue
        last = p.sort_values("date").iloc[-1]
        passed.append({
            "ticker": r.code, "name": r.stock_name, "industry": r.industry,
            "close": round(float(last["close"]), 2),
            "good": s["亮點"], "pending": s["待確認"], "risk": s["風險命中"],
            "checks": [{k: row[k] for k in ("組", "項目", "現值", "狀態")} for row in rows],
        })

    passed.sort(key=lambda x: x["ticker"])    # 代號序——刻意不排名
    prev_file = None
    if OUT.exists():
        try:
            prev_file = json.loads(OUT.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            prev_file = None
    base, dropped = _track_entry(passed, asof, prev_file)
    if base is None:                           # asof 倒退（本機舊 bundle 重跑）：保留原檔
        print(f"  ⚠ short_scan 略過更新（asof {asof} 早於已記錄的 {prev_file['_meta']['asof']}）")
        return prev_file
    return {
        "_meta": {
            "schema": SCHEMA, "asof": asof, "scanned": scanned, "passed": len(passed),
            "has_margin": margin is not None,
            "has_chips": chips is not None,
            "new_today": sum(1 for x in passed if x["streak_days"] == 1),
            # 進榜追蹤從哪天開始記（第一天全部會是 streak 1，不代表真的都是新進）
            "tracking_since": ((prev_file or {}).get("_meta") or {}).get("tracking_since") or asof,
        },
        "dropped": dropped,
        "_prev": base,
        "stocks": passed,
    }


def main() -> int:
    out = build()
    DERIVED.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    m = out["_meta"]
    print(f"short_scan: asof {m['asof']} · 掃 {m['scanned']} 檔 · 全過 {m['passed']} 檔 "
          f"· margin={m['has_margin']} → {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
