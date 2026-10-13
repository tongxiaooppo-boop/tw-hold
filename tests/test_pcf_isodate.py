"""PCF 日期解析（scripts/pcf_fetchers._isodate）：統一 ezmoney 的 `/Date(ms)/` 是台北午夜，不能用 UTC 取日期。"""
from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "pf", Path(__file__).resolve().parents[1] / "scripts" / "pcf_fetchers.py")
pf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pf)

TPE = timezone(timedelta(hours=8))


def _asp(y, m, d, suffix=""):
    return f"/Date({int(datetime(y, m, d, tzinfo=TPE).timestamp() * 1000)}{suffix})/"


@pytest.mark.parametrize("ymd", [(2026, 10, 12), (2026, 10, 5), (2026, 9, 21), (2026, 1, 1)])
def test_asp_net_date_is_taipei_midnight_not_previous_utc_day(ymd):
    assert pf._isodate(_asp(*ymd)) == f"{ymd[0]:04d}-{ymd[1]:02d}-{ymd[2]:02d}"      # 以前會少一天（週一變週日）


def test_asp_net_date_with_offset_suffix_and_other_formats_unchanged():
    assert pf._isodate(_asp(2026, 10, 12, "+0800")) == "2026-10-12"
    assert pf._isodate("2026-10-12T00:00:00") == "2026-10-12"                          # 同一天另一台 server 回 ISO：兩種格式必須同一天
    assert pf._isodate("115/10/12") == "2026-10-12"
    assert pf._isodate("0001-01-01T00:00:00") == "0001-01-01"                          # 沒資料的占位值照舊（由呼叫端以持股數判斷）
    assert pf._isodate("") == "" and pf._isodate(None) == ""


def test_both_server_formats_give_same_data_date():
    assert pf._isodate("2026-10-12T00:00:00") == pf._isodate(_asp(2026, 10, 12))
