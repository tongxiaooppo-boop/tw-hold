# bt2.py
# 預註冊優先，不更動G0/G1/G2/G3與四條通過標準。
# §2括註提及高成長3年/50，但沒有預註冊可重播的高成長識別規則；
# §3及本任務又禁止任何分類。本腳本不自行新增高成長分類門檻，
# 所有非金融PE樣本固定採任務明定的5年、48個月、cap=30。
# 12個月的交易日操作口徑依任務明定：次一交易日open進場，其後第252日close出場。
# 「相鄰方向一致」的固定實作：G0→G1→G2→G3的全樣本內外超額差同為正，
# 不另新增未預註冊的差值大小單調要求；P20只作子群報告，不作第五個候選。
from __future__ import annotations

import sys
from collections import Counter
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
import replay as _replay
_replay.OUT = _replay.HERE / 'out_v11'   # v1.1：修正 astra 審查第 1 條（分組現價前視）
from screener import detect, multiples
from replay import (
    COST,
    LIMITATIONS,
    PRICE_CHECK,
    eligible_universe,
    init_output,
    isfinite,
    known_price,
    log_error,
    md_table,
    number,
    point_in_time,
    population_tables,
    ratio,
    replay_dates,
    scoring_schedule,
    scoring_trade,
)

START = "2023-08-15"
END = "2025-08-15"
EXCLUDE_EXIT_FROM = pd.Timestamp("2026-01-01")
BAND_YEARS = 5
MIN_MONTHS = 48
PE_CAP = 30.0
EVENT_THRESHOLD = 0.03
MAIN_GROUPS = ("G0", "G1", "G2", "G3")
P20_GROUPS = tuple(f"{g}_P20" for g in MAIN_GROUPS)
GROUPS = MAIN_GROUPS + P20_GROUPS
GROWTH_FACTORS = {"G1": 1.00, "G2": 1.05, "G3": 1.10}
TOP_N = 10
DISCLAIMER = (
    "獨立年度約 3、樣本為現行上市櫃（存活者偏差）、"
    "區間內外同時暴露於 2026 超級循環；即使通過只算方向性證據"
)
SCORED_COLUMNS = [
    "t", "rd", "entry_date", "exit_date", "ret", "ret_net",
    "benchmark_0050", "ew_return", "excess", "excess_net",
    "buyable", *GROUPS,
]


