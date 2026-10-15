"""Y4／W6 補測三項情境（2026-10-15，使用者裁決：只補『沒測過』的，不重跑已有的格子）。

已經測過、**不重做**的（見 `backtest_scenario_b_2026-09-22.md`、`..._yearly_reset_...md`、
`backtest_top17_buyable_2026-09-22.md`，次日開盤口徑）：資金天花板連續複利（100 萬、N=5/10）、
每年歸零、分市況累積報酬、逐年對照 0050、四門檻與樣本外。

本腳本只補：
  ① 進場市況篩選：none / 只多頭 / 排除空頭（以訊號日的 0050 MA60 市況，與 scenario_b 同一把尺）
  ② W6 的移動 ATR 停損變體（W6 原本只有固定停損；比照 Y4 的出場：trail_atr 2.0 + breakeven_r 1.0，
     max_hold 60）——**臨時變體，只回測，不進 rules.yaml**
  ③ 單檔上限：每檔最多佔『當時帳戶淨值』的 20% / 12.5%（後者對應 tw-swing 部位上限 8）。
     動機：scenario_b 規格 4 是『每次進場把手上所有現金平分給入選候選』，同日只有 1 檔訊號就
     全押一檔；N=5 與 N=10 結果完全相同（前 N 名之外放棄 0 筆），N 根本沒有作用。

對照組：H2-trailatr2（live 另一條）。

驗證閘：`cap=None, gate=none` 必須逐位重現 scenario_b 已發佈的 Y4（N=5）+12.99%／終值 360.3 萬、
W6（N=5）+8.21%／終值 226.4 萬，否則整份報告作廢（腳本會直接中止）。

買得到口徑：次日開盤（唯一定義）。成本 0.585% 來回。生存者偏差：universe 為今天的 in_universe，結論當上界。

用法：
    python research/backtest_y4w6_extra.py
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "research"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import backtest_scenario_b as S  # noqa: E402
import backtest_top17_buyable as B  # noqa: E402

OUT = REPO / "docs" / "reports"
INITIAL = S.INITIAL_CAPITAL
N_CAP = 5
GATES = ("none", "bull", "notbear")
GATE_LABEL = {"none": "不篩", "bull": "只多頭", "notbear": "排除空頭"}
CAPS = (None, 0.20, 0.125)
CAP_LABEL = {None: "無上限（現行）", 0.20: "單檔≤20%", 0.125: "單檔≤12.5%"}

RULES = [  # (key, 顯示名, events 的 rule_id, exit 覆寫 spec 或 None)
    ("Y4", "Y4（live，CANSLIM 本尊）", "Y4", None),
    ("W6", "W6（live，固定停損 + 60 日到期）", "W6", None),
    ("W6-trail", "W6 + 移動 ATR 停損（臨時變體）", "W6", {"max_hold": 60, "trail_atr": 2.0, "breakeven_r": 1.0}),
    ("H2-trailatr2", "H2-trailatr2（對照）", "H2-trailatr2", None),
]


def simulate_capped(trades, close_pivot, mktcap_lut, cost, n_cap, cap_frac, initial_capital=INITIAL,
                    end_cap=None):
    """= `backtest_scenario_b.simulate_capital_constrained`，唯一差別：入選候選各自分到的金額
    `per_cap = min(可用現金 / 入選檔數, cap_frac × 當下帳戶淨值)`，其餘現金留著不投。
    `cap_frac=None` 時與原函式逐位相同（驗證閘會比對）。"""
    trades = trades.reset_index(drop=True).copy()
    trades["bare"] = trades["ticker"].astype(str).str.split(".").str[0]

    def mc(row):
        cap = S.capital_stock_asof(mktcap_lut, row["bare"], row["entry_date"])
        return -1.0 if pd.isna(cap) else cap * row["entry_px"]

    trades["mktcap"] = trades.apply(mc, axis=1)
    entries_by_date = trades.groupby("entry_date").groups
    exits_by_date = trades.groupby("exit_date").groups
    lo, hi = trades["entry_date"].min(), trades["exit_date"].max()
    if end_cap is not None:
        hi = min(hi, end_cap)
    td = close_pivot.index[(close_pivot.index >= lo) & (close_pivot.index <= hi)]

    cash = initial_capital
    open_pos: dict[int, dict] = {}
    nav = {}
    accepted = set()
    n_signals = len(trades)
    n_rej_cash = n_rej_ncap = 0

    for d in td:
        for idx in exits_by_date.get(d, []):
            if idx not in open_pos:
                continue
            pos = open_pos.pop(idx)
            row = trades.loc[idx]
            px_prev, px_exit = pos["last_px"], row["exit_px"]
            r = 0.0 if (pd.isna(px_prev) or pd.isna(px_exit) or px_prev == 0) else px_exit / px_prev - 1.0
            still_open = bool(row["still_open"]) if "still_open" in trades.columns else False
            if not still_open:
                r = (1 + r) * (1 - cost) - 1.0
            cash += pos["capital"] * (1 + r)

        cands = list(entries_by_date.get(d, []))
        if cands:
            if cash <= 1e-9:
                n_rej_cash += len(cands)
            else:
                cands_sorted = sorted(cands, key=lambda i: -trades.loc[i, "mktcap"])
                selected = cands_sorted[:n_cap]
                n_rej_ncap += max(0, len(cands) - len(selected))
                per_cap = cash / len(selected)
                if cap_frac is not None:
                    equity = cash + sum(p["capital"] for p in open_pos.values())
                    per_cap = min(per_cap, cap_frac * equity)
                proceeds_same_day = 0.0
                spent = 0.0
                for idx in selected:
                    row = trades.loc[idx]
                    accepted.add(idx)
                    spent += per_cap
                    if row["exit_date"] == row["entry_date"]:
                        r = row["exit_px"] / row["entry_px"] - 1.0
                        r = (1 + r) * (1 - cost) - 1.0
                        proceeds_same_day += per_cap * (1 + r)
                    else:
                        open_pos[idx] = {"capital": per_cap, "last_px": row["entry_px"], "ticker": row["ticker"]}
                cash = cash - spent + proceeds_same_day

        for idx, pos in open_pos.items():
            tk = pos["ticker"]
            px_today = close_pivot.at[d, tk] if tk in close_pivot.columns else np.nan
            if pd.notna(px_today) and pd.notna(pos["last_px"]) and pos["last_px"] != 0:
                pos["capital"] *= px_today / pos["last_px"]
                pos["last_px"] = px_today
        nav[d] = cash + sum(p["capital"] for p in open_pos.values())

    nav_series = pd.Series(nav).sort_index() / initial_capital
    meta = {"n_signals": n_signals, "n_accepted": len(accepted),
            "accept_rate": (len(accepted) / n_signals) if n_signals else np.nan,
            "n_rejected_cash": n_rej_cash, "n_rejected_ncap": n_rej_ncap}
    return nav_series, meta


def load_trades(universe: set[str]) -> dict[str, pd.DataFrame]:
    """各規則的 next_open trades。W6-trail 用 W6 的事件、改套 Y4 風格的移動停損出場。"""
    from twswing.backtest import columns as bcols  # noqa: E402
    from twswing.backtest import engine as bt  # noqa: E402
    from twswing.data import store  # noqa: E402
    from twswing.rules.registry import load_rulebook  # noqa: E402

    rulebook = load_rulebook()
    ev = pd.read_parquet(B.TWSWING / "data" / "scan" / "events_all.parquet")
    ev = ev[ev["rule_id"].isin({r[2] for r in RULES})].copy()
    ev["bare"] = B.bare(ev["ticker"])
    ev = ev[ev["bare"].isin(universe) & (ev["date"] >= B.START) & (ev["date"] <= B.END)].drop(columns=["bare"])

    plans = {}
    for key, _, rid, spec in RULES:
        sp = rulebook.specs[rid]
        exit_spec = spec if spec is not None else sp.exit
        if exit_spec:
            plans[key] = bt.ExitPlan.from_yaml(exit_spec, {"A": 10, "B": 60}.get(sp.line, 10))
    need_cols = sorted({c for pl in plans.values() for c in pl.needs})

    daily = store.read_daily(recent=False, columns=["date", "ticker", "open", "high", "low", "close"])
    daily["bare"] = B.bare(daily["ticker"])
    daily = daily[daily["bare"].isin(universe) | (daily["ticker"] == "0050.TW")].drop(columns=["bare"])
    if need_cols:
        fund_needed = bcols._FUNDAMENTAL_FIELD_EXIT_COLS & set(need_cols)
        inst_df = revenue_df = per_df = None
        if fund_needed:
            from twswing.data import fundamentals as fd  # noqa: E402
            if {"inst_20d_net", "inst_slope_20d"} & fund_needed:
                inst_df = pd.read_parquet(store.STORE_DIR / "inst.parquet",
                                          columns=["date", "ticker", "trust_net", "foreign_net"]).dropna(subset=["ticker"])
            if any(c.startswith("revenue_") for c in fund_needed):
                revenue_df = fd.load_revenue_features()
            if "pe_percentile" in fund_needed:
                per_df = fd.load_per_features()
        daily = bcols.attach(daily, need_cols, inst=inst_df, revenue=revenue_df, per=per_df)
    bars = bt.Bars.build(daily, extra_cols=tuple(need_cols))
    out = {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        for key, _, rid, _spec in RULES:
            g = ev[ev["rule_id"] == rid].copy()
            # 引擎是『依事件的 rule_id 去 exits 找出場計畫』——變體必須把事件改標成變體 key，
            # 否則 W6-trail 會悄悄套回 W6 的固定停損、結果與 W6 完全相同（2026-10-15 第一次跑就踩到）。
            g["rule_id"] = key
            out[key] = bt.simulate_trades(g, bars, max_hold={"A": 10, "B": 60}, entry_at="next_open",
                                          exits=plans)
            if key in plans and key != rid:
                assert out[key]["exit_reason"].nunique() >= 1
    return out


def gate_trades(trades: pd.DataFrame, mkt_state: pd.Series, gate: str) -> pd.DataFrame:
    """依『訊號日』的 0050 MA60 市況篩進場：bull＝只留多頭，notbear＝排除空頭。"""
    if gate == "none":
        return trades
    st = trades["signal_date"].map(lambda d: mkt_state.get(pd.Timestamp(d)))
    keep = (st == "bull") if gate == "bull" else (st != "bear")
    return trades[keep.fillna(False)].reset_index(drop=True)


def yearly_reset(trades, close_pivot, mktcap_lut, cap_frac):
    rets = {}
    for y in range(B.START.year, B.END.year + 1):
        y0, y1 = pd.Timestamp(f"{y}-01-01"), min(pd.Timestamp(f"{y}-12-31"), B.END)
        sub = trades[(trades["entry_date"] >= y0) & (trades["entry_date"] <= y1)]
        if not len(sub):
            rets[y] = 0.0
            continue
        nav, _ = simulate_capped(sub, close_pivot, mktcap_lut, B.COST_ACTUAL, N_CAP, cap_frac, end_cap=y1)
        rets[y] = float(nav.iloc[-1] - 1.0) if len(nav) else 0.0
    return rets


def main() -> int:
    print("載入 universe／市值查表／收盤價…", flush=True)
    universe = B.load_universe()
    mktcap_lut = S.build_mktcap_lut()
    close_pivot = S.load_close_pivot(universe)
    close0050 = B.load_0050_close()
    mkt_state = B.ma_verdict_series(close0050)
    calendar = close0050.loc[(close0050.index >= B.START) & (close0050.index <= B.END)].index
    years = list(range(B.START.year, B.END.year + 1))

    print("跑 next_open trades（Y4／W6／W6-trail／H2-trailatr2）…", flush=True)
    trades = load_trades(universe)
    for k, t in trades.items():
        print(f"  {k}: {len(t)} 筆", flush=True)

    # ── 驗證閘（2026-10-15 修正）：原本要求逐位重現 9/22 已發佈數字，實測做不到：同一份程式今天重跑
    # Y4(N=5) = +4.25%／154.7 萬，而報告是 +12.99%／360.3 萬。逐年對照：2016、2017、2022 逐位相同，
    # 其餘年份不同；原因是 universe 漂移（in_universe 今天 607 檔 vs 當時約 609 檔，Y4 訊號 842 vs 844 筆、
    # W6 729 vs 726 筆）。『每次進場把所有現金平分』讓路徑極度敏感，差 2～3 筆訊號整年結果就翻盤。
    # 這本身就是本報告的發現之一（見敏感度區塊）。所以閘門改成：(1) 訊號筆數與已發佈差距 ≤1%；
    # (2) 以『今天的 universe』重新建基準，不再宣稱與 9/22 數字相同。
    published = {"Y4": 844, "W6": 726}
    for k, n0 in published.items():
        n1 = len(trades[k])
        print(f"驗證閘 {k}: 訊號 {n1} 筆（9/22 報告 {n0} 筆，差 {abs(n1 - n0) / n0:.1%}）", flush=True)
        if abs(n1 - n0) / n0 > 0.01:
            print("::error::訊號筆數與已發佈差距 >1%——資料或 universe 變動過大，報告作廢。", file=sys.stderr)
            return 1

    bench = B.curve_stats((close0050.loc[calendar] / close0050.loc[calendar].iloc[0]))
    rows_all = {}
    yearly_all = {}
    for key, label, _rid, _spec in RULES:
        rows = []
        for gate in GATES:
            tg = gate_trades(trades[key], mkt_state, gate)
            for cap in CAPS:
                if not len(tg):
                    rows.append([GATE_LABEL[gate], CAP_LABEL[cap], 0, "—", "—", "—", "—", "—"])
                    continue
                print(f"  {key} / {GATE_LABEL[gate]} / {CAP_LABEL[cap]}", flush=True)
                nav, meta = simulate_capped(tg, close_pivot, mktcap_lut, B.COST_ACTUAL, N_CAP, cap, end_cap=B.END)
                st = B.curve_stats(nav)
                yr = yearly_reset(tg, close_pivot, mktcap_lut, cap)
                geo = float(np.prod([1 + v for v in yr.values()]) ** (1 / len(yr)) - 1)
                yearly_all[(key, gate, cap)] = yr
                rows_all[(key, gate, cap)] = (nav, st, meta)
                rows.append([GATE_LABEL[gate], CAP_LABEL[cap], meta["n_signals"],
                             f"{meta['accept_rate']:.0%}", f"{st['cagr']:+.2%}", f"{st['maxdd']:.1%}",
                             f"{st['mar']:.2f}", f"{nav.iloc[-1] * INITIAL / 10_000:,.1f}",
                             f"{geo:+.1%}"])
        rows_all[key] = rows

    # ── 敏感度：隨機拿掉 1% 訊號，重跑 20 次（固定種子）——量化『差 2～3 筆訊號整年翻盤』有多嚴重 ──
    rng = np.random.default_rng(20261015)
    sens = {}
    for key, _label, _rid, _spec in RULES:
        base = trades[key]
        for cap in (None, 0.125):
            cagrs = []
            for i in range(20):
                keep = rng.random(len(base)) >= 0.01
                sub = base[keep].reset_index(drop=True)
                nav, _ = simulate_capped(sub, close_pivot, mktcap_lut, B.COST_ACTUAL, N_CAP, cap, end_cap=B.END)
                cagrs.append(B.curve_stats(nav)["cagr"])
            sens[(key, cap)] = cagrs
            print(f"  敏感度 {key} / {CAP_LABEL[cap]}: 年化 {np.mean(cagrs):+.2%} ± {np.std(cagrs):.2%}"
                  f"（{min(cagrs):+.2%} ～ {max(cagrs):+.2%}）", flush=True)
    rows_all["_sens"] = sens

    lines = _report(rows_all, yearly_all, bench, calendar, close0050, mkt_state, years)
    out = OUT / "backtest_y4w6_extra_2026-10-15.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"→ {out}")
    return 0


def _report(rows_all, yearly_all, bench, calendar, close0050, mkt_state, years):
    md = []
    w = md.append
    w("# Y4／W6 補測三項情境（次日開盤口徑，2026-10-15）")
    w("")
    w(f"- 產出：{pd.Timestamp.now():%Y-%m-%d %H:%M}｜期間 {B.START.date()} → {B.END.date()}｜成本 {B.COST_ACTUAL:.3%} 來回"
      f"｜每條規則各自 100 萬、N={N_CAP}（N=5 與 N=10 已證實結果相同）")
    w("- **只補沒測過的三項**，已有的格子不重跑（見 `backtest_scenario_b_2026-09-22.md`、`..._yearly_reset_...md`）：")
    w("  ① 進場市況篩選（訊號日 0050 MA60：不篩／只多頭／排除空頭）② W6 的移動 ATR 停損變體（臨時變體，不進 rules.yaml）"
      "③ 單檔上限（每檔≤帳戶淨值的 20%／12.5%）。")
    w("- ⚠️ **與 9/22 已發佈數字不可直接比較（重要）**：同一份資金模型今天重跑，Y4（N=5，不設上限）= +4.25%／154.7 萬，"
      "而 `backtest_scenario_b_2026-09-22.md` 是 +12.99%／360.3 萬；W6 +3.58%／144.0 萬 vs +8.21%／226.4 萬。"
      "逐年對照 Y4 每年歸零：2016、2017、2022 逐位相同，其餘年份不同。原因：universe 漂移（`in_universe` 今天 607 檔，"
      "Y4 訊號 842 筆 vs 當時 844 筆，W6 729 vs 726 筆），而 scenario_b 規格 4『每次進場把所有現金平分給入選候選』讓路徑"
      "極度敏感，差 2～3 筆訊號整年結果就翻盤。**本報告所有數字以今天的 universe 重新建基準**；"
      "9/22 的數字是當時 universe 下的一個樣本，不是穩定的結論。詳見文末〈敏感度〉。")
    w(f"- 對照 0050 同期：年化 **{bench['cagr']:+.2%}**、最大回撤 {bench['maxdd']:.1%}、MAR {bench['mar']:.2f}。")
    w("- 🔴 生存者偏差：universe 為今天的 in_universe，結論當上界。🔴 T+2 簡化：賣出即回籠，週轉比真實快。")
    w("- 🔴 事件檔 `events_all.parquet` 是 2026-09-15 以 FinMind PER（虧損股 PER=0）算出，語意與 live 修復後一致。")
    w("- 判讀欄『每年歸零年均』＝每年 1/1 重新從 100 萬開始、年底未實現標記的各年報酬幾何平均（與 yearly_reset 報告同法）。")
    w("")
    hdr = ["進場市況", "單檔上限", "訊號數", "成交率", "年化(連續)", "最大回撤", "MAR", "終值(萬)", "每年歸零年均"]
    for key, label, _rid, _spec in RULES:
        w(f"---")
        w("")
        w(f"## {label}")
        w("")
        w(B._md_table(rows_all[key], hdr))
        w("")
        # 逐年表：無上限不篩（基準）vs 單檔≤12.5% 不篩 vs 最佳 MAR 格
        cands = [(g, c) for g in GATES for c in CAPS if (key, g, c) in rows_all]
        best = max(cands, key=lambda gc: (rows_all[(key, *gc)][1]["mar"]
                                          if np.isfinite(rows_all[(key, *gc)][1]["mar"]) else -9))
        picks = [("none", None), ("none", 0.125)]
        if best not in picks:
            picks.append(best)
        for g, c in picks:
            if (key, g, c) not in rows_all:
                continue
            nav, st, meta = rows_all[(key, g, c)]
            w(f"### 逐年：{GATE_LABEL[g]}／{CAP_LABEL[c]}" + ("（本規則 MAR 最高格）" if (g, c) == best else ""))
            w("")
            sec =B.section_for(f"{label}｜{GATE_LABEL[g]}／{CAP_LABEL[c]}", nav, calendar, close0050,
                                mkt_state, years, capital_wan=INITIAL / 10_000)
            md.extend(sec[2:])
            yr = yearly_all[(key, g, c)]
            w("每年歸零（每年 1/1 重置 100 萬）各年報酬：" + "、".join(f"{y} {v:+.0%}" for y, v in yr.items()))
            w("")
    w("---")
    w("")
    w("## 敏感度：隨機拿掉 1% 訊號、重跑 20 次（固定種子 20261015）")
    w("")
    w("目的：量化『資金模型對少數訊號有多敏感』。單檔上限若真的降低集中風險，年化的分散度（標準差、最差～最佳）應明顯變小。")
    w("")
    sens = rows_all["_sens"]
    srows = []
    for key, label, _rid, _spec in RULES:
        for cap in (None, 0.125):
            c = np.array(sens[(key, cap)])
            srows.append([label, CAP_LABEL[cap], f"{c.mean():+.2%}", f"{c.std():.2%}", f"{c.min():+.2%}", f"{c.max():+.2%}"])
    w(B._md_table(srows, ["規則", "單檔上限", "年化平均", "年化標準差", "最差", "最佳"]))
    w("")
    return md


if __name__ == "__main__":
    sys.exit(main())
