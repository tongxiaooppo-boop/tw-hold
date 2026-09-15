"""scripts.fetch_tx_futures 的純邏輯部分（近月篩選 + 欄位轉換 + 夜盤缺失偵測），不打網路。"""
from __future__ import annotations

import json

from scripts.fetch_tx_futures import _to_record, fetch_front_month_rows


def _row(month: str, session: str, last: str = "45780", settle: str = "45777") -> dict:
    return {"Date": "20260914", "Contract": "TX", "ContractMonth(Week)": month,
            "TradingSession": session, "Last": last, "SettlementPrice": settle}


def test_只留純六碼月份_取最小當近月(monkeypatch):
    rows = [_row("202610", "一般"), _row("202610", "盤後"),
            _row("202609", "一般"), _row("202609", "盤後"),
            _row("202609/202610", "一般")]  # 價差單複合月份，要濾掉

    class _Resp:
        def read(self):
            import json
            return json.dumps(rows).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("scripts.fetch_tx_futures.urllib.request.urlopen", lambda *a, **k: _Resp())
    front = fetch_front_month_rows()
    assert len(front) == 2
    assert all(r["ContractMonth(Week)"] == "202609" for r in front)


def test_to_record日盤夜盤標籤與結算價():
    day = _to_record(_row("202609", "一般", last="45780", settle="45777"))
    assert day == {"date": day["date"], "session": "day", "contract_month": "202609",
                    "last": 45780.0, "settlement": 45777.0}

    night = _to_record(_row("202609", "盤後", last="46588", settle="NULL"))
    assert night["session"] == "night"
    assert night["settlement"] is None


def test_to_record沒有last值回None():
    assert _to_record(_row("202609", "一般", last="-")) is None
    assert _to_record(_row("202609", "未知時段")) is None


class _Resp:
    def __init__(self, rows):
        self._rows = rows

    def read(self):
        return json.dumps(self._rows).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_夜盤缺席時main寫meta並標記missing_night(monkeypatch, tmp_path):
    import scripts.fetch_tx_futures as mod

    out, meta = tmp_path / "tx_futures.parquet", tmp_path / "tx_futures_meta.json"
    monkeypatch.setattr(mod, "OUT", out)
    monkeypatch.setattr(mod, "META_OUT", meta)
    # 只有日盤，沒有夜盤那列
    monkeypatch.setattr(mod.urllib.request, "urlopen",
                         lambda *a, **k: _Resp([_row("202609", "一般")]))

    mod.main()
    m = json.loads(meta.read_text(encoding="utf-8"))
    assert m["missing_night"] is True
    assert m["date"] == "2026-09-14"


def test_日盤夜盤都有時main寫meta標記正常(monkeypatch, tmp_path):
    import scripts.fetch_tx_futures as mod

    out, meta = tmp_path / "tx_futures.parquet", tmp_path / "tx_futures_meta.json"
    monkeypatch.setattr(mod, "OUT", out)
    monkeypatch.setattr(mod, "META_OUT", meta)
    monkeypatch.setattr(mod.urllib.request, "urlopen",
                         lambda *a, **k: _Resp([_row("202609", "一般"), _row("202609", "盤後")]))

    mod.main()
    m = json.loads(meta.read_text(encoding="utf-8"))
    assert m["missing_night"] is False