def prediction_record(d, t, rd, point) -> dict:
    """純PIT選股路徑：不讀target*、進場open、出場close或未來報酬。"""
    result = {
        "t": t,
        "rd": rd,
        "buyable": False,
        "known_price_date": pd.NaT,
        "known_price": np.nan,
        "n_months": np.nan,
        "confidence": "未計算",
        "event_blocked": False,
        "reasons": [],
        **dict.fromkeys(GROUPS, False),
    }
    pit = point_in_time(d, t, rd)
    if pit is None:
        result["reasons"].append("PIT不可用")
        return result

    q, monthly, per = pit["q"], pit["monthly"], pit["per"]
    b = multiples.band(
        per,
        "per",
        years=BAND_YEARS,
        min_months=MIN_MONTHS,
        cap=PE_CAP,
        asof=rd,
    )
    result["n_months"] = b.get("n_months", np.nan)
    p = multiples.prices(point["eps_nc"], b)

    checks = [
        detect.nonop_gate(q),
        detect.revenue_caliber(q, monthly),
        detect.bridge_residual(q, point["params"]),
        detect.shares_check(q),
    ]
    checks.extend(
        detect.Check("NC旗標", "degrade", None, str(flag))
        for flag in point["flags"]
    )
    checks.extend(
        [
            detect.dist_check(b),
            detect.near_zero_eps(
                point["eps_nc"] if isfinite(point["eps_nc"]) else None, q
            ),
        ]
    )
    confidence = detect.confidence(checks)
    result["confidence"] = confidence["level"]

    events_map = d.get("events", {})
    events = events_map.get(t)
    if events is None:
        result["reasons"].append("股數事件資料未知")
        result["event_blocked"] = True
    else:
        window_start = rd - pd.DateOffset(years=BAND_YEARS)
        for event_date, multiplier in events:
            event_date = pd.Timestamp(event_date)
            future = rd <= event_date <= rd + pd.DateOffset(months=15)
            if not (window_start <= event_date < rd) and not future:
                continue
            multiplier = number(multiplier)
            if not isfinite(multiplier):
                result["event_blocked"] = True
                result["reasons"].append("窗內股數事件倍率缺值")
                break
            if round(abs(multiplier - 1), 9) >= EVENT_THRESHOLD:
                result["event_blocked"] = True
                result["reasons"].append("窗內股數事件>=3%")
                break

    price_date, price = known_raw_price(d, t, rd)
    result["known_price_date"] = price_date
    result["known_price"] = price
    if not b.get("ok", False):
        result["reasons"].append("PER有效月數不足")
    if p is None:
        result["reasons"].append("無法給三價")
    elif not all(
        isfinite(p.get(name)) and p[name] > 0
        for name in ("cheap", "fair", "dear")
    ):
        result["reasons"].append("三價非有限或非正")
    if confidence["level"] not in ("高", "中"):
        result["reasons"].append("可信度" + confidence["level"])
    if not isfinite(price) or price <= 0:
        result["reasons"].append("前一市場交易日收盤缺價")

    if result["reasons"]:
        return result

    result["buyable"] = True
    result["G0"] = bool(price <= p["fair"])
    f4, ttm = number(point["eps_f4"]), number(point["eps_ttm"])
    for group, factor in GROWTH_FACTORS.items():
        result[group] = bool(
            result["G0"] and isfinite(f4) and isfinite(ttm)
            and f4 >= factor * ttm
        )
    cheap = price <= p["cheap"]
    for group in MAIN_GROUPS:
        result[f"{group}_P20"] = bool(result[group] and cheap)
    return result


def mean_value(frame: pd.DataFrame, column: str) -> float:
    if frame.empty:
        return np.nan
    values = pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype=float)
    values = values[np.isfinite(values)]
    return float(values.mean()) if len(values) else np.nan


def positive_rate(values) -> float:
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    return float(np.mean(values > 0)) if len(values) else np.nan


def side_metrics(frame: pd.DataFrame, prefix: str) -> dict:
    result = {
        f"n_{prefix}": len(frame),
        f"stocks_{prefix}": frame["t"].nunique() if not frame.empty else 0,
        f"{prefix}_return": mean_value(frame, "ret"),
        f"{prefix}_return_net": mean_value(frame, "ret_net"),
        f"{prefix}_excess": mean_value(frame, "excess"),
        f"{prefix}_excess_net": mean_value(frame, "excess_net"),
        f"{prefix}_ew_return": mean_value(frame, "ew_return"),
        f"{prefix}_0050_return": mean_value(frame, "benchmark_0050"),
    }
    if frame.empty:
        for key in (
            "win_rate", "win_rate_net", "excess_win_rate",
            "excess_win_rate_net", "0050_excess", "0050_excess_net",
            "0050_win_rate", "0050_n",
        ):
            result[f"{prefix}_{key}"] = 0 if key == "0050_n" else np.nan
        return result

    result[f"{prefix}_win_rate"] = positive_rate(frame["ret"])
    result[f"{prefix}_win_rate_net"] = positive_rate(frame["ret_net"])
    result[f"{prefix}_excess_win_rate"] = positive_rate(frame["excess"])
    result[f"{prefix}_excess_win_rate_net"] = positive_rate(frame["excess_net"])
    r = pd.to_numeric(frame["ret"], errors="coerce").to_numpy(dtype=float)
    b = pd.to_numeric(
        frame["benchmark_0050"], errors="coerce"
    ).to_numpy(dtype=float)
    valid = np.isfinite(r) & np.isfinite(b)
    result[f"{prefix}_0050_n"] = int(valid.sum())
    result[f"{prefix}_0050_excess"] = (
        float(np.mean(r[valid] - b[valid])) if valid.any() else np.nan
    )
    result[f"{prefix}_0050_excess_net"] = (
        float(np.mean(r[valid] - COST - b[valid])) if valid.any() else np.nan
    )
    result[f"{prefix}_0050_win_rate"] = (
        positive_rate(r[valid] - b[valid]) if valid.any() else np.nan
    )
    return result


