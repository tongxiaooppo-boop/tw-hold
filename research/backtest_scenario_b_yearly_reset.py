"""情境 B 的「每年歸零重跑」版本：跟連續複利版（`backtest_scenario_b.py`）用
同一套資金約束規則（各自獨立本金、資金不足放棄、市值排序取前N、可用現金
平分、賣出即回籠），差別只在——**每年 1/1 都重新從本金開始，不延續前一年
的資金水位**，也不延續前一年還沒平倉的部位（前一年底還開著的部位，就地用
當天收盤價做未實現標記後直接捨棄，不帶進新的一年）。

目的（2026-09-22 討論記錄，`docs/DESIGN_capital_scenarios_2026-09-22.md`）：
把「規則本身逐年的品質」跟「資金路徑依賴」（某年賺多了隔年本金變大、某年
虧多了隔年本金變小）拆開來看——連續複利版回答的是「這樣操作十年，帳戶會
變怎樣」，這支回答的是「每年都給規則同樣的起跑點，它平均/逐年的表現是
好是壞」。兩者不是互相取代，是回答不同問題。

輸出獨立成一份新報告 `docs/reports/backtest_scenario_b_yearly_reset_2026-09-22.md`，
不併入既有的 `backtest_scenario_b_2026-09-22.md`（使用者 2026-09-22 明確指示）。

已知限制（跟連續複利版不同、這支特有的）：
- 每年年底如果有部位還沒真的出場（stop 沒觸發、也還沒到 max_hold），這裡
  用當天收盤價做「未實現標記」算進當年年末價值，然後**直接捨棄這筆部位**
  （不算出場、不扣成本，但也不會帶到隔年）——隔年這檔股票如果訊號沒有重新
  觸發，就不會再出現。這是「歸零重跑」語意下唯一自洽的做法，但代表某些
  年末數字包含未實現損益，不是真正落袋的錢。
- 價值線（季度整批換股）的「年」跟日曆年邊界對不齊（換股日是 3/6/9/12月
  15日），Q4（12月）那次換股的持有期本來就會跨進隔年 3 月——這裡一樣在
  年底做未實現標記、不延續到隔年，處理邏輯跟事件驅動的規則一致。
- 價值線每年重置後沒有追蹤「上一期持股」，成本一律用「假設整批換手」計算
  （每期都當作 100% 換手扣成本），不是用實際新增/剔除檔數算——連續複利版
  的原始邏輯會抓實際換手率（同一檔股票連續入選就不用重買、不扣成本），
  這裡簡化成保守估計（成本算得比實際更高一點），跟連續複利版的成本數字
  不完全可比。

用法：
    python research/backtest_scenario_b_yearly_reset.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "research"))

import backtest_top17_buyable as B  # noqa: E402
import backtest_scenario_b as S  # noqa: E402

OUT = REPO / "docs" / "reports"
OUT.mkdir(parents=True, exist_ok=True)


def yearly_reset_swing_or_longswing(trades: pd.DataFrame, close_pivot: pd.DataFrame,
                                    mktcap_lut: dict, cost: float, n_cap: int,
                                    initial_capital: float, years: list[int]) -> dict:
    """每年只用「當年進場」的訊號、本金重置——不延續前一年任何部位或現金。"""
    out = {}
    for y in years:
        y0, y1 = pd.Timestamp(y, 1, 1), min(pd.Timestamp(y, 12, 31), B.END)
        if y0 > B.END:
            break
        sub = trades[(trades["entry_date"] >= y0) & (trades["entry_date"] <= y1)]
        if not len(sub):
            out[y] = {"ret": 0.0, "end_val_frac": 1.0, "n_signals": 0, "n_accepted": 0,
                      "accept_rate": np.nan, "n_rejected_cash": 0, "n_rejected_ncap": 0}
            continue
        nav, meta = S.simulate_capital_constrained(sub, close_pivot, mktcap_lut, cost, n_cap,
                                                    initial_capital=initial_capital, end_cap=y1)
        end_val_frac = float(nav.iloc[-1]) if len(nav) else 1.0
        out[y] = {"ret": end_val_frac - 1.0, "end_val_frac": end_val_frac, **meta}
    return out


def yearly_reset_value(universe: set[str], n_cap: int, initial_capital: float,
                       mktcap_lut: dict, cost: float, years: list[int]) -> dict:
    """價值線的年度重置版：每年 1/1 重新從本金開始，只用「換股日 d0 落在這一年」
    的幾期（通常 4 期）；如果第 4 期（12 月）的持有期跨過年底，就在年底當天
    用收盤價做未實現標記，不算完整一期報酬、不扣成本、不帶到隔年。"""
    from twswing.data import store  # noqa: E402
    from factors.factors import quarterly_factors  # noqa: E402
    from reference.loader import load_quarterly  # noqa: E402
    from screener.screen import screen_value  # noqa: E402

    q = load_quarterly()
    qf = quarterly_factors(q)
    px = store.read_daily(recent=False, columns=["date", "ticker", "open", "close"])
    px["ticker"] = B.bare(px["ticker"])
    px = px[px["date"] <= B.END]
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
    for y in range(2016, B.END.year + 1):
        for m in (3, 6, 9, 12):
            d = pd.Timestamp(y, m, 15)
            nxt = idx[idx >= d]
            if len(nxt):
                dates.append(nxt[0])
    dates = [d for d in dates if d <= idx.max()]

    out = {}
    for y in years:
        y0, y1 = pd.Timestamp(y, 1, 1), min(pd.Timestamp(y, 12, 31), B.END)
        if y0 > B.END:
            break
        year_dates = [d0 for d0 in dates[:-1] if d0.year == y and d0 <= B.END]
        eq = initial_capital
        n_periods = 0
        for d0 in year_dates:
            i = dates.index(d0)
            d1 = dates[i + 1]
            cands, n_ok = pick_value(d0)
            e0 = next_open_date(d0)
            if e0 is None:
                continue
            e1_full = next_open_date(d1)
            capped = e1_full is not None and e1_full > y1
            e1 = (close.index[close.index <= y1][-1] if capped else e1_full)
            if e1 is None or e1 <= e0:
                continue
            cols = [t for t in cands if t in openp.columns]
            p_e0 = openp.loc[e0].reindex(cols) if cols else pd.Series(dtype="float64")
            scored = []
            for t in cols:
                price = p_e0.get(t)
                cap = S.capital_stock_asof(mktcap_lut, t, e0)
                mcap = cap * price if (pd.notna(cap) and pd.notna(price)) else -1.0
                scored.append((t, mcap))
            scored.sort(key=lambda x: -x[1])
            held = [t for t, _ in scored[:n_cap]]
            if held:
                a = openp.loc[e0].reindex(held)
                # 未平倉標記用收盤價（e1 若是年底，就是年底收盤；不是換股日就不查開盤）
                b = (close.loc[e1].reindex(held) if capped else openp.loc[e1].reindex(held))
                r = (b / a - 1.0).dropna()
                gross = r.mean() if len(r) else np.nan
            else:
                gross = np.nan
            cost_frac = 0.0 if capped else (cost / 2) * len(held) / max(1, len(held))
            net = (gross - cost_frac) if pd.notna(gross) else 0.0
            eq *= (1 + net)
            n_periods += 1
        out[y] = {"ret": eq / initial_capital - 1.0, "end_val_frac": eq / initial_capital,
                  "n_periods": n_periods}
    return out


def _pct(v):
    return f"{v:+.1%}" if v is not None and pd.notna(v) else "—"


def main() -> int:
    print("載入 universe / 市值查表 / 收盤價矩陣…", flush=True)
    universe = B.load_universe()
    mktcap_lut = S.build_mktcap_lut()
    close_pivot = S.load_close_pivot(universe)
    close0050 = B.load_0050_close()
    years = list(range(B.START.year, B.END.year + 1))
    mkt_yearly = {y: v for y, v in zip(
        years,
        [22.1, 18.0, -5.5, 36.1, 30.2, 19.9, -21.7, 26.9, 49.3, 38.1, 60.9])}

    print("跑 14 條規則的事件過濾 + next_open trades…", flush=True)
    sw_results, _specs = B.run_swing_rules(universe)

    lines: list[str] = []

    def w(*xs):
        lines.extend(xs) if xs else lines.append("")

    w("# 情境 B（每年歸零重跑版）：拆開資金路徑依賴，看規則逐年的獨立表現")
    w()
    w(f"- 產出：{pd.Timestamp.now():%Y-%m-%d %H:%M}")
    w("- 跟 `backtest_scenario_b_2026-09-22.md`（連續複利版）用同一套資金約束規則"
      "（各自獨立本金、資金不足放棄、市值排序取前N、可用現金平分、賣出即回籠），"
      "**唯一差異**：每年 1/1 都重新從本金開始，不延續前一年的資金水位或未平倉部位。")
    w("- 目的：把「規則逐年的品質」跟「資金路徑依賴」（某年賺多了隔年本金變大、"
      "某年虧多了隔年本金變小）拆開來看。連續複利版回答「這樣操作十年帳戶會"
      "變怎樣」，這份回答「每年都給規則同樣的起跑點，逐年表現好不好」——"
      "兩者不是互相取代。")
    w("- 已知限制：年底還沒出場的部位用當天收盤價做未實現標記後直接捨棄，"
      "不算出場、不扣成本，也不會帶到隔年（「歸零重跑」語意下唯一自洽的做法，"
      "但代表某些年末數字含未實現損益，不是真正落袋的錢）。")
    w()

    for rid, name, src_cagr in B.TWSWING_CANDIDATES:
        trades = sw_results[rid]["trades"]
        w(f"## {rid} · {name}", "")
        if not len(trades):
            w("沒有任何一筆訊號成交，跳過。", "")
            continue
        for n_cap in S.N_VALUES:
            print(f"  {rid}（N={n_cap}）每年歸零…", flush=True)
            yr = yearly_reset_swing_or_longswing(trades, close_pivot, mktcap_lut,
                                                 B.COST_ACTUAL, n_cap, S.INITIAL_CAPITAL, years)
            w(f"### N={n_cap}（本金 100 萬，每年重置）", "")
            rows = []
            for y in years:
                if y not in yr:
                    break
                r = yr[y]
                rows.append([str(y), _pct(r["ret"]), f"{r['end_val_frac']*100:,.1f}",
                            _pct(mkt_yearly.get(y, np.nan) / 100 if y in mkt_yearly else None),
                            str(r.get("n_accepted", 0)) if r.get("n_signals", 0) else "0（當年無訊號）"])
            w(B._md_table(rows, ["年", "策略當年報酬", "年末價值(萬)", "0050當年報酬", "成交筆數"]))
            w()

    # 長波段（歸零版）
    w("## 長波段候選池（各自獨立 200 萬，每年重置）", "")
    print("跑長波段 trades…", flush=True)
    ls_trades, ls_close, ls_meta = S.get_longswing_trades(universe)
    for n_cap in S.N_VALUES:
        print(f"  長波段（N={n_cap}）每年歸零…", flush=True)
        yr = yearly_reset_swing_or_longswing(ls_trades, ls_close, mktcap_lut, B.COST_ACTUAL,
                                             n_cap, S.LONGSWING_VALUE_CAPITAL, years)
        w(f"### N={n_cap}（本金 200 萬，每年重置）", "")
        rows = []
        for y in years:
            if y not in yr:
                break
            r = yr[y]
            rows.append([str(y), _pct(r["ret"]), f"{r['end_val_frac']*200:,.1f}",
                        _pct(mkt_yearly.get(y, np.nan) / 100 if y in mkt_yearly else None),
                        str(r.get("n_accepted", 0)) if r.get("n_signals", 0) else "0（當年無訊號）"])
        w(B._md_table(rows, ["年", "策略當年報酬", "年末價值(萬)", "0050當年報酬", "成交筆數"]))
        w()

    # 價值線（歸零版）
    w("## 價值因子指數（各自獨立 200 萬，每年重置，維持季度整批換股節奏）", "")
    for n_cap in S.N_VALUES:
        print(f"  價值線（N={n_cap}）每年歸零…", flush=True)
        yr = yearly_reset_value(universe, n_cap, S.LONGSWING_VALUE_CAPITAL, mktcap_lut,
                                B.COST_ACTUAL, years)
        w(f"### N={n_cap}（本金 200 萬，每年重置）", "")
        rows = []
        for y in years:
            if y not in yr:
                break
            r = yr[y]
            rows.append([str(y), _pct(r["ret"]), f"{r['end_val_frac']*200:,.1f}",
                        _pct(mkt_yearly.get(y, np.nan) / 100 if y in mkt_yearly else None),
                        f"{r['n_periods']} 期"])
        w(B._md_table(rows, ["年", "策略當年報酬", "年末價值(萬)", "0050當年報酬", "換股期數"]))
        w()

    out_md = OUT / "backtest_scenario_b_yearly_reset_2026-09-22.md"
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n-> {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
