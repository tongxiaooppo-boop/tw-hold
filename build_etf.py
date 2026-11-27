"""ETF 分頁衍生資料：data/etf/{prices,events}.parquet → data/derived/etf.json。

框架 2026-11-27（Opus 定，實作者不得改函式簽名、欄名、JSON schema；有問題停下回報）。
決策文件：d:/g/claude/etf_display_2026-11-27/DECISION.md

輸入（scripts/etf_track.py 產出）
- prices：ticker, date(datetime64), open, high, low, close, volume, source   —— 原始未還原價
- events：ticker, date, type('div'|'split'), cash(每股現金，該事件當時的股數口徑；split 為 NaN),
          prev_close, ref_price, factor(div＝ref/prev；split＝新價÷舊價), source

還原（向後還原，最後一天＝原始價）
- tr_*（總報酬還原）：t 日價 × Π{事件 e：e.date > t} e.factor（div 與 split 都乘）
- sp_*（只還原分割）：t 日價 × Π{split e：e.date > t} e.factor
- 事件「當天」不乘自己（除息日當天的價已是除息後）。
- 只用該檔「最後一筆價格日（含）以前」的事件；更晚的事件（例如分割表裡還沒到的日子）忽略，保證最後一天＝原始價。
- 總報酬還原＝除息日按參考價把配息買回（近似，跟實際隔天開盤買回有小差距；EXPLAIN／DCA_NOTE 已註明）。

日曆：每檔用自己的價格日期當交易日曆。單檔計算（ma、ret_1y、yield、yearly、dca）一律以「該檔 last_date」當 asof；
停牌沒有最新價的檔不補價。頂層 asof 只是顯示用。

輸出 data/derived/etf.json（schema 固定）
{
  "asof": "YYYY-MM-DD",                 # 所有白名單 ETF 最新一筆日期的最大值
  "generated_at": "YYYY-MM-DDTHH:MM:SSZ",
  "rows": [                             # 依 GROUPS 順序、組內依代號
    {"code": str, "name": str, "group": "cap"|"div"|"lev", "close": float, "last_date": "YYYY-MM-DD",
     "first_date": "YYYY-MM-DD",
     "ma": {"60": float|null, "120": float|null, "240": float|null},   # 收盤相對均線位置（0.031＝+3.1%）
     "ret_1y": float|null,              # 近一年總報酬（tr_close）
     "yield_1y": float|null, "yield_1y_n": int|null}                  # 只有 div 組有值，其他組 null
  ],
  "missing": [str],                     # 白名單裡沒有任何價格的代號
  "yearly": {code: {"YYYY": {"rate": float, "partial": bool}}},       # 只有 div 組
  "dca": {code: {"reinvest": DCA|null, "cash": DCA|null,
                 "bench_reinvest": DCA|null, "bench_cash": DCA|null}},  # bench＝同扣款月份的 0050；0050 自己為 null
  "annual": {code: ANNUAL|null},        # 每年年初買一筆（2026-11-27 加）；全部組都有
  "div_cash": {code: {"years": {"YYYY": float|null}, "avg": float|null, "n": int}}  # 只有 div 組（2026-11-27 加）
}
DCA = {"start": "YYYY-MM-DD"(第一次買進日), "end": "YYYY-MM-DD"(傳入的 asof＝該檔 last_date), "buys": int,
       "invested": float, "value": float, "irr": float|null, "worst": float}
ANNUAL = {"start": "YYYY", "years": [{"year": "YYYY", "ret": float, "pnl": float, "partial": bool}, ...由舊到新],
          "invested": float, "value": float, "bench_value": float|null}   # bench＝同樣年份買 0050；0050 自己為 null
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from reference.etf_universe import (BENCH, DCA_AMOUNT, DCA_MIN_BUYS, ETF_UNIVERSE, GROUPS, JUMP_LIMIT,
                                    MA_WINDOWS, YEARLY_YIELD_YEARS, DIV_CASH_YEARS)

ROOT = Path(__file__).resolve().parent
ETF_DIR = ROOT / "data" / "etf"
OUT = ROOT / "data" / "derived" / "etf.json"


def load_inputs(etf_dir: Path = ETF_DIR) -> tuple[pd.DataFrame, pd.DataFrame]:
    """讀 prices.parquet、events.parquet；date 轉 datetime64、依 (ticker, date) 排序。"""
    px = pd.read_parquet(etf_dir / "prices.parquet")
    ev = pd.read_parquet(etf_dir / "events.parquet")
    px["date"] = pd.to_datetime(px["date"])
    ev["date"] = pd.to_datetime(ev["date"])
    return (px.sort_values(["ticker", "date"]).reset_index(drop=True),
            ev.sort_values(["ticker", "date"]).reset_index(drop=True))


def _suffix_factor(dates: pd.Series, ev_dates: np.ndarray, ev_factors: np.ndarray) -> np.ndarray:
    """每個 dates 的 Π{事件日 > t} factor。ev_dates 已排序。"""
    n = len(ev_factors)
    suffix = np.ones(n + 1)
    for i in range(n - 1, -1, -1):
        suffix[i] = suffix[i + 1] * ev_factors[i]
    idx = np.searchsorted(ev_dates, dates.to_numpy(dtype="datetime64[ns]"), side="right")
    return suffix[idx]


def adjust(prices: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """回傳 prices 加四欄 tr_open, tr_close, sp_open, sp_close（定義見模組說明）。不改原欄。"""
    parts = []
    for tk, g in prices.groupby("ticker", sort=False):
        g = g.sort_values("date").copy()
        last = g["date"].iloc[-1]
        e = events[(events["ticker"] == tk) & (events["date"] <= last)].sort_values("date")
        ed = e["date"].to_numpy(dtype="datetime64[ns]")
        f_all = _suffix_factor(g["date"], ed, e["factor"].to_numpy(dtype=float))
        sf = np.where(e["type"].to_numpy() == "split", e["factor"].to_numpy(dtype=float), 1.0)
        f_sp = _suffix_factor(g["date"], ed, sf)
        g["tr_open"] = g["open"].to_numpy(dtype=float) * f_all
        g["tr_close"] = g["close"].to_numpy(dtype=float) * f_all
        g["sp_open"] = g["open"].to_numpy(dtype=float) * f_sp
        g["sp_close"] = g["close"].to_numpy(dtype=float) * f_sp
        parts.append(g)
    if not parts:
        out = prices.copy()
        for c in ("tr_open", "tr_close", "sp_open", "sp_close"):
            out[c] = pd.Series(dtype=float)
        return out
    return pd.concat(parts, ignore_index=True)


def check_jumps(adj: pd.DataFrame) -> list[str]:
    """每檔相鄰兩筆 tr_close 比值超出 JUMP_LIMIT（含邊界外）→ 一條訊息 f"{ticker} {date:%Y-%m-%d} {ratio:.3f}"。"""
    lo, hi = JUMP_LIMIT
    msgs = []
    for tk, g in adj.groupby("ticker", sort=True):
        g = g.sort_values("date")
        ratio = g["tr_close"] / g["tr_close"].shift(1)
        for d, r in zip(g["date"], ratio):
            if r == r and (r < lo or r > hi):
                msgs.append(f"{tk} {d:%Y-%m-%d} {r:.3f}")
    return msgs


def ma_position(tr_close: pd.Series, n: int) -> float | None:
    """最後一筆 ÷ 最後 n 筆平均 − 1；不足 n 筆 → None。"""
    if len(tr_close) < n:
        return None
    tail = tr_close.iloc[-n:]
    return float(tr_close.iloc[-1] / tail.mean() - 1)


def ret_1y(tr_close: pd.Series, asof: pd.Timestamp) -> float | None:
    """tr_close（index＝date）在 asof 的值 ÷ 「asof−365 天當天或之前最後一筆」的值 − 1。
    第一筆日期 > asof−365 天 → None。"""
    s = tr_close[tr_close.index <= asof]
    cutoff = asof - pd.Timedelta(days=365)
    if len(s) == 0 or s.index[0] > cutoff:
        return None
    base = s[s.index <= cutoff].iloc[-1]
    return float(s.iloc[-1] / base - 1)


def cash_in_current_units(events: pd.DataFrame) -> pd.Series:
    """單一檔的 div 事件，每筆 cash × Π{該事件日期之後的 split factor}，index＝除息日。
    （一拆四後，舊的 1 元現金＝每新股 0.25 元）"""
    d = events[events["type"] == "div"].sort_values("date")
    sp = events[events["type"] == "split"]
    sd = sp["date"].to_numpy(dtype="datetime64[ns]")
    sf = sp["factor"].to_numpy(dtype=float)
    vals = []
    for dt, c in zip(d["date"], d["cash"]):
        vals.append(float(c) * float(np.prod(sf[sd > np.datetime64(dt, "ns")])) if len(sf) else float(c))
    return pd.Series(vals, index=pd.DatetimeIndex(d["date"].to_list()), dtype=float)


def trailing_yield(events: pd.DataFrame, close: float, asof: pd.Timestamp,
                   first_date: pd.Timestamp) -> tuple[float | None, int | None]:
    """近一年配息率：除息日落在 (asof−365 天, asof] 的 cash_in_current_units 合計 ÷ close，與筆數。
    照日期區間算，13 次就算 13 次。first_date > asof−365 天 → (None, None)。區間內 0 筆 → (0.0, 0)。"""
    cutoff = asof - pd.Timedelta(days=365)
    if first_date > cutoff:
        return None, None
    c = cash_in_current_units(events)
    c = c[(c.index > cutoff) & (c.index <= asof)]
    return float(c.sum() / close), int(len(c))


def yearly_yields(sp_close: pd.Series, events: pd.DataFrame, asof: pd.Timestamp,
                  years: int = YEARLY_YIELD_YEARS) -> dict[str, dict]:
    """最近 `years` 個曆年（含 asof 那年），每年 {"rate", "partial"}：
    rate＝該年除息的 cash_in_current_units 合計 ÷ 該年第一筆 sp_close（上市當年＝上市後第一筆）。
    partial＝上市當年 或 asof 那年。該年沒有任何價格 → 不放這年。"""
    c = cash_in_current_units(events)
    listing_year = int(sp_close.index[0].year) if len(sp_close) else None
    out: dict[str, dict] = {}
    for y in range(asof.year - years + 1, asof.year + 1):
        s = sp_close[(sp_close.index.year == y) & (sp_close.index <= asof)]
        if len(s) == 0:
            continue
        cy = c[(c.index.year == y) & (c.index <= asof)]
        out[str(y)] = {"rate": float(cy.sum() / s.iloc[0]), "partial": bool(y == listing_year or y == asof.year)}
    return out


def yearly_cash(events: pd.DataFrame, asof: pd.Timestamp, first_date: pd.Timestamp,
                years: int = DIV_CASH_YEARS) -> dict:
    """近 `years` 個完整曆年（asof 那年之前；asof=2026 → 2021～2025）每年除息現金合計（元／每單位，
    用 cash_in_current_units，分割已換成現在單位）。框架 2026-11-27（Opus 定）。
    - 年份 ≤ first_date 的年（上市當年不完整、更早還沒上市）→ None；之後的年沒除息 → 0.0。
    - avg＝非 None 年份的平均（全 None → None）；n＝非 None 年數。
    回 {"years": {"YYYY": float|None, …由舊到新、一定 `years` 個 key}, "avg": float|None, "n": int}"""
    c = cash_in_current_units(events)
    out: dict[str, float | None] = {}
    for y in range(asof.year - years, asof.year):
        if y <= first_date.year:
            out[str(y)] = None
        else:
            out[str(y)] = float(c[c.index.year == y].sum())
    vals = [v for v in out.values() if v is not None]
    return {"years": out, "avg": float(sum(vals) / len(vals)) if vals else None, "n": len(vals)}


def xirr(flows: list[tuple[pd.Timestamp, float]]) -> float | None:
    """年化資金加權報酬：Σ amount × (1+r)^(−天數/365) = 0；二分法 r∈[−0.99, 10]，誤差 1e-7。解不出 → None。"""
    if not flows:
        return None
    t0 = min(d for d, _ in flows)
    pts = [((d - t0).days / 365.0, float(a)) for d, a in flows]

    def f(r: float) -> float:
        return sum(a * (1.0 + r) ** (-t) for t, a in pts)

    lo, hi = -0.99, 10.0
    flo, fhi = f(lo), f(hi)
    if flo == 0:
        return lo
    if fhi == 0:
        return hi
    if flo * fhi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        fm = f(mid)
        if fm == 0 or hi - lo < 1e-9:
            return float(mid)
        if flo * fm < 0:
            hi = mid
        else:
            lo, flo = mid, fm
    return float((lo + hi) / 2)


def dca(adj: pd.DataFrame, events: pd.DataFrame, asof: pd.Timestamp, reinvest: bool,
        amount: float = DCA_AMOUNT, start_month: str | None = None) -> dict | None:
    """單一檔定期定額（adj 只含該檔、已依日期排序；events 只含該檔）。
    - 買進＝每個月第一個交易日開盤（2026-11-27 使用者定，跟年初回測同口徑）；只算買進日 ≤ asof 的。
    - 起始月：start_month（'YYYY-MM'）給了就用；否則＝第一筆價格所在月的「下個月」。
    - reinvest=True：units += amount / tr_open[買進日]；市值_t＝units_t × tr_close_t。
    - reinvest=False：units += amount / sp_open[買進日]；每個 div 事件日 e，
      現金 += （買進日 < e.date 的累計 units）× cash_in_current_units[e]；市值_t＝units_t × sp_close_t ＋ 現金_t。
    - worst＝第一次買進日起每個交易日 min(市值_t ÷ 累計投入_t − 1)（買進日當天收盤已計入當天的投入）。
    - irr＝xirr（每次買進 −amount、asof 那天 +期末市值）。
    - 買進次數 < DCA_MIN_BUYS → None。
    回傳 DCA dict（見模組說明）。"""
    a = adj[adj["date"] <= asof].sort_values("date").reset_index(drop=True)
    n = len(a)
    if n == 0:
        return None
    dates = a["date"]
    months = dates.dt.strftime("%Y-%m")
    if start_month is None:
        start_month = (dates.iloc[0].to_period("M") + 1).strftime("%Y-%m")
    first_idx = months.drop_duplicates().index            # 每月第一個交易日的位置
    buy_idx = [i for i in first_idx if months.iloc[i] >= start_month]
    if len(buy_idx) < DCA_MIN_BUYS:
        return None
    open_col, close_col = ("tr_open", "tr_close") if reinvest else ("sp_open", "sp_close")
    opens = a[open_col].to_numpy(dtype=float)
    closes = a[close_col].to_numpy(dtype=float)
    inc = np.zeros(n)
    cnt = np.zeros(n)
    for i in buy_idx:
        inc[i] += amount / opens[i]
        cnt[i] += 1
    units = np.cumsum(inc)
    invested = np.cumsum(cnt) * amount
    value = units * closes
    if not reinvest:
        cash = np.zeros(n)
        cu = cash_in_current_units(events)
        dn = dates.to_numpy(dtype="datetime64[ns]")
        for dt, c in cu.items():
            k = int(np.searchsorted(dn, np.datetime64(dt, "ns"), side="left"))
            if k >= n:
                continue
            held = units[k - 1] if k > 0 else 0.0
            cash[k:] += held * c
        value = value + cash
    s = buy_idx[0]
    worst = float(np.min(value[s:] / invested[s:] - 1))
    flows = [(dates.iloc[i], -float(amount)) for i in buy_idx] + [(dates.iloc[-1], float(value[-1]))]
    return {"start": f"{dates.iloc[s]:%Y-%m-%d}", "end": f"{asof:%Y-%m-%d}", "buys": len(buy_idx),
            "invested": float(invested[-1]), "value": float(value[-1]), "irr": xirr(flows), "worst": worst}


def annual_lump(adj: pd.DataFrame, asof: pd.Timestamp, amount: float = DCA_AMOUNT,
                start_year: int | None = None) -> dict | None:
    """每年年初買一筆 amount 元（配息再投入，用 tr_open／tr_close）。adj 只含該檔。框架 2026-11-27（Opus 定）。
    - 只用 date ≤ asof 的列。起始年：start_year 給了就用；否則＝第一筆價格年份 + 1（上市當年不算）。
    - 每個「起始年 ≤ 年 ≤ asof 年」且該年有價格的曆年：買進＝該年第一個交易日 tr_open；
      年底＝該年最後一個交易日 tr_close（asof 那年＝asof 前最後一列，partial=True；其他年 partial=False）。
    - ret＝年底 ÷ 買進 − 1；pnl＝amount × ret。
    - 累計（每年那筆都抱到 asof）：invested＝amount × 年數；value＝Σ amount × tr_close[最後一列] ÷ tr_open[該年買進]。
    - 沒有任何一年 → None。
    回傳 ANNUAL 但不含 bench_value（build 補）；start＝第一個有算到的年（字串）。"""
    a = adj[adj["date"] <= asof].sort_values("date").reset_index(drop=True)
    if len(a) == 0:
        return None
    if start_year is None:
        start_year = int(a["date"].iloc[0].year) + 1
    years_col = a["date"].dt.year
    last_close = float(a["tr_close"].iloc[-1])
    asof_year = int(a["date"].iloc[-1].year)
    years, value = [], 0.0
    for y in sorted(int(v) for v in years_col.unique()):
        if y < start_year or y > asof_year:
            continue
        g = a[years_col == y]
        buy = float(g["tr_open"].iloc[0])
        end = float(g["tr_close"].iloc[-1])
        ret = end / buy - 1
        years.append({"year": str(y), "ret": ret, "pnl": amount * ret, "partial": y == asof_year})
        value += amount * last_close / buy
    if not years:
        return None
    return {"start": years[0]["year"], "years": years, "invested": float(amount * len(years)), "value": float(value)}


def _f(x) -> float | None:
    return None if x is None or x != x else float(x)


def build(prices: pd.DataFrame, events: pd.DataFrame, now: datetime | None = None) -> dict:
    """組 etf.json。只處理 ETF_UNIVERSE 內的代號；先 check_jumps，有任何訊息 → raise ValueError（整串訊息）。
    bench_*：用 dca(0050, asof＝該檔 last_date, start_month＝該檔 reinvest 結果 start 的月份) 算；
    該檔 reinvest 為 None → bench 都 None。
    annual[code]＝annual_lump(該檔, last)，非 None 時加 bench_value＝annual_lump(0050, last,
    start_year=int(該檔 start))["value"]（0050 自己、沒有 0050、或結果為 None → null；
    0050 年數與該檔不同時仍照算，不另對齊）。
    div_cash[code]＝yearly_cash(該檔 events, last, first)，只有 div 組。"""
    prices = prices[prices["ticker"].isin(ETF_UNIVERSE)]
    events = events[events["ticker"].isin(ETF_UNIVERSE)]
    adj = adjust(prices, events)
    msgs = check_jumps(adj)
    if msgs:
        raise ValueError("\n".join(msgs))
    have = set(adj["ticker"].unique())
    order = [c for g in GROUPS for c in sorted(k for k, (_, gg) in ETF_UNIVERSE.items() if gg == g)]
    now = now or datetime.now(timezone.utc)
    rows, yearly, dca_out, annual_out, div_cash = [], {}, {}, {}, {}
    bench_adj = adj[adj["ticker"] == BENCH].sort_values("date") if BENCH in have else None
    bench_ev = events[events["ticker"] == BENCH]
    for code in order:
        if code not in have:
            continue
        name, grp = ETF_UNIVERSE[code]
        g = adj[adj["ticker"] == code].sort_values("date").reset_index(drop=True)
        ev = events[events["ticker"] == code]
        last, first = g["date"].iloc[-1], g["date"].iloc[0]
        close = float(g["close"].iloc[-1])
        tr = pd.Series(g["tr_close"].to_numpy(), index=pd.DatetimeIndex(g["date"]))
        y1, yn = (trailing_yield(ev, close, last, first) if grp == "div" else (None, None))
        rows.append({"code": code, "name": name, "group": grp, "close": close, "last_date": f"{last:%Y-%m-%d}",
                     "first_date": f"{first:%Y-%m-%d}",
                     "ma": {str(w): _f(ma_position(tr, w)) for w in MA_WINDOWS},
                     "ret_1y": _f(ret_1y(tr, last)), "yield_1y": _f(y1), "yield_1y_n": yn})
        if grp == "div":
            yearly[code] = yearly_yields(pd.Series(g["sp_close"].to_numpy(), index=pd.DatetimeIndex(g["date"])), ev, last)
            div_cash[code] = yearly_cash(ev, last, first)
        d_re =dca(g, ev, last, True)
        d_ca = dca(g, ev, last, False)
        b_re = b_ca = None
        if code != BENCH and bench_adj is not None:
            if d_re is not None:
                b_re = dca(bench_adj, bench_ev, last, True, start_month=d_re["start"][:7])
            if d_ca is not None:
                b_ca = dca(bench_adj, bench_ev, last, False, start_month=d_ca["start"][:7])
        dca_out[code] = {"reinvest": d_re, "cash": d_ca, "bench_reinvest": b_re, "bench_cash": b_ca}
        an = annual_lump(g, last)
        if an is not None:
            bv = None
            if code != BENCH and bench_adj is not None:
                bn = annual_lump(bench_adj, last, start_year=int(an["start"]))
                bv = bn["value"] if bn is not None else None
            an["bench_value"] = bv
        annual_out[code] = an
    asof = max((r["last_date"] for r in rows), default=None)
    return {"asof": asof, "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "rows": rows,
            "missing": [c for c in order if c not in have], "yearly": yearly, "dca": dca_out, "annual": annual_out,
            "div_cash": div_cash}


def main(argv: list[str] | None = None) -> int:
    """讀 → build → 寫 OUT（先建父目錄；ensure_ascii=False, indent=1）。ValueError → 印到 stderr、回 1、不寫檔。
    路徑一律用 ROOT 相對（CI 的工作目錄不一定是 repo 根）。"""
    try:
        px, ev = load_inputs()
        out = build(px, ev)
    except ValueError as e:
        print(f"build_etf 失敗：\n{e}", file=sys.stderr)
        return 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"etf.json asof {out['asof']} rows {len(out['rows'])} missing {out['missing']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