def group_metrics(frame: pd.DataFrame, group: str) -> dict:
    mask = frame[group].fillna(False).astype(bool)
    inside, outside = frame.loc[mask], frame.loc[~mask]
    result = {
        "group": group,
        "n_buyable": len(frame),
        **side_metrics(inside, "in"),
        **side_metrics(outside, "out"),
    }
    result["spread"] = result["in_excess"] - result["out_excess"]
    result["spread_net"] = result["in_excess_net"] - result["out_excess_net"]
    return result


def remove_top_contributors(frame: pd.DataFrame, group: str) -> tuple:
    """以對組內合併平均超額的加總貢獻排序；同檔所有重播觀察整檔移除。"""
    inside = frame.loc[frame[group].fillna(False).astype(bool)]
    if inside.empty:
        return frame.copy(), [], pd.DataFrame(columns=["t", "contribution"])
    contribution = inside.groupby("t", as_index=False)["excess"].sum()
    contribution["contribution"] = contribution["excess"] / len(inside)
    contribution = contribution.sort_values(
        ["contribution", "t"], ascending=[False, True], kind="stable"
    )
    top = contribution.head(TOP_N)
    tickers = top["t"].tolist()
    remaining = frame.loc[~frame["t"].isin(tickers)].copy()
    return remaining, tickers, top[["t", "contribution"]]


def adjacent_direction_consistent(metrics: dict, names) -> bool:
    """四點鏈各相鄰端的內外差均為正；不要求差值大小單調。"""
    for left, right in zip(names[:-1], names[1:]):
        a = number(metrics[left]["spread"])
        b = number(metrics[right]["spread"])
        if not (isfinite(a) and isfinite(b) and a > 0 and b > 0):
            return False
    return True


def band_month_stats(predictions) -> dict:
    values = np.asarray(
        [number(row["n_months"]) for row in predictions], dtype=float
    )
    values = values[np.isfinite(values)]
    if not len(values):
        return {
            "per_months_n": 0,
            "per_months_min": np.nan,
            "per_months_p25": np.nan,
            "per_months_p50": np.nan,
            "per_months_p75": np.nan,
            "per_months_max": np.nan,
            "per_months_ge48": 0,
        }
    q = np.percentile(values, [0, 25, 50, 75, 100])
    return {
        "per_months_n": len(values),
        **dict(
            zip(
                [
                    "per_months_min", "per_months_p25", "per_months_p50",
                    "per_months_p75", "per_months_max",
                ],
                map(float, q),
            )
        ),
        "per_months_ge48": int(np.sum(values >= MIN_MONTHS)),
    }


def bt1_price_restriction(out: Path) -> str:
    """只讀同資料夾既有BT1結果；不把BT1結果拿來改BT2格點或四條判定。"""
    path = out / "bt1_error_by_point.csv"
    if not path.exists():
        return (
            "尚未找到BT1結果：以下僅判定BT2方向性證據，不授權實際價格門檻。"
            "依預註冊，須另確認F4/NC沒有skill≤0的禁止條款。"
        )
    try:
        errors = pd.read_csv(path)
        base = errors.loc[
            errors["scope"].eq("all")
            & errors["cut"].eq("all")
            & errors["stratum"].eq("all")
        ]
        messages = []
        for model in ("F4", "NC"):
            a = base.loc[base["model"].eq(model), "skill"]
            skill = number(a.iloc[0]) if not a.empty else np.nan
            if not isfinite(skill):
                messages.append(f"{model} skill未知，不得據此授權價格門檻")
            elif skill <= 0:
                messages.append(
                    f"{model} skill={skill:.6g}≤0，依預註冊不得用於任何價格門檻"
                )
            else:
                messages.append(f"{model} skill={skill:.6g}>0")
        return "；".join(messages) + "。BT2四條檢查不取代上述先決限制。"
    except Exception as exc:
        log_error("", None, "read_bt1_restriction", exc)
        return "BT1結果讀取失敗；不得將BT2方向性通過視為價格門檻授權。"


