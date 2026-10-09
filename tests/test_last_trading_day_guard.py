"""自建上游改每週收集：只在「當週最後交易日」跑（scripts/last_trading_day_guard.py）。"""
from __future__ import annotations

import importlib.util
from datetime import date, datetime
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "guard", Path(__file__).resolve().parents[1] / "scripts" / "last_trading_day_guard.py")
g = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(g)

# 2026 官方休市表的片段（含「最後交易日」「開始交易日」這類有交易的標記列）
ROWS = [
    {"Name": "國慶日", "Date": "1151009", "Weekday": "五"},                    # 10-09（週五）補假
    {"Name": "國慶日", "Date": "1151010", "Weekday": "六"},
    {"Name": "農曆春節前最後交易日", "Date": "1150211", "Weekday": "三"},       # 有交易，不是休市
    {"Name": "市場無交易，僅辦理結算交割作業", "Date": "1150212", "Weekday": "四"},
    {"Name": "市場無交易，僅辦理結算交割作業", "Date": "1150213", "Weekday": "五"},
    {"Name": "國曆新年開始交易日", "Date": "1150102", "Weekday": "五"},         # 有交易
]
CLOSED = g.closed_dates(ROWS)


def test_closed_dates_excludes_open_markers():
    assert date(2026, 10, 9) in CLOSED and date(2026, 2, 12) in CLOSED
    assert date(2026, 2, 11) not in CLOSED and date(2026, 1, 2) not in CLOSED      # 最後交易日／開始交易日是有交易的


def test_normal_friday_is_last_trading_day():
    assert g.is_last_trading_day_of_week(date(2026, 10, 16), CLOSED)               # 一般週五
    assert not g.is_last_trading_day_of_week(date(2026, 10, 15), CLOSED)           # 同週週四不是


def test_thursday_before_friday_holiday_is_last_trading_day():
    assert g.is_last_trading_day_of_week(date(2026, 10, 8), CLOSED)                # 10-09 週五補假 → 週四是當週最後交易日
    assert not g.is_last_trading_day_of_week(date(2026, 10, 7), CLOSED)
    assert not g.is_last_trading_day_of_week(date(2026, 10, 9), CLOSED)            # 休市日本身不是


def test_long_holiday_week():
    assert g.is_last_trading_day_of_week(date(2026, 2, 11), CLOSED)                # 春節前最後交易日（週三）：之後 02-12、02-13 休市
    assert not g.is_last_trading_day_of_week(date(2026, 2, 10), CLOSED)


def test_weekend_is_never_run():
    assert not g.is_last_trading_day_of_week(date(2026, 10, 10), CLOSED)           # 週六
    assert not g.is_last_trading_day_of_week(date(2026, 10, 11), CLOSED)           # 週日


def test_decide_fail_open_and_dispatch():
    assert g.decide(date(2026, 10, 7), None)[0] is True                            # 抓不到休市表 → 照跑
    assert g.decide(date(2026, 10, 7), CLOSED, event="workflow_dispatch")[0] is True
    assert g.decide(date(2026, 10, 7), CLOSED)[0] is False
    assert g.decide(date(2026, 10, 8), CLOSED)[0] is True


def test_roc_date_parse():
    assert g._roc("1151009") == date(2026, 10, 9)
    assert g._roc("1150102") == date(2026, 1, 2)


def test_force_run_dates_override(monkeypatch):
    monkeypatch.setattr(g, "FORCE_RUN_DATES", {date(2026, 10, 7)})
    assert g.decide(date(2026, 10, 7), CLOSED)[0] is True                       # 指定補跑日：平常會跳過的週三也跑
    assert g.decide(date(2026, 10, 7), CLOSED)[1].endswith("執行")
    monkeypatch.setattr(g, "FORCE_RUN_DATES", set())
    assert g.decide(date(2026, 10, 7), CLOSED)[0] is False


def test_effective_date_late_schedule_counts_as_previous_day():
    # 2026-10-06 實測：23:59 那班（當時 cron `59 15`；10/7 起改 `58 15`）延遲到 10-07 04:47 才觸發，要算 10-06
    assert g.effective_date(datetime(2026, 10, 7, 4, 47)) == date(2026, 10, 6)
    assert g.effective_date(datetime(2026, 10, 7, 7, 59)) == date(2026, 10, 7 - 1)
    assert g.effective_date(datetime(2026, 10, 7, 9, 30)) == date(2026, 10, 6)        # 延遲 9.5 小時（本 repo 實測最長約 8.8）
    assert g.effective_date(datetime(2026, 10, 7, 23, 59)) == date(2026, 10, 7)       # 準時
    assert g.effective_date(datetime(2026, 10, 7, 4, 47), "workflow_dispatch") == date(2026, 10, 7)


def test_late_thursday_before_holiday_still_runs():
    # 10-08（週四）班延遲到 10-09 凌晨（休市日）：不能被誤判成「休市略過」
    d = g.effective_date(datetime(2026, 10, 9, 3, 30))
    assert d == date(2026, 10, 8) and g.decide(d, CLOSED)[0] is True
    # 週五班延遲到週六凌晨：算週五
    d = g.effective_date(datetime(2026, 10, 17, 2, 0))
    assert d == date(2026, 10, 16) and g.decide(d, CLOSED)[0] is True


def test_force_dates_cleared():
    assert not g.FORCE_RUN_DATES


# ── R2 自癒：已發佈 manifest 有洞或落後 → 非週最後交易日也跑 ──

def test_selfheal_gaps_runs_midweek():
    run, why = g.decide(date(2026, 10, 7), CLOSED, published={"complete_day": "2026-10-06", "gaps": {"TWO": ["2026-10-02"]}})
    assert run is True and "自建資料包有洞或落後" in why


def test_selfheal_lagging_runs_midweek():
    # 週四 10-15 23:58：今天之前最近交易日＝10-14，完整日 10-13 落後 1 → 補收
    run, why = g.decide(date(2026, 10, 15), CLOSED, published={"complete_day": "2026-10-13", "gaps": {}})
    assert run is True and "自建資料包有洞或落後" in why


def test_selfheal_lag_skips_holiday():
    # 週一 10-12 之前最近交易日＝10-08（10-09 補假、週末）；完整日 10-08 不算落後 → 維持原判斷（非週最後交易日）
    assert g.decide(date(2026, 10, 12), CLOSED, published={"complete_day": "2026-10-08", "gaps": {}})[0] is False


def test_selfheal_healthy_keeps_original_decision():
    ok = {"complete_day": "2026-10-14", "gaps": {}}
    assert g.decide(date(2026, 10, 15), CLOSED, published=ok)[0] is False
    assert g.decide(date(2026, 10, 16), CLOSED, published=ok)[0] is True       # 週五照舊
    assert g.decide(date(2026, 10, 15), CLOSED, published=None)[0] is False    # 沒下載到 manifest


def test_selfheal_never_runs_on_closed_day():
    bad = {"complete_day": "2026-10-01", "gaps": {"TW": ["2026-10-02"]}}
    assert g.decide(date(2026, 10, 9), CLOSED, published=bad)[0] is False      # 休市日
    assert g.decide(date(2026, 10, 10), CLOSED, published=bad)[0] is False     # 週六
