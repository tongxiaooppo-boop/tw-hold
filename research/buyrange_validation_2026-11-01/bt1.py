# bt1.py
# 預註冊優先：§1 僅要求 TTM>0、目標>0，沒有 F4>0 的額外限制。
# 因而主分析保留有限但非正的 F4/NC 預測；與任務文字衝突處依預註冊。
# 「TTM相對近5年中位數≥P80」的事前操作定義：
# 每股最近20個季度終點之連續4季TTM，至少12個有效值、其中位數>0；
# 以當期TTM/自身歷史中位數，在每個重播點的可分層母體取橫斷面P80。
from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "app"))
sys.path.insert(0, str(HERE))

import numpy as np
import pandas as pd

import data
from screener import detect
from replay import (
    LIMITATIONS,
    eligible_universe,
    init_output,
    isfinite,
    log_error,
    md_table,
    number,
    point_in_time,
    population_tables,
    quarter_eps,
    ratio,
    replay_dates,
)

START = "2018-04-01"
END = "2025-08-15"
TARGET_2026 = pd.Timestamp("2026-01-01")
NW_LAG = 3
BOOTSTRAP_DRAWS = 5000
BOOTSTRAP_SEED = 20261101
HISTORY_TTM_ENDPOINTS = 20
MIN_HISTORY_TTMS = 12

STRATA = (
    "all",
    "ttm_high",
    "ttm_not_high",
    "ttm_unclassified",
    "revenue_positive",
    "revenue_negative",
    "revenue_zero",
    "revenue_unknown",
    "nonop_ok",
    "nonop_degrade",
    "nonop_block",
)
CUTS = ("all", "exclude_2026")
ERROR_FIELDS = [
    "n", "p10", "p25", "p50", "p75", "p90",
    "median_absolute_error", "naive_median_absolute_error", "skill",
]
Q_FIELDS = [f"q{i}_actual_growth_median" for i in range(1, 6)]
BASE_COLUMNS = [
    "t", "rd", "q_last", "k", "eps_nc", "eps_f4", "eps_ttm",
    "target4", "target_nc", "target4_end", "ttm_relative",
    "ttm_history_n", "ttm_class", "revenue_growth_3m", "nonop_level",
]


def past_features(q, monthly, eps_ttm) -> dict:
    result = {
        "ttm_relative": np.nan,
        "ttm_history_n": 0,
        "revenue_growth_3m": np.nan,
        "nonop_level": "unknown",
    }
    e = quarter_eps(q)
    if not e.empty:
        grid = pd.period_range(
            end=e.index[-1], periods=HISTORY_TTM_ENDPOINTS + 3, freq="Q-DEC"
        )
        history = e.reindex(grid).rolling(4, min_periods=4).sum().iloc[-20:]
        valid = history.loc[np.isfinite(history.to_numpy(dtype=float))]
        result["ttm_history_n"] = len(valid)
        if len(valid) >= MIN_HISTORY_TTMS:
            med = number(valid.median())
            if isfinite(med) and med > 0:
                result["ttm_relative"] = number(eps_ttm) / med

    if not monthly.empty:
        m = pd.Series(
            pd.to_numeric(monthly, errors="coerce").to_numpy(dtype=float),
            index=pd.DatetimeIndex(monthly.index).to_period("M"),
        )
        if m.index.has_duplicates:
            raise ValueError("月營收同月重複")
        current = pd.period_range(end=m.index.max(), periods=3, freq="M")
        a = m.reindex(current).to_numpy(dtype=float)
        b = m.reindex(current - 12).to_numpy(dtype=float)
        if np.isfinite(a).all() and np.isfinite(b).all() and b.sum() != 0:
            result["revenue_growth_3m"] = a.sum() / b.sum() - 1

    result["nonop_level"] = detect.nonop_gate(q).level
    return result


def select_stratum(frame: pd.DataFrame, stratum: str) -> pd.DataFrame:
    if stratum == "all":
        return frame
    if stratum.startswith("ttm_"):
        label = {
            "ttm_high": "high",
            "ttm_not_high": "not_high",
            "ttm_unclassified": "unknown",
        }[stratum]
        return frame.loc[frame["ttm_class"].eq(label)]
    if stratum.startswith("nonop_"):
        return frame.loc[frame["nonop_level"].eq(stratum.removeprefix("nonop_"))]
    g = pd.to_numeric(frame["revenue_growth_3m"], errors="coerce")
    mask = {
        "revenue_positive": g.gt(0),
        "revenue_negative": g.lt(0),
        "revenue_zero": g.eq(0),
        "revenue_unknown": g.isna(),
    }[stratum]
    return frame.loc[mask]