def known_raw_price(d, t, rd):
    """v1.1：分組用的現價＝rd 當時的**未還原**收盤價（含息還原價會被 rd 後的股利壓低，等於偷看未來）。
    報酬仍用含息還原價。"""
    raw = d.get('raw', {}).get(t)
    cal = _replay.market_calendar(d)
    i = cal.searchsorted(pd.Timestamp(rd), side='right') - 1
    if raw is None or i < 0:
        return None, np.nan
    date = pd.Timestamp(cal[i])
    row = raw.loc[raw['date'] == date, 'close']
    v = float(row.iloc[0]) if len(row) else np.nan
    return date, (v if np.isfinite(v) and v > 0 else np.nan)


def main() -> None:
    out = init_output()
    dates = replay_dates(START, END)
    d = data.load_all()
    rp = pd.read_parquet(data.UP / 'prices_raw_close.parquet', columns=['ticker', 'date', 'close'])
    rp['ticker'] = data._bare(rp['ticker']); rp['date'] = pd.to_datetime(rp['date'])
    d['raw'] = {k: g.sort_values('date').reset_index(drop=True) for k, g in rp.groupby('ticker')}
    scored_records, audits, reason_rows = [], [], []
    schedules = {}

    for rd in dates:
        universe = eligible_universe(d, rd)
        predictions = []
        for t, point in universe.items():
            try:
                predictions.append(prediction_record(d, t, rd, point))
            except Exception as exc:
                log_error(t, rd, "bt2_prediction_record", exc)
                predictions.append(
                    {
                        "t": t,
                        "rd": rd,
                        "buyable": False,
                        "n_months": np.nan,
                        "confidence": "例外",
                        "event_blocked": False,
                        "reasons": ["估值或可信度例外"],
                        **dict.fromkeys(GROUPS, False),
                    }
                )

        prediction_map = {r["t"]: r for r in predictions}

        # 僅供評分：選股條件已完全凍結，才讀進出場及0050價格。
        schedule = scoring_schedule(d, rd)
        schedules[rd] = schedule
        priced = []
        price_failures = Counter()
        for t in universe:
            score = scoring_trade(d, t, rd)
            if not score["ok"]:
                price_failures[score["reason"]] += 1
                continue
            prediction = prediction_map[t]
            priced.append(
                {
                    "t": t,
                    "rd": rd,
                    "entry_date": score["entry_date"],
                    "exit_date": score["exit_date"],
                    "ret": score["ret"],
                    "ret_net": score["ret_net"],
                    "benchmark_0050": score["benchmark_0050"],
                    "buyable": prediction["buyable"],
                    **{g: prediction[g] for g in GROUPS},
                }
            )

        ew = float(np.mean([r["ret"] for r in priced])) if priced else np.nan
        for row in priced:
            row["ew_return"] = ew
            row["excess"] = row["ret"] - ew
            # 淨超額對照固定使用未扣成本母體；內外兩側均扣同一成本。
            row["excess_net"] = row["ret_net"] - ew
            scored_records.append(row)

        population, _ = population_tables(d, [rd])
        audit = population.iloc[0].to_dict()
        audit.update(
            {
                **band_month_stats(predictions),
                "entry_date": schedule["entry_date"],
                "exit_date": schedule["exit_date"],
                "priced_universe": len(priced),
                "ew_return": ew,
                "ew_return_net": ew - COST if isfinite(ew) else np.nan,
                "buyable_before_price_scoring": sum(r["buyable"] for r in predictions),
                "buyable_with_returns": sum(r["buyable"] for r in priced),
                "benchmark_0050_n": sum(
                    isfinite(r["benchmark_0050"]) for r in priced
                ),
                "event_blocked": sum(r["event_blocked"] for r in predictions),
            }
        )
        conf = Counter(r["confidence"] for r in predictions)
        for level in ("高", "中", "低", "不給價", "未計算", "例外"):
            audit["confidence_" + level] = conf[level]
        audits.append(audit)

        prediction_failures = Counter(
            reason for r in predictions for reason in r["reasons"]
        )
        for stage, counts in (
            ("可買條件", prediction_failures),
            ("價格評分", price_failures),
        ):
            for reason, n in sorted(counts.items()):
                reason_rows.append(
                    {
                        "rd": rd.date().isoformat(),
                        "stage": stage,
                        "reason": reason,
                        "n": n,
                    }
                )
        print(
            f"BT2 {rd.date()} 母體={audit['base_universe']} "
            f"eligible={len(universe)} 有報酬={len(priced)} "
            f"可買有報酬={audit['buyable_with_returns']} "
            f"NC={audit['NC_n']} F4={audit['F4_n']}",
            flush=True,
        )

    scored = pd.DataFrame(scored_records)
    if scored.empty:
        scored = pd.DataFrame(columns=SCORED_COLUMNS)
    for c in ("rd", "entry_date", "exit_date"):
        scored[c] = pd.to_datetime(scored[c])
    for g in ("buyable", *GROUPS):
        scored[g] = scored[g].fillna(False).astype(bool)
    buyable = scored.loc[scored["buyable"]].copy()
    audit_frame = pd.DataFrame(audits)
    audit_map = {
        pd.Timestamp(a["rd"]): a for a in audits
    }

    point_rows = []
    for rd in dates:
        a = buyable.loc[buyable["rd"].eq(rd)]
        for group in GROUPS:
            point_rows.append(
                {
                    "scope": "point",
                    "rd": rd.date().isoformat(),
                    **group_metrics(a, group),
                    **{
                        key: value
                        for key, value in audit_map[rd].items()
                        if key != "rd"
                    },
                }
            )
    point_frame = pd.DataFrame(point_rows)
    point_frame.to_csv(
        out / "bt2_groups.csv", index=False, encoding="utf-8-sig"
    )

    # 僅供評分的敏感度分析：整個重播點剔除，而非只刪其中個股。
    retained_dates = [
        rd for rd in dates
        if pd.notna(schedules[rd]["exit_date"])
        and schedules[rd]["exit_date"] < EXCLUDE_EXIT_FROM
        and not schedules[rd]["reason"]
    ]
    excluded = buyable.loc[buyable["rd"].isin(retained_dates)]
    full_metrics = {g: group_metrics(buyable, g) for g in GROUPS}
    excluded_metrics = {g: group_metrics(excluded, g) for g in GROUPS}

    chain_ok = adjacent_direction_consistent(full_metrics, MAIN_GROUPS)
    p20_chain_ok = adjacent_direction_consistent(full_metrics, P20_GROUPS)
    checks, summary_rows, top_rows = [], [], []
    passed_groups = []

    for group in GROUPS:
        full = full_metrics[group]
        ex = excluded_metrics[group]
        reduced, removed, contributions = remove_top_contributors(buyable, group)
        trimmed = group_metrics(reduced, group)
        point_spreads = point_frame.loc[
            point_frame["group"].eq(group), "spread"
        ].to_numpy(dtype=float)
        valid_points = int(np.isfinite(point_spreads).sum())
        positive_points = int(np.sum(np.isfinite(point_spreads) & (point_spreads > 0)))
        # 空內/外組的點不以缺值隱藏；分母固定為全部預註冊重播點。
        positive_fraction = ratio(positive_points, len(dates))
        c1_full = isfinite(full["spread"]) and full["spread"] > 0
        c1_excluded = isfinite(ex["spread"]) and ex["spread"] > 0
        c1 = bool(c1_full and c1_excluded)
        c2 = bool(isfinite(positive_fraction) and positive_fraction >= 2 / 3)
        c3 = bool(isfinite(trimmed["spread"]) and trimmed["spread"] > 0)
        c4 = chain_ok if group in MAIN_GROUPS else p20_chain_ok
        passed = bool(c1 and c2 and c3 and c4)

        if group in MAIN_GROUPS and passed:
            passed_groups.append(group)
        checks.append(
            {
                "group": group,
                "candidate": group in MAIN_GROUPS,
                "full_spread": full["spread"],
                "exclude_2026_spread": ex["spread"],
                "C1_full_and_excluded_positive": c1,
                "positive_points": positive_points,
                "valid_comparison_points": valid_points,
                "all_registered_points": len(dates),
                "positive_point_fraction": positive_fraction,
                "C2_at_least_two_thirds": c2,
                "trimmed_spread": trimmed["spread"],
                "trimmed_n_in": trimmed["n_in"],
                "trimmed_n_out": trimmed["n_out"],
                "C3_remove_top10_positive": c3,
                "C4_adjacent_direction": c4,
                "all_four_pass": passed,
                "removed_tickers": ",".join(removed),
            }
        )
        for scope, metrics in (
            ("all", full),
            ("exclude_2026_exit_points", ex),
            ("remove_top10", trimmed),
        ):
            summary_rows.append({"scope": scope, **metrics})
        for row in contributions.to_dict("records"):
            top_rows.append({"group": group, **row})

    check_frame = pd.DataFrame(checks)
    summary_frame = pd.DataFrame(summary_rows)
    top_frame = pd.DataFrame(
        top_rows, columns=["group", "t", "contribution"]
    )
    population, universe_failures = population_tables(d, dates)
    reasons = pd.DataFrame(
        reason_rows, columns=["rd", "stage", "reason", "n"]
    )
    reason_totals = (
        reasons.groupby(["stage", "reason"], as_index=False)["n"].sum()
        if not reasons.empty
        else pd.DataFrame(columns=["stage", "reason", "n"])
    )
    universe_failure_totals = (
        universe_failures.groupby("reason", as_index=False)["n"].sum()
        if not universe_failures.empty
        else pd.DataFrame(columns=["reason", "n"])
    )

    if passed_groups:
        selected = next(g for g in MAIN_GROUPS if g in passed_groups)
        conclusion = (
            f"BT2四條全過的格點：{', '.join(passed_groups)}；"
            f"其中最寬者為 **{selected}**。只成立方向性證據，"
            "實際使用仍受BT1估計器skill禁止條款約束。"
        )
    else:
        conclusion = "**不立買進區間**：四個事前候選沒有任何一個四條全過。"

    restriction = bt1_price_restriction(out)
    point_counts = []
    point_spread_rows = []
    for rd in dates:
        rows = point_frame.loc[point_frame["rd"].eq(rd.date().isoformat())]
        counts = {"rd": rd.date().isoformat()}
        spreads = {"rd": rd.date().isoformat()}
        for group in GROUPS:
            row = rows.loc[rows["group"].eq(group)].iloc[0]
            counts[group + "_in"] = row["n_in"]
            counts[group + "_out"] = row["n_out"]
            spreads[group] = row["spread"]
        point_counts.append(counts)
        point_spread_rows.append(spreads)

    chain_rows = []
    for names, label in ((MAIN_GROUPS, "主格點"), (P20_GROUPS, "P20子群")):
        for left, right in zip(names[:-1], names[1:]):
            a, b = full_metrics[left]["spread"], full_metrics[right]["spread"]
            chain_rows.append(
                {
                    "type": label,
                    "adjacent": f"{left}→{right}",
                    "left_spread": a,
                    "right_spread": b,
                    "same_positive_direction": (
                        isfinite(a) and isfinite(b) and a > 0 and b > 0
                    ),
                }
            )

    text = [
        DISCLAIMER,
        "",
        "# BT2：PE估值帶方向性報酬驗證",
        "",
        f"重播 {START}～{END}，共 {len(dates)} 點；"
        f"現行財報代號數 {len(d['qf'])}。",
        "",
        "## 明確結論",
        "",
        conclusion,
        "",
        "**BT1先決限制：** " + restriction,
        "",
        "## 先決檢查及固定口徑",
        "",
        PRICE_CHECK,
        "",
        "- 全母體為eligible_universe；等權對照使用同點全母體中有完整進出場價者，"
        "包含可信度低、不能給三價、PER月份不足及股數事件被擋的股票。",
        "- PE固定5年、至少48個有效月份、cap=30，per嚴格date<rd。"
        "預註冊沒有可重播高成長識別規則，且禁止分類，因此不自行新增3年/50路線。",
        "- 可信度只用PIT業外、月營收口徑、橋接、股數、NC旗標、倍數分布及近零EPS；"
        "每個NC旗標轉成degrade Check，只留高／中，不用任何股票分類。",
        "- 股數事件窗口為[rd−5年,rd)，|m−1|≥3%排除可買資格；"
        "未知事件資料不冒充沒有事件。被擋者仍保留在有價母體對照。",
        "- 預測選股先凍結，再讀取未來價格評分。進場為rd之後首個市場交易日open；"
        "出場為進場日之後第252個市場交易日close，出場不得晚於2026-10-30。"
        "缺進出場當日價格不遞延、不以前後價格替代。",
        "- 現價為進場前一市場交易日close，日期≤rd；若該股該日缺價，"
        "不向前找舊價，不給可買資格。",
        "- G0為現價≤fair；G1/G2/G3依序另要求F4≥1.00/1.05/1.10×TTM。"
        "G0不因F4缺值自動被刪除。每組P20子群另要求現價≤cheap。",
        "- 各組區間外為同點可買且有報酬母體中不屬該組者；"
        "P20子群的外組是同一可買母體對該P20子群的補集。"
        "P20僅作附帶報告，不加入最寬格點選擇。",
        "- 全樣本以個股×重播點觀察等權合併，先逐點扣除全母體等權R，"
        "再計算內組平均超額減外組平均超額；不是直接比較兩組原始R。",
        "- 淨報酬=R−0.006，淨超額對照固定為未扣成本等權母體；"
        "兩側都扣相同成本，所以內外差與未扣成本版相同。"
        "另列全母體扣成本R供對照。0050為同一進場日及出場日close比。",
        "- 勝率分別列R>0、淨R>0、超額>0、淨超額>0；"
        "0050缺值不剔除有效個股報酬，僅從0050輔助統計分母排除。",
        "- 排除2026出場以整個重播點為單位：只保留預定出場日<2026-01-01的點。"
        "不是只刪部分個股，也不是排除2026之後才開始的年份。",
        "- 四條通過檢查：C1全樣本與排除2026後內外差均>0；"
        "C2逐點差>0比例≥2/3；C3剔除最大10檔貢獻者仍>0；C4相鄰格點方向一致。",
        "- C2分母固定為全部事前重播點；空內組／外組的點保留為NA且不算正點，"
        "不能靠略去空群提高正點比例。",
        "- 最大貢獻者按各股票對組內合併平均超額的貢獻"
        "sum(該股組內超額)/全部組內觀察數排序；選前10個不同代號，"
        "從內外兩側所有重播觀察整檔移除，固定原始等權對照後重算。"
        "不足10檔則全部移除，若無可比較內外組，C3不通過。",
        "- C4操作化為G0→G1→G2→G3每個相鄰端的內外差同為正，"
        "即整條鏈同向；不新增差值大小單調要求。P20的同項僅為子群診斷。",
        "- 表中報酬與比例均為小數比率，非百分比；NA不是0。",
        "",
        "## 母體與NC/F4可算比例",
        "",
        "base_universe為≥8季、有毛利、連續四季TTM>0；"
        "eligible另要求nowcast.ok，NC/F4比例以base_universe為分母。",
        "",
        md_table(population),
        "## 季報／估計器失敗原因",
        "",
        md_table(universe_failure_totals),
        "### 逐點季報／估計器原因",
        "",
        md_table(universe_failures),
        "## PER有效月數、可信度及有價母體先決檢查",
        "",
        md_table(
            audit_frame,
            [
                "rd", "entry_date", "exit_date", "priced_universe",
                "buyable_before_price_scoring", "buyable_with_returns",
                "ew_return", "ew_return_net", "benchmark_0050_n",
                "per_months_n", "per_months_min", "per_months_p25",
                "per_months_p50", "per_months_p75", "per_months_max",
                "per_months_ge48", "event_blocked",
                "confidence_高", "confidence_中", "confidence_低",
                "confidence_不給價", "confidence_未計算", "confidence_例外",
            ],
        ),
        "PER有效月數統計對每點eligible母體計算，不只看通過估值篩選者；"
        "可買資格失敗原因可重複計數。",
        "",
        md_table(reason_totals),
        "### 逐點可買條件／價格失敗原因",
        "",
        md_table(reasons),
        "## 四條通過檢查（主格點及P20子群診斷）",
        "",
        md_table(
            check_frame,
            [
                "group", "candidate", "full_spread", "exclude_2026_spread",
                "C1_full_and_excluded_positive",
                "positive_points", "valid_comparison_points",
                "all_registered_points", "positive_point_fraction",
                "C2_at_least_two_thirds", "trimmed_spread",
                "trimmed_n_in", "trimmed_n_out", "C3_remove_top10_positive",
                "C4_adjacent_direction", "all_four_pass",
            ],
        ),
        "排除2026出場保留重播點："
        + (", ".join(str(rd.date()) for rd in retained_dates) or "無"),
        "",
        "### 相鄰格點方向逐對檢查",
        "",
        md_table(pd.DataFrame(chain_rows)),
        "## 合併報酬、檔數及內外差",
        "",
        "n為個股×重播點觀察數；stocks為不同代號數。",
        "",
        md_table(
            summary_frame,
            [
                "scope", "group", "n_in", "n_out", "stocks_in", "stocks_out",
                "in_return", "out_return", "in_return_net", "out_return_net",
                "in_excess", "out_excess", "in_excess_net", "out_excess_net",
                "spread", "spread_net",
            ],
        ),
        "## 勝率與0050輔助對照",
        "",
        md_table(
            summary_frame.loc[summary_frame["scope"].eq("all")],
            [
                "group", "in_win_rate", "out_win_rate",
                "in_win_rate_net", "out_win_rate_net",
                "in_excess_win_rate", "out_excess_win_rate",
                "in_excess_win_rate_net", "out_excess_win_rate_net",
                "in_0050_n", "out_0050_n",
                "in_0050_return", "out_0050_return",
                "in_0050_excess", "out_0050_excess",
                "in_0050_excess_net", "out_0050_excess_net",
                "in_0050_win_rate", "out_0050_win_rate",
            ],
        ),
        "## 逐點內外檔數",
        "",
        md_table(pd.DataFrame(point_counts)),
        "## 逐點內外超額差",
        "",
        md_table(pd.DataFrame(point_spread_rows)),
        "完整逐點逐組的未扣／扣成本報酬、勝率、0050及先決檢查"
        "寫於bt2_groups.csv。",
        "",
        "## 被剔除的最大10檔貢獻者",
        "",
        md_table(check_frame, ["group", "removed_tickers"]),
        md_table(top_frame),
        "## 已知限制",
        "",
        LIMITATIONS,
        "",
        DISCLAIMER,
        "",
    ]
    (out / "bt2_summary.md").write_text("\n".join(text), encoding="utf-8")


if __name__ == "__main__":
    main()
