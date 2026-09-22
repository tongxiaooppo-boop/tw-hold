"""情境 B：14 條 tw-swing 規則，各自獨立 100 萬資金池，真實資金約束回測。

交接來源：`docs/DESIGN_capital_scenarios_2026-09-22.md`（討論記錄，所有假設在
使用者跟 AI 來回討論中拍板，這支腳本落地執行）。跟 `backtest_top17_buyable.py`
的差異：那支是「訊號全買、無部位上限、動態等權」（隱含無限資金），這支是
「每個規則各自 100 萬、資金不夠就放棄、同一天多檔用市值排序取前 N」——測的
是「規則在真實可執行資金下能不能用」，不是規則本身有沒有方向性。

═══════════════════════════ 情境 B 完整規格（2026-09-22 使用者拍板） ═══════════════════════════

1. 每個規則各自獨立 100 萬（14 條 = 14 個平行世界，互不共用、互不搶錢）。
2. 資金不足就放棄，不排隊——訊號當天資金不夠（可用現金為 0）就直接跳過，
   不等資金回籠後延遲買進。
3. 同一天同一規則有多檔訊號時，只挑前 N 檔（N ∈ {5, 10}，本次兩個都跑），
   排序依據＝**市值，由大到小**。市值＝訊號進場日（次日開盤）的價格 ×
   「財報公告日 ≤ 進場日」的最近一期已公告股本（`reference.loader.load_quarterly()`
   的 `capital_stock`/`disclosure_date`，避免用到當時還沒公告的股本，防止
   前視偏誤）。找不到已公告股本的股票排在最後面。
4. 資金分配：選中的候選之間，把「當下可用現金」平分（不是固定金額、不是
   依訊號強度加權）——換句話說每次進場都會把手上所有現金全部部署完畢。
5. 資金回籠：賣出當下即視為現金立即可再部署，不模擬 T+2 交割延遲（已知
   簡化假設，見報告〈已知限制〉）。
6. 買得到口徑不變：訊號日次一交易日開盤才成交（沿用 `events_all.parquet` +
   `twswing.backtest.engine.simulate_trades(entry_at="next_open")` 算出的
   trades，跟 `backtest_top17_buyable.py` 用同一批 trades，只是「要不要真的
   進場」多了資金約束這一關）。

用法：
    python research/backtest_scenario_b.py
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

OUT = REPO / "docs" / "reports"
OUT.mkdir(parents=True, exist_ok=True)

INITIAL_CAPITAL = 1_000_000.0
N_VALUES = (5, 10)


# ─────────────────────────── 市值（點時、防前視） ───────────────────────────

def build_mktcap_lut() -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """逐股票的（已公告日, 股本）排序陣列，供 as-of 查詢用。"""
    from reference.loader import load_quarterly  # noqa: E402
    q = load_quarterly().dropna(subset=["disclosure_date", "capital_stock"])
    lut = {}
    for tk, g in q.groupby("ticker"):
        g2 = g.sort_values("disclosure_date")
        lut[str(tk)] = (g2["disclosure_date"].values.astype("datetime64[D]"),
                        g2["capital_stock"].values.astype("float64"))
    return lut


def capital_stock_asof(lut: dict, ticker: str, date) -> float:
    arr = lut.get(ticker)
    if arr is None:
        return np.nan
    dates, caps = arr
    d = np.datetime64(pd.Timestamp(date), "D")
    idx = np.searchsorted(dates, d, side="right") - 1
    if idx < 0:
        return np.nan
    return float(caps[idx])


# ─────────────────────────── 情境 B 核心模擬 ───────────────────────────

def simulate_capital_constrained(trades: pd.DataFrame, close_pivot: pd.DataFrame,
                                  mktcap_lut: dict, cost: float, n_cap: int,
                                  initial_capital: float = INITIAL_CAPITAL,
                                  end_cap: pd.Timestamp | None = None):
    """逐日事件驅動模擬：每個規則各自 100 萬，資金不足放棄、同日多檔用市值
    取前 N、可用現金平分、賣出當下資金即回籠。回傳 (nav_series, meta)。

    `end_cap`：把模擬日曆硬截到這一天為止（給「每年歸零重跑」用——即使某筆
    交易的真實出場日超過年底，模擬也只跑到年底，該筆部位在年底當天用收盤價
    做未實現標記，不算平倉、不扣成本，隔年不會延續這筆部位）。"""
    trades = trades.reset_index(drop=True).copy()
    trades["bare"] = trades["ticker"].astype(str).str.split(".").str[0]

    def mc(row):
        cap = capital_stock_asof(mktcap_lut, row["bare"], row["entry_date"])
        if pd.isna(cap):
            return -1.0  # 查不到股本：排最後面，不是排最前面
        return cap * row["entry_px"]

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
    n_rejected_cash = 0      # 有市值排序資格但當下現金為 0，整批放棄
    n_rejected_ncap = 0      # 現金 > 0，但排在 N 名之外被放棄

    for d in td:
        # 1) 出場：資金回籠
        for idx in exits_by_date.get(d, []):
            if idx not in open_pos:
                continue
            pos = open_pos.pop(idx)
            row = trades.loc[idx]
            px_prev, px_exit = pos["last_px"], row["exit_px"]
            r = 0.0 if (pd.isna(px_prev) or pd.isna(px_exit) or px_prev == 0) else px_exit / px_prev - 1.0
            still_open = bool(row["still_open"]) if "still_open" in trades.columns else False
            if not still_open:
                r = (1 + r) * (1 - cost) - 1.0  # 真正平倉才扣成本；still_open 是回測結束時的期末標記價，不是真的賣出
            cash += pos["capital"] * (1 + r)

        # 2) 進場：市值排序取前 N，可用現金平分
        cands = list(entries_by_date.get(d, []))
        if cands:
            if cash <= 1e-9:
                n_rejected_cash += len(cands)
            else:
                cands_sorted = sorted(cands, key=lambda i: -trades.loc[i, "mktcap"])
                selected = cands_sorted[:n_cap]
                n_rejected_ncap += max(0, len(cands) - len(selected))
                per_cap = cash / len(selected)
                proceeds_same_day = 0.0
                for idx in selected:
                    row = trades.loc[idx]
                    accepted.add(idx)
                    if row["exit_date"] == row["entry_date"]:
                        r = row["exit_px"] / row["entry_px"] - 1.0
                        r = (1 + r) * (1 - cost) - 1.0
                        proceeds_same_day += per_cap * (1 + r)
                    else:
                        open_pos[idx] = {"capital": per_cap, "last_px": row["entry_px"], "ticker": row["ticker"]}
                cash = proceeds_same_day

        # 3) 其餘未平倉部位：標記到今日收盤
        for idx, pos in open_pos.items():
            tk = pos["ticker"]
            px_today = close_pivot.at[d, tk] if tk in close_pivot.columns else np.nan
            if pd.notna(px_today) and pd.notna(pos["last_px"]) and pos["last_px"] != 0:
                r = px_today / pos["last_px"] - 1.0
                pos["capital"] *= (1 + r)
                pos["last_px"] = px_today

        nav[d] = cash + sum(p["capital"] for p in open_pos.values())

    nav_series = pd.Series(nav).sort_index() / initial_capital
    meta = {
        "n_signals": n_signals,
        "n_accepted": len(accepted),
        "accept_rate": (len(accepted) / n_signals) if n_signals else np.nan,
        "n_rejected_cash": n_rejected_cash,
        "n_rejected_ncap": n_rejected_ncap,
    }
    return nav_series, meta


# ─────────────────────────── 長波段 / 價值線（各自 200 萬，respond 使用者 2026-09-22 追加指示） ───────────────────────────

LONGSWING_VALUE_CAPITAL = 2_000_000.0


def get_longswing_trades(universe: set[str]):
    """跟 `backtest_top17_buyable.py::run_longswing` 同一批 next_open + notbear +
    移動 ATR 停損 trades，只是這裡要拿原始 trades 清單（含 still_open 旗標）
    自己做資金約束模擬，不能直接用它已經算好的動態等權 curve。"""
    sys.path.insert(0, str(REPO / "research"))
    import backtest_longswing as ls  # noqa: E402

    qf, rev, chips, uni_bundle, daily, idx_close = ls.load_all()
    daily = daily[daily["date"] <= B.END].copy()
    idx_close = idx_close[idx_close.index <= B.END]
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
    df = pd.DataFrame(trades).rename(columns={"entry_price": "entry_px", "exit_price": "exit_px"})
    return df, panels["close"], {"n_weeks": len(weeks), "n_abandoned": n_abandoned}


def run_value_capital_constrained(universe: set[str], n_cap: int,
                                  initial_capital: float, mktcap_lut: dict, cost: float):
    """價值線的情境 B 版本：**維持季度整批換股的節奏**（不是把它拆成逐日事件
    跟 tw-swing 14 條規則搶資金那種模型）——使用者指示「價值就必須守3個月
    買一次的概念」。每次換股日，把當下**全部**資金（上一期全部賣出、資金
    100% 回籠）依市值由大到小，只買前 N 檔、平分資金。跟 `backtest_top17_buyable.
    py::run_value` 的差異只在「選前 N 檔」這一步，其餘（次日開盤買賣、換股
    週期）完全沿用。"""
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

    eq = initial_capital
    prev = set()
    curve_pts = []
    rows = []
    for d0, d1 in zip(dates[:-1], dates[1:]):
        cands, n_ok = pick_value(d0)
        e0, e1 = next_open_date(d0), next_open_date(d1)
        if e0 is None or e1 is None:
            continue
        if not curve_pts:
            curve_pts.append((e0, eq))

        cols = [t for t in cands if t in openp.columns]
        p_e0 = openp.loc[e0].reindex(cols) if cols else pd.Series(dtype="float64")
        # 市值排序取前 n_cap（用 e0 當天開盤價 x 最近已公告股本）
        scored = []
        for t in cols:
            price = p_e0.get(t)
            cap = capital_stock_asof(mktcap_lut, t, e0)
            mcap = cap * price if (pd.notna(cap) and pd.notna(price)) else -1.0
            scored.append((t, mcap))
        scored.sort(key=lambda x: -x[1])
        held = [t for t, _ in scored[:n_cap]]

        if held:
            a = openp.loc[e0].reindex(held)
            b = openp.loc[e1].reindex(held)
            r = (b / a - 1.0).dropna()
            gross = r.mean() if len(r) else np.nan
        else:
            gross = np.nan
        h = set(held)
        adds, drops = len(h - prev), len(prev - h)
        turnover_cost = (cost / 2) * (adds + drops) / max(1, len(held)) if held else 0.0
        net = (gross - turnover_cost) if pd.notna(gross) else 0.0
        eq *= (1 + net)
        curve_pts.append((e1, eq))
        rows.append({"date": d0, "entry_date": e0, "n_candidates": n_ok,
                    "n_held": len(held), "gross": gross, "net": net})
        prev = h

    curve = pd.Series(dict(curve_pts)).sort_index() / initial_capital
    df = pd.DataFrame(rows)
    meta = {"n_periods": len(df), "med_cand": df["n_candidates"].median() if len(df) else np.nan,
           "blank": (df["n_candidates"] == 0).mean() if len(df) else np.nan,
           "avg_held": df["n_held"].mean() if len(df) else np.nan}
    return curve, meta


def load_close_pivot(universe: set[str]) -> pd.DataFrame:
    from twswing.data import store  # noqa: E402
    daily = store.read_daily(recent=False, columns=["date", "ticker", "close"])
    daily["bare"] = daily["ticker"].astype(str).str.split(".").str[0]
    daily = daily[daily["bare"].isin(universe)]
    return daily.pivot_table(index="date", columns="ticker", values="close").sort_index()


# ─────────────────────────── 出場邏輯文件（使用者 2026-09-22 要求如實記錄） ───────────────────────────

EXIT_RULES = [
    ("W4", "月營收動能突破半年高", "固定ATR停損+到期", "進場當根最低價 − 0.5×ATR14（不移動）", "B線 60 個交易日"),
    ("H2", "三日兩缺口", "固定ATR停損+到期", "第二個缺口當根最低價 − 0.5×ATR14（不移動）", "A線 10 個交易日"),
    ("W5", "法人籌碼波段 + 估值未過熱", "固定ATR停損+到期", "進場當根最低價 − 0.5×ATR14（不移動）", "B線 60 個交易日"),
    ("V4", "上升三角形突破", "固定ATR停損+到期", "今日最低 − 0.5×ATR14（不移動）", "B線 60 個交易日"),
    ("G3", "海龜 55 日突破", "結構性出場+到期", "進場價 − 2×ATR14（初始）", "跌破前 20 日低點，或撐滿 120 個交易日"),
    ("W6", "月營收創年高 + 估值便宜", "固定ATR停損+到期", "進場當根最低價 − 0.5×ATR14（不移動）", "B線 60 個交易日"),
    ("P1", "營收成長加速循環", "基本面轉壞出場+到期", "進場當根最低價 − 2×ATR14（初始，只當保險）", "月營收年增率跌破 5%，或撐滿 120 個交易日"),
    ("P3", "GARP 估值修復", "基本面轉壞出場+到期", "進場當根最低價 − 2×ATR14（初始，只當保險）", "PE 百分位重新爬回 65 以上，或撐滿 120 個交易日"),
    ("W3", "三日兩缺口 + 估值未過熱確認", "固定ATR停損+到期", "同 H2：第二個缺口當根最低價 − 0.5×ATR14（不移動）", "A線 10 個交易日"),
    ("J1", "雙重底頸線突破", "固定ATR停損+到期", "今日最低 − 0.5×ATR14（不移動）", "B線 60 個交易日"),
    ("D7", "極度量縮後成交量梯形遞增", "固定ATR停損+到期", "凹洞量當日最低 − 0.5×ATR14（不移動）", "B線 60 個交易日"),
    ("Y4-plow20", "Y4 出場變體·收盤跌破前20日低", "結構性出場+到期", "同 Y4：突破K棒最低價 − 0.5×ATR14（初始）", "跌破前 20 日低點，或撐滿 60 個交易日"),
    ("B2", "投信連續買超", "固定ATR停損+到期", "進場價 − 2×ATR14（不移動；籌碼跟隨無結構性價位可用）", "B線 60 個交易日"),
    ("Y1", "上升軌道突破 + 月營收年增加速確認", "移動停損", "突破K棒最低價 − 0.5×ATR14（初始）；2×ATR 移動停損，獲利1R後移到成本價保本", "撐滿 60 個交易日"),
]


def exit_rules_section() -> list[str]:
    lines = ["## 出場邏輯（本報告完全沿用 tw-swing 規則庫原始定義，未改動）", "",
            "情境 B 只改「要不要真的進場」（資金約束）跟「進場時機」（次日開盤），"
            "出場邏輯原封不動——跟 tw-swing 官方報告用同一套 `bt.ExitPlan`/"
            "`bt.simulate_trades(exits=plans)`。14 條規則分四種出場風格：", ""]
    rows = [[rid, name, style, stop, exitc] for rid, name, style, stop, exitc in EXIT_RULES]
    lines.append(_md_table_local(rows, ["規則", "名稱", "出場風格", "停損（初始/是否移動）", "主要出場條件"]))
    lines += ["",
             "**風格分布**：9 條是「固定 ATR 停損 + 時間到期」（停損設定後不移動，"
             "出場只看有沒有觸價或有沒有撐到最大持有天數，不判斷型態/訊號是否真的"
             "走完）；2 條有結構性出場（跌破前 20 日低點才出場）；2 條用基本面轉壞"
             "當主要出場理由（月營收年增轉弱 / PE 不再便宜）；1 條（Y1）用移動停損"
             "+保本機制。", ""]
    return lines


def _md_table_local(rows, header):
    return B._md_table(rows, header)


# ─────────────────────────── 報告組裝 ───────────────────────────

def main() -> int:
    print("載入 universe / 市值查表 / 收盤價矩陣…", flush=True)
    universe = B.load_universe()
    mktcap_lut = build_mktcap_lut()
    close_pivot = load_close_pivot(universe)

    close0050 = B.load_0050_close()
    mkt_state = B.ma_verdict_series(close0050)
    calendar = close0050.loc[(close0050.index >= B.START) & (close0050.index <= B.END)].index
    years = list(range(B.START.year, B.END.year + 1))

    print("跑 14 條規則的事件過濾 + next_open trades（跟情境 A/無邊際版本同一批 trades）…", flush=True)
    sw_results, _specs = B.run_swing_rules(universe)

    lines: list[str] = []

    def w(*xs):
        lines.extend(xs) if xs else lines.append("")

    w("# 情境 B：14 條規則，各自獨立 100 萬資金池、真實資金約束回測")
    w()
    w(f"- 產出：{pd.Timestamp.now():%Y-%m-%d %H:%M}")
    w(f"- 期間：{B.START.date()} → {B.END.date()}｜universe：{len(universe)} 檔")
    w("- 買得到口徑：訊號次一交易日開盤才成交（跟無邊際版本同一批 trades，未改動）")
    w(f"- 成本：{B.COST_ACTUAL:.3%}（來回），出場時扣一次")
    w()
    w("## 情境 B 規格（本報告的核心假設，逐條列出）")
    w()
    w("1. **每個規則各自獨立 100 萬**——14 條規則 = 14 個平行世界，互不共用、互不搶錢。")
    w("2. **資金不足就放棄，不排隊**——訊號當天可用現金為 0 就直接跳過，不等資金回籠後延遲買進。")
    w("3. **同一天多檔訊號，市值由大到小取前 N 檔**（N=5、N=10 本報告兩個都跑）。市值＝進場日"
      "（次日開盤）價格 × 「財報公告日 ≤ 進場日」的最近一期已公告股本（`load_quarterly()` 的"
      "`capital_stock`/`disclosure_date`，防止用到當時還沒公告的股本）。查不到已公告股本的"
      "股票排在最後面（不是排最前面，避免資料缺漏反而佔到便宜）。")
    w("4. **資金分配：可用現金平分給入選的候選**——每次進場都把當下所有現金全部部署完畢，"
      "不是固定金額、不是依訊號強度加權。")
    w("5. **資金回籠：賣出當下即可再部署**——不模擬 T+2 交割延遲（已知簡化假設，見〈已知限制〉）。")
    w()
    w("## 已知限制")
    w()
    w("- 🔴 **T+2 簡化**：真實台股交割是 T+2，賣出後現金要 2 個交易日後才真的入帳（信用/當沖"
      "交易例外）。本報告假設賣出當下現金立即可用，會讓資金週轉速度比真實帳戶快，可能高估"
      "報酬（資金閒置時間被低估）。")
    w("- **市值排序是本報告的設計選擇，不是規則本身的邏輯**——同一天多檔訊號時優先買大型股，"
      "這個排序本身會系統性偏向大型股的報酬特徵，不是規則原始設計的一部分，解讀時要意識到"
      "這一層。")
    w("- **「查不到已公告股本排最後」可能誤傷新掛牌或資料缺漏的股票**——這類股票會系統性地"
      "更容易被 N 名額擠掉，不是因為市值小，是因為資料缺漏。")
    w("- 生存者偏差、跨規則資料範疇差異等限制與 `backtest_top17_buyable_2026-09-22.md` 相同，"
      "不重複列出。")
    w()
    w(*exit_rules_section())

    for rid, name, src_cagr in B.TWSWING_CANDIDATES:
        trades = sw_results[rid]["trades"]
        n_ev = sw_results[rid]["n_events"]
        w(f"## {rid} · {name}", "")
        if not len(trades):
            w("沒有任何一筆訊號成交，跳過。", "")
            continue

        for n_cap in N_VALUES:
            print(f"  模擬 {rid}（N={n_cap}）…", flush=True)
            nav, meta = simulate_capital_constrained(trades, close_pivot, mktcap_lut,
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
                                 capital_wan=INITIAL_CAPITAL / 10_000))
            else:
                w("樣本太少，無法算年切/市況切。", "")
            w()

    # ── 長波段 / 價值線：各自獨立 200 萬（使用者 2026-09-22 追加指示） ──
    w("## 長波段候選池（各自獨立 200 萬）", "")
    w("沿用 `backtest_top17_buyable.py::run_longswing` 同一批 next_open + notbear "
      "市況閘門 + 移動 ATR 停損 trades，套上情境 B 的資金約束（市值取前 N、可用"
      "現金平分、賣出即回籠），本金改成 **200 萬**（使用者指示：長波段/價值線"
      "各自 200 萬，不是 100 萬）。", "")
    print("跑長波段 trades…", flush=True)
    ls_trades, ls_close, ls_meta = get_longswing_trades(universe)
    for n_cap in N_VALUES:
        print(f"  模擬長波段（N={n_cap}）…", flush=True)
        nav, meta = simulate_capital_constrained(ls_trades, ls_close, mktcap_lut,
                                                  B.COST_ACTUAL, n_cap,
                                                  initial_capital=LONGSWING_VALUE_CAPITAL,
                                                  end_cap=B.END)
        st = B.curve_stats(nav)
        w(f"### N={n_cap}", "")
        w(f"- {ls_meta['n_weeks']:,} 週、{meta['n_signals']} 筆訊號可能進場；實際成交"
          f"（資金足夠且排進前 {n_cap} 名）**{meta['n_accepted']} 筆（{meta['accept_rate']:.0%}）**，"
          f"因現金為 0 放棄 {meta['n_rejected_cash']} 筆，因排在前 {n_cap} 名之外放棄"
          f"{meta['n_rejected_ncap']} 筆（另有 {ls_meta['n_abandoned']} 筆訊號成交時已跌破"
          "停損位、從一開始就不在candidate trades 裡，兩者不重疊）。")
        if len(nav) >= 2:
            w(f"- 全期年化 **{st['cagr']:+.2%}**、最大回撤 {st['maxdd']:.1%}、"
              f"MAR {st['mar']:.2f}（初始資金 200 萬，終值 {nav.iloc[-1] * 200:.1f} 萬）。")
            w(*B.section_for(f"長波段（N={n_cap}）", nav, calendar, close0050, mkt_state, years,
                             capital_wan=LONGSWING_VALUE_CAPITAL / 10_000))
        else:
            w("樣本太少，無法算年切/市況切。", "")
        w()

    w("## 價值因子指數（各自獨立 200 萬，維持季度整批換股節奏）", "")
    w("**跟 tw-swing 14 條規則不一樣的地方**：價值線不拆成逐日事件搶資金，"
      "維持原本 3/6/9/12 月換股的節奏（使用者指示：「價值就必須守3個月買一次"
      "的概念」）——每次換股日，上一期全部賣出、資金 100% 回籠，依市值由大到小"
      "只買前 N 檔、平分資金，其餘（次日開盤買賣、換股週期）完全沿用"
      "`backtest_top17_buyable.py::run_value`。", "")
    for n_cap in N_VALUES:
        print(f"  模擬價值線（N={n_cap}）…", flush=True)
        nav, meta = run_value_capital_constrained(universe, n_cap, LONGSWING_VALUE_CAPITAL,
                                                   mktcap_lut, B.COST_ACTUAL)
        st = B.curve_stats(nav)
        w(f"### N={n_cap}", "")
        w(f"- {meta['n_periods']} 期，每期候選中位數 {meta['med_cand']:.0f} 檔、空白期 "
          f"{meta['blank']:.0%}，因資金約束只買前 {n_cap} 檔（平均實際持有 "
          f"{meta['avg_held']:.1f} 檔/期——受限於某些期候選數不足 {n_cap} 檔）。")
        if len(nav) >= 2:
            w(f"- 全期年化 **{st['cagr']:+.2%}**、最大回撤 {st['maxdd']:.1%}、"
              f"MAR {st['mar']:.2f}（初始資金 200 萬，終值 {nav.iloc[-1] * 200:.1f} 萬）。")
            w(*B.section_for(f"價值線（N={n_cap}）", nav, calendar, close0050, mkt_state, years,
                             capital_wan=LONGSWING_VALUE_CAPITAL / 10_000))
        else:
            w("樣本太少，無法算年切/市況切。", "")
        w()
    w("**⚠️ 對價值線設計哲學的衝擊，如實記錄**：價值線原本的設計是「過硬門檻的"
      "候選全部等權買進」（每期中位數 217 檔，追求分散），現在被迫「只買市值"
      "最大的前 5 或 10 檔」——這不是同一個策略的資金約束版本，而是**把一個"
      "分散型策略硬改成集中型策略**，數字上的差異主要來自「集中在最大型股」"
      "這個效果，不是「資金不夠買」的效果（每期候選中位數 217 遠多於 N，但"
      "200 萬本來就分不到 217 檔，所以這裡真正的限制是 N 本身，不是資金）。")
    w()

    out_md = OUT / "backtest_scenario_b_2026-09-22.md"
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n-> {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
