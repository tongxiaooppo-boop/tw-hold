"""影子比對：收盤相符率、只有一邊有的代號、法人／融資相符率。"""
from __future__ import annotations

import sys
import zipfile

sys.path.insert(0, "scripts")
import selfhost_shadow_compare as sc  # noqa: E402


def _zip(path, closes, inst_total=5):
    with zipfile.ZipFile(path, "w") as z:
        for code, mk, c in closes:
            z.writestr(f"data/{code}.{mk}.csv", f"Date,Open,High,Low,Close,Volume\n2026-10-06,1,1,1,9,100\n2026-10-07,1,1,1,{c},100\n")
            z.writestr(f"data/institutional/{code}_inst.csv", f"﻿ticker,date,total_net\n{code},2026-10-07,{inst_total}\n")
            z.writestr(f"data/margin/{code}_margin.csv", f"ticker,date,margin_balance,short_balance\n{code},2026-10-07,10,1\n")


def test_最新日收盤對不上要列出代號(tmp_path):
    a, b = tmp_path / "s.zip", tmp_path / "u.zip"
    _zip(a, [("0050", "TW", 10.0), ("3625", "TWO", 10.10)])
    _zip(b, [("0050", "TW", 10.0), ("3625", "TWO", 19.86)])            # 上游預套未來減資因子
    rep = sc.compare(sc.read_recent(a, 5), sc.read_recent(b, 5), 5)
    last = rep["per_day"]["2026-10-07"]
    assert last["close_match"] == 0.5 and last["close_mismatch_codes"] == ["3625"]
    assert last["inst"]["total_net_match"] == 1.0                     # BOM 表頭也讀得到
    assert last["margin"]["margin_balance_match"] == 1.0
