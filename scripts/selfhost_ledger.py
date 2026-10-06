"""自建上游：每檔股票的「事件簿」——把價格為什麼變、什麼時候缺、什麼時候被停，全部攤在同一條時間軸上。

## 為什麼
價格序列本身看不出「這個跳動是真的行情、事件、停牌復牌，還是我們的資料壞了」。
事件簿把所有已知的解釋集中到一張表；**每個價格跳動都要能歸到一個解釋，歸不到的就標 `flag`——那就是難以察覺的 gap 的偵測器**
（月檢查 `selfhost_monthly_review.py` 只需要處理 flag，不必重看全部）。

## 輸出
- `data/selfhost/ledger.parquet`：ticker, date, kind, level, title, detail
  - `level`：`info`（已解釋）／`warn`（值得看）／`flag`（歸不到解釋，**要人查**）
- `data/derived/selfhost_ledger_summary.json`：各 kind／level 的件數、flag 清單前 300 筆（給月檢查與頁面）

## kind
| kind | 內容 | level |
| :-- | :-- | :-- |
| `listed` | 實價首筆／最後一筆日期（最後一筆早於全市場最後日 ⇒ 疑似下市／停牌中） | info／warn |
| `event` | 公司行為（除權息、現增、減資、面額變更）：前收→參考價、因子、來源、有無 conflict、上游接縫狀態；日期晚於最後實價日的標「未來（未套用）」 | info／warn（conflict、現增分類不明） |
| `halt` | 上市停止買賣中快照（開始日、原因） | warn |
| `gap` | 連續 ≥3 個交易日沒有實價：能歸因（無成交旁表／停止買賣快照）or 未歸因 | info／warn |
| `jump` | 未還原收盤相鄰日 |漲跌| 超過漲跌幅限制（2015-06-01 前 7.5%、之後 10.5%）：歸因於事件／新上市前 5 日／ETF（無限制）；都不是 ⇒ **flag** | info／flag |
| `adj_jump` | 還原收盤相鄰日跳動超過 10.5%（還原後應連續；超過 ⇒ 因子可能錯、事件缺漏） | info／flag |
| `margin_note` | 融資券註記（O 停止融資／X 停止融券…）改變——講的是**次一營業日**，所以標的日期是「宣告日」，生效日是下一個交易日 | info |

用法：
    python scripts/selfhost_ledger.py                  # 建表＋摘要
    python scripts/selfhost_ledger.py --ticker 2614    # 印出一檔的完整時間軸
    python scripts/selfhost_ledger.py --flags          # 只列 flag
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SH = ROOT / "data" / "selfhost"
OUT = SH / "ledger.parquet"
SUMMARY = ROOT / "data" / "derived" / "selfhost_ledger_summary.json"
COLS = ["ticker", "date", "kind", "level", "title", "detail"]
LIMIT_OLD, LIMIT_NEW = 0.075, 0.105           # 2015-06-01 起漲跌幅 7%→10%（留 0.5% 容差給 tick）
LIMIT_CUT = pd.Timestamp("2015-06-01")
MIN_GAP = 3
NEW_LISTING_DAYS = 5
TYPE_ZH = {"ex_div": "除息", "ex_rights": "除權", "ex_both": "除權息", "cap_reduction": "減資",
           "par_change": "面額變更", "split": "分割"}


def _row(t, d, kind, level, title, detail=""):
    return {"ticker": t, "date": pd.Timestamp(d), "kind": kind, "level": level, "title": title, "detail": detail}


def build(raw: pd.DataFrame, ca: pd.DataFrame, adj: pd.DataFrame | None, seam: pd.DataFrame | None,
          notrade: pd.DataFrame | None, stophalt: pd.DataFrame | None, margin_note: pd.DataFrame | None,
          adjlog: pd.DataFrame | None = None) -> pd.DataFrame:
    rows: list[dict] = []
    raw = raw.sort_values(["ticker", "date"]).reset_index(drop=True)
    cal = np.sort(raw["date"].unique())
    ci = {d: i for i, d in enumerate(cal)}
    last_all = pd.Timestamp(cal[-1])
    raw["i"] = raw["date"].map(ci)
    first = raw.groupby("ticker")["date"].min()
    last = raw.groupby("ticker")["date"].max()
    ca = ca.copy()
    ca["date"] = pd.to_datetime(ca["date"])
    ev_by = {t: g.sort_values("date") for t, g in ca.groupby("ticker")}
    seam_by = {}
    if seam is not None and len(seam):
        seam = seam.copy()
        seam["ex_eff"] = pd.to_datetime(seam["ex_eff"])
        seam_by = {(str(r.ticker), r.ex_eff, r.type): r.status for r in seam.itertuples()}
    conflict = set()
    if adjlog is not None and len(adjlog) and "conflict" in adjlog:
        a = adjlog[adjlog["conflict"].astype(str).str.lower() == "true"]
        conflict = {(str(r.ticker), pd.Timestamp(r.date)) for r in a.itertuples()}

    # ── listed ──
    for t in first.index:
        rows.append(_row(t, first[t], "listed", "info", "實價首筆"))
        if last[t] < last_all:
            rows.append(_row(t, last[t], "listed", "warn", f"實價最後一筆（早於全市場最後日 {last_all.date()}：疑似下市／停牌中／無成交）"))

    # ── event ──
    for t, g in ev_by.items():
        for r in g.itertuples():
            future = r.date > last_all
            seam_s = seam_by.get((t, r.date, r.type), "")
            warn = ((t, r.date) in conflict) or ("cash_increase" in str(r.detail) and False)
            title = (f"{TYPE_ZH.get(r.type, r.type)}：前收 {r.prev_close:g} → 參考價 {r.ref_price:g}（因子 {r.factor:.4f}）[{r.source}]"
                     + ("｜⚠未來事件（尚未發生，不套用）" if future else "")
                     + ("｜⚠來源間因子衝突" if (t, r.date) in conflict else "")
                     + (f"｜上游還原：{seam_s}" if seam_s else ""))
            rows.append(_row(t, r.date, "event", "warn" if (future or warn) else "info", title, str(r.detail)[:300]))

    # ── halt（停止買賣快照）──
    halted = set()
    if stophalt is not None and len(stophalt):
        s = stophalt.copy()
        s["date"] = pd.to_datetime(s["date"])
        for t, g in s.groupby("ticker"):
            halted.add(t)
            g = g.sort_values("date")
            since = g["halt_since"].iloc[-1]
            rows.append(_row(t, pd.Timestamp(since) if since else g["date"].iloc[0], "halt", "warn",
                             f"停止買賣中（自 {since or '?'}；最近快照 {g['date'].iloc[-1].date()}）", str(g["reason"].iloc[-1])[:200]))

    # ── gap（連續無實價）──
    nt = set()
    if notrade is not None and len(notrade):
        n = notrade.copy()
        n["date"] = pd.to_datetime(n["date"])
        nt = set(zip(n["ticker"].astype(str), n["date"]))
    for t, g in raw.groupby("ticker", sort=False):
        idx = g["i"].to_numpy()
        d = np.diff(idx)
        for k in np.flatnonzero(d > MIN_GAP):                 # 缺 d-1 > MIN_GAP-1 ⇒ 缺 ≥ MIN_GAP 天
            a, b = int(idx[k]) + 1, int(idx[k + 1]) - 1
            days = [pd.Timestamp(cal[j]) for j in range(a, b + 1)]
            n_nt = sum((t, x) in nt for x in days)
            halted_here = t in halted
            why = "無成交旁表涵蓋 %d/%d 天" % (n_nt, len(days))
            lvl = "info" if n_nt >= len(days) * 0.8 else "warn"
            g_ev = ev_by.get(t)
            swap = g_ev[g_ev["type"].isin(["cap_reduction", "par_change", "split"])
                        & (g_ev["date"] >= days[0]) & (g_ev["date"] <= days[-1] + pd.Timedelta(days=7))] if g_ev is not None else None
            if swap is not None and len(swap):
                lvl, why = "info", why + f"；減資／面額變更換發股票停牌（恢復買賣日 {swap['date'].iloc[0].date()}）"
            elif lvl == "warn" and not halted_here:
                why += "；其餘未歸因（可能停牌／漏抓）"
            rows.append(_row(t, days[0], "gap", lvl, f"連續 {len(days)} 個交易日無實價（{days[0].date()}～{days[-1].date()}）：{why}"))

    # ── jump（未還原）──
    pr = raw.groupby("ticker")["close"].shift()
    pd_ = raw.groupby("ticker")["date"].shift()
    ret = raw["close"] / pr - 1
    lim = np.where(raw["date"] < LIMIT_CUT, LIMIT_OLD, LIMIT_NEW)
    cand = raw[(ret.abs() > lim) & ~raw["ticker"].str.startswith("0")].copy()
    cand["ret"] = ret[cand.index]
    cand["prev_date"] = pd_[cand.index]
    first_map = first.to_dict()
    for r in cand.itertuples():
        t = r.ticker
        g = ev_by.get(t)
        evd = g[(g["date"] > r.prev_date) & (g["date"] <= r.date)] if g is not None else None
        pos = r.i - ci[first_map[t]]
        if evd is not None and len(evd):
            rows.append(_row(t, r.date, "jump", "info", f"未還原收盤 {r.ret:+.1%}：事件 {','.join(TYPE_ZH.get(x, x) for x in evd['type'])}"))
        elif pos < NEW_LISTING_DAYS:
            rows.append(_row(t, r.date, "jump", "info", f"未還原收盤 {r.ret:+.1%}：新上市前 {NEW_LISTING_DAYS} 日（無漲跌幅限制）"))
        else:
            rows.append(_row(t, r.date, "jump", "flag", f"未還原收盤 {r.ret:+.1%} 超過漲跌幅限制且無任何事件可解釋（前一筆 {r.prev_date.date()}）",
                             f"close {r.close:g}"))

    # ── adj_jump（還原後仍跳）──
    if adj is not None and len(adj):
        a = adj.sort_values(["ticker", "date"])
        ar = a["close"] / a.groupby("ticker")["close"].shift() - 1
        pdt = a.groupby("ticker")["date"].shift()
        c2 = a[(ar.abs() > LIMIT_NEW) & ~a["ticker"].str.startswith("0") & (a["date"] >= LIMIT_CUT)].copy()
        c2["ret"] = ar[c2.index]
        c2["prev_date"] = pdt[c2.index]
        for r in c2.itertuples():
            t = r.ticker
            g = ev_by.get(t)
            evd = g[(g["date"] > r.prev_date) & (g["date"] <= r.date)] if g is not None else None
            pos = ci.get(r.date, 0) - ci.get(first_map.get(t), 0)
            if pos < NEW_LISTING_DAYS:
                continue
            if evd is not None and len(evd):
                rows.append(_row(t, r.date, "adj_jump", "flag",
                                 f"還原後收盤仍 {r.ret:+.1%}（事件日：{','.join(TYPE_ZH.get(x, x) for x in evd['type'])}）——因子可能不對或事件重複／缺漏"))
            else:
                rows.append(_row(t, r.date, "adj_jump", "flag", f"還原後收盤 {r.ret:+.1%} 且無事件（與未還原 jump 同源）"))

    # ── margin_note ──
    if margin_note is not None and len(margin_note):
        m = margin_note.sort_values(["ticker", "date"])
        prev = m.groupby("ticker")["note"].shift().fillna("")
        chg = m[m["note"].fillna("") != prev]
        chg = chg.assign(prev=prev[chg.index])
        for r in chg.itertuples():
            rows.append(_row(r.ticker, r.date, "margin_note", "info",
                             f"融資券註記 {r.prev!r} → {(r.note or '')!r}（講的是次一營業日）"))
    out = pd.DataFrame(rows, columns=COLS)
    return out.sort_values(["ticker", "date", "kind"]).reset_index(drop=True)


def render(ledger: pd.DataFrame, ticker: str) -> str:
    g = ledger[ledger["ticker"] == ticker]
    if g.empty:
        return f"{ticker}：事件簿沒有紀錄"
    mark = {"info": "  ", "warn": "⚠ ", "flag": "⛔"}
    lines = [f"# {ticker} 事件簿（{len(g)} 筆）"]
    for r in g.itertuples():
        lines.append(f"{r.date.date()}  {mark[r.level]} [{r.kind}] {r.title}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker")
    ap.add_argument("--flags", action="store_true")
    a = ap.parse_args(argv)
    if a.ticker or a.flags:
        led = pd.read_parquet(OUT)
        if a.ticker:
            print(render(led, a.ticker))
        else:
            f = led[led["level"] == "flag"]
            print(f.groupby("kind").size().to_string())
            print(f.head(60)[["ticker", "date", "kind", "title"]].to_string(index=False))
        return 0

    def rd(name, **kw):
        p = SH / name
        return pd.read_parquet(p, **kw) if p.suffix == ".parquet" and p.exists() else (pd.read_csv(p, dtype={"ticker": str}) if p.exists() else None)

    raw = pd.read_parquet(SH / "raw_prices.parquet", columns=["ticker", "date", "close"])
    raw["date"] = pd.to_datetime(raw["date"])
    raw["ticker"] = raw["ticker"].astype(str)
    ca = pd.read_parquet(SH / "corp_actions.parquet")
    ca["ticker"] = ca["ticker"].astype(str)
    adj = rd("adj_prices.parquet", columns=["ticker", "date", "close"])
    if adj is not None:
        adj["date"] = pd.to_datetime(adj["date"])
        adj["ticker"] = adj["ticker"].astype(str)
    mn = rd("margin.parquet", columns=["ticker", "date", "note"])
    if mn is not None:
        mn["ticker"] = mn["ticker"].astype(str)
        mn["date"] = pd.to_datetime(mn["date"])
    nt, sp = rd("notrade.parquet"), rd("stophalt.parquet")
    for d in (nt, sp):
        if d is not None:
            d["ticker"] = d["ticker"].astype(str)
    led = build(raw, ca, adj, rd("seam_events.csv"), nt, sp, mn, rd("adjust_log.csv"))
    led.to_parquet(OUT, index=False, compression="zstd")
    flags = led[led["level"] == "flag"]
    summ = {"schema": 1, "rows": int(len(led)), "tickers": int(led["ticker"].nunique()),
            "by_kind_level": {f"{k}/{l}": int(n) for (k, l), n in led.groupby(["kind", "level"]).size().items()},
            "flags": flags.head(300).assign(date=lambda d: d["date"].dt.strftime("%Y-%m-%d")).to_dict("records")}
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY.write_text(json.dumps(summ, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"事件簿 {len(led)} 筆／{led['ticker'].nunique()} 檔 → {OUT}")
    print(json.dumps(summ["by_kind_level"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
