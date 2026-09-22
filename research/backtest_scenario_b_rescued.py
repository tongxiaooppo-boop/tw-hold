"""「復活候選」的資金約束回測——跟原本 14 條 tw-swing 規則（`backtest_scenario_b.py`）
用同一套情境 B 方法論（各自獨立 100 萬、資金不足放棄、市值排序取前N、可用
現金平分、賣出即回籠、次日開盤買得到），只是換成另外 6 條規則：這些規則
當初在 tw-swing 自己的規則層測試裡表現健康（四道門檻多半全過、樣本外撐住），
但被組合層（部位上限 8、依風險%配置）的排擠效應否決——診斷跟 H2 是同一種
死法（訊號齊發/稀疏日過度集中 → 拖累而非放大獲利）。

篩選來源：2026-09-22 用背景 agent 翻 `tw-swing/docs/RULE_LEDGER.md`（3989行）
找出的候選，判準見 `docs/DESIGN_capital_scenarios_2026-09-22.md`。**這份報告
故意跟 `backtest_scenario_b_2026-09-22.md`（上午測的原始14條）分開，不合併**
（使用者 2026-09-22 明確指示）。

優先序（agent 判斷的證據強度，非本腳本自己排序）：H1 → V6 → Y8 → T7 → E5 → V2

| 規則 | 名稱 | 原本否決理由（摘要，見 RULE_LEDGER 行號） |
| --- | --- | --- |
| H1 | 多頭排列中的向上跳空續攻 | 規則層全過，組合層跟H2一起進default後回撤-9.1%→-32.0%，單日峰值13.79%全庫最高（730-864行） |
| V6 | 缺口之上見長紅K強勢整理 | 規則層過，只卡②aMAR 0.47，文件原話「MAR失敗純粹是回撤驅動」（1299-1332行） |
| Y8 | 跳空記憶+均線通道突破 | 樣本18787筆、樣本外一致性最好，只卡回撤-30%，「不是進場邏輯沒有優勢」（3862-3884行） |
| T7 | 一星二陽（續勢） | 規則層過、樣本外撐住，只卡②aMAR 0.35（1299-1332行） |
| E5 | 帶量長紅突破前高（不限漲速） | 規則層全過、樣本外正，死因混合：跟A3重疊+組合層排擠A3的機會（220-270行，信心打折） |
| V2 | MA通道乖離上緣帶量突破 | 規則層過，MAR 0.61差一點卡門檻（1299-1332行） |

用法：
    python research/backtest_scenario_b_rescued.py
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
OUT.mkdir(parents=True, exist_ok=True)

RESCUED_CANDIDATES = [
    ("H1", "多頭排列中的向上跳空續攻", "規則層全過，組合層跟H2一起進default後回撤-9.1%→-32.0%，單日峰值13.79%全庫最高"),
    ("V6", "缺口之上見長紅K強勢整理", "規則層過，只卡MAR 0.47，文件原話：MAR失敗純粹是回撤驅動"),
    ("Y8", "跳空記憶＋均線通道突破", "樣本18787筆、樣本外一致性最好，只卡回撤-30%，非進場邏輯問題"),
    ("T7", "一星二陽（續勢）", "規則層過、樣本外撐住，只卡MAR 0.35"),
    ("E5", "帶量長紅突破前高（不限漲速）", "規則層全過、樣本外正；死因混合(跟A3重疊+組合層排擠)，信心打折"),
    ("V2", "MA通道乖離上緣帶量突破", "規則層過，MAR 0.61差一點卡門檻"),
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

    candidates = [(rid, name, 0.0) for rid, name, _ in RESCUED_CANDIDATES]
    reason_by_rid = {rid: reason for rid, _, reason in RESCUED_CANDIDATES}

    print("跑 6 條復活候選的事件過濾 + next_open trades…", flush=True)
    sw_results, _specs = B.run_swing_rules(universe, candidates=candidates)

    lines: list[str] = []

    def w(*xs):
        lines.extend(xs) if xs else lines.append("")

    w("# 復活候選：6 條曾被組合層排擠否決的規則，改用真實資金約束重測")
    w()
    w(f"- 產出：{pd.Timestamp.now():%Y-%m-%d %H:%M}")
    w(f"- 期間：{B.START.date()} → {B.END.date()}｜universe：{len(universe)} 檔")
    w("- 買得到口徑：訊號次一交易日開盤才成交")
    w(f"- 成本：{B.COST_ACTUAL:.3%}（來回）")
    w("- **這份報告刻意跟 `backtest_scenario_b_2026-09-22.md`（上午測的原始14條）分開**"
      "，不合併——測的是完全不同的一批規則，來源、篩選邏輯、目的都不一樣。")
    w()
    w("## 情境 B 規格（跟原始14條完全相同，複製過來不重新定義）")
    w()
    w("1. 每個規則各自獨立 100 萬。")
    w("2. 資金不足就放棄，不排隊。")
    w("3. 同一天多檔訊號，市值由大到小取前 N 檔（N=5、N=10 都跑）。")
    w("4. 資金分配：可用現金平分給入選候選。")
    w("5. 資金回籠：賣出當下即可再部署。")
    w()
    w("## 這 6 條規則當初被否決的理由（來源：`tw-swing/docs/RULE_LEDGER.md`）")
    w()
    rows = [[rid, name, reason] for rid, name, reason in RESCUED_CANDIDATES]
    w(B._md_table(rows, ["規則", "名稱", "原始否決理由摘要"]))
    w()

    for rid, name, _reason in RESCUED_CANDIDATES:
        res = sw_results[rid]
        trades = res["trades"]
        n_ev = res["n_events"]
        n_fill_all = len(trades)
        w(f"## {rid} · {name}", "")
        w(f"- 原始否決理由：{reason_by_rid[rid]}", "")
        if not n_fill_all:
            w(f"tw-hold universe/期間內過濾後**沒有任何一筆訊號成交**（事件檔內原有 {n_ev} 個訊號）。", "")
            continue
        for n_cap in S.N_VALUES:
            print(f"  模擬 {rid}（N={n_cap}）…", flush=True)
            nav, meta = S.simulate_capital_constrained(trades, close_pivot, mktcap_lut,
                                                        B.COST_ACTUAL, n_cap, end_cap=B.END)
            st = B.curve_stats(nav)
            w(f"### N={n_cap}", "")
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

    w("## 已知限制")
    w()
    w("- 生存者偏差、跨repo口徑不可比、市值排序是設計選擇等限制跟"
      "`backtest_scenario_b_2026-09-22.md`相同，不重複列出。")
    w("- **這 6 條沒有原始tw-swing『全市場/全歷史/次日開盤/部位上限8』的可比年化數字**"
      "——當初否決它們用的是不同的診斷指標（規則層每筆超額報酬、樣本外訓練/驗證段），"
      "不是像原始14條那樣有一個現成的『組合模擬部位上限8年化』數字可以對照，所以"
      "這份報告只呈現資金約束模型下的結果，不做『原始 vs 資金約束』的直接對照——"
      "只能對照『被否決的定性理由』有沒有在資金約束下改善（訊號成交率、年化轉正與否）。")
    w("- E5 的否決理由是混合案例（機制重疊 + 組合層排擠），資金約束模型只能處理"
      "「排擠」那一半，不能處理「重疊」那一半——如果 E5 在這裡表現變好，不代表"
      "重疊問題也解決了，只代表排擠效應被拆掉了。")
    w()

    out_md = OUT / "backtest_scenario_b_rescued_2026-09-22.md"
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n-> {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
