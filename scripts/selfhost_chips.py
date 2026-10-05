"""自建上游 P1：三大法人買賣超 ＋ 融資融券（個股、上市＋上櫃）依日期收集。

輸出（長表）。**與 tw-swing `data/store/inst.parquet`／`margin.parquet` 的差異**（實測 2026-10-05，數值對得上：
2330 在 2026-10-02 的 T86、MI_MARGN 與 store 完全一致）：store 用 `code`（category）＋`ticker`（帶 .TW/.TWO 後綴），
這裡用 `ticker`（純 4 碼代號）＋`market`（TW/TWO）；margin 的數值欄這裡是 float。切換下游前要做一層欄位轉接，不是直接替換：
- `data/selfhost/inst.parquet`   date, ticker, market, foreign_net, fi_prop_net, trust_net, dealer_net, total_net（股）
- `data/selfhost/margin.parquet` date, ticker, market, margin_balance, margin_buy, margin_sell, margin_redeem,
                                 short_balance, short_buy, short_sell, short_redeem, offset（張）

## 與上游做法的差異（見 `UPSTREAM_PRACTICES_AUDIT.md`）
- **上市、上櫃各自記進度、各自補洞**：上游用 2330 的最後日當唯一基準，上櫃缺日永遠不會補（C3/M4）。
  這裡「已有」＝ (資料集, 市場, 日期) 三元組；只補缺的。
- 用欄名／欄位數辨識表格，不寫死位置；回應日期必須等於請求日（pitfalls 檔頭）。
- 休市日（空表）不是錯誤、不重試；任一市場抓取失敗 → 該市場該日不寫，下次補。

## 口徑（實測，對照 tw-swing store）
- `foreign_net`＝外資及陸資**不含外資自營商**（上市 T86、上櫃兩邊同口徑）；`fi_prop_net`＝外資自營商（只有上市有）。
- `dealer_net`＝自營商買賣超（自行買賣＋避險）；`total_net`＝三大法人合計。

用法：
    python scripts/selfhost_chips.py --start 2026-05-04
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
SH = ROOT / "data" / "selfhost"
INST = SH / "inst.parquet"
MARGIN = SH / "margin.parquet"
UA = {"User-Agent": "Mozilla/5.0"}
SLEEP = 2.0
T86 = "https://www.twse.com.tw/rwd/zh/fund/T86?date={d}&selectType=ALLBUT0999&response=json"
TPEX_INST = "https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade?type=Daily&sect=AL&date={d}&response=json"
MI_MARGN = "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date={d}&selectType=STOCK&response=json"
TPEX_MARGIN = "https://www.tpex.org.tw/www/zh-tw/margin/balance?date={d}&response=json"
INST_COLS = ["date", "ticker", "market", "foreign_net", "fi_prop_net", "trust_net", "dealer_net", "total_net"]
MARGIN_COLS = ["date", "ticker", "market", "margin_balance", "margin_buy", "margin_sell", "margin_redeem",
               "short_balance", "short_buy", "short_sell", "short_redeem", "offset"]


def _get(url: str, retries: int = 3) -> dict | None:
    for i in range(retries):
        try:
            r = requests.get(url, headers=UA, timeout=40)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            print(f"  請求失敗（第 {i + 1} 次）：{str(e)[:80]}", file=sys.stderr)
            time.sleep(3 * (i + 1))
    return None


def _n(x) -> float | None:
    s = str(x).replace(",", "").strip()
    if s in ("", "--", "---", "nan"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _trading_calendar() -> set[date] | None:
    """官方實價（raw_prices）出現過的日期 ＝ 已知交易日。檔案不存在 → None（不判休市）。"""
    p = SH / "raw_prices.parquet"
    if not p.exists():
        return None
    return {pd.Timestamp(x).date() for x in pd.read_parquet(p, columns=["date"])["date"].unique()}


def _code_ok(c: str) -> bool:
    return c.isdigit() and len(c) == 4


def _pick(fields: list[str], *names: str) -> int | None:
    """依欄名取位置：先完整比對、再前綴比對（容忍歷年欄名差異；16 欄時代見 inst_twse 的註解）。"""
    for nm in names:
        if nm in fields:
            return fields.index(nm)
    for nm in names:
        for i, f in enumerate(fields):
            if f.startswith(nm):
                return i
    return None


# ───────────────────────── 三大法人 ─────────────────────────
def inst_twse(d: date) -> pd.DataFrame | None:
    ymd = d.strftime("%Y%m%d")
    j = _get(T86.format(d=ymd))
    if j is None:
        return None
    if j.get("stat") != "OK" or not j.get("data"):
        return pd.DataFrame(columns=INST_COLS)          # 是否「休市」由 run() 對照交易日曆判定
    if str(j.get("date")) != ymd:
        print(f"::warning::T86 {ymd} 回應日期 {j.get('date')} 不符，丟棄", file=sys.stderr)
        return None
    f = j["fields"]
    # 欄名歷年有三種：19 欄時代「外陸資買賣超股數(不含外資自營商)」；16 欄時代（≥2015～至少 2017-12）只有「外資買賣超股數」
    # （當時 TWSE 不拆外資自營商，fi_prop_net 留空）。完整比對優先，所以「外資買賣超股數」不會誤取到別的欄。
    ix = {"foreign_net": _pick(f, "外陸資買賣超股數(不含外資自營商)", "外資及陸資(不含外資自營商)買賣超股數",
                               "外陸資買賣超股數", "外資買賣超股數"),
          "fi_prop_net": _pick(f, "外資自營商買賣超股數"),
          "trust_net": _pick(f, "投信買賣超股數"),
          "dealer_net": _pick(f, "自營商買賣超股數"),       # 完整比對優先 → 取合計欄而非(自行買賣)子欄
          "total_net": _pick(f, "三大法人買賣超股數")}
    if ix["foreign_net"] is None or ix["trust_net"] is None or ix["total_net"] is None:
        print(f"::warning::T86 {ymd} 欄位對不上：{f}", file=sys.stderr)
        return None
    rows = []
    for r in j["data"]:
        c = str(r[0]).strip()
        if _code_ok(c):
            rows.append({"date": pd.Timestamp(d), "ticker": c, "market": "TW",
                         **{k: (_n(r[i]) if i is not None else None) for k, i in ix.items()}})
    return pd.DataFrame(rows, columns=INST_COLS)


def inst_tpex(d: date) -> pd.DataFrame | None:
    """TPEx 法人有兩種格式（實測 2026-10-05，Opus 複查發現）：
    - ≥ 2018-03：`tables[0]`，24 欄（買進／賣出／買賣超 ×7 組＋合計）。
    - ≤ 2018-01（至少回溯到 2017-06）：資料在 **`tables[1]`**，16 欄，`tables[0]` 是空殼；
      外資只有「外資及陸資」一組（**沒有拆外資自營商；是否含外資自營商未註明**，故 `foreign_net` 在此段歷史的口徑與 24 欄時代
      「不含外資自營商」可能不同），自營商只有淨買與自行／避險子欄。
    兩種格式都沒有資料（休市或根本沒有）→ 空表；有資料但欄數不是 24／16 → None（改版，視為失敗）。"""
    ymd = d.strftime("%Y%m%d")
    j = _get(TPEX_INST.format(d=d.strftime("%Y/%m/%d")))
    if j is None:
        return None
    if str(j.get("date")) != ymd:
        print(f"::warning::TPEx 法人 {ymd} 回應日期 {j.get('date')} 不符，丟棄", file=sys.stderr)
        return None
    t = next((x for x in (j.get("tables") or []) if x.get("data")), None)      # 依「有資料」挑表，不寫死 tables[0]
    if t is None:
        return pd.DataFrame(columns=INST_COLS)
    n = len(t.get("fields") or [])
    rows = []
    if n == 24:
        # 組序：①外資(不含自營)(2-4) ②外資自營(5-7) ③外資合計(8-10) ④投信(11-13) ⑤自營自行(14-16) ⑥自營避險(17-19) ⑦自營合計(20-22) 合計(23)
        pos = {"foreign_net": 4, "trust_net": 13, "dealer_net": 22, "total_net": 23}
    elif n == 16:
        pos = {"foreign_net": 4, "trust_net": 7, "dealer_net": 8, "total_net": 15}
    else:
        print(f"::warning::TPEx 法人 {ymd} 欄數 {n}（非 24／16），丟棄", file=sys.stderr)
        return None
    for r in t["data"]:
        c = str(r[0]).strip()
        if _code_ok(c):
            rows.append({"date": pd.Timestamp(d), "ticker": c, "market": "TWO", "fi_prop_net": None,
                         **{k: _n(r[i]) for k, i in pos.items()}})
    return pd.DataFrame(rows, columns=INST_COLS)


# ───────────────────────── 融資融券 ─────────────────────────
def margin_twse(d: date) -> pd.DataFrame | None:
    ymd = d.strftime("%Y%m%d")
    j = _get(MI_MARGN.format(d=ymd))
    if j is None:
        return None
    if j.get("stat") != "OK":
        return pd.DataFrame(columns=MARGIN_COLS)
    if str(j.get("date")) != ymd:
        print(f"::warning::MI_MARGN {ymd} 回應日期 {j.get('date')} 不符，丟棄", file=sys.stderr)
        return None
    tab = next((t for t in j.get("tables", []) if len(t.get("fields") or []) == 16 and t.get("data")), None)
    if tab is None:     # stat=OK 卻找不到個股表 → 改版或殘缺，算失敗（不是休市）
        print(f"::warning::MI_MARGN {ymd} stat=OK 但找不到 16 欄個股表，視為失敗", file=sys.stderr)
        return None
    rows = []
    for r in tab["data"]:
        c = str(r[0]).strip()
        if _code_ok(c):   # 欄序（pitfalls／上游同）：融資 買進2 賣出3 現償4 前日5 今日6 限額7；融券 買進8 賣出9 券償10 前日11 今日12 限額13；資券互抵14
            rows.append({"date": pd.Timestamp(d), "ticker": c, "market": "TW", "margin_balance": _n(r[6]),
                         "margin_buy": _n(r[2]), "margin_sell": _n(r[3]), "margin_redeem": _n(r[4]),
                         "short_balance": _n(r[12]), "short_buy": _n(r[8]), "short_sell": _n(r[9]),
                         "short_redeem": _n(r[10]), "offset": _n(r[14])})
    return pd.DataFrame(rows, columns=MARGIN_COLS)


def margin_tpex(d: date) -> pd.DataFrame | None:
    ymd = d.strftime("%Y%m%d")
    j = _get(TPEX_MARGIN.format(d=d.strftime("%Y/%m/%d")))
    if j is None:
        return None
    if str(j.get("date")) != ymd:
        print(f"::warning::TPEx 融資 {ymd} 回應日期 {j.get('date')} 不符，丟棄", file=sys.stderr)
        return None
    t = (j.get("tables") or [{}])[0]
    if not t.get("data"):
        return pd.DataFrame(columns=MARGIN_COLS)
    f = t.get("fields") or []
    if len(f) != 20:
        print(f"::warning::TPEx 融資 {ymd} 欄數 {len(f)}≠20，丟棄", file=sys.stderr)
        return None
    # 0代號 1名稱 2前資餘額 3資買 4資賣 5現償 6資餘額 ... 10前券餘額 11券賣 12券買 13券償 14券餘額 ... 18資券相抵
    rows = []
    for r in t["data"]:
        c = str(r[0]).strip()
        if _code_ok(c):
            rows.append({"date": pd.Timestamp(d), "ticker": c, "market": "TWO", "margin_balance": _n(r[6]),
                         "margin_buy": _n(r[3]), "margin_sell": _n(r[4]), "margin_redeem": _n(r[5]),
                         "short_balance": _n(r[14]), "short_buy": _n(r[12]), "short_sell": _n(r[11]),
                         "short_redeem": _n(r[13]), "offset": _n(r[18])})
    return pd.DataFrame(rows, columns=MARGIN_COLS)


# ───────────────────────── 主流程 ─────────────────────────
SOURCES = {
    "inst": (INST, INST_COLS, {"TW": inst_twse, "TWO": inst_tpex}),
    "margin": (MARGIN, MARGIN_COLS, {"TW": margin_twse, "TWO": margin_tpex}),
}


def run(dataset: str, start: date, end: date) -> int:
    path, cols, fetchers = SOURCES[dataset]
    old = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=cols)
    # 「已有」＝ (市場, 日期)；休市日另記在 closed 檔，避免每次重打（也不會被當缺口）
    have = {(m, pd.Timestamp(d).date()) for m, d in zip(old["market"], old["date"])}
    closed_f = SH / f"{dataset}_closed.csv"
    closed = set()
    if closed_f.exists():
        closed = {(r.market, date.fromisoformat(r.date)) for r in pd.read_csv(closed_f).itertuples()}
    unavail_f = SH / f"{dataset}_unavailable.csv"       # 官方該端點該日根本沒資料（目前已知情況：無；TPEx 法人 2018 前只是格式不同，不是沒資料）
    if unavail_f.exists():
        closed |= {(r.market, date.fromisoformat(r.date)) for r in pd.read_csv(unavail_f).itertuples()}
    empties: list[tuple[str, date]] = []
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    cal = _trading_calendar()
    cal_max = max(cal) if cal else None
    # 週六只在「官方實價日曆有該日」（＝補班日有交易）時才問；平日照舊
    todo = [(m, d) for d in days if (d.weekday() < 5 or (d.weekday() == 5 and cal is not None and d in cal))
            for m in fetchers if (m, d) not in have and (m, d) not in closed]
    print(f"[{dataset}] 範圍 {start}~{end}；待抓 {len(todo)} 個(市場,日)", flush=True)
    new: list[pd.DataFrame] = []
    failed, newly_closed = [], []
    SH.mkdir(parents=True, exist_ok=True)

    def flush() -> None:
        nonlocal old, new
        if new:
            allp = pd.concat([old] + new, ignore_index=True).drop_duplicates(["date", "ticker", "market"], keep="last")
            allp = allp.sort_values(["date", "market", "ticker"]).reset_index(drop=True)
            allp.to_parquet(path, index=False, compression="zstd")
            old, new = allp, []
        if newly_closed:
            pd.concat([pd.read_csv(closed_f) if closed_f.exists() else pd.DataFrame(columns=["market", "date"]),
                       pd.DataFrame(newly_closed, columns=["market", "date"])]).drop_duplicates() \
                .to_csv(closed_f, index=False)
            newly_closed.clear()

    for i, (m, d) in enumerate(todo, 1):
        df = fetchers[m](d)
        time.sleep(SLEEP)
        if df is None:
            failed.append((m, str(d)))
        elif df.empty:
            # 空表只有在「官方實價日曆已涵蓋該日、且該日不是交易日」時才記休市；
            # 日曆沒涵蓋（含今天、公布前）→ 既不記休市也不算失敗，下次再問（避免公布前執行造成永久缺洞）。
            if cal is not None and d <= cal_max and d not in cal:
                newly_closed.append((m, d.isoformat()))
            elif cal is not None and d in cal:
                empties.append((m, d))              # 交易日卻沒資料：缺料或端點無此歷史，迴圈後再分辨
        else:
            new.append(df)
        if i % 20 == 0:
            flush()
            print(f"  進度 {i}/{len(todo)}，失敗 {len(failed)}", flush=True)
    flush()
    # 交易日卻空表：若早於該市場「已成功取得的最早日」→ 端點沒有那麼早的歷史（unavailable，不是失敗）；否則是缺料（失敗）。
    min_ok = {m: pd.Timestamp(g["date"].min()).date() for m, g in old.groupby("market")} if len(old) else {}
    un = [(m, d.isoformat()) for m, d in empties if m in min_ok and d < min_ok[m]]
    failed += [(m, str(d)) for m, d in empties if not (m in min_ok and d < min_ok[m])]
    if un:
        pd.concat([pd.read_csv(unavail_f) if unavail_f.exists() else pd.DataFrame(columns=["market", "date"]),
                   pd.DataFrame(un, columns=["market", "date"])]).drop_duplicates().to_csv(unavail_f, index=False)
        print(f"[{dataset}] 端點無歷史資料（記為 unavailable）：{len(un)} 個(市場,日)", flush=True)
    print(f"[{dataset}] 完成；失敗 {len(failed)} {failed[:6]}", flush=True)
    return len(failed)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", choices=["inst", "margin", "all"], default="all")
    ap.add_argument("--start")
    ap.add_argument("--end")
    a = ap.parse_args(argv)
    end = datetime.strptime(a.end, "%Y-%m-%d").date() if a.end else date.today()
    start = datetime.strptime(a.start, "%Y-%m-%d").date() if a.start else end - timedelta(days=14)
    bad = 0
    for ds in (["inst", "margin"] if a.dataset == "all" else [a.dataset]):
        bad += run(ds, start, end)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