def select_cut(frame: pd.DataFrame, cut: str) -> pd.DataFrame:
    if cut == "all":
        return frame
    return frame.loc[frame["target4_end"].lt(TARGET_2026)]


def error_stats(frame: pd.DataFrame, model: str) -> dict:
    prediction = "eps_f4" if model == "F4" else "eps_nc"
    target = "target4" if model == "F4" else "target_nc"
    p = pd.to_numeric(frame[prediction], errors="coerce").to_numpy(dtype=float)
    y = pd.to_numeric(frame[target], errors="coerce").to_numpy(dtype=float)
    naive = pd.to_numeric(frame["eps_ttm"], errors="coerce").to_numpy(dtype=float)
    mask = (
        np.isfinite(p) & np.isfinite(y) & np.isfinite(naive)
        & (y > 0) & (naive > 0)
    )
    result = dict.fromkeys(ERROR_FIELDS, np.nan)
    result["n"] = int(mask.sum())
    if not mask.any():
        return result
    e = (p[mask] - y[mask]) / y[mask]
    e_naive = (naive[mask] - y[mask]) / y[mask]
    for key, value in zip(
        ("p10", "p25", "p50", "p75", "p90"),
        np.percentile(e, [10, 25, 50, 75, 90]),
    ):
        result[key] = float(value)
    mae = float(np.median(np.abs(e)))
    mae_naive = float(np.median(np.abs(e_naive)))
    result["median_absolute_error"] = mae
    result["naive_median_absolute_error"] = mae_naive
    result["skill"] = 1 - mae / mae_naive if mae_naive > 0 else np.nan
    return result


def spearman_rank_ic(x, y) -> float:
    a = pd.Series(x, dtype=float).rank(method="average").to_numpy(dtype=float)
    b = pd.Series(y, dtype=float).rank(method="average").to_numpy(dtype=float)
    if len(a) < 2:
        return np.nan
    a, b = a - a.mean(), b - b.mean()
    denominator = np.sqrt(np.dot(a, a) * np.dot(b, b))
    return float(np.dot(a, b) / denominator) if denominator > 0 else np.nan


def newey_west_t(values, lag=NW_LAG) -> float:
    """截距平均數的 Bartlett HAC；gamma_l 使用除以 n 的定義。"""
    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 2:
        return np.nan
    u = x - x.mean()
    long_run_variance = float(np.dot(u, u) / n)
    for ell in range(1, min(lag, n - 1) + 1):
        weight = 1 - ell / (lag + 1)
        long_run_variance += 2 * weight * float(np.dot(u[ell:], u[:-ell]) / n)
    if long_run_variance <= 0:
        return np.nan
    return float(x.mean() / np.sqrt(long_run_variance / n))


