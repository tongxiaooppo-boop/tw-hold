"""附加：H2-trailatr2、Y4——tw-swing **實際上線**版本的「每年歸零重跑」回測。

背景：`backtest_scenario_b_live_addendum.py` 已經把這兩個實際上線版本補進連續
複利版報告，但當時沒有同步補進 `backtest_scenario_b_yearly_reset.py`（歸零版）
——歸零版原本只測了「家族本尊」H2 跟「家族最佳版」Y4-plow20，沒有 tw-swing
`capital_watch` 真正在跑的 H2-trailatr2 / Y4（本尊）。W6 本來就在歸零版清單裡，
不用補。

跟連續複利版的關係：連續複利版回答「這樣操作十年帳戶會變怎樣」，這份回答
「每年都給規則同樣的起跑點，逐年表現好不好」——兩者不是互相取代，用途見
`backtest_scenario_b_yearly_reset.py` 開頭的說明。

用法：
    python research/backtest_scenario_b_yearly_reset_live_addendum.py
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
import backtest_scenario_b_yearly_reset as YR  # noqa: E402

OUT = REPO / "docs" / "reports"

LIVE_CANDIDATES = [
    ("H2-trailatr2", "三日兩缺口（移動ATR停損版，實際上線）", 0.0),
    ("Y4", "上升軌道突破＋月營收年增加速（CANSLIM，實際上線，非Y4-plow20變體）", 0.0),
]


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

    print("跑 H2-trailatr2 / Y4 事件過濾 + next_open trades…", flush=True)
    sw_results, _specs = B.run_swing_rules(universe, candidates=LIVE_CANDIDATES)

    lines: list[str] = []

    def w(*xs):
        lines.extend(xs) if xs else lines.append("")

    w("## 附加：H2-trailatr2 / Y4（tw-swing 實際上線版本，每年歸零重跑）")
    w()
    w("跟連續複利版的附加章節同一批 trades，換成「每年歸零重跑」的資金模型"
      "（跟本報告前面 W6 等 14 條規則同一套邏輯）——H2（前面測的）跟 Y4-plow20"
      "（前面測的）是「同家族裡表現最好的版本」，這裡另外測 tw-swing 模擬單"
      "真正在跑的 `H2-trailatr2`（移動ATR停損變體）跟 `Y4`（CANSLIM本尊），"
      "跟上面並列，不是取代。")
    w()

    for rid, name, _ in LIVE_CANDIDATES:
        trades = sw_results[rid]["trades"]
        w(f"### {rid} · {name}", "")
        if not len(trades):
            w("tw-hold universe/期間內過濾後沒有任何一筆訊號成交。", "")
            continue
        for n_cap in S.N_VALUES:
            print(f"  {rid}（N={n_cap}）每年歸零…", flush=True)
            yr = YR.yearly_reset_swing_or_longswing(trades, close_pivot, mktcap_lut,
                                                     B.COST_ACTUAL, n_cap,
                                                     S.INITIAL_CAPITAL, years)
            w(f"#### N={n_cap}（本金 100 萬，每年重置）", "")
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

    addendum = "\n".join(lines)
    report_path = OUT / "backtest_scenario_b_yearly_reset_2026-09-22.md"
    existing = report_path.read_text(encoding="utf-8")
    report_path.write_text(existing.rstrip("\n") + "\n\n" + addendum, encoding="utf-8")
    print(f"\n-> 附加到 {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
