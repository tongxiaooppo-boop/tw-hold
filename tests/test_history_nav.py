"""推薦回顧逐日翻閱：只翻「主畫面那天以前」的日子（2026-10-16）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _d(d, state, origin=None, n=0):
    r = {"d": d, "wd": "一", "state": state, "n": n}
    if origin:
        r["origin"] = origin
    return r


def test_排除主畫面那天_新到舊_略過休市():
    import streamlit_app as sa
    days = [_d("2026-10-07", "zero", "live"), _d("2026-10-08", "ok", "live", 2), _d("2026-10-09", "holiday"),
            _d("2026-10-12", "recomp", "backfill-csv", 3), _d("2026-10-13", "notrun"),
            _d("2026-10-14", "ok", "live", 1), _d("2026-10-15", "pending")]
    got = [x["d"] for x in sa._hist_past_days(days)]
    assert got == ["2026-10-13", "2026-10-12", "2026-10-08", "2026-10-07"]


def test_純補算日不算主畫面那天():
    import streamlit_app as sa
    days = [_d("2026-10-01", "recomp", "recompute", 2), _d("2026-10-02", "ok", "live", 1),
            _d("2026-10-05", "recomp", "recompute", 1)]
    assert [x["d"] for x in sa._hist_past_days(days)] == ["2026-10-01"]


def test_沒有任何紀錄():
    import streamlit_app as sa
    assert sa._hist_past_days([_d("2026-10-15", "pending")]) == []
