"""resolve_splits：自建事件表 → 股數事件（m／pf）的規則。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import resolve_splits as rs  # noqa: E402


def test_nice_吸附整數與簡分數():
    assert rs._nice(7.001) == 7
    assert rs._nice(1.9998) == 2
    assert rs._nice(0.5003) == 0.5
    assert rs._nice(6.5) == 6.5            # 半整數
    assert rs._nice(3.72) == 3.72          # 差整數/半整數 >0.5% → 保持原值
    assert rs._nice(3.999) == 4


def _row(tk, d, typ, pre, ref, src, detail="{}", reason=None):
    return {"ticker": tk, "date": pd.Timestamp(d), "type": typ, "prev_close": pre,
            "ref_price": ref, "source": src, "detail": detail, "reason": reason}


def test_build_events_各類規則():
    corp = pd.DataFrame([
        _row("5904", "2026-08-10", "par_change", 720.0, 72.0, "tpex_par"),
        _row("5904", "2026-08-10", "par_change", 720.0, 72.0, "fm_split"),       # 重複來源
        _row("2321", "2026-09-21", "cap_reduction", 15.10, 27.61, "twse_red", reason="彌補虧損"),
        _row("9945", "2023-09-25", "cap_reduction", 34.90, 37.66, "twse_red", reason="退還股款"),
        _row("6669", "2026-09-02", "ex_rights", 7800.0, 2614.99, "twse_ex"),
        _row("9950", "2017-08-30", "ex_rights", 13.85, 13.45, "tpex_ex",
             detail=json.dumps({"stock_div_per_1000": "30.00000516"})),
        _row("1234", "2026-08-01", "ex_rights", 50.0, 48.0, "twse_ex"),         # 純現增
        _row("2330", "2026-07-01", "ex_div", 1000.0, 995.0, "twse_ex"),
        _row("7777", "2026-08-05", "ex_both", 40.0, 36.0, "twse_ex"),           # 還沒查配股率
    ])
    cache = {"6669:2026-09-02": 1982.8, "1234:2026-08-01": 0.0}
    ev, missing = rs.build_events(corp, cache)
    assert ev["5904"] == [{"date": "2026-08-10", "type": "par_change", "m": 10, "pf": 10,
                           "src": "tpex_par"}]
    assert 0.54 < ev["2321"][0]["m"] < 0.55 and ev["2321"][0]["m"] == ev["2321"][0]["pf"]
    assert ev["9945"][0]["m"] is None and ev["9945"][0]["pf"] < 1      # 現金減資
    assert ev["6669"][0]["m"] == 2.9828 and ev["6669"][0]["pf"] is None
    assert ev["9950"][0]["m"] == 1.03
    assert "1234" not in ev and "2330" not in ev
    assert missing == ["7777:2026-08-05"]
