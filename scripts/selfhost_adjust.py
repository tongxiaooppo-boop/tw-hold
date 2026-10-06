"""自建上游 P2：由官方實價 ＋ 公司行為事件表 重算還原日線（**不依賴 data_pack / Yahoo**）。

    adj(t) = raw(t) × Π { factor_e : 事件日 date_e > t }

事件日當天與之後的列不乘（事件日是新價格水位的第一天）。高低開收同乘；成交量保持原值
（跟官方一致；Yahoo 只對分割調量，口徑差異另行對帳）。

## 事件去重（同一件事多個來源 → 只套用一次）
每檔每日按「類別」分組：
- `div`   ：ex_div / ex_rights / ex_both（官方 twse_ex / tpex_ex）
- `par`   ：par_change / split / reverse_split（FinMind fm_split / fm_par）
- `red`   ：cap_reduction（FinMind fm_reduction）
同組內多筆取優先序第一筆（官方 > fm_split > fm_par），**因子差 >0.5% 記 conflict**，供人工檢視。
不同類別同一天各自套用並記 `multi_class`；**唯一例外**：減資＋除權息同日只套減資（見下方）。

## 已知口徑分歧（Opus 審查 2026-10-05，對帳時要預期）
- **現金增資**：官方因子＝理論除權價 / 前收（認購價高於市價時 factor > 1，TPEx 約 483 件、TWSE 約 11 件）。自建**依官方理論除權價還原**；
  上游（Yahoo）對這類事件的處理本身不穩（實測 1586、3234、5227、4714 呈現「ex 前約 9 天到前一天被乘、其餘未還原」的怪樣），兩者必然不同，不算自建誤差。
- **權息同日**：Yahoo 與官方因子可差數個百分點（例：6870 Yahoo 0.90 vs 官方 0.8266），自建以官方為準。
- **成交量**：不隨分割調整（官方原值）；Yahoo 只對分割調量。切換資料源時分割點的量能／成交值類指標會不連續。
- **同日除息＋減資**：官方減資參考價公式已含息值，所以**同日的除權息列會被丟掉、只套減資**（`resolve_events`，印出被丟的清單）；目前資料 0 組，這是防呆。

## 輸出
- `data/selfhost/adj_prices.parquet`：ticker, date, open, high, low, close, volume, raw_close
- `data/selfhost/adjust_log.csv`：每個被套用的事件（ticker, date, class, type, factor, source, 重複來源的因子、conflict 旗標）
  → 任何還原價的階梯都能從這張表追到事件與來源。

用法：
    python scripts/selfhost_adjust.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SH = ROOT / "data" / "selfhost"
RAW = SH / "raw_prices.parquet"
EV = SH / "corp_actions.parquet"
OUT = SH / "adj_prices.parquet"
LOG = SH / "adjust_log.csv"

CLASS = {"ex_div": "div", "ex_rights": "div", "ex_both": "div",
         "par_change": "par", "split": "par", "reverse_split": "par", "cap_reduction": "red"}
PRIORITY = {"twse_ex": 0, "tpex_ex": 0, "twse_red": 0, "tpex_red": 0, "twse_par": 0, "tpex_par": 0,   # 官方優先
            "fm_split": 1, "fm_par": 2, "fm_reduction": 1}
CONFLICT_TOL = 0.005


def resolve_events(ev: pd.DataFrame) -> pd.DataFrame:
    """多來源去重：回傳『每檔、每日、每類別一列』的待套用事件。"""
    ev = ev.copy()
    ev["cls"] = ev["type"].map(CLASS)
    ev = ev[ev["cls"].notna()]                 # 未知類型（ex_other:*）不套用，另列
    ev["prio"] = ev["source"].map(PRIORITY).fillna(9)
    ev = ev.sort_values(["ticker", "date", "cls", "prio"])
    rows = []
    for (t, d, c), g in ev.groupby(["ticker", "date", "cls"], sort=False):
        first = g.iloc[0]
        facs = g["factor"].tolist()
        rows.append({"ticker": t, "date": d, "cls": c, "type": first["type"], "factor": first["factor"],
                     "source": first["source"], "n_sources": len(g),
                     "all_factors": ";".join(f"{s}:{f:.6f}" for s, f in zip(g["source"], facs)),
                     "conflict": bool(max(facs) / min(facs) - 1 > CONFLICT_TOL) if len(facs) > 1 else False})
    res = pd.DataFrame(rows)
    if res.empty:
        return res
    # 減資與除權息同一天只算一次：官方公式「恢復買賣參考價＝(停止買賣前收盤價−息值−每股退還股款)/減資換股率」已含息值，
    # 兩邊都乘會把除息扣兩次（tw-stock-data READ_CONTRACT「減資：三件跟除權息不一樣的事」③；本庫目前 0 組，這是防呆）
    red_days = set(zip(res.loc[res["cls"] == "red", "ticker"], res.loc[res["cls"] == "red", "date"]))
    if red_days:
        drop = res["cls"].eq("div") & pd.Series(list(zip(res["ticker"], res["date"])), index=res.index).isin(red_days)
        if drop.any():
            print(f"  同日減資＋除權息：丟掉 {int(drop.sum())} 筆除權息（減資參考價已含息值）：{res.loc[drop, ['ticker', 'date']].astype(str).values.tolist()[:6]}")
            res = res[~drop].copy()
    cnt = res.groupby(["ticker", "date"])["cls"].transform("size")
    res["multi_class"] = cnt > 1
    return res


def drop_future(res: pd.DataFrame, last_day: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    """事件日晚於最後一個實價日的事件還沒發生（官方預告表／減資公告會提前列出），不可套用：
    套了之後「最新價」就不等於未還原價（最新價的 F 必須是 1，現價不動、被調整的是歷史）。
    實測 2026-10-06：6 件（2614、8021 除權息；2323、3085、4527、5301 減資），其中 2614 最後一列 close 被乘 0.8445。
    回傳 (可套用, 被丟掉的)。"""
    if res.empty:
        return res, res
    fut = res["date"] > last_day
    return res[~fut].copy(), res[fut].copy()


def adjust(raw: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """raw：ticker,date,open,high,low,close,volume；events：resolve_events 的輸出。"""
    raw = raw.sort_values(["ticker", "date"]).copy()
    raw["raw_close"] = raw["close"]
    ev_by = {t: g.sort_values("date") for t, g in events.groupby("ticker")} if len(events) else {}
    parts = []
    for t, g in raw.groupby("ticker", sort=False):
        e = ev_by.get(t)
        if e is None or e.empty:
            parts.append(g)
            continue
        dates = g["date"].to_numpy()
        mult = np.ones(len(g))
        for d, f in zip(e["date"].to_numpy(), e["factor"].to_numpy()):
            mult[dates < d] *= f            # 事件日之前的列乘因子
        g = g.copy()
        for c in ("open", "high", "low", "close"):
            g[c] = g[c].to_numpy() * mult
        parts.append(g)
    return pd.concat(parts, ignore_index=True)


def main(argv=None) -> int:
    argparse.ArgumentParser().parse_args(argv)
    raw = pd.read_parquet(RAW)
    raw["date"] = pd.to_datetime(raw["date"])
    ev = pd.read_parquet(EV)
    ev["date"] = pd.to_datetime(ev["date"])
    res = resolve_events(ev)
    unknown = ev[~ev["type"].isin(CLASS)]
    print(f"事件：原始 {len(ev)} 列 → 去重後 {len(res)} 件；"
          f"conflict {int(res['conflict'].sum()) if len(res) else 0}；未知類型 {len(unknown)}")
    res, future = drop_future(res, raw["date"].max())
    if len(future):
        print(f"  未來事件 {len(future)} 件不套用（事件日晚於最後實價日 {raw['date'].max().date()}）："
              f"{future[['ticker', 'date']].assign(date=future['date'].dt.strftime('%m-%d')).values.tolist()}")
    # 只套用落在實價涵蓋期之後的事件（涵蓋期之前的事件發生在第一筆實價之前，不影響）
    adj = adjust(raw[["ticker", "date", "open", "high", "low", "close", "volume"]], res)
    adj = adj.merge(raw[["ticker", "date", "close"]].rename(columns={"close": "raw_close"}), on=["ticker", "date"], how="left") \
        if "raw_close" not in adj.columns else adj
    adj.to_parquet(OUT, index=False, compression="zstd")
    res.to_csv(LOG, index=False, encoding="utf-8-sig")
    print(f"→ {OUT.name}（{len(adj)} 列）、{LOG.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
