"""個股查詢／多軌體檢的中文股名模糊查詢（bundle_data.match_names / stock_names）。"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import bundle_data as bd  # noqa: E402

NAMES = {"2330": "台積電", "2303": "聯電", "2454": "聯發科", "3034": "聯詠", "2317": "鴻海",
         "2891": "中信金", "1101": "臺泥", "2882": "國泰金", "2881": "富邦金"}


def test_exact_before_head_before_part():
    names = {**NAMES, "9999": "大聯電", "8888": "聯"}
    r = bd.match_names("聯", names)
    assert r[0] == ("8888", "聯")                       # 完全相符最前
    assert [c for c, _ in r[1:4]] == ["2303", "2454", "3034"]   # 開頭相符，依代號
    assert r[-1] == ("9999", "大聯電")                  # 只是包含的最後


def test_unique_hit():
    assert bd.match_names("鴻海", NAMES) == [("2317", "鴻海")]
    assert bd.match_names("台積", NAMES) == [("2330", "台積電")]


def test_tai_variant_and_spaces():
    assert bd.match_names("台泥", NAMES) == [("1101", "臺泥")]     # 台 ≈ 臺
    assert bd.match_names("臺積電", NAMES) == [("2330", "台積電")]
    assert bd.match_names(" 國 泰金 ", NAMES) == [("2882", "國泰金")]


def test_no_hit_and_empty():
    assert bd.match_names("不存在", NAMES) == []
    assert bd.match_names("", NAMES) == []
    assert bd.match_names("   ", NAMES) == []


def test_limit():
    many = {f"{i:04d}": f"測試{i}" for i in range(1000, 1100)}
    assert len(bd.match_names("測試", many, limit=30)) == 30


def test_stock_names_reads_universe(tmp_path, monkeypatch):
    p = tmp_path / "universe.parquet"
    pd.DataFrame({"ticker": ["2330", "2303.TW", None, "9999"],
                  "stock_name": ["台積電", "聯電", "壞列", " "]}).to_parquet(p)
    monkeypatch.setattr(bd, "_dest", lambda name: p)
    assert bd.stock_names() == {"2330": "台積電", "2303": "聯電"}


def test_stock_names_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(bd, "_dest", lambda name: tmp_path / "nope.parquet")
    assert bd.stock_names() == {}


def test_universe_is_a_bundle_asset():
    assert "universe.parquet" in bd._ASSETS and "universe.parquet" in bd._FUND
    assert bd._dest("universe.parquet").name == "universe.parquet"
    assert bd._dest("universe.parquet").parent.name == "fundamentals"


def test_is_code_and_normalize():
    for ok in ("2330", "00878", "00981A", "2330.TW", "6488.TWO", "2330.tw"):
        assert bd.is_code(ok), ok
    for bad in ("台積電", "聯", "abc", "233", "2330 台積", "２３３０"):
        assert not bd.is_code(bad), bad
    assert bd.normalize_query(" ２３３０　") == "2330"
    assert bd.is_code(bd.normalize_query("２３３０"))
