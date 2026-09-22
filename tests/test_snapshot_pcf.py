"""scripts.snapshot_pcf——MIN_HOLDINGS 防守：holdings 異常少當抓失敗處理，
不落快照、進 missing（2026-09-22 Opus 審出：投信網站改版/回空陣列但沒丟例外
時，不擋的話會讓下游 build_active_etf_flags.py 把「幾乎全空」誤判成
「幾乎全部出清」，產出假的全體 consensus_sell）。
"""
from __future__ import annotations

import json
import sys

import pytest

sys.path.insert(0, ".")
import scripts.snapshot_pcf as sp  # noqa: E402


def _fund(code: str, n_holdings: int, data_date: str = "2026-09-22") -> dict:
    return {
        "code": code, "issuer": "測試投信", "name": f"測試{code}", "name_full": "",
        "data_date": data_date, "post_date": data_date, "nav": 1_000_000.0,
        "fetched_at": "2026-09-22T00:00:00+00:00", "close": None, "close_date": None,
        "holdings": [{"stock_code": str(1000 + i), "stock_name": f"n{i}",
                      "shares": 1000.0, "weight": 1.0, "market_value": 10000.0,
                      "price": 10.0} for i in range(n_holdings)],
    }


@pytest.fixture()
def _isolated(monkeypatch, tmp_path):
    """把落地路徑指到 tmp_path，測試不動真的 data/pcf/；sys.argv 蓋掉 pytest
    自己的參數，不然 main() 的 argparse 會吃到 -q 這些炸掉。"""
    pcf_dir = tmp_path / "pcf"
    index = pcf_dir / "_index.json"
    monkeypatch.setattr(sp, "REPO", tmp_path)
    monkeypatch.setattr(sp, "PCF_DIR", pcf_dir)
    monkeypatch.setattr(sp, "INDEX", index)
    monkeypatch.setattr(sys, "argv", ["snapshot_pcf.py"])
    return pcf_dir, index


def test_holdings正常筆數_正常落地(monkeypatch, _isolated):
    pcf_dir, index = _isolated
    monkeypatch.setattr(sp, "fetch_all", lambda: ([_fund("00981A", 30)], []))
    rc = sp.main()
    assert rc == 0
    assert (pcf_dir / "00981A" / "2026-09-22.parquet").exists()
    idx = json.loads(index.read_text(encoding="utf-8"))
    assert "00981A" in idx["funds"]
    assert idx["missing"] == []


def test_holdings異常少_當抓失敗不落地(monkeypatch, _isolated):
    pcf_dir, index = _isolated
    monkeypatch.setattr(sp, "fetch_all", lambda: ([_fund("00981A", 3)], []))
    rc = sp.main()
    assert rc == 0
    assert not (pcf_dir / "00981A" / "2026-09-22.parquet").exists()
    idx = json.loads(index.read_text(encoding="utf-8"))
    assert "00981A" not in idx["funds"]
    assert len(idx["missing"]) == 1
    assert idx["missing"][0]["code"] == "00981A"


def test_holdings空陣列_當抓失敗不落地(monkeypatch, _isolated):
    pcf_dir, index = _isolated
    monkeypatch.setattr(sp, "fetch_all", lambda: ([_fund("00981A", 0)], []))
    rc = sp.main()
    assert rc == 0
    idx = json.loads(index.read_text(encoding="utf-8"))
    assert "00981A" not in idx["funds"]
    assert len(idx["missing"]) == 1


def test_混合_正常的照落地_異常的不落地(monkeypatch, _isolated):
    pcf_dir, index = _isolated
    monkeypatch.setattr(
        sp, "fetch_all",
        lambda: ([_fund("00981A", 30), _fund("00991A", 2)], [{"code": "00982A", "issuer": "x", "error": "timeout"}]))
    rc = sp.main()
    assert rc == 0
    assert (pcf_dir / "00981A" / "2026-09-22.parquet").exists()
    assert not (pcf_dir / "00991A" / "2026-09-22.parquet").exists()
    idx = json.loads(index.read_text(encoding="utf-8"))
    assert "00981A" in idx["funds"]
    assert "00991A" not in idx["funds"]
    missing_codes = {b["code"] for b in idx["missing"]}
    assert missing_codes == {"00991A", "00982A"}
