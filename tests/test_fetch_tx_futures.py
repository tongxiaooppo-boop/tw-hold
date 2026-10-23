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


_CSV = ("交易日期,契約,到期月份(週別),開盤價,最高價,最低價,收盤價,漲跌價,漲跌%,成交量,結算價,未沖銷契約數,最後最佳買價,最後最佳賣價,歷史最高價,歷史最低價,是否因訊息面暫停交易,交易時段,價差對單式委託成交量\n"
        "2026/10/15,TX,202610  ,47716,47720,46883,46979,-1819,-3.73%,84911,46931,106781,46974,46994,50265,39852,,一般,,\n"
        "2026/10/15,TX,202611  ,47716,47720,46883,46900,-1819,-3.73%,1,46900,1,1,1,1,1,,一般,,\n"
        "2026/10/15,TX,202610/202611,1,1,1,1,1,1%,1,-,-,1,1,1,1,,一般,,\n"
        "2026/10/16,TX,202610  ,46926,47417,46456,47366,435,0.93%,41283,-,-,47332,47367,50265,39852,,盤後,,\n"
        "2026/10/16,MTX,202610  ,1,1,1,1,1,1%,1,-,-,1,1,1,1,,盤後,,\n")


def test_csv解析_近月_含下一交易日盤後():
    from scripts.fetch_tx_futures import parse_csv
    recs = parse_csv(_CSV)
    got = {(str(r["date"].date()), r["session"]): (r["contract_month"], r["last"], r["settlement"]) for r in recs}
    assert got == {("2026-10-15", "day"): ("202610", 46979.0, 46931.0),
                   ("2026-10-16", "night"): ("202610", 47366.0, None)}


def test_csv有資料就不打OpenAPI_且早上多一筆盤後不算缺(monkeypatch, tmp_path):
    import scripts.fetch_tx_futures as mod
    from scripts.fetch_tx_futures import parse_csv
    monkeypatch.setattr(mod, "OUT", tmp_path / "tx.parquet")
    monkeypatch.setattr(mod, "META_OUT", tmp_path / "meta.json")
    monkeypatch.setattr(mod, "fetch_csv_records", lambda *a, **k: parse_csv(_CSV))
    monkeypatch.setattr(mod, "fetch_front_month_rows", lambda: (_ for _ in ()).throw(AssertionError("不該打 OpenAPI")))
    mod.main()
    m = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    assert m["date"] == "2026-10-16" and m["missing_night"] is False


def test_結算價0視為無():
    """最後交易日期交所結算價欄填 0（2026-10-21 10 月合約）。"""
    from scripts.fetch_tx_futures import _settle
    assert _settle(0.0) is None and _settle(None) is None and _settle(46341.0) == 46341.0
