"""B2 配套：merge_manifest.json 附 closed_days（休市日），swing 端才不會在連假後多算一天落後。"""
from __future__ import annotations

import json
import sys
from datetime import date

import pandas as pd

sys.path.insert(0, "scripts")
import last_trading_day_guard as g  # noqa: E402
import selfhost_daily_merge as dm  # noqa: E402


def test_closed_days_只留平日_排序_來源標記():
    days, src = dm.closed_days_for_manifest(lambda: {date(2026, 10, 26), date(2026, 10, 10), date(2026, 10, 9)})
    assert days == ["2026-10-09", "2026-10-26"]                      # 10/10 是週六，不需要列
    assert src == "twse_holidaySchedule"


def test_closed_days_抓不到_fail_open():
    assert dm.closed_days_for_manifest(lambda: None) == ([], "unavailable")
    assert dm.closed_days_for_manifest(lambda: set()) == ([], "unavailable")

    def boom():
        raise RuntimeError("連不上")
    assert dm.closed_days_for_manifest(boom) == ([], "unavailable")


def test_main_manifest有closed_days(tmp_path, monkeypatch):
    from tests.test_selfhost_events_daily_merge_main import _setup
    (tmp_path / "x").mkdir()
    w, dd, o = _setup(tmp_path / "x", with_meta=True)
    monkeypatch.setattr(g, "fetch_closed", lambda: {date(2026, 10, 26)})
    assert dm.main(["--weekly-dir", str(w), "--daily-dir", str(dd), "--out-dir", str(o)]) == 0
    man = json.loads((o / "merge_manifest.json").read_text(encoding="utf-8"))
    assert man["closed_days"] == ["2026-10-26"] and man["closed_days_source"] == "twse_holidaySchedule"


def test_main_休市表抓不到_manifest照樣產出(tmp_path, monkeypatch):
    from tests.test_selfhost_events_daily_merge_main import _setup
    (tmp_path / "x").mkdir()
    w, dd, o = _setup(tmp_path / "x", with_meta=True)
    monkeypatch.setattr(g, "fetch_closed", lambda: None)
    assert dm.main(["--weekly-dir", str(w), "--daily-dir", str(dd), "--out-dir", str(o)]) == 0
    man = json.loads((o / "merge_manifest.json").read_text(encoding="utf-8"))
    assert man["closed_days"] == [] and man["closed_days_source"] == "unavailable"


def test_closed_days_不影響input_hash(tmp_path, monkeypatch):
    """休市表更新（例如年中補公告）不應讓資料包無謂重做：雜湊只算資料檔。"""
    from tests.test_selfhost_events_daily_merge_main import _setup
    (tmp_path / "x").mkdir()
    w, dd, o = _setup(tmp_path / "x", with_meta=True)
    monkeypatch.setattr(g, "fetch_closed", lambda: {date(2026, 10, 26)})
    dm.main(["--weekly-dir", str(w), "--daily-dir", str(dd), "--out-dir", str(o)])
    h1 = json.loads((o / "merge_manifest.json").read_text(encoding="utf-8"))["input_hash"]
    monkeypatch.setattr(g, "fetch_closed", lambda: {date(2026, 10, 26), date(2026, 12, 25)})
    dm.main(["--weekly-dir", str(w), "--daily-dir", str(dd), "--out-dir", str(tmp_path / "o2")])
    h2 = json.loads((tmp_path / "o2" / "merge_manifest.json").read_text(encoding="utf-8"))["input_hash"]
    assert h1 == h2