def yearly_block_ci(point_rows) -> tuple[float, float, int]:
    """整個重播年一起重抽，保留每年有效點數，以逐點IC平均為估計量。"""
    valid = [
        (pd.Timestamp(row["rd"]).year, number(row["ic"]))
        for row in point_rows
        if isfinite(row["ic"])
    ]
    years = sorted({year for year, _ in valid})
    if len(years) < 2:
        return np.nan, np.nan, len(years)
    sums = np.array(
        [sum(value for year, value in valid if year == y) for y in years],
        dtype=float,
    )
    counts = np.array(
        [sum(year == y for year, _ in valid) for y in years], dtype=float
    )
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    selected = rng.integers(0, len(years), size=(BOOTSTRAP_DRAWS, len(years)))
    means = sums[selected].sum(axis=1) / counts[selected].sum(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return float(lo), float(hi), len(years)


def growth_sample(frame: pd.DataFrame) -> pd.DataFrame:
    columns = ["eps_f4", "eps_ttm", "target4"]
    values = frame[columns].apply(pd.to_numeric, errors="coerce")
    mask = np.isfinite(values.to_numpy(dtype=float)).all(axis=1)
    mask &= values["eps_ttm"].gt(0).to_numpy()
    mask &= values["target4"].gt(0).to_numpy()
    result = frame.loc[mask, ["t", "rd"]].copy()
    values = values.loc[mask]
    result["predicted_growth"] = values["eps_f4"] / values["eps_ttm"] - 1
    result["actual_growth"] = values["target4"] / values["eps_ttm"] - 1
    return result


def quintile_medians(frame: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    result = dict.fromkeys(Q_FIELDS, np.nan)
    assigned = frame.copy()
    assigned["quintile"] = np.nan
    if len(frame) >= 5:
        # 平均名次，不用 ticker/輸入順序拆散相同訊號；同值多時允許空分位。
        assigned["quintile"] = np.ceil(
            assigned["predicted_growth"].rank(method="average", pct=True) * 5
        ).clip(1, 5)
        for i in range(1, 6):
            a = assigned.loc[assigned["quintile"].eq(i), "actual_growth"]
            if not a.empty:
                result[f"q{i}_actual_growth_median"] = float(a.median())
    return result, assigned


def ic_analysis(frame: pd.DataFrame, dates) -> tuple[list[dict], dict]:
    sample = growth_sample(frame)
    rows, assigned_points = [], []
    for rd in dates:
        a = sample.loc[sample["rd"].eq(rd)]
        qstats, assigned = quintile_medians(a)
        rows.append(
            {
                "scope": "point",
                "rd": rd,
                "n": len(a),
                "ic": spearman_rank_ic(a["predicted_growth"], a["actual_growth"]),
                **qstats,
            }
        )
        assigned_points.append(assigned)

    pooled = pd.concat(assigned_points, ignore_index=True)
    pooled_q = dict.fromkeys(Q_FIELDS, np.nan)
    for i in range(1, 6):
        a = pooled.loc[pooled["quintile"].eq(i), "actual_growth"]
        if not a.empty:
            pooled_q[f"q{i}_actual_growth_median"] = float(a.median())

    ics = np.array([number(row["ic"]) for row in rows], dtype=float)
    finite = ics[np.isfinite(ics)]
    lo, hi, years = yearly_block_ci(rows)
    qvalues = [pooled_q[key] for key in Q_FIELDS]
    q5_gt_q1 = (
        isfinite(qvalues[0]) and isfinite(qvalues[-1])
        and qvalues[-1] > qvalues[0]
    )
    monotonic = bool(
        all(isfinite(x) for x in qvalues) and np.all(np.diff(qvalues) >= 0)
    )
    summary = {
        "scope": "all",
        "rd": "ALL",
        "n": len(sample),
        "ic_points": len(finite),
        "ic_mean": float(finite.mean()) if len(finite) else np.nan,
        "nw_lag": NW_LAG,
        "nw_t": newey_west_t(ics),
        "bootstrap_years": years,
        "bootstrap_draws": BOOTSTRAP_DRAWS,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "ci_low": lo,
        "ci_high": hi,
        **pooled_q,
        "q5_gt_q1": bool(q5_gt_q1),
        "quintiles_monotonic": monotonic,
    }
    return rows, summary


def positive_direction(row) -> bool:
    return bool(
        isfinite(row["ic_mean"]) and row["ic_mean"] > 0
        and row["q5_gt_q1"]
    )


def estimator_verdict(skill) -> str:
    if not isfinite(skill):
        return "skill無法判定；不得據此宣稱可用於價格門檻"
    if skill <= 0:
        return "輸給樸素預測（skill≤0）；依預註冊不得用於任何價格門檻"
    return "skill>0；不代表已通過BT2或已取得價格門檻依據"


def main() -> None:
    out = init_output()
    dates = replay_dates(START, END)
    d = data.load_all()
    records = []

    for rd in dates:
        universe = eligible_universe(d, rd)
        point_records = []
        for t, point in universe.items():
            features = {
                "ttm_relative": np.nan,
                "ttm_history_n": 0,
                "revenue_growth_3m": np.nan,
                "nonop_level": "unknown",
            }
            try:
                pit = point_in_time(d, t, rd)
                if pit is not None:
                    features = past_features(
                        pit["q"], pit["monthly"], point["eps_ttm"]
                    )
            except Exception as exc:
                log_error(t, rd, "bt1_past_features", exc)
            # 僅供評分的目標日期；不參與 PIT 分層。
            target_end = (
                pd.Timestamp(point["q_last"]).to_period("Q-DEC") + 4
            ).end_time.normalize()
            point_records.append(
                {
                    **point,
                    **features,
                    "target4_end": target_end,
                    "ttm_class": "unknown",
                }
            )

        valid_ratios = [
            r["ttm_relative"] for r in point_records
            if isfinite(r["ttm_relative"])
        ]
        p80 = float(np.percentile(valid_ratios, 80)) if valid_ratios else np.nan
        for row in point_records:
            if isfinite(row["ttm_relative"]) and isfinite(p80):
                row["ttm_class"] = (
                    "high" if row["ttm_relative"] >= p80 else "not_high"
                )
            records.append(row)
        pop, _ = population_tables(d, [rd])
        p = pop.iloc[0]
        print(
            f"BT1 {rd.date()} 現行={p['current_tickers']} "
            f"母體={p['base_universe']} eligible={len(universe)} "
            f"NC={p['NC_n']} F4={p['F4_n']}",
            flush=True,
        )

    frame = pd.DataFrame(records)
    if frame.empty:
        frame = pd.DataFrame(columns=BASE_COLUMNS)
    for c in ("rd", "q_last", "target4_end"):
        frame[c] = pd.to_datetime(frame[c])
    for c in (
        "eps_nc", "eps_f4", "eps_ttm", "target4", "target_nc",
        "ttm_relative", "revenue_growth_3m",
    ):
        frame[c] = pd.to_numeric(frame[c], errors="coerce")

    error_rows, ic_rows = [], []
    error_summaries, ic_summaries = {}, {}
    for cut in CUTS:
        cut_frame = select_cut(frame, cut)
        for stratum in STRATA:
            a = select_stratum(cut_frame, stratum)
            for model in ("F4", "NC"):
                summary = {
                    "scope": "all",
                    "cut": cut,
                    "stratum": stratum,
                    "rd": "ALL",
                    "model": model,
                    **error_stats(a, model),
                }
                error_rows.append(summary)
                error_summaries[(cut, stratum, model)] = summary
                for rd in dates:
                    error_rows.append(
                        {
                            "scope": "point",
                            "cut": cut,
                            "stratum": stratum,
                            "rd": rd.date().isoformat(),
                            "model": model,
                            **error_stats(a.loc[a["rd"].eq(rd)], model),
                        }
                    )

            points, summary = ic_analysis(a, dates)
            for row in points:
                ic_rows.append(
                    {
                        **row,
                        "rd": pd.Timestamp(row["rd"]).date().isoformat(),
                        "cut": cut,
                        "stratum": stratum,
                    }
                )
            summary.update(cut=cut, stratum=stratum)
            ic_summaries[(cut, stratum)] = summary

    for stratum in STRATA:
        full = ic_summaries[("all", stratum)]
        excluded = ic_summaries[("exclude_2026", stratum)]
        direction_unchanged = positive_direction(excluded)
        passed = bool(
            isfinite(full["ci_low"]) and full["ci_low"] > 0
            and full["q5_gt_q1"] and direction_unchanged
        )
        full["exclude_2026_direction_unchanged"] = direction_unchanged
        full["growth_signal_pass"] = passed
        excluded["positive_direction"] = direction_unchanged

    for cut in CUTS:
        for stratum in STRATA:
            ic_rows.append(ic_summaries[(cut, stratum)])

    errors = pd.DataFrame(error_rows)
    ics = pd.DataFrame(ic_rows)
    errors.to_csv(out / "bt1_error_by_point.csv", index=False, encoding="utf-8-sig")
    ics.to_csv(out / "bt1_ic.csv", index=False, encoding="utf-8-sig")

    population, failures = population_tables(d, dates)
    full = ic_summaries[("all", "all")]
    excluded = ic_summaries[("exclude_2026", "all")]
    f4 = error_summaries[("all", "all", "F4")]
    nc = error_summaries[("all", "all", "NC")]
    conclusion = "通過" if full["growth_signal_pass"] else "不通過"
    checks = pd.DataFrame(
        [
            {
                "檢查": "平均IC年度區塊bootstrap CI下界>0",
                "數值": full["ci_low"],
                "成立": isfinite(full["ci_low"]) and full["ci_low"] > 0,
            },
            {
                "檢查": "逐點五分位合併後Q5>Q1",
                "數值": number(full[Q_FIELDS[-1]]) - number(full[Q_FIELDS[0]]),
                "成立": full["q5_gt_q1"],
            },
            {
                "檢查": "排除2026目標後平均IC>0且Q5>Q1",
                "數值": excluded["ic_mean"],
                "成立": full["exclude_2026_direction_unchanged"],
            },
        ]
    )

    all_errors = errors.loc[errors["scope"].eq("all")]
    all_ics = ics.loc[ics["scope"].eq("all")]
    point_errors = errors.loc[
        errors["scope"].eq("point") & errors["stratum"].eq("all")
    ]
    point_ics = ics.loc[
        ics["scope"].eq("point") & ics["stratum"].eq("all")
    ]
    failure_totals = (
        failures.groupby("reason", as_index=False)["n"].sum()
        if not failures.empty
        else pd.DataFrame(columns=["reason", "n"])
    )

    text = [
        "# BT1：EPS估計器與成長訊號",
        "",
        f"重播區間 {START}～{END}，共 {len(dates)} 點；"
        f"現行財報代號數 {len(d['qf'])}。",
        "",
        f"## 明確結論：成長訊號{conclusion}",
        "",
        f"- F4：{estimator_verdict(f4['skill'])}。",
        f"- NC：{estimator_verdict(nc['skill'])}。",
        "- 成長訊號通過與否，和估計值能否用於價格門檻是兩件事；"
        "即使成長訊號通過，skill≤0 仍受預註冊禁止條款約束。",
        "",
        md_table(checks),
        "## 口徑",
        "",
        "- 主樣本依預註冊：TTM>0、各模型自己的目標>0、預測有限；"
        "保留非正預測，不套任務文字額外的F4>0篩選。",
        "- e=(預測−實際)/實際；MAE在本報告專指中位絕對相對誤差，"
        "不是平均絕對誤差。skill=1−模型MAE/同樣本樸素MAE；"
        "樸素MAE=0時skill記NA。",
        "- TTM不變與去年同季不變在本口徑完全等價："
        "未來四季各取去年同季，合計仍為Q_last−3..Q_last的TTM，故只保留一個基準。",
        "- TTM分層：最近20個季度終點計算連續四季TTM，至少12個有效值且"
        "歷史中位數>0，取當期TTM/該中位數；逐點橫斷面P80以上為high，"
        "其餘可分層者為not_high，不可分層者另列。",
        "- 營收符號為最近連續三月合計對去年同期；零與未知不硬塞進正／負。",
        "- 業外分層沿用當時detect.nonop_gate的ok/degrade/block，"
        "不因業外檢查失敗而從BT1母體刪除。",
        "- IC以pandas平均名次計算Pearson of ranks；每點等權。"
        "NW使用Bartlett權重、lag=3，缺失IC先略去。"
        f"年度區塊bootstrap固定seed={BOOTSTRAP_SEED}、{BOOTSTRAP_DRAWS}次，"
        "抽重播年並保留該年全部有效IC，對抽到的逐點IC求平均；少於兩年CI記NA。",
        "- 五分位在各點、各分層、各排除口徑內重分組，再合併個股觀察值取實際成長中位數；"
        "相同訊號不以代號任意拆開，可能出現空分位。單調定義Q1≤Q2≤...≤Q5；"
        "通過標準只要求Q5>Q1，不擅加單調條件。",
        "- 排除2026：Q_last+4季末≥2026-01-01的觀察值整筆剔除，"
        "同時重算F4、NC誤差及IC；方向不變定義為平均IC>0且Q5>Q1。",
        "- 以下所有誤差、成長與報酬均為小數比率，非百分比。",
        "",
        "## 母體與NC/F4可算比例",
        "",
        "base_universe為≥8季、有毛利、最近連續四季TTM>0；eligible另要求nowcast.ok。"
        "NC/F4比例分母為base_universe，不是已成功的eligible。",
        "",
        md_table(population),
        "## 失敗／缺值原因",
        "",
        "正常不合格原因與部分預測缺值如下；真正單檔例外另追加至errors.csv。"
        "同一觀察值可能同時計入NC缺值與F4缺值。",
        "",
        md_table(failure_totals),
        "### 逐點原因",
        "",
        md_table(failures),
        "## 全樣本及各分層誤差（含排除2026）",
        "",
        md_table(
            all_errors,
            ["cut", "stratum", "model", *ERROR_FIELDS],
        ),
        "## 全體逐重播點誤差",
        "",
        md_table(
            point_errors,
            ["cut", "rd", "model", *ERROR_FIELDS],
        ),
        "## IC、NW、bootstrap與五分位（含各分層、排除2026）",
        "",
        md_table(
            all_ics,
            [
                "cut", "stratum", "n", "ic_points", "ic_mean", "nw_t",
                "bootstrap_years", "ci_low", "ci_high", *Q_FIELDS,
                "q5_gt_q1", "quintiles_monotonic",
                "exclude_2026_direction_unchanged", "growth_signal_pass",
            ],
        ),
        "## 全體逐點IC與五分位",
        "",
        md_table(point_ics, ["cut", "rd", "n", "ic", *Q_FIELDS]),
        "完整逐點×分層資料見bt1_error_by_point.csv及bt1_ic.csv；"
        "scope=all為合併摘要，scope=point為逐點。",
        "",
        "## 已知限制",
        "",
        LIMITATIONS,
        "",
    ]
    (out / "bt1_summary.md").write_text("\n".join(text), encoding="utf-8")


if __name__ == "__main__":
    main()
