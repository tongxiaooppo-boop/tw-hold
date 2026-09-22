"""附加：H2-trailatr2、Y4——tw-swing **實際上線**版本的資金約束回測。

背景（2026-09-22）：早上「資金天花板」報告測的 14 條規則裡，H2 是規則家族
的「本尊」、Y4-plow20 是 Y4 家族裡表現最好的變體，兩者都是用「家族去重、
取最佳版本」的邏輯選出來的，**不是實際在跑的版本**。使用者後來查證發現
tw-swing 模擬單真正在跑的是 `H2-trailatr2`（H2 的移動停損變體）跟 `Y4`
（本尊，不是 Y4-plow20），要求把這兩個「真的上線」的版本也用同一套資金
約束模型（100萬、N=5/10、市值排序取前N）測一次，補進同一份報告/網頁，
跟早上測的版本並列（不是取代，因為早上測的是「這個家族最好可以到哪裡」，
這次測的是「線上實際在跑的那個版本，資金約束下表現如何」，是不同問題）。

用法：
    python research/backtest_scenario_b_live_addendum.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "research"))

import backtest_top17_buyable as B  # noqa: E402
import backtest_scenario_b as S  # noqa: E402

OUT = REPO / "docs" / "reports"

LIVE_CANDIDATES = [
    ("H2-trailatr2", "三日兩缺口（移動ATR停損版，實際上線）", 0.0),
    ("Y4", "上升軌道突破＋月營收年增加速（CANSLIM，實際上線，非Y4-plow20變體）", 0.0),
]


def main() -> int:
    print("載入 universe / 市值查表 / 收盤價矩陣…", flush=True)
    universe = B.load_universe()
    mktcap_lut = S.build_mktcap_lut()
    close_pivot = S.load_close_pivot(universe)
    close0050 = B.load_0050_close()
    mkt_state = B.ma_verdict_series(close0050)
    calendar = close0050.loc[(close0050.index >= B.START) & (close0050.index <= B.END)].index
    years = list(range(B.START.year, B.END.year + 1))

    print("跑 H2-trailatr2 / Y4 事件過濾 + next_open trades…", flush=True)
    sw_results, _specs = B.run_swing_rules(universe, candidates=LIVE_CANDIDATES)

    lines: list[str] = []

    def w(*xs):
        lines.extend(xs) if xs else lines.append("")

    w("## 附加：H2-trailatr2 / Y4（tw-swing 實際上線版本，非家族最佳版）")
    w()
    w("跟前面 14 條不同：H2（前面測的）跟 Y4-plow20（前面測的）是「同家族裡表現"
      "最好的版本」，但 tw-swing 模擬單真正在跑的是 `H2-trailatr2`（移動ATR停損"
      "變體）跟 `Y4`（CANSLIM本尊，不是 Y4-plow20 出場變體）——這裡另外測這兩個"
      "「真的上線」的版本，跟上面並列，不是取代。")
    w()

    for rid, name, _ in LIVE_CANDIDATES:
        res = sw_results[rid]
        trades = res["trades"]
        n_ev = res["n_events"]
        w(f"### {rid} · {name}", "")
        if not len(trades):
            w("tw-hold universe/期間內過濾後沒有任何一筆訊號成交。", "")
            continue
        for n_cap in S.N_VALUES:
            print(f"  模擬 {rid}（N={n_cap}）…", flush=True)
            nav, meta = S.simulate_capital_constrained(trades, close_pivot, mktcap_lut,
                                                        B.COST_ACTUAL, n_cap, end_cap=B.END)
            st = B.curve_stats(nav)
            w(f"#### N={n_cap}", "")
            w(f"- 事件檔內原有 {n_ev} 個訊號，過濾到 tw-hold universe 後 {meta['n_signals']} 筆"
              f"訊號可能進場；實際成交（資金足夠且排進前 {n_cap} 名）"
              f"**{meta['n_accepted']} 筆（{meta['accept_rate']:.0%}）**，"
              f"因現金為 0 放棄 {meta['n_rejected_cash']} 筆，因排在前 {n_cap} 名之外放棄"
              f"{meta['n_rejected_ncap']} 筆。")
            if len(nav) >= 2:
                w(f"- 全期年化 **{st['cagr']:+.2%}**、最大回撤 {st['maxdd']:.1%}、"
                  f"MAR {st['mar']:.2f}（初始資金 100 萬，終值 {nav.iloc[-1] * 100:.1f} 萬）。")
                w(*B.section_for(f"{rid}（N={n_cap}）", nav, calendar, close0050, mkt_state, years,
                                 capital_wan=100.0))
            else:
                w("樣本太少，無法算年切/市況切。", "")
            w()

    addendum = "\n".join(lines)
    report_path = OUT / "backtest_scenario_b_2026-09-22.md"
    existing = report_path.read_text(encoding="utf-8")
    report_path.write_text(existing.rstrip("\n") + "\n\n" + addendum, encoding="utf-8")
    print(f"\n-> 附加到 {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
