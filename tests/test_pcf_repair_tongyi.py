"""統一 PCF 快照日期修補（scripts/pcf_repair_tongyi.py）：依內容對回真實日、連鎖改標不互相覆蓋、補回消失日、只收 post_date＝查詢日的回應。"""
from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import pandas as pd

_spec = importlib.util.spec_from_file_location(
    "rp", Path(__file__).resolve().parents[1] / "scripts" / "pcf_repair_tongyi.py")
rp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rp)

DAYS = ["2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24", "2026-09-28"]      # 真實交易日（週一～四、下週一）


def _hold(i):                                  # 每個真實日的持股：股數不同（內容指紋不同）
    return [{"stock_code": "2330", "stock_name": "台積電", "shares": 1000.0 + i, "weight": 10.0, "market_value": 1.0, "price": 1.0},
            {"stock_code": "2317", "stock_name": "鴻海", "shares": 500.0, "weight": 5.0, "market_value": 1.0, "price": 1.0}]


def _truth():
    return {d: {"data_date": d, "post_date": d, "holdings": _hold(i), "nav": 10.0 + i, "units": 1.0} for i, d in enumerate(DAYS)}


def _snap(i, label):
    df = pd.DataFrame(_hold(i))
    df["fund_nav"], df["fund_units"], df["fund_close"], df["fund_close_date"], df["data_date"] = 10.0 + i, 1.0, 50.0 + i, "x", label
    return df


def _write(d, snaps):
    d.mkdir(parents=True, exist_ok=True)
    for lab, df in snaps.items():
        df.to_parquet(d / f"{lab}.parquet", index=False)


def _bad_store():
    # 真實 9/21、9/22、9/23、9/24：標早一天（9/20、9/21、9/22、9/23）＋9/24 又存了一份標對的（重複）；9/28 完全沒存（被蓋掉）
    return {"2026-09-20": _snap(0, "2026-09-20"), "2026-09-21": _snap(1, "2026-09-21"), "2026-09-22": _snap(2, "2026-09-22"),
            "2026-09-23": _snap(3, "2026-09-23"), "2026-09-24": _snap(3, "2026-09-24")}


def test_plan_relabels_by_content_drops_duplicates_and_fills_missing():
    plan = rp.plan_fund(_bad_store(), _truth(), keep=15)
    assert plan["relabel"] == {"2026-09-20": "2026-09-21", "2026-09-21": "2026-09-22", "2026-09-22": "2026-09-23"}
    assert plan["drop"] == ["2026-09-23"]                                  # 內容＝9/24，檔名標 9/23 的那份是重複
    assert plan["fill"] == ["2026-09-28"] and plan["unmatched"] == []
    assert plan["keep_final"] == DAYS


def test_apply_handles_chained_relabel_without_overwriting_and_keeps_close_columns(tmp_path):
    d = tmp_path / "00981A"
    _write(d, _bad_store())
    stored = {p.stem: pd.read_parquet(p) for p in sorted(d.glob("20*.parquet"))}
    plan = rp.plan_fund(stored, _truth(), keep=15)
    rp.apply_fund(d, stored, _truth(), plan)
    assert sorted(p.stem for p in d.glob("*.parquet")) == DAYS
    for i, day in enumerate(DAYS[:4]):                                     # 每個日期檔裡的內容都是該日的（連鎖改標沒有互相覆蓋）
        df = pd.read_parquet(d / f"{day}.parquet")
        assert df["data_date"].iloc[0] == day and df["shares"].iloc[0] == 1000.0 + i
        assert df["fund_close"].iloc[0] == 50.0 + i                        # 既有快照的收盤價欄位保留
    filled = pd.read_parquet(d / "2026-09-28.parquet")
    assert filled[filled.stock_code == "2330"]["shares"].iloc[0] == 1004.0 and filled["fund_close"].isna().all()      # 補回的沒有收盤價（折溢價會被略過）


def test_unmatched_snapshots_are_kept_and_reported():
    odd = _snap(9, "2026-09-10")                                           # 內容對不到任何 API 日（例如早於查詢範圍）
    plan = rp.plan_fund({**_bad_store(), "2026-09-10": odd}, _truth(), keep=15)
    assert plan["unmatched"] == ["2026-09-10"] and "2026-09-10" in plan["keep_final"] and "2026-09-10" not in plan["relabel"]


def test_keep_window_prunes_oldest():
    plan = rp.plan_fund(_bad_store(), _truth(), keep=3)
    assert plan["keep_final"] == DAYS[-3:] and plan["pruned"] == DAYS[:2]
    assert plan["fill"] == ["2026-09-28"]                                  # 補回的在窗口內才補


def test_correct_labels_produce_no_changes():
    good = {d: _snap(i, d) for i, d in enumerate(DAYS)}
    plan = rp.plan_fund(good, _truth(), keep=15)
    assert plan["relabel"] == {} and plan["drop"] == [] and plan["fill"] == [] and plan["keep_final"] == DAYS


def test_fetch_truth_only_accepts_response_whose_post_date_matches_the_query():
    def fake(fund_id, d):                                                  # 假的 API：查 9/23 卻回 post_date 9/22（API 不保證回哪天）
        post = "2026-09-22" if d == date(2026, 9, 23) else d.isoformat()
        return {"data_date": f"data-{d}", "post_date": post, "holdings": _hold(0), "nav": 1.0, "units": 1.0}
    t = rp.fetch_truth("49YTW", date(2026, 9, 21), date(2026, 9, 25), fetch_day=fake, sleep=0)
    assert sorted(t) == ["data-2026-09-21", "data-2026-09-22", "data-2026-09-24", "data-2026-09-25"]    # 9/23 那筆被丟掉
    assert rp.fetch_truth("x", date(2026, 9, 26), date(2026, 9, 27), fetch_day=fake, sleep=0) == {}      # 週末不查
