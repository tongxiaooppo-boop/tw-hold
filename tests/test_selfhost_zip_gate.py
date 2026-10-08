"""zip 閘門：倒退、縮水、錨點最新收盤≠官方未還原收盤，都要擋。"""
from __future__ import annotations

import sys
import zipfile

import pandas as pd

sys.path.insert(0, "scripts")
import selfhost_zip_gate as zg  # noqa: E402


def _zip(path, last_close=100.0, last_day="2026-10-07", codes=(("0050", "TW"), ("2330", "TW"), ("6488", "TWO"))):
    with zipfile.ZipFile(path, "w") as z:
        for c, mk in codes:
            z.writestr(f"data/{c}.{mk}.csv", f"Date,Open,High,Low,Close,Volume\n2026-10-06,1,1,1,99,1\n{last_day},1,1,1,{last_close},1\n")
            z.writestr(f"data/institutional/{c}_inst.csv", "ticker,date,total_net\nx,2026-10-07,1\n")
            z.writestr(f"data/margin/{c}_margin.csv", "ticker,date,margin_balance\nx,2026-10-07,1\n")


RAW = pd.DataFrame({"ticker": ["0050", "2330", "6488"], "date": pd.to_datetime(["2026-10-07"] * 3), "close": [100.0] * 3})
MAN = {"complete_day": "2026-10-07"}


def test_正常通過(tmp_path):
    p = tmp_path / "a.zip"
    _zip(p)
    errs, stats = zg.check(p, MAN, RAW, {"complete_day": "2026-10-06", "zip": {"price_files": 3}})
    assert errs == [] and stats["price_files"] == 3


def test_完整日倒退要擋(tmp_path):
    p = tmp_path / "a.zip"
    _zip(p)
    errs, _ = zg.check(p, MAN, RAW, {"complete_day": "2026-10-08"})
    assert any("倒退" in e for e in errs)


def test_錨點最新收盤不等於官方未還原收盤要擋(tmp_path):
    p = tmp_path / "a.zip"
    _zip(p, last_close=95.0)                     # 例：當日事件因子被乘到最新一列
    errs, _ = zg.check(p, MAN, RAW, None)
    assert sum("官方未還原收盤" in e for e in errs) == 3


def test_檔數縮水與錨點缺檔要擋(tmp_path):
    p = tmp_path / "a.zip"
    _zip(p, codes=(("0050", "TW"), ("2330", "TW")))
    errs, _ = zg.check(p, MAN, RAW, {"complete_day": "2026-10-07", "zip": {"price_files": 100}})
    assert any("縮水" in e for e in errs) and any("6488" in e for e in errs)


def test_manifest有中間缺日要擋(tmp_path):
    p = tmp_path / "a.zip"
    _zip(p)
    errs, _ = zg.check(p, {**MAN, "gaps": {"raw_prices.TW": ["2026-10-06"]}}, RAW, None)
    assert any("中間缺日" in e for e in errs)


def test_法人融資最後日不等於完整日要擋(tmp_path):
    p = tmp_path / "a.zip"
    with zipfile.ZipFile(p, "w") as z:
        for c, mk in (("0050", "TW"), ("2330", "TW"), ("6488", "TWO")):
            z.writestr(f"data/{c}.{mk}.csv", "Date,Open,High,Low,Close,Volume\n2026-10-07,1,1,1,100.0,1\n")
            z.writestr(f"data/institutional/{c}_inst.csv", "ticker,date,total_net\nx,2026-10-05,1\n")
            z.writestr(f"data/margin/{c}_margin.csv", "ticker,date,margin_balance\nx,2026-10-07,1\n")
    errs, _ = zg.check(p, MAN, RAW, None)
    assert any("inst 錨點最後日" in e for e in errs) and not any("margin 錨點" in e for e in errs)


def test_法人融資錨點檔全找不到不可靜默通過(tmp_path):
    p = tmp_path / "a.zip"
    with zipfile.ZipFile(p, "w") as z:
        for c, mk in (("0050", "TW"), ("2330", "TW"), ("6488", "TWO")):
            z.writestr(f"data/{c}.{mk}.csv", "Date,Open,High,Low,Close,Volume\n2026-10-07,1,1,1,100.0,1\n")
        z.writestr("data/institutional/9999_inst.csv", "ticker,date,total_net\nx,2026-10-07,1\n")
        z.writestr("data/margin/9999_margin.csv", "ticker,date,margin_balance\nx,2026-10-07,1\n")
    errs, _ = zg.check(p, MAN, RAW, None)
    assert sum("錨點檔都找不到" in e for e in errs) == 2
