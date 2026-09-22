"""17 條規則重新回測：長波段 1 + 價值線 1 + tw-swing 精選 14 條，統一「買得到」口徑。

交接來源：`docs/HANDOFF_2026-09-22b.md`。起因：tw-hold 價值線回測（`backtest_value.py`）
與長波段回測（`backtest_longswing.py` 已修過）曾用「訊號/換股日當天收盤成交」——
看得到、買不到的口徑。這次要把「次一交易日開盤才成交」統一套到：

  1. 長波段候選池（`screener/candidate_pool.py`，CANSLIM ∩ 趨勢模板 ∩ 市況門檻）
     ——固定一組規則，「訊號全買」（不排名、全部等權買進），直接沿用
     `research/backtest_longswing.py` 已經做好的 `next_open` + `notbear` 市況閘門
     + 移動 ATR 停損那組（跟 production `screener/candidate_pool.py::market_regime_ok`
     ＋ `screener/swing_stops.py` 的移動停損口徑一致），只是把時間範圍截到 2026-08。
  2. 價值因子指數（`screener/screen.py::screen_value`）——「訊號全買」（N=∞，
     過硬門檻的全部候選等權買進），改寫 `pick_value`/`fwd_ret` 用次日開盤成交。
  3. tw-swing 規則庫湊 15 條（同家族只取最佳版本，實測只湊到 14 條——見下方
     `TWSWING_CANDIDATES` 前的說明與最終報告〈附錄〉的篩選記錄），直接借用
     tw-swing 自己的 `data/scan/events_all.parquet`（全規則、全市場、已算好
     entry/stop 的事件表）＋ `twswing.backtest.engine` 引擎，只是：
       - 事件檔按 ticker 過濾成 tw-hold 的 universe（bundle `universe.parquet`
         `in_universe`）、日期過濾到 2016-01～2026-08；
       - 進場一律 `entry_at="next_open"`；
       - 組合層一律等權、不設部位上限（`sizing="equal"`，`max_positions` 給一個
         大到不會卡的數字），對齊「訊號全買」的精神（跟長波段/價值線一致，
         雖然這條規定原文只寫給那兩條，這裡延伸套用並在報告裡講清楚）。

市況切法：`reference/market_status.py::ma_verdict(close, window=60)` 的公式
（乖離 ±2% 分多/空/盤整）逐日向量化重算（不是逐日呼叫該函式，是同一條公式的
向量化版本，數字上完全等價，只是效能考量），對 0050 收盤序列跑。

🔴 生存者偏差：universe 用今天的 bundle `in_universe`，回溯 2016 等於已知誰
   活到今天，所有數字當上界看待（同既有回測慣例）。
🔴 研究腳本、不是產品碼：日線一律借 tw-swing 本機 `data/store/daily_full.parquet`
   （tw-hold 自己 `prices_adj.parquet` 只從 2023-05 起，長度不夠），不改 tw-swing
   任何檔案。

用法：
    python research/backtest_top17_buyable.py
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
TWSWING = Path(r"d:\g\claude\tw-swing")
sys.path.insert(0, str(TWSWING / "src"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from reference.loader import BUNDLE_DIR  # noqa: E402
from reference.market_status import BAND as MS_BAND  # noqa: E402

OUT = REPO / "docs" / "reports"
OUT.mkdir(parents=True, exist_ok=True)

START = pd.Timestamp("2016-01-01")
END = pd.Timestamp("2026-08-31")
MS_WINDOW = 60          # ma_verdict 的窗口（HANDOFF §0-4 指定用 window=60）
COST_ACTUAL = 0.00585    # 台股來回成本口徑，全 repo沿用同一個數字


# ─────────────────────────── 共用：universe / 市況分類 ───────────────────────────

def load_universe() -> set[str]:
    uni_p = BUNDLE_DIR / "fundamentals" / "universe.parquet"
    uni_df = pd.read_parquet(uni_p, columns=["ticker", "in_universe"])
    return set(uni_df.loc[uni_df["in_universe"], "ticker"].astype(str))


def bare(s: pd.Series) -> pd.Series:
    return s.astype(str).str.split(".").str[0]


def ma_verdict_series(close: pd.Series, window: int = MS_WINDOW,
                      band: float = MS_BAND) -> pd.Series:
    """`reference.market_status.ma_verdict` 公式的逐日向量化版本（同一個公式，
    只是一次算完整條序列而不是每天呼叫一次）：乖離 = 收盤/MA - 1，
    > +band 記多頭、< -band 記空頭，其餘盤整。暖機期（不足 window 天）留 NaN。"""
    s = close.astype("float64").sort_index()
    ma = s.rolling(window, min_periods=window).mean()
    gap = s / ma - 1.0
    state = pd.Series(np.where(gap > band, "bull", np.where(gap < -band, "bear", "chop")),
                      index=s.index, dtype=object)
    state[ma.isna()] = np.nan
    return state


def load_0050_close() -> pd.Series:
    """0050 還原收盤（tw-swing 本機 store，起點 2015-01，涵蓋 START 前 60 個交易日暖機）。"""
    from twswing.data import store  # noqa: E402
    df = store.read_daily(recent=False, columns=["date", "ticker", "close"])
    s = df.loc[df["ticker"] == "0050.TW"].set_index("date")["close"].sort_index()
    return s.astype("float64")


def regime_day_counts(mkt_state: pd.Series, y0: pd.Timestamp, y1: pd.Timestamp) -> dict:
    seg = mkt_state.loc[(mkt_state.index >= y0) & (mkt_state.index <= y1)].dropna()
    if not len(seg):
        return {"bull": np.nan, "bear": np.nan, "chop": np.nan, "n": 0}
    vc = seg.value_counts(normalize=True)
    return {"bull": vc.get("bull", 0.0), "bear": vc.get("bear", 0.0),
           "chop": vc.get("chop", 0.0), "n": len(seg)}


def period_return(close_like: pd.Series, y0: pd.Timestamp, y1: pd.Timestamp) -> float | None:
    seg = close_like.loc[(close_like.index >= y0) & (close_like.index <= y1)].dropna()
    if len(seg) < 2:
        return None
    return float(seg.iloc[-1] / seg.iloc[0] - 1.0)


def curve_to_dense(curve: pd.Series, calendar: pd.DatetimeIndex) -> pd.Series:
    """把（可能疏落的）權益曲線攤到完整交易日曆：曲線開始前留 NaN（還沒開始，
    不是「持平」），開始後 ffill（沒有新事件的日子淨值不變，等權組合的自然假設）。"""
    c = curve.sort_index()
    dense = c.reindex(c.index.union(calendar)).sort_index().ffill().reindex(calendar)
    dense.loc[dense.index < c.index[0]] = np.nan
    return dense


def year_rows(dense_curve: pd.Series, bench_close: pd.Series, mkt_state: pd.Series,
              years: list[int], bench_dense: pd.Series | None = None) -> list[dict]:
    """`bench_dense`：0050 的「假設同一天投入同樣本金」歸一化曲線（在策略開始
    那天＝1.0），只用來算 `bench_end_val`（0050 那筆錢年末值多少）——跟
    `bench_ret`（用原始 0050 價格算的報酬率，跟本金無關）分開算，互不影響。"""
    rows = []
    for y in years:
        y0, y1 = pd.Timestamp(y, 1, 1), min(pd.Timestamp(y, 12, 31), END)
        if y0 > END:
            break
        seg = dense_curve.loc[(dense_curve.index >= y0) & (dense_curve.index <= y1)].dropna()
        # 基準值＝「今年之前最後一筆有效值」，沒有就用 1.0（真正的起始本金）——
        # 不能用 seg.iloc[0]（今年第一筆有效值）當基準：curve 進場當天就會用當天
        # 收盤標記部位，所以曲線第一天本來就不是乾淨的 1.0，用它當基準會讓
        # 規則「第一次有交易的那一年」報酬率系統性算錯（2026-09-22 使用者抓到）。
        prior = dense_curve.loc[dense_curve.index < y0].dropna()
        base = float(prior.iloc[-1]) if len(prior) else 1.0
        strat_ret = float(seg.iloc[-1] / base - 1.0) if len(seg) else None
        end_val = float(seg.iloc[-1]) if len(seg) else None  # 年末權益（curve 的原始單位，未乘本金）
        bench_ret = period_return(bench_close, y0, y1)
        bench_end_val = None
        if bench_dense is not None:
            bseg = bench_dense.loc[(bench_dense.index >= y0) & (bench_dense.index <= y1)].dropna()
            bench_end_val = float(bseg.iloc[-1]) if len(bseg) else None
        rc = regime_day_counts(mkt_state, y0, y1)
        rows.append({"year": y, "strat_ret": strat_ret, "end_val": end_val,
                    "bench_ret": bench_ret, "bench_end_val": bench_end_val, **rc})
    return rows


def regime_rows(dense_curve: pd.Series, mkt_state: pd.Series) -> dict:
    """不分年，全期依市況分桶累積報酬（HANDOFF §0-4(b)）：每天的策略報酬
    （淨值日變動率）按當天市況分進三桶，各自複利。"""
    ret = dense_curve.pct_change()
    out = {}
    for k in ("bull", "bear", "chop"):
        mask = (mkt_state.reindex(ret.index) == k)
        sub = ret[mask].dropna()
        if len(sub):
            out[k] = {"cum": float((1 + sub).prod() - 1.0), "n": int(len(sub))}
        else:
            out[k] = {"cum": None, "n": 0}
    return out


# ─────────────────────────── 1. 長波段候選池（訊號全買，next_open） ───────────────────────────

def run_longswing(universe: set[str]) -> tuple[pd.Series, dict]:
    """沿用 `research/backtest_longswing.py` 已經做好的 next_open + notbear 市況閘門
    + 移動 ATR 停損那一格——那正是 production `candidate_pool.py::market_regime_ok`
    （只排除空頭週）與 `swing_stops.py`（移動 ATR 停損）現在實際用的口徑，所以挑它
    當「固定一組規則」的代表，不是另外挑一個實驗格。只把時間範圍截到 2026-08。"""
    sys.path.insert(0, str(REPO / "research"))
    import backtest_longswing as ls  # noqa: E402

    qf, rev, chips, uni_bundle, daily, idx_close = ls.load_all()
    daily = daily[daily["date"] <= END].copy()
    idx_close = idx_close[idx_close.index <= END]
    panels = ls.build_panels(daily, idx_close)
    td = panels["close"].index
    weeks = ls.weekly_dates(td)
    weeks = weeks[weeks <= td.max()]

    rev_st = ls.revenue_state(rev, weeks)
    inst20 = ls.inst_state(chips, weeks)
    eps_neg = ls.eps_yoy_negative_state(qf, weeks)
    cand_by_week = ls.weekly_candidates(qf, rev_st, inst20, panels, weeks, uni_bundle)

    idx_close_full = idx_close.reindex(td).ffill()
    week_regime = ls.regime_at(pd.Series(weeks), idx_close_full)
    week_regime.index = weeks
    week_regime = week_regime.where(week_regime.notna(), None)
    cand_by_week_notbear = {wk: (s if week_regime.get(wk) != "bear" else set())
                            for wk, s in cand_by_week.items()}

    trades, n_abandoned = ls.simulate("next_open", weeks, cand_by_week_notbear, panels,
                                      rev_st, eps_neg, td, trailing=True,
                                      trail_mult_by_week=None)
    curve = ls.portfolio_curve(trades, panels["close"], td)
    completed = [t for t in trades if not t["still_open"]]
    meta = {"n_trades": len(completed), "n_open": len(trades) - len(completed),
           "n_abandoned": n_abandoned, "n_weeks": len(weeks)}
    return curve, meta


# ─────────────────────────── 2. 價值因子指數（訊號全買，next_open） ───────────────────────────

def run_value(universe: set[str]) -> tuple[pd.Series, dict]:
    """`research/backtest_value.py` 的「全買」對照組（N=∞），改買得到口徑：
    換股日 d0 算出的候選，於 d0 之後第一個交易日**開盤**買進；同一批持股持有到
    d1 之後第一個交易日開盤才換手（下一期的訊號同樣要等次日開盤才買得到，
    所以「賣出」也對齊到同一個時間點——這是對稱處理，不是額外優惠）。"""
    from twswing.data import store  # noqa: E402
    from factors.factors import quarterly_factors  # noqa: E402
    from reference.loader import load_quarterly  # noqa: E402
    from screener.screen import screen_value  # noqa: E402

    q = load_quarterly()
    qf = quarterly_factors(q)
    px = store.read_daily(recent=False, columns=["date", "ticker", "open", "close"])
    px["ticker"] = bare(px["ticker"])
    px = px[px["date"] <= END]
    close = px.pivot_table(index="date", columns="ticker", values="close").sort_index()
    openp = px.pivot_table(index="date", columns="ticker", values="open").sort_index()

    def prices_asof(asof):
        row = close.loc[close.index[close.index <= asof][-1]]
        p = pd.DataFrame({"close": row})
        p.index.name = "ticker"
        return p.reset_index()

    def pick_value(asof):
        scr = screen_value(qf, prices=prices_asof(asof), asof=asof)
        scr = scr[scr["ticker"].isin(universe)]
        ok = scr[scr["passes"]].sort_values("value_score", ascending=False)
        return ok["ticker"].tolist(), len(ok)

    def next_open_date(d):
        nxt = close.index[close.index > d]
        return nxt[0] if len(nxt) else None

    idx = close.index
    dates = []
    for y in range(2016, END.year + 1):
        for m in (3, 6, 9, 12):
            d = pd.Timestamp(y, m, 15)
            nxt = idx[idx >= d]
            if len(nxt):
                dates.append(nxt[0])
    dates = [d for d in dates if d <= idx.max()]

    rows, prev = [], set()
    eq = 1.0
    curve_pts = []
    for d0, d1 in zip(dates[:-1], dates[1:]):
        cands, n_ok = pick_value(d0)
        held = cands  # 全買：過硬門檻的候選全數等權買進，不排名、不截 N
        e0, e1 = next_open_date(d0), next_open_date(d1)
        if e0 is None or e1 is None:
            continue
        if not curve_pts:
            curve_pts.append((e0, 1.0))
        cols = [t for t in held if t in openp.columns]
        if cols:
            a = openp.loc[e0].reindex(cols)
            b = openp.loc[e1].reindex(cols)
            r = (b / a - 1.0).dropna()
            gross = r.mean() if len(r) else np.nan
        else:
            gross = np.nan
        h = set(held)
        adds, drops = len(h - prev), len(prev - h)
        cost = (COST_ACTUAL / 2) * (adds + drops) / max(1, len(held)) if held else 0.0
        net = (gross - cost) if pd.notna(gross) else np.nan
        if pd.notna(net):
            eq *= (1 + net)
        curve_pts.append((e1, eq))
        rows.append({"date": d0, "entry_date": e0, "n_candidates": n_ok,
                     "n_held": len(held), "gross": gross, "net": net})
        prev = h

    curve = pd.Series(dict(curve_pts)).sort_index()
    df = pd.DataFrame(rows)
    meta = {"n_periods": len(df), "med_cand": df["n_candidates"].median() if len(df) else np.nan,
           "blank": (df["n_candidates"] == 0).mean() if len(df) else np.nan}
    return curve, meta


# ─────────────────────────── 3. tw-swing 14 條規則（重新套用 tw-hold universe + next_open） ───

#: 家族去重、篩 >10% 絕對年化後留下的候選（見附錄方法論）。
#: 數字＝來源 `tw-swing/data/scan/backtest_all_nextopen.md`〈組合模擬〉部位上限 8
#: 那一列的年化（tw-swing 自己全市場、全歷史、next_open 口徑），**只用來排序/篩選
#: 候選**——這份報告裡實際採用的績效，是下面重新在 tw-hold universe/時間範圍下
#: 用同一批事件（`events_all.parquet`）＋ `entry_at="next_open"` 跑出來的數字。
TWSWING_CANDIDATES = [
    ("W4", "月營收動能突破半年高", 21.62),
    ("H2", "三日兩缺口", 20.96),
    ("W5", "法人籌碼波段 + 估值未過熱", 20.13),
    ("V4", "上升三角形突破（水平壓力 + 墊高低點）", 17.49),
    ("G3", "海龜 55 日突破", 13.89),
    ("W6", "月營收創年高 + 估值便宜", 13.66),
    ("P1", "營收成長加速循環", 13.11),
    ("P3", "GARP 估值修復", 13.02),
    ("W3", "三日兩缺口 + 估值未過熱確認", 11.73),
    ("J1", "雙重底（W底）頸線突破", 11.35),
    ("D7", "極度量縮後成交量梯形遞增", 11.26),
    ("Y4-plow20", "Y4 出場變體·收盤跌破前20日低（Y4 家族最佳版）", 11.03),
    ("B2", "投信連續買超", 10.96),
    ("Y1", "上升軌道突破 + 月營收年增加速確認（移動停損出場）", 10.88),
]


def run_swing_rules(universe: set[str], candidates: list[tuple] | None = None):
    """借 tw-swing 自己的事件檔 + 回測引擎，只換 universe/日期範圍/進場口徑。

    `candidates`：預設 `TWSWING_CANDIDATES`（原始 14 條）；傳別的清單（例如
    `docs/RULE_LEDGER.md` 篩出來、值得用資金約束模型重測的「復活候選」）就
    改跑那一批，格式跟 `TWSWING_CANDIDATES` 一樣是 `(rule_id, name, 原始年化)`
    的 tuple list。"""
    from twswing.backtest import engine as bt  # noqa: E402
    from twswing.backtest import columns as bcols  # noqa: E402
    from twswing.data import store  # noqa: E402
    from twswing.rules.registry import load_rulebook  # noqa: E402

    candidates = candidates if candidates is not None else TWSWING_CANDIDATES
    rulebook = load_rulebook()
    ids = [rid for rid, _, _ in candidates]
    specs = {rid: rulebook.specs[rid] for rid in ids}

    ev_path = TWSWING / "data" / "scan" / "events_all.parquet"
    events = pd.read_parquet(ev_path)
    events = events[events["rule_id"].isin(ids)].copy()
    events["bare"] = bare(events["ticker"])
    events = events[events["bare"].isin(universe)]
    events = events[(events["date"] >= START) & (events["date"] <= END)]
    events = events.drop(columns=["bare"])
    n_events_by_rule = events["rule_id"].value_counts().to_dict()

    plans = {rid: bt.ExitPlan.from_yaml(sp.exit, {"A": 10, "B": 60}.get(sp.line, 10))
            for rid, sp in specs.items() if sp.exit}
    need_cols = sorted({c for pl in plans.values() for c in pl.needs})

    daily = store.read_daily(recent=False, columns=["date", "ticker", "open", "high", "low", "close"])
    daily["bare"] = bare(daily["ticker"])
    daily = daily[daily["bare"].isin(universe) | (daily["ticker"] == "0050.TW")]
    daily = daily.drop(columns=["bare"])

    inst_df = revenue_df = per_df = None
    if need_cols:
        fund_needed = bcols._FUNDAMENTAL_FIELD_EXIT_COLS & set(need_cols)
        if fund_needed:
            if {"inst_20d_net", "inst_slope_20d"} & fund_needed:
                inst_df = pd.read_parquet(store.STORE_DIR / "inst.parquet",
                                          columns=["date", "ticker", "trust_net", "foreign_net"]
                                          ).dropna(subset=["ticker"])
            if any(c.startswith("revenue_") for c in fund_needed) or "pe_percentile" in fund_needed:
                from twswing.data import fundamentals as fd  # noqa: E402
                if any(c.startswith("revenue_") for c in fund_needed):
                    revenue_df = fd.load_revenue_features()
                if "pe_percentile" in fund_needed:
                    per_df = fd.load_per_features()
        daily = bcols.attach(daily, need_cols, inst=inst_df, revenue=revenue_df, per=per_df)

    close_pivot = daily.pivot_table(index="date", columns="ticker", values="close").sort_index()
    td = close_pivot.index

    bars = bt.Bars.build(daily, extra_cols=tuple(need_cols))
    max_hold = {"A": 10, "B": 60}

    results = {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        for rid in ids:
            g = events[events["rule_id"] == rid]
            trades = bt.simulate_trades(g, bars, max_hold=max_hold, entry_at="next_open",
                                        exits=plans)
            curve = dynamic_equal_weight_curve(trades, close_pivot, td, COST_ACTUAL)
            results[rid] = {"trades": trades, "curve": curve,
                           "n_events": int(n_events_by_rule.get(rid, 0))}
    return results, specs


def dynamic_equal_weight_curve(trades: pd.DataFrame, close_pivot: pd.DataFrame,
                               td: pd.DatetimeIndex, cost: float) -> pd.Series:
    """「訊號全買、等權」的組合權益曲線——**不是** `twswing.backtest.engine.portfolio_sim`
    的固定 N 格模型（那支的 `sizing="equal"` 是 `1/max_positions`，拿一個超大
    `max_positions` 去模擬「不設上限」會把每筆權重除成趨近於 0，是這支腳本第一版
    的 bug）。改成跟 `research/backtest_longswing.py::portfolio_curve` 完全同一套邏輯：
    每天的策略報酬＝當天所有還持有部位的簡單平均（真正的動態等權，權重＝
    1/當天實際持倉數，不是 1/某個固定上限），成本在出場當天扣一次。"""
    daily_ret = pd.Series(0.0, index=td)
    daily_cnt = pd.Series(0, index=td)
    for t in trades.itertuples():
        tk = t.ticker
        if tk not in close_pivot.columns:
            continue
        i0 = td.searchsorted(t.entry_date)
        i1 = td.searchsorted(t.exit_date)
        if i1 < i0:
            continue
        px = close_pivot[tk]
        for i in range(i0, i1 + 1):
            prev_px = t.entry_px if i == i0 else px.iloc[i - 1]
            cur_px = t.exit_px if i == i1 else px.iloc[i]
            if pd.isna(prev_px) or pd.isna(cur_px) or prev_px == 0:
                continue
            r = cur_px / prev_px - 1.0
            if i == i1:
                r = (1 + r) * (1 - cost) - 1.0
            daily_ret.iloc[i] += r
            daily_cnt.iloc[i] += 1
    avg_ret = (daily_ret / daily_cnt.replace(0, np.nan)).fillna(0.0)
    return (1 + avg_ret).cumprod()


def curve_stats(curve: pd.Series) -> dict:
    if len(curve) < 2:
        return {"cagr": np.nan, "maxdd": np.nan, "mar": np.nan}
    yrs = (curve.index[-1] - curve.index[0]).days / 365.25
    cagr = float(curve.iloc[-1] ** (1 / yrs) - 1.0) if yrs > 0 else np.nan
    dd = float((curve / curve.cummax() - 1).min())
    mar = (cagr / abs(dd)) if (dd < 0 and np.isfinite(cagr)) else np.nan
    return {"cagr": cagr, "maxdd": dd, "mar": mar}


# ─────────────────────────── 報告組裝 ───────────────────────────

def _md_table(rows: list[list], header: list[str]) -> str:
    for i, r in enumerate(rows):
        if len(r) != len(header):
            raise ValueError(f"第 {i+1} 列 {len(r)} 格，表頭 {len(header)} 欄：{r!r}")
    out = ["| " + " | ".join(header) + " |",
          "| " + " | ".join([":--"] + ["--:"] * (len(header) - 1)) + " |"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def _fmt_pct(v):
    return f"{v:+.1%}" if v is not None and pd.notna(v) else "—"


def section_for(label: str, curve: pd.Series, calendar: pd.DatetimeIndex,
               bench_close: pd.Series, mkt_state: pd.Series, years: list[int],
               extra_note: str = "", capital_wan: float | None = None) -> list[str]:
    """`capital_wan`：本金（單位：萬元）。只有情境 B 這種有真實資金基準的 curve
    才傳這個參數——傳了就會在年切表多一欄「年末價值(萬)」（curve 的年末值 ×
    本金，不是報酬率，是實際帳戶水位）；原本「訊號全買、無邊際」的抽象指數
    curve 沒有真實資金基準，不傳這個參數，維持舊版只看報酬率的表格。"""
    dense = curve_to_dense(curve, calendar)
    bench_dense = None
    if capital_wan is not None:
        valid = dense.dropna()
        if len(valid):
            start_date = valid.index[0]
            base_seg = bench_close.loc[bench_close.index <= start_date]
            base_price = float(base_seg.iloc[-1]) if len(base_seg) else float(bench_close.iloc[0])
            bench_dense = (bench_close / base_price).reindex(calendar)
    md = [f"## {label}", ""]
    if extra_note:
        md += [extra_note, ""]

    # (a) 按年切
    note_suffix = (f"（含年末實際帳戶價值，本金 {capital_wan:.0f} 萬；0050 那欄是"
                   f"「同一天把 {capital_wan:.0f} 萬全部改買 0050」的對照組年末值）"
                   if capital_wan is not None else "")
    md += ["### (a) 按年切", "", f"策略當年報酬 vs 0050 當年報酬 vs 當年 MA60 多/空/震盪天數比率{note_suffix}：", ""]
    header = ["年", "策略", "0050"]
    if capital_wan is not None:
        header = ["年", "策略", "年末價值(萬)", "0050", "0050年末價值(萬)"]
    header += ["多頭天數%", "空頭天數%", "盤整天數%"]
    rows = []
    for r in year_rows(dense, bench_close, mkt_state, years, bench_dense=bench_dense):
        row = [str(r["year"]), _fmt_pct(r["strat_ret"])]
        if capital_wan is not None:
            ev = r["end_val"]
            row.append(f"{ev * capital_wan:,.1f}" if ev is not None else "—")
        row.append(_fmt_pct(r["bench_ret"]))
        if capital_wan is not None:
            bev = r["bench_end_val"]
            row.append(f"{bev * capital_wan:,.1f}" if bev is not None else "—")
        row += [f"{r['bull']:.0%}" if r["n"] else "—",
               f"{r['bear']:.0%}" if r["n"] else "—",
               f"{r['chop']:.0%}" if r["n"] else "—"]
        rows.append(row)
    md.append(_md_table(rows, header))
    md.append("")

    # (b) 按市況切（不分年）
    md += ["### (b) 按市況切（不分年，2016/01–2026/08 全期）", ""]
    rr = regime_rows(dense, mkt_state)
    rows2 = [[{"bull": "多頭", "bear": "空頭", "chop": "盤整"}[k],
             _fmt_pct(rr[k]["cum"]), f"{rr[k]['n']:,}"] for k in ("bull", "bear", "chop")]
    md.append(_md_table(rows2, ["市況", "累積報酬", "交易日數"]))
    md.append("")
    return md


def main() -> int:
    print("載入 universe / 0050 市況分類…", flush=True)
    universe = load_universe()
    print(f"  universe {len(universe)} 檔", flush=True)
    close0050 = load_0050_close()
    mkt_state = ma_verdict_series(close0050)
    calendar = close0050.loc[(close0050.index >= START) & (close0050.index <= END)].index
    years = list(range(START.year, END.year + 1))

    lines: list[str] = []
    def w(*xs: str) -> None:
        if not xs:
            lines.append("")
        else:
            lines.extend(xs)

    w(f"# 17 條規則買得到口徑重新回測（年切 vs 市況切）")
    w()
    w(f"- 產出：{pd.Timestamp.now():%Y-%m-%d %H:%M}")
    w(f"- 期間：{START.date()} → {END.date()}｜universe：{len(universe)} 檔"
      "（bundle `universe.parquet` `in_universe`，市值前500∪成交值前500）")
    w("- 買得到口徑：訊號/換股日**次一交易日開盤**才成交（不是當天收盤）")
    w(f"- 成本：{COST_ACTUAL:.3%}（來回，台股實際口徑，全 repo 沿用同一個數字）")
    w(f"- 市況分類：`reference/market_status.py::ma_verdict(close, window={MS_WINDOW})`"
      f"（乖離 ±{MS_BAND:.0%} 分多/空/盤整）對 0050 收盤序列逐日跑")
    w("- 🔴 生存者偏差：universe 用今天的 in_universe 回溯 2016，所有數字當上界")
    w("- 🔴 跨 repo 口徑不同：tw-swing 14 條與 tw-hold 長波段/價值線不是同一套程式碼/"
      "資料源，**不能放進同一張表直接比較數字**，本報告刻意分節呈現")
    w()

    # ── 1. 長波段 ──
    print("跑長波段（候選池，next_open + notbear + 移動ATR停損）…", flush=True)
    ls_curve, ls_meta = run_longswing(universe)
    w(*section_for(
        "1. 長波段候選池（CANSLIM ∩ 趨勢模板 ∩ 市況門檻，訊號全買）",
        ls_curve, calendar, close0050, mkt_state, years,
        extra_note=(f"- 沿用 `research/backtest_longswing.py` 的 `next_open` + `notbear` 市況閘門"
                   f" + 移動 ATR 停損那一格（production `candidate_pool.py::market_regime_ok` "
                   f"與 `swing_stops.py` 現行口徑一致）。完成交易 {ls_meta['n_trades']:,} 筆"
                   f"（另有 {ls_meta['n_open']} 筆回測結束仍持有、{ls_meta['n_abandoned']} 筆"
                   f"訊號成交時已跌破停損位放棄），{ls_meta['n_weeks']:,} 週。")))
    w()

    # ── 2. 價值線 ──
    print("跑價值線（screen_value，next_open 全買）…", flush=True)
    val_curve, val_meta = run_value(universe)
    w(*section_for(
        "2. 價值因子指數（screen_value 過硬門檻，訊號全買 N=∞）",
        val_curve, calendar, close0050, mkt_state, years,
        extra_note=(f"- 季中換股（3/6/9/12 月 15 日起最近交易日），{val_meta['n_periods']} 期，"
                   f"每期候選中位數 {val_meta['med_cand']:.0f} 檔、空白期 {val_meta['blank']:.0%}。"
                   "換股日、次一交易日開盤買進；下一期換股同樣次日開盤才轉換，"
                   "等於「買進」與「換手」用同一個買得到時間點，對稱處理。")))
    w()

    # ── 3. tw-swing 14 條 ──
    print("跑 tw-swing 14 條規則（events_all.parquet 過濾 universe/日期，next_open）…", flush=True)
    sw_results, sw_specs = run_swing_rules(universe)
    w("## 3. tw-swing 精選規則（家族去重後 14 條，見附錄篩選記錄）", "")
    w("> ⚠️ 目標湊 15 條，家族去重＋>10% 絕對年化篩選後只湊到 **14 條**——誠實限制，")
    w("> 不硬湊第 15 條（見文末〈已知限制〉）。")
    w()
    for rid, name, src_cagr in TWSWING_CANDIDATES:
        res = sw_results[rid]
        trades = res["trades"]
        n_ev = res["n_events"]
        n_fill = len(trades)
        if not n_fill:
            w(f"### {rid} · {name}", "",
              f"tw-hold universe/期間內過濾後**沒有任何一筆訊號成交**"
              f"（事件檔內原有 {n_ev} 個訊號）——規則本身可能依賴的標的多半不在"
              "tw-hold 前500大∪成交值前500 universe 內。跳過年切/市況切呈現。", "")
            continue
        curve = res["curve"]
        st = curve_stats(curve)
        note = (f"- tw-swing 原始（全市場/全歷史/next_open）年化 **{src_cagr:+.2f}%**"
               f"（來源：`tw-swing/data/scan/backtest_all_nextopen.md`）僅供篩選排序參考。"
               f"tw-hold universe/{START.date()}–{END.date()} 範圍內：{n_ev} 個訊號、"
               f"{n_fill:,} 筆實際成交（{n_fill / n_ev:.0%}），"
               f"全期年化 **{st['cagr']:+.2%}**、最大回撤 {st['maxdd']:.1%}、"
               f"MAR {st['mar']:.2f}（動態等權——權重＝1/當天實際持倉數，訊號全買精神，"
               "不是固定部位上限模型）。")
        w(*section_for(f"3.{TWSWING_CANDIDATES.index((rid, name, src_cagr)) + 1} {rid} · {name}",
                       curve, calendar, close0050, mkt_state, years, extra_note=note))
        w()

    # ── 附錄 ──
    w("## 附錄：15 條 tw-swing 規則篩選記錄（實際湊到 14 條）")
    w()
    w("來源：`tw-swing/data/scan/backtest_all_nextopen.md` 的〈組合模擬〉表（部位上限 8、"
      "`entry_at=next_open`，涵蓋 `rules.yaml` 全部 110 條已實作規則，全市場/全歷史）——")
    w("這張表本身就是「每條規則單獨測試過的絕對年化報酬」，比從 `RULE_LEDGER.md`/`STATUS.md`")
    w("散落的敘述句裡人工摘錄更不容易漏抓或抄錯數字，且口徑（`next_open`）與本次任務要求")
    w("的買得到原則一致。篩選規則：")
    w()
    w("1. 從全部 110 條已實作規則中，取「部位上限 8」列的年化報酬 > 10%。")
    w("2. **同家族只取最佳版本**——家族認定標準是「規則核心邏輯／代號字首是否相同」")
    w("   （`entry_from:` 有明確委派關係的算同家族，如 Y4/Y4-plow10/Y4-plow20/Y4-tgt3r；")
    w("   或 rules.yaml 裡本來就是「A 出場變體」的命名，如 H2/H2-trailatr2）——**不是**")
    w("   `rules.yaml` 的 `family:` 分類欄（那個欄位是機制大類，例如「型態反轉」底下有")
    w("   J1-J7、V4、D3、H3 等多條互不相干的規則，字面相同不代表同家族）。")
    w("3. 邊界案例：**W3**（三日兩缺口＋估值未過熱確認）跟 **H2**（三日兩缺口）共用同一個")
    w("   進場型態、只是多疊一道估值閘門，但 `rules.yaml` 沒有把 W3 宣告成 H2 的")
    w("   `entry_from` 變體（W3 是獨立的積木宣告），兩者也各自單獨回測、單獨過關過。")
    w("   這裡從寬認定為兩條不同規則——都留著，並在這裡註記讓使用者事後核對。")
    w("4. **U1**（`rules.yaml` 明載「A3 的宣告式積木自我測試複本」）與 U2（G7 的複本）")
    w("   直接排除，不當獨立候選——數字與 A3/G7 逐筆相同，是工程測試複本不是新規則。")
    w()
    rows = []
    fam_note = {"H2-trailatr2": "H2 家族（entry_from=H2），H2 本尊 20.96% 更高，取 H2",
               "P4": "P3 家族，P3 13.02% 更高，取 P3", "Y4-plow10": "Y4 家族，Y4-plow20 更高",
               "Y4": "Y4 家族（本尊 9.00%，未達10%門檻，家族最佳版是 Y4-plow20 11.03%）"}
    for rid, name, cagr in TWSWING_CANDIDATES:
        rows.append([rid, name, f"{cagr:+.2f}%", "採用"])
    w(_md_table(rows, ["規則", "名稱", "絕對年化（tw-swing 原始/next_open/部位上限8）", "結果"]))
    w()
    w("同家族但未採用（因非該家族最佳版本，未計入 14 條或 15 條名額）：")
    w()
    w("- H2-trailatr2（+16.88%，H2 家族，H2 本尊更高）")
    w("- P4（+10.93%，P3 家族，P3 本尊更高）")
    w("- Y4-plow10（+10.72%）、Y4 本尊（+9.00%，未達 10% 門檻）——皆屬 Y4 家族，"
      "家族最佳版是 Y4-plow20（+11.03%）")
    w()
    w("**已知限制（誠實記錄，非文件原先預期）**：家族去重＋>10% 篩選後，distinct 家族")
    w("只有 14 個達標，湊不滿 15。逐一核對過 `docs/RULE_LEDGER.md`／`docs/STATUS.md` 附近")
    w("提到的其餘規則（M1 +9.70%、P6 +9.48%、W1 +9.20%、Y4 本尊 +9.00%……）在這張")
    w("`--all --entry-at next_open` 全規則掃描表裡都低於 10% 門檻，沒有找到被這張表漏掉、")
    w("但個別報告裡有更高數字的規則——**不硬湊第 15 條、不放寬篩選標準**。")
    w()

    w("## 方法論總覽")
    w()
    w("- **買得到口徑**：訊號/換股日次一交易日開盤成交（不是當天收盤）。長波段/價值線"
      "沿用 `swing_stops.py`／`research/backtest_longswing.py` 的既有 `next_open` 實作；"
      "tw-swing 14 條規則用 `twswing.backtest.engine.simulate_trades(entry_at=\"next_open\")`。")
    w("- **universe**：bundle `universe.parquet` 的 `in_universe`"
      f"（市值前500∪成交值前500，今天的口徑回溯 {START.year}–{END.year}）。")
    w(f"- **時間範圍**：{START.date()} → {END.date()}。")
    w(f"- **成本**：{COST_ACTUAL:.3%}（來回），全 17 條一致。")
    w("- **持倉建構**：三條線一律「訊號全買、動態等權」——過門檻的候選/觸發的訊號全數"
      "買進，權重＝1/當天實際持倉數（不是固定 N 格），不排名、不設部位上限。長波段/"
      "價值線沿用既有 `backtest_longswing.py::portfolio_curve` 那套逐日平均報酬算法；"
      "tw-swing 14 條規則用同一套邏輯重新實作（`dynamic_equal_weight_curve()`），"
      "**沒有用** `twswing.backtest.engine.portfolio_sim`——那支的 `sizing=\"equal\"` "
      "是「固定 N 格、權重＝1/N」的線上配置模型，拿一個很大的 `max_positions` 去逼近"
      "「不設上限」會把每筆權重除成趨近於 0（本腳本第一版就是這樣寫、算出全部年化"
      "趨近 0% 才發現），跟長波段/價值線的「訊號全買」精神對不起來，所以另外寫"
      "動態等權（跟長波段同一套算法）取代。「訊號全買」原文只寫給長波段/價值線，"
      "延伸套用到 tw-swing 14 條是本報告的方法一致化決定，於此明記。")
    w("- **市況分類**：`ma_verdict(close, window=60)`，乖離 ±2% 分多/空/盤整，對 0050"
      "收盤序列逐日算（不是 `reference/regime.py` 的三態分期——長波段候選池的市況"
      "**閘門**〔notbear〕仍用 `regime.py`，production 邏輯不變；`ma_verdict` 只用在"
      "本報告的分年/分市況**呈現**層，兩者是不同用途，刻意不混用）。")
    w()
    w("## 已知限制")
    w()
    w("- 🔴 **生存者偏差**：universe 是今天的 `in_universe`，拿它回溯 2016 等於已知誰活到")
    w("  今天，所有數字都是上界，真實結果會更差（下市、重大衰退的公司回測期間看不到）。")
    w("- 🔴 **跨 repo 口徑不可比**：tw-swing 14 條規則的資料源、universe 定義原本跟")
    w("  tw-hold 不是同一套（tw-swing 原生是全市場流動性分層，這裡重新在 tw-hold universe/")
    w("  期間下用同一批事件重跑）；長波段/價值線是 tw-hold 自己的規則邏輯。三組數字**不放")
    w("  進同一張表比較**，本報告刻意分節。")
    w("- tw-swing 14 條規則的「訊號全買、無部位上限」是本報告的延伸決定，不是 tw-swing")
    w("  自己的線上配置（tw-swing 實際上線用部位上限 8、依風險％配置）——這裡刻意跟長波段/")
    w("  價值線的「訊號全買」精神對齊，數字因此會比 tw-swing 自己的『組合模擬』報告更激進")
    w("  （沒有部位排擠）。")
    w("- 家族去重＋>10% 篩選只湊到 14 條（見附錄），不硬湊第 15 條。")
    w("- 15 條篩選數字（`backtest_all_nextopen.md`）用的是 tw-swing 自己全市場/全歷史的"
      "next_open 回測，本報告 3 節裡實際採用的是「同一批事件、tw-hold universe/期間"
      "重新過濾」跑出來的數字——兩者不會一樣，篩選數字只用來排序候選、不是最終結論。")
    w("- 部分規則（尤其依賴籌碼/估值資料的 W5/W6/P3/P1/Y4-plow20）過濾到 tw-hold universe")
    w("  後樣本可能明顯縮水（原本全市場上千筆訊號，縮到只剩 universe 內前段班個股），")
    w("  年切/市況切的某些格可能樣本極小甚至掛零，解讀時要看樣本數不能只看報酬%。")
    w("- 價值線/長波段的換股頻率（季頻/週頻）與 tw-swing 規則（事件驅動、不定期觸發）")
    w("  本質不同，「訊號全買」在兩邊的實際持股數與換手率差異很大，這不是bug，是策略")
    w("  設計本身的差異。")
    w()

    out_md = OUT / "backtest_top17_buyable_2026-09-22.md"
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n-> {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
